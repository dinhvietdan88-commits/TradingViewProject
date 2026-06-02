import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from core.event_bus import EventBus
from core.events import (
    SignalReceived, SignalValidated, SignalRejected, TradeApproved,
    TradeExecuted, TradeFailed
)

# ═══════════════════════════════════════════════════════════════
# MOCKS & HELPERS FOR TESTING
# ═══════════════════════════════════════════════════════════════

@dataclass
class MockRiskParams:
    entry_price: float = 100.0
    stop_loss_price: float = 95.0
    take_profit_price: float = 110.0
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    risk_reward_ratio: float = 2.0
    quantity: float = 1.0
    cost: float = 100.0
    risk_amount: float = 5.0
    account_balance: float = 10000.0
    position_pct: float = 0.01


@dataclass
class MockOrderResult:
    success: bool = True
    dry_run: bool = True
    side: str = "BUY"
    symbol: str = "BTCUSDT"
    entry_order: Dict[str, Any] = field(default_factory=lambda: {
        "orderId": "DRY-TEST-999",
        "status": "FILLED",
        "executedQty": "1.0",
        "cummulativeQuoteQty": "100.00",
    })
    oco_order: Optional[Dict[str, Any]] = field(default_factory=lambda: {
        "orderListId": "DRY-OCO-999",
    })
    risk: Optional[MockRiskParams] = field(default_factory=MockRiskParams)
    error: Optional[str] = None


def _make_mock_client(balance=10000.0):
    adapter = AsyncMock()
    adapter.exchange_id = "binance"
    adapter.get_account_balance = AsyncMock(return_value=balance)
    adapter.execute_smart_order = AsyncMock(return_value=MockOrderResult())
    return adapter


# ═══════════════════════════════════════════════════════════════
# TESTS FOR REGIME SWITCHER MATH
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_regime_switcher_trending():
    """Verify that get_market_regime returns TRENDING when MAs align and there is normal volatility/spread."""
    from engine.regime_switcher import get_market_regime

    # Create 100 daily candles representing an upward trend (aligned MAs: EMA20 > EMA50 > EMA100)
    # EMA values will naturally align if prices are monotonically increasing
    mock_candles = []
    base_price = 100.0
    for i in range(100):
        # Stepping price up gradually
        base_price += 0.5
        mock_candles.append([0, 0, 0, 0, base_price, 0]) # close is at index 4

    with patch("engine.regime_switcher.fetch_candles_with_retry", AsyncMock(return_value=mock_candles)):
        regime = await get_market_regime("BTCUSDT", "binance")
        assert regime == "TRENDING"


@pytest.mark.asyncio
async def test_regime_switcher_chop_low_vol():
    """Verify that get_market_regime returns CHOP when volatility is extremely low (< 1.5%)."""
    from engine.regime_switcher import get_market_regime

    # Close prices fluctuate in a very tiny range around 100.0 (low volatility)
    mock_candles = []
    for i in range(100):
        price = 100.0 + (0.1 if i % 2 == 0 else -0.1)
        mock_candles.append([0, 0, 0, 0, price, 0])

    with patch("engine.regime_switcher.fetch_candles_with_retry", AsyncMock(return_value=mock_candles)):
        regime = await get_market_regime("BTCUSDT", "binance")
        assert regime == "CHOP"


@pytest.mark.asyncio
async def test_regime_switcher_chop_ema_converge():
    """Verify that get_market_regime returns CHOP when MAs are converging and not aligned."""
    from engine.regime_switcher import get_market_regime

    # 86 closes of 100.0, 10 closes of 103.0, 4 closes of 97.0
    # Creates high volatility but results in converging, unaligned EMAs (ema50 > ema100 > ema20) with spread < 2%
    mock_candles = []
    prices = [100.0]*86 + [103.0]*10 + [97.0]*4
    for p in prices:
        mock_candles.append([0, 0, 0, 0, p, 0])

    with patch("engine.regime_switcher.fetch_candles_with_retry", AsyncMock(return_value=mock_candles)):
        regime = await get_market_regime("BTCUSDT", "binance")
        assert regime == "CHOP"


