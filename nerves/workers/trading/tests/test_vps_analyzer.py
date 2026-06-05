"""
test_vps_analyzer.py — Unit tests for VpsAnalyzerWorker (Phase 5).

Tests all methods of the VPS Analyzer Worker with mocked HTTP calls
and mocked RAG functions. No real network or AI calls are made.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import config


@pytest.fixture(autouse=True)
def mock_rag_init():
    with patch("rag.init_vector_db", new_callable=AsyncMock, return_value=True):
        yield


@pytest.fixture(autouse=True)
def mock_uvicorn_serve():
    with patch("uvicorn.Server.serve", new_callable=AsyncMock) as mock_serve:
        yield mock_serve


@pytest.fixture(autouse=True)
def mock_scheduler_start_stop():
    with (
        patch("scheduler.start_scheduler") as mock_start,
        patch("scheduler.stop_scheduler") as mock_stop,
    ):
        yield mock_start, mock_stop


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_vbs_signal(queue_id=1, symbol="BTCUSDT", action="buy", price=68000.0):
    """Create a sample VBS signal dict."""
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
    """Fake aiohttp response for mocking session.get/post."""

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


# ── poll_and_analyze() ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_and_analyze_success():
    """poll_and_analyze returns analyzed results for received signals."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    # Mock _analyze_signal to return a trade payload
    trade_payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 68000.0,
        "qty": 0.003,
        "sl": 62560.0,
        "tp": 81600.0,
    }
    worker._analyze_signal = AsyncMock(return_value=trade_payload)

    vbs_response = FakeResponse(
        status=200,
        json_data={"signals": [_make_vbs_signal(queue_id=42)]},
    )

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=vbs_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    results = await worker.poll_and_analyze()

    assert len(results) == 1
    assert results[0]["queue_id"] == 42
    assert results[0]["approved"] is True
    assert results[0]["trade_payload"] == trade_payload
    worker._analyze_signal.assert_called_once()

    await worker.close()


@pytest.mark.asyncio
async def test_poll_and_analyze_empty_response():
    """poll_and_analyze returns empty list when VBS has no signals."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    vbs_response = FakeResponse(status=200, json_data={"signals": []})

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=vbs_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    results = await worker.poll_and_analyze()
    assert results == []
    await worker.close()


@pytest.mark.asyncio
async def test_poll_and_analyze_vbs_http_error():
    """poll_and_analyze returns empty list on VBS HTTP error."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    vbs_response = FakeResponse(status=503, text_data="Service Unavailable")

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=vbs_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    results = await worker.poll_and_analyze()
    assert results == []
    await worker.close()


@pytest.mark.asyncio
async def test_poll_and_analyze_vbs_connection_error():
    """poll_and_analyze returns empty list when VBS is unreachable."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    mock_session = MagicMock()
    mock_session.get = MagicMock(side_effect=Exception("Connection refused"))
    worker.get_session = AsyncMock(return_value=mock_session)

    results = await worker.poll_and_analyze()
    assert results == []
    await worker.close()


@pytest.mark.asyncio
async def test_poll_and_analyze_rejected_signal():
    """poll_and_analyze marks signal as rejected when _analyze_signal returns None."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker._analyze_signal = AsyncMock(return_value=None)

    vbs_response = FakeResponse(
        status=200,
        json_data={"signals": [_make_vbs_signal(queue_id=99)]},
    )

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=vbs_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    results = await worker.poll_and_analyze()

    assert len(results) == 1
    assert results[0]["queue_id"] == 99
    assert results[0]["approved"] is False
    assert (
        "rejected" in results[0]["reason"].lower()
        or "criteria" in results[0]["reason"].lower()
    )
    await worker.close()


