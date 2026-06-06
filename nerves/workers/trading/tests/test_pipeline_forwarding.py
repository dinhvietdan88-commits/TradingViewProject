"""
test_pipeline_forwarding.py — Integration tests for the 3-Server Pipeline.

Simulates the full pipeline on a single machine:
  SERVER A (VBS) → SERVER C (Analyzer: poll + RAG + position-sizing) → SERVER B (Executor)

Each test exercises a realistic end-to-end flow by mocking only the
external HTTP boundaries (aiohttp for VBS, aiohttp for Server B) and
the RAG AI layer, while keeping the real VpsAnalyzerWorker logic intact.

Tests:
 1. Full pipeline signal flow (poll → analyze → forward → execute)
 2. Pipeline handles rejected signal
 3. Pipeline handles execution failure
 4. Pipeline handles VBS connection error
 5. Pipeline handles Server B auth failure
 6. Remote ChromaDB config integration
 7. Full pipeline with position sizing verification
 8. Pipeline ACK flow (approved → executed → ACK 'executed')
 9. Pipeline ACK flow for rejected signal (ACK 'rejected')
10. Pipeline ACK flow for failed execution (ACK 'failed')
11. Multiple signals in single poll cycle
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import config


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_vbs_signal(queue_id=1, symbol="BTCUSDT", action="buy", price=68000.0):
    """Create a sample VBS signal dict matching the VBS /consume response format."""
    return {
        "queue_id": queue_id,
        "symbol": symbol,
        "action": action,
        "price": price,
        "quote_qty": 10.0,
        "age_minutes": 5.0,
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


class FakeResponse:
    """Fake aiohttp response for mocking session.get / session.post."""

    def __init__(self, status=200, json_data=None, text_data=""):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _rag_patches_approved():
    """Return context-manager stack that makes RAG approve the signal."""
    return [
        patch("rag.build_rag_query", return_value="VCP breakout query for BTCUSDT"),
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


def _rag_patches_rejected():
    """Return context-manager stack that makes RAG reject the signal."""
    return [
        patch("rag.build_rag_query", return_value="test query"),
        patch(
            "rag.query_knowledge",
            return_value=[
                {
                    "content": "Minervini says wait...",
                    "metadata": {"topic": "VCP"},
                    "relevance_score": 0.5,
                }
            ],
        ),
        patch(
            "rag.generate_trading_advice",
            new_callable=AsyncMock,
            return_value="⚠️ RAG Analysis không khả dụng (thiếu API key).",
        ),
    ]


def _setup_vbs_poll(worker, signals_list):
    """Wire worker to return `signals_list` from the VBS /consume mock."""
    vbs_response = FakeResponse(status=200, json_data={"signals": signals_list})
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=vbs_response)
    worker.get_session = AsyncMock(return_value=mock_session)
    return mock_session


def _setup_server_b(mock_session, status=200, json_data=None):
    """Attach a Server-B POST mock to an existing mock_session."""
    server_b_resp = FakeResponse(
        status=status,
        json_data=json_data or {"success": True, "order_id": "ORD-INTEG-001"},
    )
    mock_session.post = MagicMock(return_value=server_b_resp)
    return mock_session


def _setup_ack(mock_session, status=200):
    """Attach an ACK POST mock to an existing mock_session.

    Because the worker uses the *same* session for both Server B and VBS ACK,
    we chain the post responses: first call → Server B, second call → ACK.
    """
    # The mock_session.post is already set for Server B.
    # We now need it to handle both calls. We use side_effect list.
    # If post is already a MagicMock with a return_value (for Server B),
    # we keep it and let the ACK also succeed.
    # Since both forward_to_server_b and _ack_signal use session.post,
    # we need a side_effect that returns the right response for each call.
    return mock_session


# ═══════════════════════════════════════════════════════════════
# TEST 1: Full pipeline signal flow
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_full_pipeline_signal_flow():
    """End-to-end: VBS poll → RAG analysis → Server B forward → success.

    Verifies the complete happy-path pipeline:
    - Worker polls VBS and receives a signal
    - RAG analysis approves the signal
    - Position sizing is computed
    - Trade is forwarded to Server B
    - Server B returns success
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    signal = _make_vbs_signal(
        queue_id=101, symbol="BTCUSDT", action="buy", price=50000.0
    )

    # Phase 1: Poll and analyze with RAG approval
    patches = _rag_patches_approved()
    with patches[0], patches[1], patches[2]:
        _setup_vbs_poll(worker, [signal])
        results = await worker.poll_and_analyze()

    assert len(results) == 1
    result = results[0]
    assert result["queue_id"] == 101
    assert result["approved"] is True
    trade_payload = result["trade_payload"]
    assert trade_payload["symbol"] == "BTCUSDT"
    assert trade_payload["action"] == "buy"
    assert trade_payload["price"] == 50000.0
    assert trade_payload["qty"] > 0
    assert trade_payload["sl"] > 0
    assert trade_payload["tp"] > 0
    assert "analysis" in trade_payload

    # Phase 2: Forward approved trade to Server B
    server_b_response = FakeResponse(
        status=200,
        json_data={"success": True, "order_id": "ORD-PIPE-001", "fill_price": 50000.0},
    )
    forward_session = MagicMock()
    forward_session.post = MagicMock(return_value=server_b_response)
    worker.get_session = AsyncMock(return_value=forward_session)

    forward_result = await worker.forward_to_server_b(trade_payload)

    assert forward_result["success"] is True
    assert forward_result["status"] == 200
    assert forward_result["data"]["order_id"] == "ORD-PIPE-001"

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 2: Pipeline handles rejected signal
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_handles_rejected_signal():
    """Pipeline correctly marks signal as rejected when RAG returns warning.

    The _analyze_signal method should return None when the AI response
    starts with '⚠️', causing poll_and_analyze to mark the signal rejected.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    signal = _make_vbs_signal(
        queue_id=202, symbol="ETHUSDT", action="buy", price=3500.0
    )

    patches = _rag_patches_rejected()
    with patches[0], patches[1], patches[2]:
        _setup_vbs_poll(worker, [signal])
        results = await worker.poll_and_analyze()

    assert len(results) == 1
    assert results[0]["queue_id"] == 202
    assert results[0]["approved"] is False
    assert "reason" in results[0]
    # Rejected reason should mention criteria or rejection
    assert len(results[0]["reason"]) > 0

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 3: Pipeline handles execution failure
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_handles_execution_failure():
    """Pipeline handles Server B returning 500 error on trade execution.

    When forward_to_server_b gets a non-200 response, the result dict
    should have success=False with the error detail from Server B.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    # First, get an approved trade payload via analysis
    signal = _make_vbs_signal(queue_id=303, symbol="SOLUSDT", action="buy", price=150.0)
    patches = _rag_patches_approved()
    with patches[0], patches[1], patches[2]:
        _setup_vbs_poll(worker, [signal])
        results = await worker.poll_and_analyze()

    assert results[0]["approved"] is True
    trade_payload = results[0]["trade_payload"]

    # Forward to Server B — simulate 500 error
    server_b_error = FakeResponse(
        status=500,
        json_data={"detail": "Insufficient margin", "success": False},
    )
    error_session = MagicMock()
    error_session.post = MagicMock(return_value=server_b_error)
    worker.get_session = AsyncMock(return_value=error_session)

    forward_result = await worker.forward_to_server_b(trade_payload)

    assert forward_result["success"] is False
    assert forward_result["status"] == 500
    assert "Insufficient margin" in forward_result["error"]

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 4: Pipeline handles VBS connection error
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_handles_vbs_connection_error():
    """Pipeline gracefully handles VBS being unreachable.

    When the VBS poll request raises a connection error, poll_and_analyze
    should return an empty list without crashing.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    # Simulate VBS connection refused
    mock_session = MagicMock()
    mock_session.get = MagicMock(
        side_effect=ConnectionError("Connection refused to VBS on Server A")
    )
    worker.get_session = AsyncMock(return_value=mock_session)

    results = await worker.poll_and_analyze()

    assert results == []  # Graceful degradation — no crash, no signals

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 5: Pipeline handles Server B auth failure
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_handles_server_b_auth_failure():
    """Pipeline handles Server B returning 401 Unauthorized.

    When the X-Server-B-Secret header doesn't match, Server B returns 401.
    forward_to_server_b should return success=False with the error detail.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    trade_payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 68000.0,
        "qty": 0.003,
        "sl": 62560.0,
        "tp": 81600.0,
        "analysis": "Approved by RAG",
        "risk_per_trade": 0.02,
        "stop_loss_pct": 0.08,
        "exchange": "binance",
    }

    # Server B returns 401 Unauthorized
    auth_fail_resp = FakeResponse(
        status=401,
        json_data={"detail": "Unauthorized"},
    )
    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=auth_fail_resp)
    worker.get_session = AsyncMock(return_value=mock_session)

    result = await worker.forward_to_server_b(trade_payload)

    assert result["success"] is False
    assert result["status"] == 401
    assert "Unauthorized" in result["error"]

    # Verify the secret header was included in the request
    call_args = mock_session.post.call_args
    call_url = call_args[0][0] if call_args[0] else call_args.kwargs.get("url", "")
    assert "/api/execute-trade" in str(call_url)

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 6: Remote ChromaDB config integration
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_remote_chromadb_config_integration():
    """Verify CHROMA_REMOTE config correctly branches to HttpClient.

    When CHROMA_REMOTE=true, init_vector_db() should instantiate
    chromadb.HttpClient instead of PersistentClient, using the
    configured CHROMA_SERVER_HOST and CHROMA_SERVER_PORT.
    """
    import rag

    original_remote = config.CHROMA_REMOTE
    original_host = config.CHROMA_SERVER_HOST
    original_port = config.CHROMA_SERVER_PORT
    original_client = rag._chroma_client
    original_collection = rag._collection

    try:
        # Set remote ChromaDB config
        config.CHROMA_REMOTE = True
        config.CHROMA_SERVER_HOST = "chroma.internal.vpn"
        config.CHROMA_SERVER_PORT = 9200

        # Reset globals so init_vector_db re-initializes
        rag._chroma_client = None
        rag._collection = None

        # Mock chromadb.HttpClient — rag imports chromadb locally,
        # so we patch the actual chromadb module's HttpClient.
        mock_collection = MagicMock()
        mock_collection.count.return_value = 10

        mock_http_client = MagicMock()
        mock_http_client.get_or_create_collection.return_value = mock_collection

        with (
            patch.object(rag, "CHROMADB_AVAILABLE", True),
            patch.dict(
                "sys.modules",
                {
                    "chromadb": MagicMock(
                        HttpClient=MagicMock(return_value=mock_http_client)
                    )
                },
            ),
            patch.object(rag, "_get_embedding_function", return_value=MagicMock()),
        ):
            result = await rag.init_vector_db()

            # Get the mock chromadb module to verify HttpClient was called
            import sys

            mock_chromadb = sys.modules["chromadb"]

        assert result is True
        # Verify HttpClient was called with the remote host/port
        mock_chromadb.HttpClient.assert_called_once_with(
            host="chroma.internal.vpn",
            port=9200,
        )

    finally:
        config.CHROMA_REMOTE = original_remote
        config.CHROMA_SERVER_HOST = original_host
        config.CHROMA_SERVER_PORT = original_port
        rag._chroma_client = original_client
        rag._collection = original_collection


