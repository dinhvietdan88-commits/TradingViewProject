"""
Extended unit tests for TradeEngine component (v6.0).

Tests verify gaps from the original test_trade_engine.py:
- Sell side execution emits TradeExecuted with side=SELL.
- Exchange routing failure (router raises exception) → TradeFailed.
- Exchange fallback: actual_exchange != requested_exchange shows fallback label.
- OCO order id is passed correctly to update_trade_oco.
- SL/TP prices from event are passed to execute_smart_order.
- execute_trade with missing quote_qty defaults gracefully.
- exchange field is propagated in all emitted events.
"""

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event_bus import EventBus
from core.events import TradeApproved, TradeExecuted, TradeFailed

# ═══════════════════════════════════════════════════════════════
# MOCK FIXTURES
# ═══════════════════════════════════════════════════════════════


@dataclass
class MockRiskParams:
    entry_price: float = 68000.0
    stop_loss_price: float = 65000.0
    take_profit_price: float = 74000.0
    stop_loss_pct: float = 0.044
    take_profit_pct: float = 0.088
    risk_reward_ratio: float = 2.0
    quantity: float = 0.001
    cost: float = 68.0
    risk_amount: float = 30.0
    account_balance: float = 10000.0
    position_pct: float = 0.0068


@dataclass
class MockOrderResult:
    success: bool = True
    dry_run: bool = True
    side: str = "BUY"
    symbol: str = "BTCUSDT"
    entry_order: dict[str, Any] = field(
        default_factory=lambda: {
            "orderId": "DRY-001",
            "status": "FILLED",
            "executedQty": "0.001",
            "cummulativeQuoteQty": "68.00",
        }
    )
    oco_order: dict[str, Any] | None = field(
        default_factory=lambda: {
            "orderListId": "OCO-001",
        }
    )
    risk: MockRiskParams | None = field(default_factory=MockRiskParams)
    error: str | None = None


def _make_adapter(order_result=None, exchange_id="binance"):
    adapter = AsyncMock()
    adapter.exchange_id = exchange_id
    if order_result is None:
        order_result = MockOrderResult()
    adapter.execute_smart_order = AsyncMock(return_value=order_result)
    return adapter


def _make_event(**kwargs) -> TradeApproved:
    defaults = dict(
        signal_id=100,
        symbol="BTCUSDT",
        action="buy",
        price=68000.0,
        quote_qty=50.0,
        sl="65000",
        tp="74000",
        exchange="binance",
        approved_by="AI (Auto-Green)",
        analysis_text="Bullish pattern confirmed.",
    )
    defaults.update(kwargs)
    return TradeApproved(**defaults)


# ═══════════════════════════════════════════════════════════════
# SELL SIDE
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sell_side_emits_trade_executed_with_sell_side():
    """A sell action should execute and emit TradeExecuted with side=SELL."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    executed_events = []

    @test_bus.on(TradeExecuted)
    async def on_exec(event):
        executed_events.append(event)

    sell_result = MockOrderResult(side="SELL", symbol="ETHUSDT")
    adapter = _make_adapter(sell_result, exchange_id="binance")

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=10)
            mock_db.update_trade_oco = AsyncMock()
            mock_db.update_signal_status = AsyncMock()

            await execute_trade(
                _make_event(action="sell", symbol="ETHUSDT", signal_id=110)
            )

            assert len(executed_events) == 1
            assert executed_events[0].side == "SELL"
            assert executed_events[0].symbol == "ETHUSDT"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


# ═══════════════════════════════════════════════════════════════
# EXCHANGE ROUTING FAILURE
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_exchange_routing_failure_emits_trade_failed():
    """If ExchangeRouter raises an exception, TradeFailed should be emitted."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    failed_events = []

    @test_bus.on(TradeFailed)
    async def on_failed(event):
        failed_events.append(event)

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.side_effect = ValueError(
                "No adapter for 'unknown_exchange'"
            )
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=11)
            mock_db.update_signal_status = AsyncMock()

            await execute_trade(_make_event(exchange="unknown_exchange", signal_id=120))

            assert len(failed_events) == 1
            assert (
                "routing" in failed_events[0].error.lower()
                or "No adapter" in failed_events[0].error
            )
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