@pytest.mark.asyncio
async def test_poll_and_analyze_analysis_exception():
    """poll_and_analyze handles exception in _analyze_signal gracefully."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker._analyze_signal = AsyncMock(side_effect=RuntimeError("RAG crashed"))

    vbs_response = FakeResponse(
        status=200,
        json_data={"signals": [_make_vbs_signal(queue_id=88)]},
    )

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=vbs_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    results = await worker.poll_and_analyze()

    assert len(results) == 1
    assert results[0]["queue_id"] == 88
    assert results[0]["approved"] is False
    assert "error" in results[0]["reason"].lower()
    await worker.close()


# ── _analyze_signal() ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_signal_approved():
    """_analyze_signal returns trade payload when AI approves the signal."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    signal = _make_vbs_signal(queue_id=10, price=50000.0)

    with (
        patch("rag.build_rag_query", return_value="VCP breakout query"),
        patch(
            "rag.query_knowledge",
            return_value=[{"content": "chunk", "metadata": {}, "relevance_score": 0.9}],
        ),
        patch(
            "rag.generate_trading_advice",
            new_callable=AsyncMock,
            return_value="🟢 Tín hiệu Mạnh. Nên BUY tại pivot. SL -8%.",
        ),
    ):
        result = await worker._analyze_signal(signal)

    assert result is not None
    assert result["symbol"] == "BTCUSDT"
    assert result["action"] == "buy"
    assert result["price"] == 50000.0
    assert result["qty"] > 0
    assert result["sl"] > 0
    assert result["tp"] > 0
    assert "analysis" in result
    await worker.close()


@pytest.mark.asyncio
async def test_analyze_signal_rejected_by_ai():
    """_analyze_signal returns None when AI rejects with warning keywords."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    signal = _make_vbs_signal(queue_id=11, price=50000.0)

    with (
        patch("rag.build_rag_query", return_value="test query"),
        patch(
            "rag.query_knowledge",
            return_value=[{"content": "chunk", "metadata": {}, "relevance_score": 0.5}],
        ),
        patch(
            "rag.generate_trading_advice",
            new_callable=AsyncMock,
            return_value="⚠️ RAG Analysis không khả dụng (thiếu API key).",
        ),
    ):
        result = await worker._analyze_signal(signal)

    assert result is None
    await worker.close()


@pytest.mark.asyncio
async def test_analyze_signal_invalid_price():
    """_analyze_signal returns None for zero/invalid price."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    signal = _make_vbs_signal(queue_id=12, price=0)

    with (
        patch("rag.build_rag_query", return_value="test query"),
        patch("rag.query_knowledge", return_value=[]),
        patch(
            "rag.generate_trading_advice",
            new_callable=AsyncMock,
            return_value="Buy signal looks good",
        ),
    ):
        result = await worker._analyze_signal(signal)

    assert result is None
    await worker.close()


@pytest.mark.asyncio
async def test_analyze_signal_position_sizing():
    """_analyze_signal computes correct position sizing from config."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    signal = _make_vbs_signal(queue_id=13, price=100.0, action="buy")

    # With defaults: RISK_PER_TRADE=0.02, STOP_LOSS_PCT=0.08, MAX_QUOTE_QTY=1000
    # risk_amount = 1000 * 0.02 = 20
    # dollar_risk_per_unit = 100 * 0.08 = 8
    # qty = 20 / 8 = 2.5
    # quote_value = 2.5 * 100 = 250 <= 1000 (under cap)
    # sl = 100 * (1 - 0.08) = 92
    # tp = 100 * (1 + 0.20) = 120

    with (
        patch("rag.build_rag_query", return_value="test query"),
        patch(
            "rag.query_knowledge",
            return_value=[{"content": "chunk", "metadata": {}, "relevance_score": 0.9}],
        ),
        patch(
            "rag.generate_trading_advice",
            new_callable=AsyncMock,
            return_value="Strong BUY signal.",
        ),
    ):
        result = await worker._analyze_signal(signal)

    assert result is not None
    assert result["qty"] == 2.5
    assert result["sl"] == 92.0
    assert result["tp"] == 120.0
    await worker.close()


@pytest.mark.asyncio
async def test_analyze_signal_sell_position_sizing():
    """_analyze_signal computes correct SL/TP for sell signals."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    signal = _make_vbs_signal(queue_id=14, price=100.0, action="sell")

    # For sell: sl = 100 * (1 + 0.08) = 108, tp = 100 * (1 - 0.20) = 80

    with (
        patch("rag.build_rag_query", return_value="test query"),
        patch(
            "rag.query_knowledge",
            return_value=[{"content": "chunk", "metadata": {}, "relevance_score": 0.9}],
        ),
        patch(
            "rag.generate_trading_advice",
            new_callable=AsyncMock,
            return_value="Strong SELL signal. Bán ngay.",
        ),
    ):
        result = await worker._analyze_signal(signal)

    assert result is not None
    assert result["sl"] == 108.0
    assert result["tp"] == 80.0
    await worker.close()