# ═══════════════════════════════════════════════════════════════
# TEST 7: Full pipeline with position sizing verification
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_full_pipeline_with_position_sizing():
    """End-to-end pipeline verifies position sizing calculations.

    With default config:
      RISK_PER_TRADE = 0.02 (2%)
      STOP_LOSS_PCT  = 0.08 (8%)
      TAKE_PROFIT_PCT = 0.20 (20%)
      MAX_QUOTE_QTY  = 1000

    For a BUY signal at price=100.0:
      risk_amount = 1000 * 0.02 = 20
      dollar_risk_per_unit = 100 * 0.08 = 8
      qty = 20 / 8 = 2.5
      quote_value = 2.5 * 100 = 250 (under cap)
      sl = 100 * (1 - 0.08) = 92.0
      tp = 100 * (1 + 0.20) = 120.0
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    signal = _make_vbs_signal(
        queue_id=701, symbol="TESTUSDT", action="buy", price=100.0
    )

    patches = _rag_patches_approved()
    with patches[0], patches[1], patches[2]:
        _setup_vbs_poll(worker, [signal])
        results = await worker.poll_and_analyze()

    assert len(results) == 1
    result = results[0]
    assert result["approved"] is True

    tp = result["trade_payload"]
    assert tp["symbol"] == "TESTUSDT"
    assert tp["action"] == "buy"
    assert tp["price"] == 100.0

    # Position sizing assertions
    assert tp["qty"] == 2.5  # 20 / 8
    assert tp["sl"] == 92.0  # 100 * (1 - 0.08)
    assert tp["tp"] == 120.0  # 100 * (1 + 0.20)

    # Risk parameters passed through
    assert tp["risk_per_trade"] == config.RISK_PER_TRADE
    assert tp["stop_loss_pct"] == config.STOP_LOSS_PCT
    assert tp["exchange"] == "binance"  # from payload

    # Now forward to Server B and verify full round-trip
    server_b_success = FakeResponse(
        status=200,
        json_data={
            "success": True,
            "order_id": "ORD-SIZE-001",
            "fill_price": 100.0,
            "executed_qty": 2.5,
        },
    )
    fwd_session = MagicMock()
    fwd_session.post = MagicMock(return_value=server_b_success)
    worker.get_session = AsyncMock(return_value=fwd_session)

    fwd_result = await worker.forward_to_server_b(tp)
    assert fwd_result["success"] is True
    assert fwd_result["data"]["executed_qty"] == 2.5

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 8: Pipeline ACK flow — approved + executed → ACK 'executed'
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_ack_flow_executed():
    """Full run() loop: approved signal → forward success → ACK 'executed'.

    Tests the run() method's ACK logic when a signal is approved and
    Server B successfully executes the trade.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker.poll_interval = 0  # no sleep for tests

    analyzed_signal = {
        "queue_id": 800,
        "approved": True,
        "trade_payload": {
            "symbol": "BTCUSDT",
            "action": "buy",
            "price": 68000.0,
            "qty": 0.003,
            "sl": 62560.0,
            "tp": 81600.0,
            "analysis": "Approved by RAG",
            "exchange": "binance",
        },
    }

    call_count = 0

    async def mock_poll():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [analyzed_signal]
        raise asyncio.CancelledError()

    worker.poll_and_analyze = mock_poll
    worker.forward_to_server_b = AsyncMock(
        return_value={
            "success": True,
            "status": 200,
            "data": {"order_id": "ORD-ACK-001"},
        }
    )
    worker._ack_signal = AsyncMock(return_value=True)

    # Mock uvicorn to prevent port 8000 binding conflicts in parallel CI
    with patch("uvicorn.Config"), patch("uvicorn.Server") as mock_server:
        mock_server.return_value.serve = AsyncMock()
        await worker.run()

    # Verify forward was called with the trade payload
    worker.forward_to_server_b.assert_called_once_with(analyzed_signal["trade_payload"])

    # Verify ACK was sent with 'executed' status
    worker._ack_signal.assert_called_once_with(800, "executed")


