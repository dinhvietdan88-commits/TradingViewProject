from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event_bus import EventBus
from core.events import TradeApproved, TradeFailed

# Mock fixtures and helper components to mimic TradeEngine's expectations


@dataclass
class MockRiskParams:
    entry_price: float = 100.0
    stop_loss_price: float = 90.0
    take_profit_price: float = 120.0
    stop_loss_pct: float = 0.10
    take_profit_pct: float = 0.20
    risk_reward_ratio: float = 2.0
    quantity: float = 1.0
    cost: float = 100.0
    risk_amount: float = 10.0
    account_balance: float = 1000.0
    position_pct: float = 0.1


@dataclass
class MockOrderResult:
    success: bool = True
    dry_run: bool = True
    side: str = "BUY"
    symbol: str = "BTCUSDT"
    entry_order: dict[str, Any] = field(
        default_factory=lambda: {
            "orderId": "LIMIT-12345",
            "status": "NEW",  # Start as NEW to test monitoring / cancellation
            "executedQty": "0.0",
            "cummulativeQuoteQty": "0.00",
        }
    )
    oco_order: dict[str, Any] | None = field(
        default_factory=lambda: {
            "orderListId": "OCO-12345",
        }
    )
    risk: MockRiskParams | None = field(default_factory=MockRiskParams)
    error: str | None = None


def _make_mock_adapter(balance=1000.0, ticker_price=100.0):
    adapter = AsyncMock()
    adapter.exchange_id = "binance"
    adapter.get_account_balance = AsyncMock(return_value=balance)
    adapter.get_ticker_price = AsyncMock(return_value=ticker_price)
    adapter.execute_smart_order = AsyncMock(return_value=MockOrderResult())
    adapter.get_order = AsyncMock(return_value={"status": "NEW"})
    adapter.cancel_order = AsyncMock()
    adapter.cancel_oco_order = AsyncMock()
    return adapter


# R1: Auto-Validation & Dynamic Slippage Control Tests
@pytest.mark.asyncio
async def test_r1_slippage_greater_than_05_percent_switches_to_limit():
    """If slippage is > 0.5%, target order type should be LIMIT and monitor task is scheduled."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    # Entry price is 100.0, market price is 101.0 -> slippage = 1.0% > 0.5%
    adapter = _make_mock_adapter(balance=1000.0, ticker_price=101.0)

    event = TradeApproved(
        signal_id=201,
        symbol="BTCUSDT",
        action="buy",
        price=100.0,
        quote_qty=50.0,
        sl="90",
        tp="120",
        approved_by="AI",
        analysis_text="Slippage test",
    )

    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)
    mock_cursor.fetchone = AsyncMock(
        return_value={"action": "buy", "payload": '{"action": "buy"}'}
    )

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = MagicMock(return_value=mock_cursor)

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
        patch("aiosqlite.connect", return_value=mock_conn),
        patch("asyncio.create_task") as mock_create_task,
        patch(
            "engine.regime_switcher.get_market_regime",
            AsyncMock(return_value="TRENDING"),
        ),
    ):
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = adapter
        mock_get_router.return_value = mock_router

        mock_db.get_rolling_drawdown = AsyncMock(return_value=0.0)
        mock_db.get_recent_profit_factor = AsyncMock(return_value=1.0)
        mock_db.get_setting = AsyncMock(
            side_effect=lambda key, default: (
                "false" if key == "safe_mode_active" else default
            )
        )
        mock_db.set_setting = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=201)
        mock_db.update_trade_oco = AsyncMock()
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        # Assert execute_smart_order was called with LIMIT
        adapter.execute_smart_order.assert_awaited_once()
        called_kwargs = adapter.execute_smart_order.call_args[1]
        assert called_kwargs["order_type"] == "LIMIT"

        # Assert that monitor task was created since target order type is LIMIT and order status is NEW
        mock_create_task.assert_called_once()
        coro = mock_create_task.call_args[0][0]
        coro.close()

    from core.event_bus import bus as default_bus

    set_bus(default_bus)


@pytest.mark.asyncio
async def test_r1_slippage_less_than_05_percent_stays_market():
    """If slippage is <= 0.5%, target order type should remain MARKET."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    # Entry price is 100.0, market price is 100.2 -> slippage = 0.2% <= 0.5%
    adapter = _make_mock_adapter(balance=1000.0, ticker_price=100.2)

    event = TradeApproved(
        signal_id=202,
        symbol="BTCUSDT",
        action="buy",
        price=100.0,
        quote_qty=50.0,
        sl="90",
        tp="120",
        approved_by="AI",
        analysis_text="No slippage test",
    )

    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)
    mock_cursor.fetchone = AsyncMock(
        return_value={"action": "buy", "payload": '{"action": "buy"}'}
    )

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = MagicMock(return_value=mock_cursor)

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
        patch("aiosqlite.connect", return_value=mock_conn),
        patch(
            "engine.regime_switcher.get_market_regime",
            AsyncMock(return_value="TRENDING"),
        ),
    ):
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = adapter
        mock_get_router.return_value = mock_router

        mock_db.get_rolling_drawdown = AsyncMock(return_value=0.0)
        mock_db.get_recent_profit_factor = AsyncMock(return_value=1.0)
        mock_db.get_setting = AsyncMock(
            side_effect=lambda key, default: (
                "false" if key == "safe_mode_active" else default
            )
        )
        mock_db.set_setting = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=202)
        mock_db.update_trade_oco = AsyncMock()
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        adapter.execute_smart_order.assert_awaited_once()
        called_kwargs = adapter.execute_smart_order.call_args[1]
        assert called_kwargs["order_type"] == "MARKET"

    from core.event_bus import bus as default_bus

    set_bus(default_bus)


