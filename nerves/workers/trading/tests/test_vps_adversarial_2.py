"""
test_vps_adversarial_2.py — Adversarial unit/integration tests for Server C VPS Signal Pipeline.
Focuses on concurrent requests (idempotency race conditions), Server B execute endpoint failure modes (500, 404, invalid JSON), and webhook payloads with invalid types for ATR.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import ContentTypeError

import config
import database
from core.events import SignalReceived
from workers.vps_consumer import VpsSignalConsumer
from workers.vps_analyzer import VpsAnalyzerWorker


def _make_vbs_signal(queue_id=1, symbol="BTCUSDT", action="buy", price=100.0, atr=None):
    """Create a sample VBS signal dict with optional ATR."""
    payload = {
        "symbol": symbol,
        "action": action,
        "price": price,
        "alert_type": "vcp_breakout",
        "volume": 5000000,
        "volume_avg": 3000000,
        "exchange": "binance",
    }
    if atr is not None:
        payload["atr"] = atr

    return {
        "queue_id": queue_id,
        "symbol": symbol,
        "action": action,
        "price": price,
        "quote_qty": 10.0,
        "age_minutes": 5.0,
        "interval": "1h",
        "payload": payload,
    }


class NonJsonResponse:
    """Fake aiohttp response that raises ContentTypeError on json()."""

    def __init__(self, status=200, text_data="HTML page"):
        self.status = status
        self._text_data = text_data
        self.request_info = MagicMock()
        self.history = []
        self.headers = {}

    async def json(self):
        raise ContentTypeError(
            MagicMock(),
            MagicMock(),
            message="Attempt to decode JSON with unexpected mimetype",
        )

    async def text(self):
        return self._text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeResponse:
    """Fake aiohttp response for mocking session.get/post."""

    def __init__(self, status=200, json_data=None, text_data=""):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data
        self.request_info = MagicMock()
        self.history = []
        self.headers = {}

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ── Concurrent duplicate queue ID (idempotency checks) ───────────────────


@pytest.mark.asyncio
async def test_concurrent_duplicate_queue_id(tmp_path):
    """
    Verify that if the consumer receives two concurrent _process_signal calls for the
    same vbs_queue_id, it is prone to race condition due to lack of DB-level UNIQUE constraint.
    """
    config.DB_PATH = str(tmp_path / "test_vps.db")
    await database.init_db()

    consumer = VpsSignalConsumer()
    consumer.send_acks = AsyncMock(return_value=True)

    signal = _make_vbs_signal(
        queue_id=201, symbol="BTCUSDT", action="buy", price=68000.0
    )

    # To force the race condition deterministically, we synchronize both tasks
    # so they both perform their check (SELECT) before either performs their insert.
    original_insert = database.insert_signal
    reached_insert = 0
    event = asyncio.Event()

    async def mock_insert_signal(*args, **kwargs):
        nonlocal reached_insert
        reached_insert += 1
        if reached_insert < 2:
            await event.wait()
        else:
            event.set()
        return await original_insert(*args, **kwargs)

    # We will gather two concurrent runs of _process_signal for the same queue_id
    with patch("database.insert_signal", side_effect=mock_insert_signal):
        with patch(
            "core.event_bus.bus.emit_background", new_callable=AsyncMock
        ) as mock_emit:
            await asyncio.gather(
                consumer._process_signal(signal), consumer._process_signal(signal)
            )

            # Check DB count of signals with vbs_queue_id = 201
            import aiosqlite

            async with aiosqlite.connect(config.DB_PATH) as db:
                async with db.execute(
                    "SELECT id FROM signals WHERE vbs_queue_id = 201"
                ) as cur:
                    rows = await cur.fetchall()
                    # Verify that only one signal is inserted (idempotency enforced by DB constraint)
                    assert len(rows) == 1

            # Only one call to _process_signal proceeds to insert and emit SignalReceived event.
            assert mock_emit.call_count == 1

            # Verify the event is indeed SignalReceived
            event1 = mock_emit.call_args_list[0][0][0]
            assert isinstance(event1, SignalReceived)
            assert event1.symbol == "BTCUSDT"

    if hasattr(consumer, "_session") and consumer._session:
        await consumer.close()


# ── Server B Failures (500, 404, Invalid JSON) ───────────────────────────


@pytest.mark.asyncio
async def test_forward_to_server_b_500():
    """Verify that when Server B returns 500, forward_to_server_b returns failure payload instead of crashing."""
    worker = VpsAnalyzerWorker()
    trade_payload = {"symbol": "BTCUSDT", "action": "buy", "price": 100.0}

    # Force LOCAL_EXECUTE_URL to be empty so we fall back to Server B
    original_local_url = config.LOCAL_EXECUTE_URL
    config.LOCAL_EXECUTE_URL = ""

    try:
        # Mock Server B responding with 500
        server_b_resp = FakeResponse(
            status=500, json_data={"detail": "Server B Internal Error"}
        )
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=server_b_resp)
        worker.get_session = AsyncMock(return_value=mock_session)

        result = await worker.forward_to_server_b(trade_payload)

        assert result["success"] is False
        assert result["status"] == 500
        assert result["error"] == "Server B Internal Error"
    finally:
        config.LOCAL_EXECUTE_URL = original_local_url
        await worker.close()


@pytest.mark.asyncio
async def test_forward_to_server_b_404():
    """Verify that when Server B returns 404, forward_to_server_b returns failure payload instead of crashing."""
    worker = VpsAnalyzerWorker()
    trade_payload = {"symbol": "BTCUSDT", "action": "buy", "price": 100.0}

    original_local_url = config.LOCAL_EXECUTE_URL
    config.LOCAL_EXECUTE_URL = ""

    try:
        # Mock Server B responding with 404
        server_b_resp = FakeResponse(status=404, json_data={"detail": "Not Found"})
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=server_b_resp)
        worker.get_session = AsyncMock(return_value=mock_session)

        result = await worker.forward_to_server_b(trade_payload)

        assert result["success"] is False
        assert result["status"] == 404
        assert result["error"] == "Not Found"
    finally:
        config.LOCAL_EXECUTE_URL = original_local_url
        await worker.close()


@pytest.mark.asyncio
async def test_forward_to_server_b_non_json():
    """Verify that when Server B returns invalid JSON (e.g. text/HTML), it is handled via ContentTypeError."""
    worker = VpsAnalyzerWorker()
    trade_payload = {"symbol": "BTCUSDT", "action": "buy", "price": 100.0}

    original_local_url = config.LOCAL_EXECUTE_URL
    config.LOCAL_EXECUTE_URL = ""

    try:
        # Mock non-JSON response (e.g. status 502 with HTML from cloud provider)
        server_b_resp = NonJsonResponse(
            status=502, text_data="<html>Bad Gateway</html>"
        )
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=server_b_resp)
        worker.get_session = AsyncMock(return_value=mock_session)

        result = await worker.forward_to_server_b(trade_payload)

        assert result["success"] is False
        assert result["status"] == 500
        assert result["error"] == "Non-JSON from Server B"
    finally:
        config.LOCAL_EXECUTE_URL = original_local_url
        await worker.close()


# ── Webhook payload with invalid types for ATR ───────────────────────────


@pytest.mark.asyncio
async def test_invalid_types_for_atr_list():
    """Verify that an ATR field of list type falls back safely and does not crash SL/TP or sizing."""
    worker = VpsAnalyzerWorker()
    price = 100.0

    original_sl_pct = config.STOP_LOSS_PCT
    original_tp_pct = config.TAKE_PROFIT_PCT
    original_risk = config.RISK_PER_TRADE
    original_max = config.MAX_QUOTE_QTY

    try:
        config.STOP_LOSS_PCT = 0.08
        config.TAKE_PROFIT_PCT = 0.20
        config.RISK_PER_TRADE = 0.02
        config.MAX_QUOTE_QTY = 1000.0

        # ATR is a list (invalid type)
        signal_invalid_atr = _make_vbs_signal(atr=[1.5, 2.3])

        # Verify SL/TP calculation falls back to default percentages
        sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_invalid_atr)
        assert sl == price * (1 - config.STOP_LOSS_PCT)  # 92.0
        assert tp == price * (1 + config.TAKE_PROFIT_PCT)  # 120.0

        # Verify position sizing calculation falls back to default STOP_LOSS_PCT
        # risk_amount = 1000 * 0.02 = 20
        # qty = 20 / (100 * 0.08) = 2.5
        qty = worker._calculate_position_size(price, "buy", signal=signal_invalid_atr)
        assert qty == 2.5
    finally:
        config.STOP_LOSS_PCT = original_sl_pct
        config.TAKE_PROFIT_PCT = original_tp_pct
        config.RISK_PER_TRADE = original_risk
        config.MAX_QUOTE_QTY = original_max
        await worker.close()


@pytest.mark.asyncio
async def test_invalid_types_for_atr_dict():
    """Verify that an ATR field of dict type falls back safely and does not crash SL/TP or sizing."""
    worker = VpsAnalyzerWorker()
    price = 100.0

    original_sl_pct = config.STOP_LOSS_PCT
    original_tp_pct = config.TAKE_PROFIT_PCT
    original_risk = config.RISK_PER_TRADE
    original_max = config.MAX_QUOTE_QTY

    try:
        config.STOP_LOSS_PCT = 0.08
        config.TAKE_PROFIT_PCT = 0.20
        config.RISK_PER_TRADE = 0.02
        config.MAX_QUOTE_QTY = 1000.0

        # ATR is a dict (invalid type)
        signal_invalid_atr = _make_vbs_signal(atr={"val": 3.4})

        sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_invalid_atr)
        assert sl == price * (1 - config.STOP_LOSS_PCT)  # 92.0
        assert tp == price * (1 + config.TAKE_PROFIT_PCT)  # 120.0

        qty = worker._calculate_position_size(price, "buy", signal=signal_invalid_atr)
        assert qty == 2.5
    finally:
        config.STOP_LOSS_PCT = original_sl_pct
        config.TAKE_PROFIT_PCT = original_tp_pct
        config.RISK_PER_TRADE = original_risk
        config.MAX_QUOTE_QTY = original_max
        await worker.close()


@pytest.mark.asyncio
async def test_invalid_types_for_atr_string_fail():
    """Verify that an ATR field of non-numeric string type falls back safely and does not crash SL/TP or sizing."""
    worker = VpsAnalyzerWorker()
    price = 100.0

    original_sl_pct = config.STOP_LOSS_PCT
    original_tp_pct = config.TAKE_PROFIT_PCT
    original_risk = config.RISK_PER_TRADE
    original_max = config.MAX_QUOTE_QTY

    try:
        config.STOP_LOSS_PCT = 0.08
        config.TAKE_PROFIT_PCT = 0.20
        config.RISK_PER_TRADE = 0.02
        config.MAX_QUOTE_QTY = 1000.0

        # ATR is an invalid string
        signal_invalid_atr = _make_vbs_signal(atr="not_a_float")

        sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_invalid_atr)
        assert sl == price * (1 - config.STOP_LOSS_PCT)  # 92.0
        assert tp == price * (1 + config.TAKE_PROFIT_PCT)  # 120.0

        qty = worker._calculate_position_size(price, "buy", signal=signal_invalid_atr)
        assert qty == 2.5
    finally:
        config.STOP_LOSS_PCT = original_sl_pct
        config.TAKE_PROFIT_PCT = original_tp_pct
        config.RISK_PER_TRADE = original_risk
        config.MAX_QUOTE_QTY = original_max
        await worker.close()


@pytest.mark.asyncio
async def test_valid_types_for_atr_string_pass():
    """Verify that an ATR field of numeric string type (e.g. '1.5') is parsed correctly as float."""
    worker = VpsAnalyzerWorker()
    price = 100.0

    original_sl_pct = config.STOP_LOSS_PCT
    original_tp_pct = config.TAKE_PROFIT_PCT
    original_risk = config.RISK_PER_TRADE
    original_max = config.MAX_QUOTE_QTY

    try:
        config.STOP_LOSS_PCT = 0.08
        config.TAKE_PROFIT_PCT = 0.20
        config.RISK_PER_TRADE = 0.02
        config.MAX_QUOTE_QTY = 1000.0

        # ATR is a numeric string
        signal_valid_atr = _make_vbs_signal(atr="1.5")

        # SL = 100.0 - 2 * 1.5 = 97.0
        # TP = 100.0 + 5 * 1.5 = 107.5
        sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_valid_atr)
        assert sl == 97.0
        assert tp == 107.5

        # qty calculation:
        # sl_pct = 2 * 1.5 / 100 = 0.03
        # risk_amount = 1000 * 0.02 = 20
        # qty = 20 / (100 * 0.03) = 6.66666667
        qty = worker._calculate_position_size(price, "buy", signal=signal_valid_atr)
        assert qty == round(20 / (100 * 0.03), 8)
    finally:
        config.STOP_LOSS_PCT = original_sl_pct
        config.TAKE_PROFIT_PCT = original_tp_pct
        config.RISK_PER_TRADE = original_risk
        config.MAX_QUOTE_QTY = original_max
        await worker.close()