# ═══════════════════════════════════════════════════════════════
# TESTS FOR SIGNAL BLOCKING (CHOP REGIME)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_signal_processor_blocking_during_chop():
    """SignalProcessor must reject Daily MTT signals during a CHOP regime."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    
    rejected_events = []
    @test_bus.on(SignalRejected)
    async def on_reject(event):
        rejected_events.append(event)

    event = SignalReceived(
        signal_id=500, symbol="BTCUSDT", action="buy",
        price=100.0, quote_qty=50.0, interval="daily",
        sl="", tp="", exchange="binance"
    )

    with patch("engine.regime_switcher.get_market_regime", AsyncMock(return_value="CHOP")), \
         patch("database.set_setting", AsyncMock()) as mock_set_setting:
        
        await process_signal(event)
        
        assert len(rejected_events) == 1
        assert rejected_events[0].signal_id == 500
        assert rejected_events[0].reason == "market_regime_chop_block"


@pytest.mark.asyncio
async def test_signal_processor_allow_during_trending():
    """SignalProcessor must allow Daily MTT signals during a TRENDING regime."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    
    validated_events = []
    @test_bus.on(SignalValidated)
    async def on_valid(event):
        validated_events.append(event)

    event = SignalReceived(
        signal_id=501, symbol="BTCUSDT", action="buy",
        price=100.0, quote_qty=50.0, interval="daily",
        sl="", tp="", exchange="binance"
    )

    with patch("engine.regime_switcher.get_market_regime", AsyncMock(return_value="TRENDING")), \
         patch("database.set_setting", AsyncMock()) as mock_set_setting:
        
        await process_signal(event)
        
        assert len(validated_events) == 1
        assert validated_events[0].signal_id == 501
        assert validated_events[0].symbol == "BTCUSDT"


# ═══════════════════════════════════════════════════════════════
# TESTS FOR BEAR-END TACTICAL ENTRY SIZING
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bear_end_tactical_sizing_breakout():
    """Verify that a breakout/BO signal applies 2.5% balance sizing and 5-bar swing low stop loss."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    # 1H candles for stop loss (lows at index 3: 98.0, 97.0, 96.0, 99.0, 98.5 -> swing low is 96.0)
    mock_candles_1h = [
        [0, 0, 0, 98.0, 100.0, 0],
        [0, 0, 0, 97.0, 100.0, 0],
        [0, 0, 0, 96.0, 100.0, 0],
        [0, 0, 0, 99.0, 100.0, 0],
        [0, 0, 0, 98.5, 100.0, 0],
    ]

    mock_client = _make_mock_client(balance=20000.0) # 2.5% of 20000 = 500 USDT

    event = TradeApproved(
        signal_id=600, symbol="BTCUSDT", action="buy",
        price=100.0, quote_qty=10.0, sl="", tp="",
        approved_by="AI", analysis_text="Breakout test"
    )

    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)
    mock_cursor.fetchone = AsyncMock(return_value={"action": "bo", "payload": '{"action": "bo"}'})

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = MagicMock(return_value=mock_cursor)

    with patch("exchanges.router.get_router") as mock_get_router, \
         patch("engine.trade_engine.database") as mock_db, \
         patch("aiosqlite.connect", return_value=mock_conn), \
         patch("analysis.fetch_candles_with_retry", AsyncMock(return_value=mock_candles_1h)), \
         patch("engine.regime_switcher.get_market_regime", AsyncMock(return_value="TRENDING")):

        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = mock_client
        mock_get_router.return_value = mock_router

        mock_db.get_rolling_drawdown = AsyncMock(return_value=0.0)
        mock_db.get_recent_profit_factor = AsyncMock(return_value=1.2)
        mock_db.get_setting = AsyncMock(side_effect=lambda key, default: "false" if key == "safe_mode_active" else default)
        mock_db.set_setting = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=123)
        mock_db.update_trade_oco = AsyncMock()
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        # Assert position size is 2.5% of 20000.0 balance = 500 USDT
        mock_client.execute_smart_order.assert_awaited_once()
        called_kwargs = mock_client.execute_smart_order.call_args[1]
        assert called_kwargs["quote_qty"] == 500.0
        
        # Assert stop loss is at swing_low (96.0) * 0.998 = 95.808
        assert called_kwargs["sl_price"] == pytest.approx(96.0 * 0.998)


# ═══════════════════════════════════════════════════════════════
# TESTS FOR CAPITAL PROTECTION (SAFE MODE)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_safe_mode_halves_sizing():
    """Verify that safe mode activates when drawdown > 10% and halves position sizing."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    mock_client = _make_mock_client(balance=10000.0)

    event = TradeApproved(
        signal_id=700, symbol="BTCUSDT", action="buy",
        price=100.0, quote_qty=100.0, sl="95", tp="110",
        approved_by="AI", analysis_text="Drawdown test"
    )

    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)
    mock_cursor.fetchone = AsyncMock(return_value={"action": "buy", "payload": '{"action": "buy"}'})

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = MagicMock(return_value=mock_cursor)

    with patch("exchanges.router.get_router") as mock_get_router, \
         patch("engine.trade_engine.database") as mock_db, \
         patch("aiosqlite.connect", return_value=mock_conn):

        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = mock_client
        mock_get_router.return_value = mock_router

        # Mock drawdown is 15.0% (> 10.0%)
        mock_db.get_rolling_drawdown = AsyncMock(return_value=15.0)
        mock_db.get_recent_profit_factor = AsyncMock(return_value=1.0)
        mock_db.get_setting = AsyncMock(side_effect=lambda key, default: "false" if key == "safe_mode_active" else default)
        mock_db.set_setting = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=124)
        mock_db.update_trade_oco = AsyncMock()
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        # Verify quote_qty was halved from 100.0 to 50.0 USDT
        called_kwargs = mock_client.execute_smart_order.call_args[1]
        assert called_kwargs["quote_qty"] == 50.0
        
        # Verify safe_mode_active is stored as true
        mock_db.set_setting.assert_any_call("safe_mode_active", "true")
        mock_db.set_setting.assert_any_call("safe_mode_drawdown", "15.00")