@pytest.mark.asyncio
async def test_r1_limit_order_monitoring_and_cancellation():
    """Verify that monitor_limit_order cancels order and emits notification if unfilled after 30s."""
    from engine.trade_engine import monitor_limit_order

    adapter = _make_mock_adapter(balance=1000.0, ticker_price=100.0)
    # Mock order stays unfilled ("NEW")
    adapter.get_order = AsyncMock(return_value={"status": "NEW"})

    with (
        patch("asyncio.sleep", AsyncMock()) as mock_sleep,
        patch("notifier.notify_all", AsyncMock()) as mock_notify,
    ):
        await monitor_limit_order(adapter, "BTCUSDT", "LIMIT-12345", "OCO-12345", 100.0)

        # Assert sleep of 30 seconds was called
        mock_sleep.assert_awaited_once_with(30)

        # Assert cancellation functions were called
        adapter.cancel_order.assert_awaited_once_with("BTCUSDT", "LIMIT-12345")
        adapter.cancel_oco_order.assert_awaited_once_with("BTCUSDT", "OCO-12345")

        # Assert Telegram warning sent
        mock_notify.assert_awaited_once()
        args = mock_notify.call_args[0][0]
        assert "Slippage Warning" in args
        assert "LIMIT-12345" in args


# R2: ATR-Based Adaptive Position Sizing Tests
@pytest.mark.asyncio
async def test_r2_atr_based_sl_tp_and_sizing():
    """Verify SL/TP are calculated based on per-symbol ATR multipliers and position size is risk-based.

    BTCUSDT (Beta=1.0): atr_sl_mul=2.0, atr_tp_mul=8.0, risk_pct=1.0%
    - Balance 1000.0 USDT -> 1% risk = 10 USDT.
    - ATR=2.5, Entry=100.0.
    - Long SL = 100.0 - (2.0 * 2.5) = 95.0. TP = 100.0 + (8.0 * 2.5) = 120.0.
    - Price distance = 5.0. quote_qty = (10 / 5.0) * 100.0 = 200 USDT.
    """
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    adapter = _make_mock_adapter(balance=1000.0, ticker_price=100.0)

    event = TradeApproved(
        signal_id=203,
        symbol="BTCUSDT",
        action="buy",
        price=100.0,
        quote_qty=None,
        sl="",
        tp="",
        approved_by="AI",
        analysis_text="ATR test",
    )

    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)
    mock_cursor.fetchone = AsyncMock(
        return_value={"action": "buy", "payload": '{"atr_value": 2.5}'}
    )

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = MagicMock(return_value=mock_cursor)

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
        patch("aiosqlite.connect", return_value=mock_conn),
        patch(
            "engine.regime_switcher.get_market_regime",
            AsyncMock(return_value="TRENDING"),
        ),
    ):
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = adapter
        mock_get_router.return_value = mock_router

        mock_db.get_rolling_drawdown = AsyncMock(return_value=0.0)
        mock_db.get_recent_profit_factor = AsyncMock(return_value=1.0)
        mock_db.get_setting = AsyncMock(
            side_effect=lambda key, default: (
                "false" if key == "safe_mode_active" else default
            )
        )
        mock_db.set_setting = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=203)
        mock_db.update_trade_oco = AsyncMock()
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        adapter.execute_smart_order.assert_awaited_once()
        called_kwargs = adapter.execute_smart_order.call_args[1]
        assert called_kwargs["sl_price"] == 95.0  # entry - (atr_sl_mul=2.0 * atr=2.5)
        assert (
            called_kwargs["tp_price"] == 120.0
        )  # entry + (atr_tp_mul=8.0 * atr=2.5) ← BTC Matrix
        assert called_kwargs["quote_qty"] == 200.0  # (risk=10 / dist=5) * 100

    from core.event_bus import bus as default_bus

    set_bus(default_bus)