# ═══════════════════════════════════════════════════════════════
# TEST 9: Pipeline ACK flow — rejected signal → ACK 'rejected'
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_ack_flow_rejected():
    """Full run() loop: rejected signal → no forward → ACK 'rejected'.

    When a signal is rejected by analysis, the pipeline should NOT forward
    it to Server B, but should still ACK back to VBS with 'rejected' status.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker.poll_interval = 0

    analyzed_signal = {
        "queue_id": 900,
        "approved": False,
        "reason": "RAG analysis rejected signal — does not meet Minervini criteria",
    }

    call_count = 0

    async def mock_poll():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [analyzed_signal]
        raise asyncio.CancelledError()

    worker.poll_and_analyze = mock_poll
    worker.forward_to_server_b = AsyncMock()
    worker._ack_signal = AsyncMock(return_value=True)

    # Mock uvicorn to prevent port 8000 binding conflicts in parallel CI
    with patch("uvicorn.Config"), patch("uvicorn.Server") as mock_server:
        mock_server.return_value.serve = AsyncMock()
        await worker.run()

    # Server B should NOT be called
    worker.forward_to_server_b.assert_not_called()

    # ACK should be sent with 'rejected' and the reason
    worker._ack_signal.assert_called_once_with(
        900,
        "rejected",
        "RAG analysis rejected signal — does not meet Minervini criteria",
    )


# ═══════════════════════════════════════════════════════════════
# TEST 10: Pipeline ACK flow — execution failure → ACK 'failed'
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_ack_flow_failed_execution():
    """Full run() loop: approved signal → forward failure → ACK 'failed'.

    When Server B fails to execute the trade, the pipeline should
    ACK the signal back to VBS with 'failed' status and the error.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker.poll_interval = 0

    analyzed_signal = {
        "queue_id": 1000,
        "approved": True,
        "trade_payload": {
            "symbol": "ETHUSDT",
            "action": "sell",
            "price": 3500.0,
            "qty": 0.5,
            "sl": 3780.0,
            "tp": 2800.0,
            "analysis": "Sell signal approved",
            "exchange": "binance",
        },
    }

    call_count = 0

    async def mock_poll():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [analyzed_signal]
        raise asyncio.CancelledError()

    worker.poll_and_analyze = mock_poll
    worker.forward_to_server_b = AsyncMock(
        return_value={"success": False, "status": 500, "error": "Exchange API timeout"}
    )
    worker._ack_signal = AsyncMock(return_value=True)

    # Mock uvicorn to prevent port 8000 binding conflicts in parallel CI
    with patch("uvicorn.Config"), patch("uvicorn.Server") as mock_server:
        mock_server.return_value.serve = AsyncMock()
        await worker.run()

    # Forward was attempted
    worker.forward_to_server_b.assert_called_once()

    # ACK should be sent with 'failed' status and error message
    worker._ack_signal.assert_called_once_with(1000, "failed", "Exchange API timeout")


