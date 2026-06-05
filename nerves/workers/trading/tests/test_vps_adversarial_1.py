"""
test_vps_adversarial_1.py — Adversarial unit/integration tests for Server C VPS Signal Pipeline.
Focuses on extreme ATR values, missing keys, network failures, and timeout behaviors.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import ClientResponseError, ClientTimeout

import config


def _make_vbs_signal(
    queue_id=1,
    symbol="BTCUSDT",
    action="buy",
    price=100.0,
    atr=None,
    atr_in_payload=True,
):
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
        if atr_in_payload:
            payload["atr"] = atr
        else:
            payload["atr_value"] = atr

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


# ── Extreme ATR Value Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calculate_sl_tp_extreme_atr():
    """Test SL and TP calculation under extreme ATR values (negative, zero, very large, close to price)."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    price = 100.0

    original_sl_pct = config.STOP_LOSS_PCT
    original_tp_pct = config.TAKE_PROFIT_PCT

    try:
        config.STOP_LOSS_PCT = 0.08
        config.TAKE_PROFIT_PCT = 0.20

        # Case 1: ATR is zero -> Should fallback to percentage-based SL/TP
        signal_zero = _make_vbs_signal(atr=0.0)
        sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_zero)
        assert sl == price * (1 - config.STOP_LOSS_PCT)  # 92.0
        assert tp == price * (1 + config.TAKE_PROFIT_PCT)  # 120.0

        # Case 2: ATR is negative -> Should fallback to percentage-based SL/TP
        signal_neg = _make_vbs_signal(atr=-5.0)
        sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_neg)
        assert sl == price * (1 - config.STOP_LOSS_PCT)  # 92.0
        assert tp == price * (1 + config.TAKE_PROFIT_PCT)  # 120.0

        # Case 3: ATR is extremely large -> Should fall back to percentage-based SL/TP when SL/TP values are non-positive
        signal_huge = _make_vbs_signal(atr=1000000.0)
        sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_huge)
        assert sl == price * (1 - config.STOP_LOSS_PCT)
        assert tp == price * (1 + config.TAKE_PROFIT_PCT)

        # Case 4: ATR is close to price -> Should fall back to percentage-based SL/TP when SL/TP values are non-positive
        signal_close_buy = _make_vbs_signal(atr=60.0)
        sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_close_buy)
        assert sl == price * (1 - config.STOP_LOSS_PCT)
        assert tp == price * (1 + config.TAKE_PROFIT_PCT)

        # Case 5: Sell with large ATR -> Should fall back to percentage-based SL/TP when SL/TP values are non-positive
        signal_huge_sell = _make_vbs_signal(atr=1000000.0, action="sell")
        sl, tp = worker._calculate_sl_tp(price, "sell", signal=signal_huge_sell)
        assert sl == price * (1 + config.STOP_LOSS_PCT)
        assert tp == price * (1 - config.TAKE_PROFIT_PCT)

    finally:
        config.STOP_LOSS_PCT = original_sl_pct
        config.TAKE_PROFIT_PCT = original_tp_pct
        await worker.close()