@pytest.mark.asyncio
async def test_r3_cdp_keep_alive_reload_on_failure():
    """Verify that check_and_keep_alive_tv_cdp triggers Page.reload when Runtime.evaluate fails."""
    from scheduler import check_and_keep_alive_tv_cdp

    # Mock response for local json/list
    targets_resp = MagicMock()
    targets_resp.status = 200
    targets_resp.json = AsyncMock(
        return_value=[
            {
                "type": "page",
                "url": "https://www.tradingview.com/chart/abc/",
                "webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1",
            }
        ]
    )

    class MockWS:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def send(self, msg):
            pass

        async def recv(self):
            # Return an error or invalid response to trigger reload flow
            return '{"error": "tab crashed"}'

    # Configure mock session context manager
    mock_session_instance = MagicMock()
    mock_session_instance.get = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=targets_resp))
    )

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session_instance)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("aiohttp.ClientSession", return_value=mock_session),
        patch("websockets.connect", return_value=MockWS()) as mock_ws_connect,
        patch("scheduler.logger") as mock_logger,
    ):
        await check_and_keep_alive_tv_cdp()

        # Should log reload warning and attempt connection/message sending
        mock_logger.warning.assert_called_once()
        # Verify websockets was connected twice: once for evaluate test, and once for reload
        assert mock_ws_connect.call_count == 2


# R4: AI Market Regime Filter Tests
@pytest.mark.asyncio
async def test_r4_chop_regime_halves_normal_signals():
    """Verify that in CHOP regime, normal non-breakout signals are halved in size."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    adapter = _make_mock_adapter(balance=1000.0, ticker_price=100.0)

    event = TradeApproved(
        signal_id=204,
        symbol="BTCUSDT",
        action="buy",
        price=100.0,
        quote_qty=100.0,
        sl="90",
        tp="120",
        approved_by="AI",
        analysis_text="Normal signal in CHOP",
    )

    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)
    mock_cursor.fetchone = AsyncMock(
        return_value={"action": "buy", "payload": '{"action": "buy"}'}
    )

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = MagicMock(return_value=mock_cursor)

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
        patch("aiosqlite.connect", return_value=mock_conn),
        patch(
            "engine.regime_switcher.get_market_regime", AsyncMock(return_value="CHOP")
        ),
    ):
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = adapter
        mock_get_router.return_value = mock_router

        mock_db.get_rolling_drawdown = AsyncMock(return_value=0.0)
        mock_db.get_recent_profit_factor = AsyncMock(return_value=1.0)
        mock_db.get_setting = AsyncMock(
            side_effect=lambda key, default: (
                "false" if key == "safe_mode_active" else default
            )
        )
        mock_db.set_setting = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=204)
        mock_db.update_trade_oco = AsyncMock()
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        called_kwargs = adapter.execute_smart_order.call_args[1]
        # quote_qty should be halved from 100 to 50
        assert called_kwargs["quote_qty"] == 50.0

    from core.event_bus import bus as default_bus

    set_bus(default_bus)


@pytest.mark.asyncio
async def test_r4_chop_regime_skips_breakout_signals():
    """Verify that in CHOP regime, breakout signals are completely skipped."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    failed_events = []

    @test_bus.on(TradeFailed)
    async def on_fail(event):
        failed_events.append(event)

    adapter = _make_mock_adapter(balance=1000.0, ticker_price=100.0)

    event = TradeApproved(
        signal_id=205,
        symbol="BTCUSDT",
        action="buy",
        price=100.0,
        quote_qty=100.0,
        sl="90",
        tp="120",
        approved_by="AI",
        analysis_text="Breakout signal in CHOP",
    )

    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)
    mock_cursor.fetchone = AsyncMock(
        return_value={"action": "bo", "payload": '{"action": "bo"}'}
    )

    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = MagicMock(return_value=mock_cursor)

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
        patch("aiosqlite.connect", return_value=mock_conn),
        patch(
            "engine.regime_switcher.get_market_regime", AsyncMock(return_value="CHOP")
        ),
    ):
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = adapter
        mock_get_router.return_value = mock_router

        mock_db.get_rolling_drawdown = AsyncMock(return_value=0.0)
        mock_db.get_recent_profit_factor = AsyncMock(return_value=1.0)
        mock_db.get_setting = AsyncMock(
            side_effect=lambda key, default: (
                "false" if key == "safe_mode_active" else default
            )
        )
        mock_db.set_setting = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=205)
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        # Smart order execution must NOT be called
        adapter.execute_smart_order.assert_not_called()
        # Verify TradeFailed event was emitted
        assert len(failed_events) == 1
        assert failed_events[0].signal_id == 205
        assert "CHOP regime" in failed_events[0].error

    from core.event_bus import bus as default_bus

    set_bus(default_bus)
