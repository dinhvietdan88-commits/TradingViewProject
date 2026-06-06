"""
Tests for stop_loss_pct hard-cap enforcement in trade_engine.execute_trade().

The SL cap clamps manually-provided sl_price values that exceed the per-symbol
stop_loss_pct cap defined in symbol_config.py. The ATR-computed SL path is NOT
capped here (it already uses well-tested atr_sl_mul multipliers).

Test strategy: mock the full execute_trade() pipeline and assert:
  - sl_price beyond BTC's 8% cap is clamped to exactly 8% from entry (BUY)
  - sl_price beyond BTC's 8% cap is clamped to exactly 8% from entry (SELL)
  - sl_price within the cap passes through unchanged
"""

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event_bus import EventBus
from core.events import TradeApproved


@dataclass
class MockRiskParams:
    entry_price: float = 100.0
    stop_loss_price: float = 92.0
    take_profit_price: float = 120.0
    stop_loss_pct: float = 0.08
    take_profit_pct: float = 0.20
    risk_reward_ratio: float = 2.0
    quantity: float = 1.0
    cost: float = 100.0
    risk_amount: float = 8.0
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
            "orderId": "LIMIT-SL-CAP-TEST",
            "status": "FILLED",
            "executedQty": "1.0",
            "cummulativeQuoteQty": "100.00",
        }
    )
    oco_order: dict[str, Any] | None = field(
        default_factory=lambda: {
            "orderListId": "OCO-SL-CAP-TEST",
        }
    )
    risk: MockRiskParams | None = field(default_factory=MockRiskParams)
    error: str | None = None


def _make_adapter(ticker=100.0, balance=1000.0):
    adapter = AsyncMock()
    adapter.exchange_id = "binance"
    adapter.get_account_balance = AsyncMock(return_value=balance)
    adapter.get_ticker_price = AsyncMock(return_value=ticker)
    adapter.execute_smart_order = AsyncMock(return_value=MockOrderResult())
    adapter.get_order = AsyncMock(return_value={"status": "FILLED"})
    adapter.cancel_order = AsyncMock()
    adapter.cancel_oco_order = AsyncMock()
    return adapter


def _make_mock_conn_and_cursor(action="buy"):
    mock_cursor = AsyncMock()
    mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor.__aexit__ = AsyncMock(return_value=None)
    mock_cursor.fetchone = AsyncMock(
        return_value={
            "action": action,
            "payload": f'{{"action": "{action}"}}',
        }
    )
    mock_conn = AsyncMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = MagicMock(return_value=mock_cursor)
    return mock_conn, mock_cursor


# ── BUY SL Cap Test ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sl_cap_enforced_buy():
    """SL beyond BTC 8% cap must be clamped to entry*(1-0.08) for BUY orders.

    Setup: entry=100.0, provided_sl=85.0 (15% distance > 8% BTC cap).
    Expected clamped_sl = 100.0 * (1 - 0.08) = 92.0.
    """
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    adapter = _make_adapter(ticker=100.0)
    event = TradeApproved(
        signal_id=901,
        symbol="BTCUSDT",
        action="buy",
        price=100.0,
        quote_qty=50.0,
        sl="85",  # 15% away — beyond 8% cap
        tp="120",
        approved_by="AI",
        analysis_text="SL cap test BUY",
    )

    mock_conn, _ = _make_mock_conn_and_cursor("buy")

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
        patch("aiosqlite.connect", return_value=mock_conn),
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
        mock_db.insert_trade = AsyncMock(return_value=901)
        mock_db.update_trade_oco = AsyncMock()
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        adapter.execute_smart_order.assert_awaited_once()
        kwargs = adapter.execute_smart_order.call_args[1]
        # Clamped SL must be exactly 8% below entry
        expected_sl = 100.0 * (1.0 - 0.08)  # = 92.0
        assert abs(kwargs["sl_price"] - expected_sl) < 0.0001, (
            f"BUY SL should be clamped to {expected_sl:.4f}, got {kwargs['sl_price']}"
        )

    from core.event_bus import bus as default_bus

    set_bus(default_bus)


# ── SELL SL Cap Test ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sl_cap_enforced_sell():
    """SL beyond BTC 8% cap must be clamped to entry*(1+0.08) for SELL orders.

    Setup: entry=100.0, provided_sl=120.0 (20% distance > 8% BTC cap).
    Expected clamped_sl = 100.0 * (1 + 0.08) = 108.0.
    """
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    adapter = _make_adapter(ticker=100.0)
    event = TradeApproved(
        signal_id=902,
        symbol="BTCUSDT",
        action="sell",
        price=100.0,
        quote_qty=50.0,
        sl="120",  # 20% away — beyond 8% cap
        tp="80",
        approved_by="AI",
        analysis_text="SL cap test SELL",
    )

    mock_conn, _ = _make_mock_conn_and_cursor("sell")

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
        patch("aiosqlite.connect", return_value=mock_conn),
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
        mock_db.insert_trade = AsyncMock(return_value=902)
        mock_db.update_trade_oco = AsyncMock()
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        adapter.execute_smart_order.assert_awaited_once()
        kwargs = adapter.execute_smart_order.call_args[1]
        expected_sl = 100.0 * (1.0 + 0.08)  # = 108.0
        assert abs(kwargs["sl_price"] - expected_sl) < 0.0001, (
            f"SELL SL should be clamped to {expected_sl:.4f}, got {kwargs['sl_price']}"
        )

    from core.event_bus import bus as default_bus

    set_bus(default_bus)


# ── SL Within Cap — Unchanged ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sl_within_cap_unchanged():
    """SL within the BTC 8% cap must pass through exactly as provided.

    Setup: entry=100.0, provided_sl=95.0 (5% distance < 8% cap).
    Expected: sl_price == 95.0 (no clamping).
    """
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    adapter = _make_adapter(ticker=100.0)
    event = TradeApproved(
        signal_id=903,
        symbol="BTCUSDT",
        action="buy",
        price=100.0,
        quote_qty=50.0,
        sl="95",  # 5% away — within 8% cap
        tp="115",
        approved_by="AI",
        analysis_text="SL within cap test",
    )

    mock_conn, _ = _make_mock_conn_and_cursor("buy")

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
        patch("aiosqlite.connect", return_value=mock_conn),
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
        mock_db.insert_trade = AsyncMock(return_value=903)
        mock_db.update_trade_oco = AsyncMock()
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        adapter.execute_smart_order.assert_awaited_once()
        kwargs = adapter.execute_smart_order.call_args[1]
        assert abs(kwargs["sl_price"] - 95.0) < 0.0001, (
            f"SL within cap should be 95.0 (unchanged), got {kwargs['sl_price']}"
        )

    from core.event_bus import bus as default_bus

    set_bus(default_bus)