# ── forward_to_server_b() ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forward_to_server_b_success():
    """forward_to_server_b returns success when Server B accepts trade."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    trade_payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "price": 68000.0,
        "qty": 0.003,
        "sl": 62560.0,
        "tp": 81600.0,
        "analysis": "Buy approved",
    }

    server_b_response = FakeResponse(
        status=200,
        json_data={"status": "ok", "order_id": "ORD-456"},
    )

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=server_b_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    result = await worker.forward_to_server_b(trade_payload)

    assert result["success"] is True
    assert result["status"] == 200
    assert result["data"]["order_id"] == "ORD-456"
    await worker.close()


@pytest.mark.asyncio
async def test_forward_to_server_b_unauthorized():
    """forward_to_server_b returns failure on 401 from Server B."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    trade_payload = {"symbol": "BTCUSDT", "action": "buy", "price": 68000.0}

    server_b_response = FakeResponse(
        status=401,
        json_data={"detail": "Invalid secret"},
    )

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=server_b_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    result = await worker.forward_to_server_b(trade_payload)

    assert result["success"] is False
    assert result["status"] == 401
    assert "Invalid secret" in result["error"]
    await worker.close()


@pytest.mark.asyncio
async def test_forward_to_server_b_connection_error():
    """forward_to_server_b returns failure when Server B is unreachable."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    trade_payload = {"symbol": "BTCUSDT", "action": "buy", "price": 68000.0}

    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=Exception("Connection refused"))
    worker.get_session = AsyncMock(return_value=mock_session)

    result = await worker.forward_to_server_b(trade_payload)

    assert result["success"] is False
    assert result["status"] == 0
    assert "Connection refused" in result["error"]
    await worker.close()


# ── _ack_signal() ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ack_signal_success():
    """_ack_signal returns True when VBS accepts the ACK."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    ack_response = FakeResponse(status=200, json_data={"ok": True})

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=ack_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    result = await worker._ack_signal(42, "executed")

    assert result is True

    # Verify the POST was called with correct payload structure
    call_args = mock_session.post.call_args
    posted_json = call_args.kwargs.get("json") or call_args[1].get("json", {})
    assert "acks" in posted_json
    assert len(posted_json["acks"]) == 1
    assert posted_json["acks"][0]["queue_id"] == 42
    assert posted_json["acks"][0]["status"] == "executed"
    await worker.close()


@pytest.mark.asyncio
async def test_ack_signal_failure():
    """_ack_signal returns False when VBS rejects the ACK."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    ack_response = FakeResponse(status=500, text_data="Internal Server Error")

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=ack_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    result = await worker._ack_signal(42, "executed")

    assert result is False
    await worker.close()


@pytest.mark.asyncio
async def test_ack_signal_connection_error():
    """_ack_signal returns False when VBS is unreachable."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=Exception("Connection refused"))
    worker.get_session = AsyncMock(return_value=mock_session)

    result = await worker._ack_signal(42, "executed")

    assert result is False
    await worker.close()


# ── run() loop ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_loop_approved_signal():
    """run() forwards approved signals to Server B and ACKs them."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker.poll_interval = 0  # no sleep for tests

    analyzed_signals = [
        {
            "queue_id": 100,
            "approved": True,
            "trade_payload": {"symbol": "BTCUSDT", "action": "buy", "price": 68000.0},
        }
    ]

    call_count = 0

    async def mock_poll():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return analyzed_signals
        # Cancel after first iteration
        raise asyncio.CancelledError()

    worker.poll_and_analyze = mock_poll
    worker.forward_to_server_b = AsyncMock(return_value={"success": True})
    worker._ack_signal = AsyncMock(return_value=True)

    await worker.run()

    worker.forward_to_server_b.assert_called_once_with(
        analyzed_signals[0]["trade_payload"]
    )
    worker._ack_signal.assert_called_once_with(100, "executed")


@pytest.mark.asyncio
async def test_run_loop_rejected_signal():
    """run() ACKs rejected signals without forwarding."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker.poll_interval = 0

    analyzed_signals = [
        {
            "queue_id": 200,
            "approved": False,
            "reason": "Does not meet criteria",
        }
    ]

    call_count = 0

    async def mock_poll():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return analyzed_signals
        raise asyncio.CancelledError()

    worker.poll_and_analyze = mock_poll
    worker.forward_to_server_b = AsyncMock()
    worker._ack_signal = AsyncMock(return_value=True)

    await worker.run()

    worker.forward_to_server_b.assert_not_called()
    worker._ack_signal.assert_called_once_with(
        200, "rejected", "Does not meet criteria"
    )