# ═══════════════════════════════════════════════════════════════
# EXCHANGE FALLBACK LABEL
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fallback_exchange_label_in_trade_executed():
    """When adapter.exchange_id differs from requested exchange, the event telegram_message
    should note the fallback."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    executed_events = []

    @test_bus.on(TradeExecuted)
    async def on_exec(event):
        executed_events.append(event)

    # Adapter resolves to "binance" even though "bybit" was requested
    adapter = _make_adapter(exchange_id="binance")

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=12)
            mock_db.update_trade_oco = AsyncMock()
            mock_db.update_signal_status = AsyncMock()

            await execute_trade(_make_event(exchange="bybit", signal_id=130))

            assert len(executed_events) == 1
            # telegram_message should contain "Fallback" label since bybit != binance
            assert "Fallback" in executed_events[0].telegram_message
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


# ═══════════════════════════════════════════════════════════════
# OCO ORDER ID WIRING
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_oco_order_id_passed_to_db():
    """OCO order list ID from exchange response should be saved to DB via update_trade_oco."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    oco_call_args = {}

    async def capture_oco(**kwargs):
        oco_call_args.update(kwargs)

    adapter = _make_adapter()  # MockOrderResult has oco_order.orderListId="OCO-001"

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=13)
            mock_db.update_trade_oco = AsyncMock(side_effect=capture_oco)
            mock_db.update_signal_status = AsyncMock()

            await execute_trade(_make_event(signal_id=140))

            assert oco_call_args.get("oco_order_id") == "OCO-001"
            assert oco_call_args.get("stop_loss_price") == pytest.approx(65000.0)
            assert oco_call_args.get("take_profit_price") == pytest.approx(74000.0)
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


# ═══════════════════════════════════════════════════════════════
# SL/TP PASSED TO ADAPTER
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sl_tp_prices_passed_to_execute_smart_order():
    """SL and TP prices from the TradeApproved event should be forwarded to the adapter."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    adapter = _make_adapter()
    captured_order_args = {}

    async def capture_execute(**kwargs):
        captured_order_args.update(kwargs)
        return MockOrderResult()

    adapter.execute_smart_order = capture_execute

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=14)
            mock_db.update_trade_oco = AsyncMock()
            mock_db.update_signal_status = AsyncMock()

            await execute_trade(
                _make_event(sl="65000", tp="74000", price=68000.0, signal_id=150)
            )

            assert captured_order_args.get("sl_price") == pytest.approx(65000.0)
            assert captured_order_args.get("tp_price") == pytest.approx(74000.0)
            assert captured_order_args.get("entry_price") == pytest.approx(68000.0)
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


# ═══════════════════════════════════════════════════════════════
# EXCHANGE PROPAGATION IN EVENTS
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_trade_executed_carries_actual_exchange():
    """TradeExecuted.exchange should reflect the adapter's exchange_id (not the requested one)."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    executed_events = []

    @test_bus.on(TradeExecuted)
    async def on_exec(event):
        executed_events.append(event)

    adapter = _make_adapter(exchange_id="okx")

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=15)
            mock_db.update_trade_oco = AsyncMock()
            mock_db.update_signal_status = AsyncMock()

            await execute_trade(_make_event(exchange="okx", signal_id=160))

            assert executed_events[0].exchange == "okx"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


@pytest.mark.asyncio
async def test_trade_failed_carries_requested_exchange():
    """TradeFailed.exchange should reflect the originally requested exchange name."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    failed_events = []

    @test_bus.on(TradeFailed)
    async def on_failed(event):
        failed_events.append(event)

    fail_result = MockOrderResult(success=False, error="API timeout")
    adapter = _make_adapter(fail_result, exchange_id="binance")

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=16)
            mock_db.update_signal_status = AsyncMock()

            await execute_trade(_make_event(exchange="bybit", signal_id=170))

            assert len(failed_events) == 1
            # exchange on TradeFailed is the requested (bybit), not the actual (binance)
            assert failed_events[0].exchange == "bybit"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


# ═══════════════════════════════════════════════════════════════
# PRICE EDGE CASES
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_comma_formatted_sl_tp_parsed_correctly():
    """SL/TP values with comma-thousand separators (e.g., '65,000') must be parsed to float."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    adapter = _make_adapter()
    captured_args = {}

    async def capture_execute(**kwargs):
        captured_args.update(kwargs)
        return MockOrderResult()

    adapter.execute_smart_order = capture_execute

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=17)
            mock_db.update_trade_oco = AsyncMock()
            mock_db.update_signal_status = AsyncMock()

            await execute_trade(
                _make_event(sl="65,000", tp="74,000", price="68,000", signal_id=180)
            )

            assert captured_args["sl_price"] == pytest.approx(65000.0)
            assert captured_args["tp_price"] == pytest.approx(74000.0)
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


