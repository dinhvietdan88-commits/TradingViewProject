"""
test_vbs_recovery.py — VPS Analyzer Worker recovery scenario tests.

Tests the VpsAnalyzerWorker's resilience during recovery situations:
  1. Backlog drain in FIFO order (queue_id ascending)
  2. Empty queue returns gracefully (no crash)
  3. VBS unreachable (ConnectionError) — graceful degradation
  4. Partial failure: worker continues processing remaining signals
  5. Poll timeout (asyncio.TimeoutError) — graceful empty return

All tests are fully isolated — no network, no real DB, no real Telegram.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ──────────────────────────────────────────────────────────────


class FakeResponse:
    """Fake aiohttp response for mocking session.get / session.post."""

    def __init__(self, status=200, json_data=None):
        self.status = status
        self._json_data = json_data or {}

    async def json(self):
        return self._json_data

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass


def _make_vbs_signal(queue_id, symbol, action, price):
    """Create a sample VBS signal dict matching the /consume-long response."""
    return {
        "queue_id": queue_id,
        "symbol": symbol,
        "action": action,
        "price": price,
        "quote_qty": 10.0,
        "age_minutes": 2.0,
        "interval": "1h",
        "payload": {
            "symbol": symbol,
            "action": action,
            "price": price,
            "alert_type": "vcp_breakout",
            "volume": 5000000,
            "volume_avg": 3000000,
            "exchange": "binance",
        },
    }


def _setup_poll_session(worker, json_data):
    """Wire worker.get_session to return a mock with .get() → FakeResponse."""
    vbs_response = FakeResponse(status=200, json_data=json_data)
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=vbs_response)
    mock_session.post = MagicMock(
        return_value=FakeResponse(status=200, json_data={"ok": True})
    )
    worker.get_session = AsyncMock(return_value=mock_session)
    return mock_session


def _rag_patches_approved():
    """Context managers that make RAG approve the signal with BUY keyword."""
    return [
        patch("rag.build_rag_query", return_value="VCP breakout query"),
        patch(
            "rag.query_knowledge",
            return_value=[
                {
                    "content": "Minervini SEPA rules...",
                    "metadata": {"topic": "VCP"},
                    "relevance_score": 0.92,
                }
            ],
        ),
        patch(
            "rag.generate_trading_advice",
            new_callable=AsyncMock,
            return_value="🟢 Tín hiệu Mạnh. Nên BUY tại pivot. SL -8%.",
        ),
    ]


# ═══════════════════════════════════════════════════════════════
# TEST 1: Backlog drain in FIFO order
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_backlog_drain_fifo_order():
    """Worker nhận 3 signals trong 1 poll cycle, xử lý theo thứ tự FIFO (queue_id tăng dần).

    Verifies that when VBS returns multiple backlogged signals,
    poll_and_analyze processes all of them and returns results
    matching queue_id order.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    signals = [
        _make_vbs_signal(queue_id=10, symbol="BTCUSDT", action="buy", price=68000.0),
        _make_vbs_signal(queue_id=11, symbol="ETHUSDT", action="buy", price=3500.0),
        _make_vbs_signal(queue_id=12, symbol="SOLUSDT", action="buy", price=150.0),
    ]

    patches = _rag_patches_approved()
    with patches[0], patches[1], patches[2]:
        _setup_poll_session(worker, {"signals": signals})
        results = await worker.poll_and_analyze()

    # All 3 signals processed
    assert len(results) == 3

    # Verify queue_ids are present and match FIFO input order
    result_queue_ids = [r["queue_id"] for r in results]
    assert 10 in result_queue_ids
    assert 11 in result_queue_ids
    assert 12 in result_queue_ids

    # Verify ascending FIFO order preserved
    assert result_queue_ids == sorted(result_queue_ids)

    # Each result has expected structure
    for r in results:
        assert "approved" in r
        assert "queue_id" in r

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 2: Empty queue — graceful handling
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_empty_queue_graceful():
    """VBS trả về queue rỗng [], worker không crash và trả về [].

    When VBS has no signals (e.g. after cold start), poll_and_analyze
    should return an empty list without raising any exception.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    _setup_poll_session(worker, {"signals": []})
    results = await worker.poll_and_analyze()

    assert results == []

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 3: Connection refused — graceful degradation
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_connection_refused_graceful():
    """VBS không reachable (ConnectionError), poll_and_analyze trả về [] không crash.

    Simulates SERVER A being offline (e.g. during deploy, restart).
    The worker should catch the error and return empty results.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    # Simulate connection refused: session.get raises inside context manager
    mock_session = MagicMock()
    mock_session.get = MagicMock(
        side_effect=ConnectionError("Connection refused to VBS on Server A")
    )
    worker.get_session = AsyncMock(return_value=mock_session)

    results = await worker.poll_and_analyze()

    assert results == []

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 4: Partial failure — continues processing remaining signals
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_partial_failure_continues_processing():
    """3 signals: #1 approved, #2 forward fails, #3 approved. Worker xử lý tiếp #3 sau khi #2 thất bại.

    Simulates a batch where the middle signal's forward_to_server_b
    call fails. Worker should still process and return results for all 3.
    This tests the run() loop's asyncio.gather(return_exceptions=True) logic.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker.poll_interval = 0

    # Pre-analyzed signals (as returned by poll_and_analyze)
    analyzed_signals = [
        {
            "queue_id": 201,
            "approved": True,
            "trade_payload": {
                "symbol": "BTCUSDT",
                "action": "buy",
                "price": 68000.0,
            },
        },
        {
            "queue_id": 202,
            "approved": True,
            "trade_payload": {
                "symbol": "ETHUSDT",
                "action": "buy",
                "price": 3500.0,
            },
        },
        {
            "queue_id": 203,
            "approved": True,
            "trade_payload": {
                "symbol": "SOLUSDT",
                "action": "buy",
                "price": 150.0,
            },
        },
    ]

    call_count = 0

    async def mock_poll():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return analyzed_signals
        raise asyncio.CancelledError()

    async def mock_forward(payload):
        """#1 succeeds, #2 fails, #3 succeeds."""
        if payload["symbol"] == "ETHUSDT":
            return {
                "success": False,
                "status": 500,
                "error": "Exchange API timeout for ETHUSDT",
            }
        return {
            "success": True,
            "status": 200,
            "data": {"order_id": f"ORD-{payload['symbol']}"},
        }

    worker.poll_and_analyze = mock_poll
    worker.forward_to_server_b = mock_forward
    worker._ack_signal = AsyncMock(return_value=True)
    worker._notify_analysis_telegram = AsyncMock()

    with patch("uvicorn.Config"), patch("uvicorn.Server") as mock_server:
        mock_server.return_value.serve = AsyncMock()
        await worker.run()

    # All 3 signals should be ACK'd (none skipped)
    assert worker._ack_signal.call_count == 3

    ack_map = {
        call.args[0]: call.args[1:] for call in worker._ack_signal.call_args_list
    }

    # Signal #1: approved + forward success → ACK 'executed'
    assert ack_map[201] == ("executed",)

    # Signal #2: approved + forward failed → ACK 'failed'
    assert ack_map[202][0] == "failed"
    assert "ETHUSDT" in ack_map[202][1]

    # Signal #3: approved + forward success → ACK 'executed' (not skipped!)
    assert ack_map[203] == ("executed",)

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 5: Poll timeout — returns empty gracefully
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_poll_timeout_returns_empty():
    """VBS phản hồi rất chậm (asyncio.TimeoutError), worker trả về [] gracefully.

    When VBS long-poll exceeds the client-side timeout, the worker
    should catch asyncio.TimeoutError and return an empty list
    without crashing or propagating the exception.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    # Simulate timeout: session.get raises asyncio.TimeoutError
    mock_session = MagicMock()
    mock_session.get = MagicMock(
        side_effect=asyncio.TimeoutError("VBS poll timed out after 35s")
    )
    worker.get_session = AsyncMock(return_value=mock_session)

    results = await worker.poll_and_analyze()

    assert results == []

    await worker.close()