@pytest.mark.asyncio
async def test_safe_mode_deactivation():
    """Verify that safe mode deactivates when recent profit factor > 1.5."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    mock_client = _make_mock_client(balance=10000.0)

    event = TradeApproved(
        signal_id=701, symbol="BTCUSDT", action="buy",
        price=100.0, quote_qty=100.0, sl="95", tp="110",
        approved_by="AI", analysis_text="Recovery test"
    )

    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = MagicMock(return_value=None)
    mock_cursor.fetchone = AsyncMock(return_value={"action": "buy", "payload": '{"action": "buy"}'})

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = MagicMock(return_value=None)
    mock_conn.execute = MagicMock(return_value=mock_cursor)

    with patch("exchanges.router.get_router") as mock_get_router, \
         patch("engine.trade_engine.database") as mock_db, \
         patch("aiosqlite.connect", return_value=mock_conn):

        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = mock_client
        mock_get_router.return_value = mock_router

        # Mock low drawdown (5.0%) and high profit factor (2.1 > 1.5)
        # Safe mode was previously active ("true")
        mock_db.get_rolling_drawdown = AsyncMock(return_value=5.0)
        mock_db.get_recent_profit_factor = AsyncMock(return_value=2.1)
        mock_db.get_setting = AsyncMock(side_effect=lambda key, default: "true" if key == "safe_mode_active" else default)
        mock_db.set_setting = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=125)
        mock_db.update_trade_oco = AsyncMock()
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        # Verify quote_qty remains 100.0 (not halved) since safe mode was deactivated
        called_kwargs = mock_client.execute_smart_order.call_args[1]
        assert called_kwargs["quote_qty"] == 100.0
        
        # Verify safe_mode_active is stored as false
        mock_db.set_setting.assert_any_call("safe_mode_active", "false")


# ═══════════════════════════════════════════════════════════════
# TESTS FOR VISION AI LOCAL SDK FALLBACK
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_vision_sdk_fallback_parsing():
    """Verify that _analyze_chart_sdk_fallback successfully requests port 9101 and parses confidence."""
    from vision import _analyze_chart_sdk_fallback

    mock_resp_data = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "👁️ VISUAL ANALYSIS (SDK FALLBACK) — BTCUSDT\n\nTrend is strongly bullish. Consolidating tightly. Compliant SEPA setup.\nScore: 8/10"
                }
            }
        ]
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = mock_resp_data

    # Mock RAG connection and httpx post
    with patch("rag._collection", None), \
         patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_response)) as mock_post:

        result = await _analyze_chart_sdk_fallback("BTCUSDT", {"trend_template_score": 8})

        # Verify correct URL used (port 9101)
        mock_post.assert_called_once()
        url_called = mock_post.call_args[0][0]
        assert "http://127.0.0.1:9101/v1/chat/completions" == url_called

        # Verify parsed results
        assert result["symbol"] == "BTCUSDT"
        assert result["confidence"] == 8
        assert "SDK FALLBACK" in result["analysis"]
        assert result["error"] is None