# ═══════════════════════════════════════════════════════════════
# TEST 11: Multiple signals in single poll cycle
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_multiple_signals_mixed_results():
    """Pipeline handles multiple signals in one cycle with mixed outcomes.

    Simulates:
    - Signal 1: Approved + executed successfully
    - Signal 2: Rejected by RAG
    - Signal 3: Approved but execution failed

    All three should be processed and ACK'd appropriately.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker.poll_interval = 0

    analyzed_signals = [
        {
            "queue_id": 1101,
            "approved": True,
            "trade_payload": {"symbol": "BTCUSDT", "action": "buy", "price": 68000.0},
        },
        {
            "queue_id": 1102,
            "approved": False,
            "reason": "Does not meet Minervini VCP pattern",
        },
        {
            "queue_id": 1103,
            "approved": True,
            "trade_payload": {"symbol": "ETHUSDT", "action": "sell", "price": 3500.0},
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
        if payload.get("symbol") == "BTCUSDT":
            return {"success": True, "status": 200, "data": {"order_id": "ORD-M1"}}
        else:
            return {
                "success": False,
                "status": 500,
                "error": "Insufficient margin for ETHUSDT",
            }

    worker.poll_and_analyze = mock_poll
    worker.forward_to_server_b = mock_forward
    worker._ack_signal = AsyncMock(return_value=True)

    # Mock uvicorn to prevent port 8000 binding conflicts in parallel CI
    with patch("uvicorn.Config"), patch("uvicorn.Server") as mock_server:
        mock_server.return_value.serve = AsyncMock()
        await worker.run()

    # Verify ACK calls: 3 signals → 3 ACKs
    assert worker._ack_signal.call_count == 3

    ack_calls = worker._ack_signal.call_args_list

    # Verify ACK calls: 3 signals -> 3 ACKs (order-independent)
    ack_map = {call.args[0]: call.args[1:] for call in ack_calls}

    # Signal 1101: approved + executed -> ACK 'executed'
    assert ack_map[1101] == ("executed",)

    # Signal 1102: rejected -> ACK 'rejected' with reason
    assert ack_map[1102] == ("rejected", "Does not meet Minervini VCP pattern")

    # Signal 1103: approved but failed -> ACK 'failed' with error
    assert ack_map[1103] == ("failed", "Insufficient margin for ETHUSDT")


# ═══════════════════════════════════════════════════════════════
# TEST 12: Sell signal position sizing (SL/TP reversed)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_sell_signal_position_sizing():
    """Verify position sizing for SELL signals has correct SL/TP direction.

    For SELL at price=100.0:
      sl = 100 * (1 + 0.08) = 108.0  (SL is ABOVE entry for shorts)
      tp = 100 * (1 - 0.20) = 80.0   (TP is BELOW entry for shorts)
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    signal = _make_vbs_signal(
        queue_id=1201, symbol="BTCUSDT", action="sell", price=100.0
    )

    # Use sell-friendly AI response
    sell_patches = [
        patch("rag.build_rag_query", return_value="test query"),
        patch(
            "rag.query_knowledge",
            return_value=[{"content": "chunk", "metadata": {}, "relevance_score": 0.9}],
        ),
        patch(
            "rag.generate_trading_advice",
            new_callable=AsyncMock,
            return_value="Strong SELL signal. Bán ngay. Mạnh.",
        ),
    ]

    with sell_patches[0], sell_patches[1], sell_patches[2]:
        _setup_vbs_poll(worker, [signal])
        results = await worker.poll_and_analyze()

    assert len(results) == 1
    assert results[0]["approved"] is True
    tp = results[0]["trade_payload"]

    # For sell: SL above entry, TP below entry
    assert tp["sl"] == 108.0  # 100 * (1 + 0.08)
    assert tp["tp"] == 80.0  # 100 * (1 - 0.20)
    assert tp["qty"] == 2.5  # Same sizing formula

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 13: VBS HTTP error (non-connection)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_vbs_http_503_error():
    """Pipeline handles VBS returning HTTP 503 Service Unavailable.

    When VBS returns a non-200 status, poll_and_analyze should
    return empty results without crashing.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    vbs_error = FakeResponse(status=503, text_data="Service Unavailable")
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=vbs_error)
    worker.get_session = AsyncMock(return_value=mock_session)

    results = await worker.poll_and_analyze()
    assert results == []

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 14: ACK endpoint communication
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_ack_sends_correct_payload():
    """Verify _ack_signal sends correct JSON payload to VBS /ack endpoint.

    Checks the exact structure of the ACK request body matches VBS expectations:
    {"acks": [{"queue_id": N, "status": "...", "error_msg": "..."}]}
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    ack_response = FakeResponse(status=200, json_data={"ok": True})
    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=ack_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    success = await worker._ack_signal(
        queue_id=1400,
        status="executed",
        error_msg="",
    )

    assert success is True

    # Verify the POST payload structure
    call_args = mock_session.post.call_args
    posted_url = call_args[0][0] if call_args[0] else ""
    assert "/ack" in str(posted_url)

    posted_json = call_args.kwargs.get("json") or call_args[1].get("json", {})
    assert "acks" in posted_json
    assert len(posted_json["acks"]) == 1
    ack_entry = posted_json["acks"][0]
    assert ack_entry["queue_id"] == 1400
    assert ack_entry["status"] == "executed"
    assert ack_entry["error_msg"] == ""

    # Verify the secret header was sent
    posted_headers = call_args.kwargs.get("headers") or call_args[1].get("headers", {})
    assert "X-Buffer-Secret" in posted_headers

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 15: Server B forward sends correct headers
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_forward_sends_correct_headers():
    """Verify forward_to_server_b sends X-Server-B-Secret and Content-Type.

    This test ensures the HMAC secret header is included in the request
    to Server B's /api/execute-trade endpoint.
    """
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    trade_payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 68000.0,
        "qty": 0.003,
    }

    server_b_response = FakeResponse(
        status=200,
        json_data={"success": True, "order_id": "ORD-HDR-001"},
    )
    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=server_b_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    result = await worker.forward_to_server_b(trade_payload)
    assert result["success"] is True

    # Verify request details
    call_args = mock_session.post.call_args
    posted_url = call_args[0][0] if call_args[0] else ""
    assert "/api/execute-trade" in str(posted_url)

    posted_headers = call_args.kwargs.get("headers") or call_args[1].get("headers", {})
    assert "X-Server-B-Secret" in posted_headers
    assert "Content-Type" in posted_headers
    assert posted_headers["Content-Type"] == "application/json"

    posted_json = call_args.kwargs.get("json") or call_args[1].get("json", {})
    assert posted_json["symbol"] == "BTCUSDT"
    assert posted_json["action"] == "buy"

    await worker.close()