@pytest.mark.asyncio
async def test_run_loop_server_b_failure():
    """run() ACKs with 'failed' status when Server B rejects the trade."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker.poll_interval = 0

    analyzed_signals = [
        {
            "queue_id": 300,
            "approved": True,
            "trade_payload": {"symbol": "ETHUSDT", "action": "buy", "price": 3500.0},
        }
    ]

    call_count = 0

    async def mock_poll():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return analyzed_signals
        raise asyncio.CancelledError()

    worker.poll_and_analyze = mock_poll
    worker.forward_to_server_b = AsyncMock(
        return_value={"success": False, "error": "Insufficient margin"}
    )
    worker._ack_signal = AsyncMock(return_value=True)

    await worker.run()

    worker._ack_signal.assert_called_once_with(300, "failed", "Insufficient margin")


@pytest.mark.asyncio
async def test_run_loop_error_recovery():
    """run() continues after non-fatal exception in loop body."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker.poll_interval = 0

    call_count = 0

    async def mock_poll():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Transient network error")
        if call_count == 2:
            return []  # Recovered
        raise asyncio.CancelledError()

    worker.poll_and_analyze = mock_poll

    await worker.run()

    # Should have called poll 3 times (error, empty, cancel)
    assert call_count == 3


# ── Session management ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_creates_new():
    """get_session creates a new aiohttp.ClientSession."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    session = await worker.get_session()

    assert session is not None
    assert not session.closed

    await worker.close()
    assert session.closed


@pytest.mark.asyncio
async def test_get_session_reuses_existing():
    """get_session reuses existing session if not closed."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    session1 = await worker.get_session()
    session2 = await worker.get_session()

    assert session1 is session2

    await worker.close()


@pytest.mark.asyncio
async def test_close_idempotent():
    """close() is safe to call multiple times."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    await worker.get_session()

    await worker.close()
    await worker.close()  # Should not raise


# ── Multiple signals in one poll ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_and_analyze_multiple_signals():
    """poll_and_analyze processes multiple signals with mixed results."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()

    trade_payload = {"symbol": "BTCUSDT", "action": "buy", "price": 68000.0}
    call_index = 0

    async def mock_analyze(signal):
        nonlocal call_index
        call_index += 1
        if call_index == 1:
            return trade_payload  # approved
        return None  # rejected

    worker._analyze_signal = mock_analyze

    signals = [
        _make_vbs_signal(queue_id=50, symbol="BTCUSDT"),
        _make_vbs_signal(queue_id=51, symbol="ETHUSDT"),
    ]
    vbs_response = FakeResponse(status=200, json_data={"signals": signals})

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=vbs_response)
    worker.get_session = AsyncMock(return_value=mock_session)

    results = await worker.poll_and_analyze()

    assert len(results) == 2
    assert results[0]["approved"] is True
    assert results[0]["queue_id"] == 50
    assert results[1]["approved"] is False
    assert results[1]["queue_id"] == 51
    await worker.close()


