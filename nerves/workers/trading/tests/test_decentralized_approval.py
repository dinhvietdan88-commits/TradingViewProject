"""
test_decentralized_approval.py — Verification tests for Telegram Bot signal synchronization and gating.
Tests low, medium, and high confidence payloads, hold_for_approval, and callback query simulation.
"""

import pytest
import pytest_asyncio
import os
import sys
import pathlib
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

# Ensure server/ is on path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from httpx import AsyncClient, ASGITransport

VALID_HEADERS = {"X-Server-B-Secret": "test-exec-secret"}

VALID_PAYLOAD = {
    "symbol": "BTCUSDT",
    "action": "buy",
    "price": 68000.0,
    "quote_qty": 50.0,
    "sl": "67000",
    "tp": "72000",
    "exchange": "binance",
    "analysis_text": "Strong bullish pattern detected by AI analyzer.",
}


@pytest_asyncio.fixture
async def exec_client(tmp_path):
    """Provide httpx.AsyncClient wired to execution_server.app with mocked telegram bot lifecycle."""
    import config
    import database

    config.DB_PATH = str(tmp_path / "test_exec.db")
    config.SERVER_B_SECRET = "test-exec-secret"  # noqa: S105
    config.DEFAULT_EXCHANGE = "binance"
    config.TELEGRAM_BOT_ENABLED = True
    config.BRIEF_ENABLED = False
    config.MCP_ENABLED = False
    config.RAG_ENABLED = False
    os.environ["DB_PATH"] = config.DB_PATH

    await database.init_db()

    import hub.notification_hub as notification_hub

    notification_hub.PENDING_TRADES.clear()

    # Import app inside the patched context to ensure the lifespan does not invoke real start_bot / stop_bot
    with patch("telegram_bot.start_bot"), patch("telegram_bot.stop_bot"):
        from execution_server import app

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac


# 1. Low confidence (< 50) triggers auto-reject.
@pytest.mark.asyncio
async def test_low_confidence_auto_reject(exec_client):
    """Payload with confidence < 50 triggers auto-reject and returns 400."""
    payload = {**VALID_PAYLOAD, "ai_confidence": 45}
    resp = await exec_client.post(
        "/api/execute-trade", json=payload, headers=VALID_HEADERS
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["success"] is False
    assert data["status"] == "auto_rejected"
    assert "auto-rejected" in data["error"].lower()

    # Verify signal is not in PENDING_TRADES
    import hub.notification_hub as notification_hub

    assert len(notification_hub.PENDING_TRADES) == 0


# 2. Medium confidence (50-79) is held, stored in PENDING_TRADES,
# sends the Telegram interactive message, and returns "status": "pending_approval".
@pytest.mark.asyncio
async def test_medium_confidence_holding(exec_client):
    """Payload with medium confidence (50-79) is held for approval, tracked in timeout manager."""
    payload = {**VALID_PAYLOAD, "ai_confidence": 65}

    mock_send = AsyncMock(return_value=[(123456, 7890)])
    mock_timeout_mgr = MagicMock()
    mock_timeout_mgr.track_message = MagicMock()

    with (
        patch("telegram_bot.send_interactive_trade_approval", mock_send),
        patch("telegram_bot.get_approval_timeout_mgr", return_value=mock_timeout_mgr),
    ):
        resp = await exec_client.post(
            "/api/execute-trade", json=payload, headers=VALID_HEADERS
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "pending_approval"
    signal_id = data["signal_id"]
    assert signal_id > 0

    # Verify event stored in PENDING_TRADES
    import hub.notification_hub as notification_hub

    assert signal_id in notification_hub.PENDING_TRADES
    event = notification_hub.PENDING_TRADES[signal_id]
    assert event.symbol == "BTCUSDT"
    assert event.confidence == 65
    assert event.interactive_required is True

    # Verify telegram send and tracking
    mock_send.assert_called_once()
    mock_timeout_mgr.track_message.assert_called_once_with(signal_id, 123456, 7890)


@pytest.mark.asyncio
async def test_hold_for_approval_true_holding(exec_client):
    """Payload with hold_for_approval=True is held for approval."""
    payload = {**VALID_PAYLOAD, "hold_for_approval": True}

    mock_send = AsyncMock(return_value=[(123456, 7890)])
    mock_timeout_mgr = MagicMock()
    mock_timeout_mgr.track_message = MagicMock()

    with (
        patch("telegram_bot.send_interactive_trade_approval", mock_send),
        patch("telegram_bot.get_approval_timeout_mgr", return_value=mock_timeout_mgr),
    ):
        resp = await exec_client.post(
            "/api/execute-trade", json=payload, headers=VALID_HEADERS
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["status"] == "pending_approval"
    signal_id = data["signal_id"]

    import hub.notification_hub as notification_hub

    assert signal_id in notification_hub.PENDING_TRADES


# 3. High confidence (>= 80) bypasses the gate and executes immediately.
@pytest.mark.asyncio
async def test_high_confidence_bypass(exec_client):
    """Payload with confidence >= 80 bypasses the gate and executes immediately."""
    payload = {**VALID_PAYLOAD, "ai_confidence": 85}

    from core.events import TradeExecuted

    async def mock_execute_trade(event):
        from engine import trade_engine

        current_bus = trade_engine.get_bus()
        await current_bus.emit(
            TradeExecuted(
                signal_id=event.signal_id,
                trade_id=1,
                symbol=event.symbol,
                side=event.action.upper(),
                order_id="ORD-BYPASS-001",
                status="FILLED",
                executed_qty=0.000735,
                executed_price=68000.0,
                quote_qty=50.0,
                exchange="binance",
            )
        )

    with patch("engine.trade_engine.execute_trade", side_effect=mock_execute_trade):
        with patch("notifier.notify_all", new_callable=AsyncMock):
            resp = await exec_client.post(
                "/api/execute-trade", json=payload, headers=VALID_HEADERS
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["order_id"] == "ORD-BYPASS-001"

    import hub.notification_hub as notification_hub

    assert len(notification_hub.PENDING_TRADES) == 0


# 4. Simulating the button callback (popping from PENDING_TRADES and emitting TradeApproved on the default event bus)
# triggers execute_trade and executes it on the exchange.
@pytest.mark.asyncio
async def test_simulate_button_callback_approval(exec_client):
    """Simulates popping a pending trade and emitting TradeApproved on the default event bus, verifying it executes."""
    # First, hold a trade for approval
    payload = {**VALID_PAYLOAD, "ai_confidence": 75}
    mock_send = AsyncMock(return_value=[(123456, 7890)])
    mock_timeout_mgr = MagicMock()
    mock_timeout_mgr.track_message = MagicMock()

    with (
        patch("telegram_bot.send_interactive_trade_approval", mock_send),
        patch("telegram_bot.get_approval_timeout_mgr", return_value=mock_timeout_mgr),
    ):
        resp = await exec_client.post(
            "/api/execute-trade", json=payload, headers=VALID_HEADERS
        )

    assert resp.status_code == 200
    signal_id = resp.json()["signal_id"]

    import hub.notification_hub as notification_hub
    from core.event_bus import bus as _default_bus
    from core.events import TradeApproved, TradeExecuted

    assert signal_id in notification_hub.PENDING_TRADES
    pending_event = notification_hub.PENDING_TRADES.pop(signal_id)

    # Mock the router and adapter
    mock_adapter = AsyncMock()
    mock_adapter.exchange_id = "binance"
    mock_adapter.exchange_name = "binance"
    mock_adapter.is_testnet = True
    mock_adapter.is_dry_run = True

    # Setup mock OrderResult
    from exchanges.base import OrderResult, RiskParams

    mock_risk = RiskParams(
        entry_price=68000.0,
        stop_loss_price=67000.0,
        take_profit_price=72000.0,
        stop_loss_pct=0.015,
        take_profit_pct=0.05,
        risk_reward_ratio=3.3,
        quantity=0.000735,
        cost=50.0,
        risk_amount=0.735,
        account_balance=1000.0,
        position_pct=0.05,
    )
    mock_order_result = OrderResult(
        success=True,
        dry_run=True,
        side="BUY",
        symbol="BTCUSDT",
        exchange="binance",
        entry_order={
            "orderId": "ORD-CALLBACK-001",
            "status": "FILLED",
            "executedQty": "0.000735",
            "cummulativeQuoteQty": "50.0",
        },
        risk=mock_risk,
    )
    mock_adapter.execute_smart_order = AsyncMock(return_value=mock_order_result)
    mock_adapter.get_account_balance = AsyncMock(return_value=1000.0)
    mock_adapter.get_ticker_price = AsyncMock(return_value=68000.0)

    # Capture execution event
    executed_events = []

    @_default_bus.on(TradeExecuted)
    async def capture_executed(event: TradeExecuted):
        executed_events.append(event)

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
        patch("notifier.notify_all", new_callable=AsyncMock),
    ):
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = mock_adapter
        mock_get_router.return_value = mock_router

        mock_db.get_rolling_drawdown = AsyncMock(return_value=0.0)
        mock_db.get_recent_profit_factor = AsyncMock(return_value=1.0)
        mock_db.get_setting = AsyncMock(
            side_effect=lambda key, default: (
                "false" if key == "safe_mode_active" else default
            )
        )
        mock_db.set_setting = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=101)
        mock_db.update_trade_oco = AsyncMock()
        mock_db.update_signal_status = AsyncMock()

        # Re-construct TradeApproved event and emit on default bus
        approved_event = TradeApproved(
            signal_id=signal_id,
            symbol=pending_event.symbol,
            action=pending_event.action,
            price=pending_event.price,
            quote_qty=pending_event.quote_qty,
            sl=pending_event.sl,
            tp=pending_event.tp,
            exchange=pending_event.exchange,
            approved_by="telegram_user",
            analysis_text=pending_event.analysis_text,
        )

        await _default_bus.emit(approved_event)

        # Allow async loop to process event handler
        await asyncio.sleep(0.1)

    assert len(executed_events) == 1
    assert executed_events[0].order_id == "ORD-CALLBACK-001"
    assert executed_events[0].signal_id == signal_id