@pytest.mark.asyncio
async def test_calculate_position_size_extreme_atr():
    """Test position sizing with extreme ATR values to verify safety and capping."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    price = 100.0

    original_risk = config.RISK_PER_TRADE
    original_max = config.MAX_QUOTE_QTY

    try:
        config.RISK_PER_TRADE = 0.02
        config.MAX_QUOTE_QTY = 1000.0

        # risk_amount = 1000 * 0.02 = 20

        # Case 1: ATR is zero -> fallback to STOP_LOSS_PCT = 0.08
        # qty = 20 / (100 * 0.08) = 2.5
        signal_zero = _make_vbs_signal(atr=0.0)
        qty = worker._calculate_position_size(price, "buy", signal=signal_zero)
        assert qty == 2.5

        # Case 2: ATR is negative -> fallback to STOP_LOSS_PCT = 0.08
        signal_neg = _make_vbs_signal(atr=-5.0)
        qty = worker._calculate_position_size(price, "buy", signal=signal_neg)
        assert qty == 2.5

        # Case 3: ATR is extremely small (e.g. 0.00001) -> sl_pct is tiny, qty would be huge
        # sl_pct = 2 * 0.00001 / 100 = 2e-7
        # qty_uncapped = 20 / (100 * 2e-7) = 1,000,000
        # Capped to portfolio / price = 1000 / 100 = 10.0
        signal_tiny = _make_vbs_signal(atr=0.00001)
        qty = worker._calculate_position_size(price, "buy", signal=signal_tiny)
        assert qty == 10.0

        # Case 4: ATR is extremely large (e.g. 1000000) -> Should fall back to percentage-based STOP_LOSS_PCT = 0.08
        signal_huge = _make_vbs_signal(atr=1000000.0)
        qty = worker._calculate_position_size(price, "buy", signal=signal_huge)
        expected_qty = (config.MAX_QUOTE_QTY * config.RISK_PER_TRADE) / (
            price * config.STOP_LOSS_PCT
        )
        assert qty == expected_qty

    finally:
        config.RISK_PER_TRADE = original_risk
        config.MAX_QUOTE_QTY = original_max
        await worker.close()


# ── Missing or Invalid ATR Key / Value Tests ─────────────────────────────


@pytest.mark.asyncio
async def test_missing_or_invalid_atr():
    """Test that missing atr keys, nested/root variations, and unparseable types do not crash the analyzer."""
    from workers.vps_analyzer import VpsAnalyzerWorker

    worker = VpsAnalyzerWorker()
    price = 100.0

    # Case 1: ATR key completely missing
    signal_no_atr = _make_vbs_signal(atr=None)
    del signal_no_atr["payload"][
        "exchange"
    ]  # just random change, but verify key not in payload at all
    # verify no crash and correct SL/TP
    sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_no_atr)
    assert sl == price * (1 - config.STOP_LOSS_PCT)

    # Case 2: ATR is None explicitly
    signal_none_atr = _make_vbs_signal(atr=None)
    signal_none_atr["payload"]["atr"] = None
    sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_none_atr)
    assert sl == price * (1 - config.STOP_LOSS_PCT)

    # Case 3: ATR is a string (numeric but stringified)
    signal_str_atr = _make_vbs_signal(atr=None)
    signal_str_atr["payload"]["atr"] = "3.5"
    sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_str_atr)
    # SL = 100 - 2 * 3.5 = 93.0
    assert sl == 93.0

    # Case 4: ATR is an invalid unparseable string
    signal_invalid_atr = _make_vbs_signal(atr=None)
    signal_invalid_atr["payload"]["atr"] = "not-a-float"
    sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_invalid_atr)
    assert sl == price * (1 - config.STOP_LOSS_PCT)

    # Case 5: ATR at root instead of payload
    signal_root_atr = _make_vbs_signal(atr=None)
    signal_root_atr["atr"] = 4.0
    sl, tp = worker._calculate_sl_tp(price, "buy", signal=signal_root_atr)
    # SL = 100 - 2 * 4 = 92.0
    assert sl == 92.0

    await worker.close()


# ── Consumer Network Failure and Timeout Tests ───────────────────────────


@pytest.mark.asyncio
async def test_consumer_session_attribute_bug():
    """Verify that calling get_session on a fresh VpsSignalConsumer initializes session successfully and does not raise AttributeError."""
    from workers.vps_consumer import VpsSignalConsumer

    consumer = VpsSignalConsumer()
    assert consumer._session is None
    session = await consumer.get_session()
    assert session is not None
    assert not session.closed
    await consumer.close()


@pytest.mark.asyncio
async def test_consumer_pull_signals_http_error():
    """Verify pull_signals raises ClientResponseError on non-200 HTTP status."""
    from workers.vps_consumer import VpsSignalConsumer

    consumer = VpsSignalConsumer()
    consumer._session = (
        None  # Workaround for the production attribute bug to test pull_signals
    )

    # Mock response to return 500
    mock_resp = FakeResponse(status=500, text_data="Internal Server Error")
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    consumer.get_session = AsyncMock(return_value=mock_session)

    with pytest.raises(ClientResponseError) as exc_info:
        await consumer.pull_signals()

    assert exc_info.value.status == 500
    await consumer.close()


@pytest.mark.asyncio
async def test_consumer_pull_signals_timeout():
    """Verify pull_signals propagates connection and total timeouts correctly."""
    from workers.vps_consumer import VpsSignalConsumer

    consumer = VpsSignalConsumer()
    consumer._session = (
        None  # Workaround for the production attribute bug to test pull_signals
    )

    # Mock get to raise asyncio.TimeoutError
    mock_session = MagicMock()
    mock_session.get = MagicMock(
        side_effect=asyncio.TimeoutError("Connection timed out")
    )
    consumer.get_session = AsyncMock(return_value=mock_session)

    with pytest.raises(asyncio.TimeoutError):
        await consumer.pull_signals()

    # Check timeout configs passed to aiohttp session.get
    call_args = mock_session.get.call_args
    timeout_passed = call_args.kwargs.get("timeout")
    assert isinstance(timeout_passed, ClientTimeout)
    assert timeout_passed.connect == 10
    assert timeout_passed.total == 35

    await consumer.close()


@pytest.mark.asyncio
async def test_consumer_poll_loop_recovers():
    """Verify that poll_loop handles exceptions from pull_signals, backs off, and continues."""
    from workers.vps_consumer import VpsSignalConsumer

    consumer = VpsSignalConsumer()
    consumer._session = (
        None  # Workaround for the production attribute bug to test poll_loop
    )

    # We will trigger the loop. The first call to pull_signals raises RuntimeError.
    # The second call is CancelledError to break the loop.
    call_count = 0

    async def mock_pull_signals(limit=5):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Temporary Network Failure")
        else:
            raise asyncio.CancelledError()

    consumer.pull_signals = mock_pull_signals

    # Mock asyncio.sleep to check it is called with a backoff value
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await consumer.poll_loop()

        # Verify it slept with an exponential backoff value (5-8s range due to jitter)
        assert mock_sleep.call_count >= 1
        sleep_val = mock_sleep.call_args_list[0][0][0]
        assert 5 <= sleep_val <= 8, f"Expected backoff in [5, 8], got {sleep_val}"
        # And it called pull_signals twice
        assert call_count == 2

    await consumer.close()