# ── Local & Server B Failover Tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_forward_to_local_success():
    """If LOCAL_EXECUTE_URL is configured and succeeds, we use Local and don't call Server B."""
    from workers.vps_analyzer import VpsAnalyzerWorker
    import config

    original_local_url = config.LOCAL_EXECUTE_URL
    original_local_secret = config.LOCAL_EXECUTE_SECRET
    original_b_url = config.SERVER_B_EXECUTE_URL

    try:
        config.LOCAL_EXECUTE_URL = "http://local-windows:5000"
        config.LOCAL_EXECUTE_SECRET = "local-sec"
        config.SERVER_B_EXECUTE_URL = "http://server-b:5000"

        worker = VpsAnalyzerWorker()
        trade_payload = {"symbol": "BTCUSDT", "action": "buy", "price": 68000.0}

        local_response = FakeResponse(
            status=200, json_data={"success": True, "order_id": "LOCAL-123"}
        )

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=local_response)
        worker.get_session = AsyncMock(return_value=mock_session)

        result = await worker.forward_to_server_b(trade_payload)

        assert result["success"] is True
        assert result["executed_on"] == "local"
        assert result["data"]["order_id"] == "LOCAL-123"

        # Verify only one post call (to Local) was made
        assert mock_session.post.call_count == 1
        call_url = mock_session.post.call_args[0][0]
        assert "local-windows" in call_url

        await worker.close()
    finally:
        config.LOCAL_EXECUTE_URL = original_local_url
        config.LOCAL_EXECUTE_SECRET = original_local_secret
        config.SERVER_B_EXECUTE_URL = original_b_url


@pytest.mark.asyncio
async def test_forward_to_local_fails_fallback_to_server_b_success():
    """If Local fails (connection error or timeout), we log warning, send Telegram, and try Server B."""
    from workers.vps_analyzer import VpsAnalyzerWorker
    import config
    from unittest.mock import patch

    original_local_url = config.LOCAL_EXECUTE_URL
    original_local_secret = config.LOCAL_EXECUTE_SECRET
    original_b_url = config.SERVER_B_EXECUTE_URL
    original_b_secret = config.SERVER_B_SECRET

    try:
        config.LOCAL_EXECUTE_URL = "http://local-windows:5000"
        config.LOCAL_EXECUTE_SECRET = "local-sec"
        config.SERVER_B_EXECUTE_URL = "http://server-b:5000"
        config.SERVER_B_SECRET = "b-sec"

        worker = VpsAnalyzerWorker()
        trade_payload = {"symbol": "BTCUSDT", "action": "buy", "price": 68000.0}

        # Mock post side_effects: 1st call (Local) raises connection error, 2nd call (Server B) succeeds
        b_response = FakeResponse(
            status=200, json_data={"success": True, "order_id": "B-456"}
        )

        mock_session = MagicMock()

        # Side effect to raise error on first call and return b_response on second
        call_count = 0

        def post_side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection refused to Local Windows")
            return b_response

        mock_session.post = MagicMock(side_effect=post_side_effect)
        worker.get_session = AsyncMock(return_value=mock_session)

        # Mock Telegram alert to avoid real requests
        with patch(
            "notifier.send_telegram_alert", new_callable=AsyncMock
        ) as mock_alert:
            result = await worker.forward_to_server_b(trade_payload)

            assert result["success"] is True
            assert result["executed_on"] == "server_b"
            assert result["data"]["order_id"] == "B-456"
            assert mock_session.post.call_count == 2
            mock_alert.assert_called_once()
            assert "Local Windows Offline" in mock_alert.call_args[0][0]

        await worker.close()
    finally:
        config.LOCAL_EXECUTE_URL = original_local_url
        config.LOCAL_EXECUTE_SECRET = original_local_secret
        config.SERVER_B_EXECUTE_URL = original_b_url
        config.SERVER_B_SECRET = original_b_secret


