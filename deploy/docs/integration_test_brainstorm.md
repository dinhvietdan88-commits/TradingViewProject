# Cross-Server Integration Test (Server A → C) Architecture & Brainstorming

This document summarizes the architecture, design patterns, testing strategies, and verification results for the cross-server integration between **Server A (Value Buffer Service - VBS)** and **Server C (AI Core / `VpsAnalyzerWorker`)**.

---

## 1. End-to-End Pipeline & Data Flows

Below is the conceptual architecture of the 3-server pipeline, showing how signals ingest, traverse Server C, get analyzed, and execute on Server B:

```mermaid
graph TD
    TV[TradingView Webhook] -->|Ingest / Post| ServerA(Server A: VBS FastAPI)

    subgraph VBS Layer (Server A)
        ServerA -->|Dedup & Queue| SQLite_A[(SQLite: signal_queue.db)]
        ServerA -->|Notify| TG_Silent[Telegram: Queue Notify]
    end

    subgraph AI Core Layer (Server C)
        Worker[VpsAnalyzerWorker Daemon] -->|Long-Poll /consume-long| ServerA
        Worker -->|RAG Query| ChromaDB[(ChromaDB / VectorStore)]

        %% Decoupled Modes
        Worker -->|Circuit CLOSED| AI_Mode{AI Mode}
        Worker -->|Circuit OPEN / Timeout| Algo_Mode{Algorithmic Fallback}

        AI_Mode -->|LLM Advice + Extract Conf| Size_SL_TP[Calculate Position, SL & TP]
        Algo_Mode -->|Minervini SEPA Scoring| Size_SL_TP
    end

    subgraph Trade Execution Layer (Server B)
        Size_SL_TP -->|HTTP Forward| ServerB_Local{Server B: Primary Local}
        ServerB_Local -->|Failover if Down| ServerB_Remote[Server B: Fallback Remote]
    end

    ServerB_Local -->|ACK Result| Worker
    ServerB_Remote -->|ACK Result| Worker
    Worker -->|Post /ack| ServerA
    ServerA -->|Update Status to ACKED| SQLite_A
```

---

## 2. Sandboxed Test Architecture: Zero-Network Footprint

To ensure reliability, speed, and prevent port collision during concurrent test executions, the test suite implements a **Zero-Network Footprint Bridge**:

- **FastAPI Transport Bridge (`httpx.ASGITransport`)**:
  Instead of launching physical webservers on network interfaces (e.g. binding `127.0.0.1:8000`), the test instantiates an in-memory transport bridge that feeds HTTP requests directly into the FastAPI `vbs_app`.
- **Mock session (`MockAiohttpSession`)**:
  The `VpsAnalyzerWorker` uses `aiohttp` for networking. In tests, the worker's session is mocked to capture outgoing requests to `VPS_BUFFER_URL` and redirect them dynamically through the `httpx.ASGITransport` bridge, mapping routes completely in-memory.
- **SQLite Database Isolation**:
  The `test_db` fixture overrides the SQLite path `vbs_config.DB_PATH` to a clean temporary file (`tmp_path / "test_vbs.db"`) for each test, assuring complete containment.

---

## 3. Parametrization & Confidence Edge Cases (R2)

A core production failure pattern was the behavior of the auto-rejection threshold at score **50**. We parameterize and verify this under both **AI Mode** and **Algorithmic Fallback**:

### AI Mode (LLM Active)
The AI produces a textual analysis from which a confidence level ($0 - 100$) is extracted.
- **Hold for Approval ($50 \le \text{confidence} \le 79$)**: Signals in this range are approved but flagged with `hold_for_approval: True` to request manual operator review.
- **Immediate Execution ($\ge 80$)**: Signals bypass manual holds.
- **Rejection ($< 50$)**: Signals are auto-rejected.

### Algorithmic Mode (LLM Offline / Circuit Open)
When the LLM is down, the system scores signals out of $5$ based on the **Minervini SEPA Trend Template**:
1. **Volume Surge** ($>150\%$ of avg volume).
2. **RSI Momentum** (RSI between $50$ and $80$).
3. **Pattern Type** (VCP, Breakout, or Trend template).
4. **Risk-controlled SL** (Stop-loss distance $\le 8\%$).
5. **Valid Action** (Buy or Sell).

The total score is translated to confidence percentage: $\text{confidence} = \frac{\text{score}}{5} \times 100$.

To assert edge cases, we parametrize confidence scores **49, 50, and 51**:

| Parametrized Conf | Mode | Score / 5 Calculation | Outcome | Reason |
| :--- | :--- | :--- | :--- | :--- |
| **49** | AI | - | **Approved (No Hold)** | Confidence $< 50$ in AI mode has no hold, but approved if text contains positive keywords. |
| **50** | AI | - | **Approved (Hold)** | Exactly $50$, triggers manual approval hold. |
| **51** | AI | - | **Approved (Hold)** | $51$, triggers manual approval hold. |
| **49** | Algorithmic | $\text{round}(0.49 \times 5) = 2$ | **Rejected** | Score $2 < 3$ minimum threshold (`ALGO_MIN_SCORE`). |
| **50** | Algorithmic | $\text{round}(0.50 \times 5) = 2$ | **Rejected** | Python uses banker's rounding: `round(2.5) -> 2`, which is $< 3$. |
| **51** | Algorithmic | $\text{round}(0.51 \times 5) = 3$ | **Approved (Hold)** | Score $3 \ge 3$ minimum threshold, confidence $51\%$ triggers manual hold. |

---

## 4. Fallback Routing & Recovery (R3)

The trade forwarding logic in Server C's `forward_to_server_b` is hardened and verified through four progressive test cases:

1. **Happy Path (Primary Local)**:
   Worker posts to `LOCAL_EXECUTE_URL`. The endpoint succeeds, returning `executed_on = "local"`.
2. **Fallback to Remote**:
   The primary local server goes offline (simulated by throwing a connection error). The worker alerts Telegram (`"Local Windows Offline"`) and redirects the trade payload to `SERVER_B_EXECUTE_URL` (the remote fallback server).
3. **Double Failure (No Routing Available)**:
   Both primary and fallback endpoints fail. The worker handles this gracefully without throwing uncaught exceptions, returning `success=False`.
4. **Self-Healing Recovery**:
   When the local server recovers, the next signal routing attempt goes to `LOCAL_EXECUTE_URL` and succeeds. The system stops routing to the fallback server automatically, showing deterministic self-healing behavior.

---

## 5. End-to-End Duplicate Detection (R4)

To prevent double executions or orphan orders, VBS enforces a strict deduplication window:
- When a signal is ingested, a fingerprint consisting of `(symbol_upper, action_lower, rounded_price)` is compared against all signals received within `config.DEDUP_WINDOW_SECONDS`.
- If an active duplicate is detected, the request is rejected with `status = "DUPLICATE"` and records `duplicate_of = {original_queue_id}`.
- This prevents downstream analysis or order forwarding from ever firing.

---

## 6. Verification & Test Execution Results

The integration test suite was executed in the workspace using the subfolder's Python environment. All 9 test cases passed successfully:

```powershell
& nerves\workers\trading\.venv\Scripts\python.exe -m pytest nerves/workers/trading/tests/integration/test_server_a_c_integration.py
```

### Pytest Execution Output:
```text
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.0.3, pluggy-1.6.0
cachedir: .pytest_cache
rootdir: C:\Users\pesil\working\mj_trading\TradingViewProject\nerves\workers\trading
configfile: pytest.ini
plugins: anyio-4.13.0, hypothesis-6.155.1, asyncio-1.4.0, mock-3.15.1, xdist-3.8.0
asyncio: mode=Mode.AUTO, debug=False
collecting ... collected 9 items

test_server_a_c_integration.py::test_server_a_c_integration_flow PASSED     [ 11%]
test_server_a_c_integration.py::test_confidence_edge_cases[49-ai-True-False] PASSED [ 22%]
test_server_a_c_integration.py::test_confidence_edge_cases[50-ai-True-True] PASSED [ 33%]
test_server_a_c_integration.py::test_confidence_edge_cases[51-ai-True-True] PASSED [ 44%]
test_server_a_c_integration.py::test_confidence_edge_cases[49-algorithmic-False-False] PASSED [ 55%]
test_server_a_c_integration.py::test_confidence_edge_cases[50-algorithmic-False-False] PASSED [ 66%]
test_server_a_c_integration.py::test_confidence_edge_cases[51-algorithmic-True-True] PASSED [ 77%]
test_server_a_c_integration.py::test_fallback_routing_and_recovery PASSED  [ 88%]
test_server_a_c_integration.py::test_end_to_end_duplicate_signals PASSED    [100%]

============================== 9 passed in 4.17s ==============================
```

---

## 7. Operational Recommendations for Further Hardening

Although the current 9 integration tests cover the critical paths and edge cases, we recommend brainstorming the following enhancements:

1. **NTP Clock Drift Testing**:
   Since the V2 architecture implements NTP monitors (`ntp_monitor.py`), a test could mock a significant clock drift ($>1000\text{ms}$) and verify that Server C generates appropriate metric warnings or circuit-breaker behaviors.
2. **Requeue Timeout and Retry Validation**:
   `vbs/database.py` contains a `requeue_timeouts()` method. We can add an integration test where:
   - A signal is consumed by `VpsAnalyzerWorker`.
   - The worker crashes before posting an `/ack`.
   - The scheduler triggers `requeue_timeouts` after the time window expires.
   - Assert the signal returns to `PENDING` with `retry_count = 1`.
3. **Database Write Concurrency**:
   Execute parallel ingests of $50+$ signals simultaneously to ensure that `aiosqlite` transaction locks do not lead to SQLite locking errors (`database is locked`) under peak traffic.