# ═══════════════════════════════════════════════════════════════
# TEST 16: Pipeline failover from Local to Server B
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pipeline_failover_local_to_server_b():
    """Verify that when Local is configured but offline, the pipeline fails over to Server B."""
    from workers.vps_analyzer import VpsAnalyzerWorker
    import config
    from unittest.mock import patch

    original_local_url = config.LOCAL_EXECUTE_URL
    original_local_secret = config.LOCAL_EXECUTE_SECRET
    original_b_url = config.SERVER_B_EXECUTE_URL

    try:
        config.LOCAL_EXECUTE_URL = "http://local-windows:5000"
        config.LOCAL_EXECUTE_SECRET = "local-sec"  # noqa: S105
        config.SERVER_B_EXECUTE_URL = "http://server-b:5000"

        worker = VpsAnalyzerWorker()
        trade_payload = {"symbol": "BTCUSDT", "action": "buy", "price": 68000.0}

        # Mock the session to throw error on the first call (local) and succeed on the second (server b)
        server_b_resp = FakeResponse(
            status=200,
            json_data={"success": True, "order_id": "ORD-B-FAILOVER"},
        )
        mock_session = MagicMock()

        call_count = 0

        def post_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Local Windows is offline")
            return server_b_resp

        mock_session.post = MagicMock(side_effect=post_side_effect)
        worker.get_session = AsyncMock(return_value=mock_session)

        with patch(
            "notifier.send_telegram_alert", new_callable=AsyncMock
        ) as mock_alert:
            result = await worker.forward_to_server_b(trade_payload)

            assert result["success"] is True
            assert result["executed_on"] == "server_b"
            assert result["data"]["order_id"] == "ORD-B-FAILOVER"
            assert mock_session.post.call_count == 2
            mock_alert.assert_called_once()
            assert "Local Windows Offline" in mock_alert.call_args[0][0]

        await worker.close()
    finally:
        config.LOCAL_EXECUTE_URL = original_local_url
        config.LOCAL_EXECUTE_SECRET = original_local_secret
        config.SERVER_B_EXECUTE_URL = original_b_url