# ── Dynamic ATR-based Sizing & SL/TP Tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_calculate_sl_tp_with_atr():
    """_calculate_sl_tp calculates SL/TP using ATR if present in payload or root."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    price = 100.0

    original_risk = config.RISK_PER_TRADE
    original_max = config.MAX_QUOTE_QTY
    original_sl_pct = config.STOP_LOSS_PCT
    original_tp_pct = config.TAKE_PROFIT_PCT

    try:
        config.RISK_PER_TRADE = 0.02
        config.MAX_QUOTE_QTY = 1000.0
        config.STOP_LOSS_PCT = 0.08
        config.TAKE_PROFIT_PCT = 0.20

        # Test case 1: Buy signal with ATR in payload
        signal_buy_payload = {"payload": {"atr": 5.0}}
        sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_buy_payload)
        # Long: SL = Price - 2*ATR = 100 - 10 = 90
        # Long: TP = Price + 5*ATR = 100 + 25 = 125
        assert sl == 90.0
        assert tp == 125.0

        # Test case 2: Sell signal with atr_value at root
        signal_sell_root = {"atr_value": 4.0}
        sl, tp = worker._calculate_sl_tp(price, "sell", signal=signal_sell_root)
        # Short: SL = Price + 2*ATR = 100 + 8 = 108
        # Short: TP = Price - 5*ATR = 100 - 20 = 80
        assert sl == 108.0
        assert tp == 80.0

        # Test case 3: Fallback when ATR is zero
        signal_zero_atr = {"payload": {"atr": 0.0}}
        sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_zero_atr)
        original_sl = round(price * (1 - config.STOP_LOSS_PCT), 8)
        original_tp = round(price * (1 + config.TAKE_PROFIT_PCT), 8)
        assert sl == original_sl
        assert tp == original_tp

    finally:
        config.RISK_PER_TRADE = original_risk
        config.MAX_QUOTE_QTY = original_max
        config.STOP_LOSS_PCT = original_sl_pct
        config.TAKE_PROFIT_PCT = original_tp_pct


@pytest.mark.asyncio
async def test_calculate_position_size_with_atr():
    """_calculate_position_size uses dynamic risk based on ATR and caps total value."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    price = 100.0

    original_risk = config.RISK_PER_TRADE
    original_max = config.MAX_QUOTE_QTY
    original_sl_pct = config.STOP_LOSS_PCT
    original_tp_pct = config.TAKE_PROFIT_PCT

    try:
        config.RISK_PER_TRADE = 0.02
        config.MAX_QUOTE_QTY = 1000.0
        config.STOP_LOSS_PCT = 0.08
        config.TAKE_PROFIT_PCT = 0.20

        # Config values: MAX_QUOTE_QTY = 1000, RISK_PER_TRADE = 0.02
        # So risk_amount = 1000 * 0.02 = 20
        # Test case 1: ATR = 5.0. Dynamic sl_pct = 2 * 5.0 / 100 = 0.10 (10%)
        # qty = risk_amount / (price * sl_pct) = 20 / (100 * 0.10) = 2.0
        signal_payload = {"payload": {"atr_value": 5.0}}
        qty = worker._calculate_position_size(price, "buy", signal=signal_payload)
        assert qty == 2.0

        # Test case 2: Large ATR makes sl_pct huge, or small ATR makes sl_pct tiny.
        # If ATR = 0.1. Dynamic sl_pct = 0.2 / 100 = 0.002
        # qty = 20 / (100 * 0.002) = 100.0
        # Total quote value = 100 * 100 = 10000 > 1000. Cap to portfolio / price = 1000 / 100 = 10.0
        signal_tiny_atr = {"atr": 0.1}
        qty_capped = worker._calculate_position_size(
            price, "buy", signal=signal_tiny_atr
        )
        assert qty_capped == 10.0

        # Test case 3: Fallback when signal is None
        qty_fallback = worker._calculate_position_size(price, "buy", signal=None)
        # sl_pct = config.STOP_LOSS_PCT = 0.08
        # qty = 20 / (100 * 0.08) = 20 / 8 = 2.5
        assert qty_fallback == 2.5

    finally:
        config.RISK_PER_TRADE = original_risk
        config.MAX_QUOTE_QTY = original_max
        config.STOP_LOSS_PCT = original_sl_pct
        config.TAKE_PROFIT_PCT = original_tp_pct


# ── V2 Integration Features Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_endpoint_healthy():
    """/health endpoint returns correct JSON structure and values."""
    from workers.vps_analyzer import app
    from httpx import AsyncClient
    from workers.liveness_monitor import ServerHealth

    servers_mock = [
        ServerHealth(name="SERVER_A", url="", is_healthy=True),
        ServerHealth(name="SERVER_B", url="", is_healthy=True),
    ]

    with (
        patch("workers.vps_analyzer._get_servers", return_value=servers_mock),
        patch(
            "workers.ntp_monitor.last_drift_results",
            {"server_a": {"drift_ms": 1.5}, "server_b": {"drift_ms": 2.1}},
        ),
        patch("shutil.disk_usage", return_value=(1000, 400, 600)),
    ):
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["liveness_status_server_a"] == "healthy"
        assert data["liveness_status_server_b"] == "healthy"
        assert data["disk_usage_pct"] == 40.0
        assert data["ntp_clock_drift_ms"] == 2.1
        assert data["circuit_breaker_status"] == "closed"