@pytest.mark.asyncio
async def test_invalid_sl_tp_gracefully_becomes_none():
    """Invalid SL/TP strings should resolve to None, not crash the engine."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    executed_events = []

    @test_bus.on(TradeExecuted)
    async def on_exec(event):
        executed_events.append(event)

    adapter = _make_adapter()
    captured_args = {}

    async def capture_execute(**kwargs):
        captured_args.update(kwargs)
        return MockOrderResult()

    adapter.execute_smart_order = capture_execute

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=18)
            mock_db.update_trade_oco = AsyncMock()
            mock_db.update_signal_status = AsyncMock()

            await execute_trade(_make_event(sl="INVALID", tp="N/A", signal_id=190))

            assert captured_args["sl_price"] is None
            assert captured_args["tp_price"] is None
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


@pytest.mark.asyncio
async def test_invalid_entry_price_fails_trade_gracefully():
    """If entry price is <= 0.0 or non-numeric, TradeEngine must fail the trade and emit TradeFailed."""
    from core.events import TradeFailed
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    failed_events = []

    @test_bus.on(TradeFailed)
    async def on_fail(event):
        failed_events.append(event)

    adapter = _make_adapter()

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=19)
            mock_db.update_signal_status = AsyncMock()

            # Test zero price
            await execute_trade(_make_event(price=0.0, signal_id=200))
            assert len(failed_events) == 1
            assert failed_events[0].signal_id == 200
            assert "Invalid entry price" in failed_events[0].error

            # Test negative price
            await execute_trade(_make_event(price=-100.0, signal_id=201))
            assert len(failed_events) == 2
            assert failed_events[1].signal_id == 201
            assert "Invalid entry price" in failed_events[1].error

            # Test non-numeric price
            await execute_trade(_make_event(price="NotANumber", signal_id=202))
            assert len(failed_events) == 3
            assert failed_events[2].signal_id == 202
            assert "Invalid entry price" in failed_events[2].error
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


@pytest.mark.asyncio
async def test_negative_sl_tp_clamped_to_none():
    """Negative or zero SL/TP values must be clamped to None to avoid downstream issues."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    adapter = _make_adapter()
    captured_args = {}

    async def capture_execute(**kwargs):
        captured_args.update(kwargs)
        return MockOrderResult()

    adapter.execute_smart_order = capture_execute

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=20)
            mock_db.update_trade_oco = AsyncMock()
            mock_db.update_signal_status = AsyncMock()

            await execute_trade(
                _make_event(sl="-10.0", tp="0.0", price=100.0, signal_id=210)
            )

            assert captured_args["sl_price"] is None
            assert captured_args["tp_price"] is None
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


@pytest.mark.asyncio
async def test_negative_or_zero_qty_clamped_to_none():
    """Negative or zero quote quantities must be sanitized to None (so exchange uses defaults)."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    adapter = _make_adapter()
    captured_args = {}

    async def capture_execute(**kwargs):
        captured_args.update(kwargs)
        return MockOrderResult()

    adapter.execute_smart_order = capture_execute

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=21)
            mock_db.update_trade_oco = AsyncMock()
            mock_db.update_signal_status = AsyncMock()

            # Test negative qty
            await execute_trade(_make_event(quote_qty=-5.0, price=100.0, signal_id=220))
            assert captured_args["quote_qty"] is None

            # Test zero qty
            await execute_trade(_make_event(quote_qty=0.0, price=100.0, signal_id=221))
            assert captured_args["quote_qty"] is None

            # Test non-numeric qty
            await execute_trade(
                _make_event(quote_qty="InvalidQty", price=100.0, signal_id=222)
            )
            assert captured_args["quote_qty"] is None
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


@pytest.mark.asyncio
async def test_weex_routing_success():
    """Verify that Weex exchange events are correctly routed to the Weex adapter."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    executed_events = []

    @test_bus.on(TradeExecuted)
    async def on_exec(event):
        executed_events.append(event)

    adapter = _make_adapter(exchange_id="weex")

    try:
        with (
            patch("exchanges.router.get_router") as mock_get_router,
            patch("engine.trade_engine.database") as mock_db,
        ):
            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = adapter
            mock_get_router.return_value = mock_router

            mock_db.insert_trade = AsyncMock(return_value=30)
            mock_db.update_trade_oco = AsyncMock()
            mock_db.update_signal_status = AsyncMock()

            await execute_trade(
                _make_event(exchange="weex", symbol="BTCUSDT", signal_id=300)
            )

            assert len(executed_events) == 1
            assert executed_events[0].exchange == "weex"
            assert executed_events[0].symbol == "BTCUSDT"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