@pytest.mark.asyncio
async def test_health_endpoint_unhealthy_servers():
    """/health endpoint correctly reports unhealthy status for Server A/B."""
    from workers.vps_analyzer import app
    from httpx import AsyncClient
    from workers.liveness_monitor import ServerHealth

    servers_mock = [
        ServerHealth(name="SERVER_A", url="", is_healthy=False),
        ServerHealth(name="SERVER_B", url="", is_healthy=False),
    ]

    with (
        patch("workers.vps_analyzer._get_servers", return_value=servers_mock),
        patch("workers.ntp_monitor.last_drift_results", {}),
        patch("shutil.disk_usage", return_value=(1000, 400, 600)),
    ):
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["liveness_status_server_a"] == "unhealthy"
        assert data["liveness_status_server_b"] == "unhealthy"
        assert data["disk_usage_pct"] == 40.0
        assert data["ntp_clock_drift_ms"] == 0.0


@pytest.mark.asyncio
async def test_metrics_endpoint_json():
    """/metrics returns JSON data if Accept header requests application/json."""
    from workers.vps_analyzer import app
    from httpx import AsyncClient
    from workers.liveness_monitor import ServerHealth

    servers_mock = [
        ServerHealth(name="SERVER_A", url="", is_healthy=True),
        ServerHealth(name="SERVER_B", url="", is_healthy=False),
    ]

    with (
        patch("workers.vps_analyzer._get_servers", return_value=servers_mock),
        patch(
            "workers.ntp_monitor.last_drift_results", {"server_a": {"drift_ms": 3.4}}
        ),
        patch("shutil.disk_usage", return_value=(100, 35, 65)),
    ):
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/metrics", headers={"accept": "application/json"})

        assert response.status_code == 200
        data = response.json()
        assert data["liveness_status_server_a"] == 1.0
        assert data["liveness_status_server_b"] == 0.0
        assert data["disk_usage_pct"] == 35.0
        assert data["ntp_clock_drift_ms"] == 3.4
        assert data["circuit_breaker_state"] == 0.0


@pytest.mark.asyncio
async def test_metrics_endpoint_prometheus_text():
    """/metrics returns Prometheus gauge format by default."""
    from workers.vps_analyzer import app
    from httpx import AsyncClient
    from workers.liveness_monitor import ServerHealth

    servers_mock = [
        ServerHealth(name="SERVER_A", url="", is_healthy=True),
        ServerHealth(name="SERVER_B", url="", is_healthy=False),
    ]

    with (
        patch("workers.vps_analyzer._get_servers", return_value=servers_mock),
        patch(
            "workers.ntp_monitor.last_drift_results", {"server_a": {"drift_ms": 3.4}}
        ),
        patch("shutil.disk_usage", return_value=(100, 35, 65)),
    ):
        import httpx

        transport = httpx.ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/metrics")

        assert response.status_code == 200
        text = response.text
        assert "# HELP liveness_status_server_a" in text
        assert "liveness_status_server_a 1.0" in text
        assert "liveness_status_server_b 0.0" in text
        assert "disk_usage_pct 35.0" in text
        assert "ntp_clock_drift_ms 3.4" in text
        assert "circuit_breaker_state 0.0" in text


@pytest.mark.asyncio
async def test_run_startup_sequences():
    """run() initializes database, starts scheduler, starts health server, and configures logging."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    worker.poll_interval = 0

    # We will trigger the shutdown event immediately to exit the run loop
    async def mock_poll():
        worker._shutdown_event.set()
        return []

    worker.poll_and_analyze = mock_poll

    with (
        patch(
            "rag.init_vector_db", new_callable=AsyncMock, return_value=True
        ) as mock_db,
        patch("scheduler.start_scheduler") as mock_start_sched,
        patch("scheduler.stop_scheduler") as mock_stop_sched,
        patch("workers.vps_analyzer.setup_logging") as mock_setup_log,
        patch("uvicorn.Server.serve", new_callable=AsyncMock) as mock_uv_serve,
    ):
        await worker.run()

        mock_db.assert_called_once()
        mock_start_sched.assert_called_once()
        mock_stop_sched.assert_called_once()
        mock_setup_log.assert_called()
        mock_uv_serve.assert_called_once()
