"""
Extended unit tests for NotificationHub component (v6.0).

Tests verify (gaps from original test_notification_hub.py):
- AnalysisComplete with confidence >= 8: auto-approve → emits TradeApproved.
- AnalysisComplete with confidence 5-7: human gate → stores in PENDING_TRADES, calls send_interactive_trade_approval.
- AnalysisComplete with confidence < 5: auto-reject → sends notification (NOT TradeApproved).
- TradeApprovalTimeout removes pending trade and notifies user.
- TradeExecuted notification includes exchange, symbol, execution details.
- TradeFailed notification includes error and signal_id.
- PositionClosed P&L notification: positive PNL uses 🟢, negative uses 🔴.
- PENDING_TRADES state: get/remove helpers work correctly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event_bus import EventBus
from core.events import (
    AnalysisComplete,
    PositionClosed,
    SignalRejected,
    TradeApprovalTimeout,
    TradeApproved,
    TradeExecuted,
    TradeFailed,
)

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════


def _make_analysis_event(
    confidence: int, signal_id: int = 100, **kwargs
) -> AnalysisComplete:
    defaults = dict(
        signal_id=signal_id,
        symbol="BTCUSDT",
        action="buy",
        price=68000.0,
        quote_qty=50.0,
        sl="66000",
        tp="72000",
        exchange="binance",
        confidence=confidence,
        analysis_text="Strong pattern detected.",
        screenshot_path="",
        combined_score=f"{confidence}/10",
        vision_result={},
        should_trade=(confidence >= 8),
        interactive_required=(5 <= confidence <= 7),
    )
    defaults.update(kwargs)
    return AnalysisComplete(**defaults)


# ═══════════════════════════════════════════════════════════════
# CONFIDENCE GATE: AUTO-APPROVE (>= 8)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_high_confidence_auto_approves_trade():
    """Confidence >= 8 → emit TradeApproved immediately without human interaction."""
    from hub.notification_hub import process_analysis_complete, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    approved_events = []

    @test_bus.on(TradeApproved)
    async def on_approved(event):
        approved_events.append(event)

    try:
        with patch("hub.notification_hub.notifier") as mock_notifier:
            mock_notifier.notify_all = AsyncMock()

            await process_analysis_complete(
                _make_analysis_event(confidence=8, signal_id=200)
            )

            assert len(approved_events) == 1
            evt = approved_events[0]
            assert evt.signal_id == 200
            assert evt.symbol == "BTCUSDT"
            assert evt.approved_by == "AI (Auto-Green)"
            # Notification should have been sent
            mock_notifier.notify_all.assert_awaited_once()
            msg = mock_notifier.notify_all.call_args[0][0]
            assert "AUTO-APPROVE" in msg or "auto" in msg.lower()
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


@pytest.mark.asyncio
async def test_max_confidence_auto_approves():
    """Confidence of 10 should also auto-approve."""
    from hub.notification_hub import process_analysis_complete, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    approved_events = []

    @test_bus.on(TradeApproved)
    async def on_approved(event):
        approved_events.append(event)

    try:
        with patch("hub.notification_hub.notifier") as mock_notifier:
            mock_notifier.notify_all = AsyncMock()
            await process_analysis_complete(
                _make_analysis_event(confidence=10, signal_id=201)
            )
            assert len(approved_events) == 1
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


# ═══════════════════════════════════════════════════════════════
# CONFIDENCE GATE: HUMAN GATE (5-7)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_medium_confidence_stores_pending_trade():
    """Confidence 5-7 → trade stored in PENDING_TRADES for interactive approval."""
    import sys

    from hub.notification_hub import (
        PENDING_TRADES,
        get_pending_trade,
        process_analysis_complete,
        remove_pending_trade,
        set_bus,
    )

    PENDING_TRADES.clear()

    test_bus = EventBus()
    set_bus(test_bus)
    approved_events = []

    @test_bus.on(TradeApproved)
    async def on_approved(event):
        approved_events.append(event)

    try:
        mock_bot = MagicMock()
        mock_bot.send_interactive_trade_approval = AsyncMock(
            return_value=[(12345, 67890)]
        )
        mock_bot.get_approval_timeout_mgr = MagicMock(return_value=None)

        with (
            patch("hub.notification_hub.notifier") as mock_notifier,
            patch.dict(sys.modules, {"telegram_bot": mock_bot}),
        ):
            mock_notifier.notify_all = AsyncMock()

            await process_analysis_complete(
                _make_analysis_event(confidence=6, signal_id=300)
            )

            # No auto-approve should have fired
            assert len(approved_events) == 0
            # Trade should be stored in PENDING_TRADES
            pending = get_pending_trade(300)
            assert pending is not None
            assert pending.signal_id == 300

        # Cleanup
        remove_pending_trade(300)
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        PENDING_TRADES.clear()


@pytest.mark.asyncio
async def test_human_gate_fallback_when_bot_not_running():
    """When interactive bot fails (returns no pairs), notifier.notify_all fallback is used."""
    import sys

    from hub.notification_hub import PENDING_TRADES, process_analysis_complete, set_bus

    PENDING_TRADES.clear()

    test_bus = EventBus()
    set_bus(test_bus)

    try:
        mock_bot = MagicMock()
        # No message pairs returned = bot not running
        mock_bot.send_interactive_trade_approval = AsyncMock(return_value=[])
        mock_bot.get_approval_timeout_mgr = MagicMock(return_value=None)

        with (
            patch("hub.notification_hub.notifier") as mock_notifier,
            patch.dict(sys.modules, {"telegram_bot": mock_bot}),
        ):
            mock_notifier.notify_all = AsyncMock()

            await process_analysis_complete(
                _make_analysis_event(confidence=5, signal_id=301)
            )

            # Fallback notify_all should have been called
            mock_notifier.notify_all.assert_awaited()
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        PENDING_TRADES.clear()


# ═══════════════════════════════════════════════════════════════
# CONFIDENCE GATE: AUTO-REJECT (< 5)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_low_confidence_auto_rejects():
    """Confidence < 5 → notification sent but NO TradeApproved emitted."""
    from hub.notification_hub import (
        PENDING_TRADES,
        notify_signal_rejected,
        process_analysis_complete,
        set_bus,
    )

    PENDING_TRADES.clear()

    test_bus = EventBus()
    set_bus(test_bus)
    approved_events = []

    test_bus.on(SignalRejected)(notify_signal_rejected)

    @test_bus.on(TradeApproved)
    async def on_approved(event):
        approved_events.append(event)

    try:
        with (
            patch("hub.notification_hub.notifier") as mock_notifier,
            patch("hub.notification_hub._get_vbs_metadata", AsyncMock(return_value={})),
        ):
            mock_notifier.notify_all = AsyncMock()

            await process_analysis_complete(
                _make_analysis_event(confidence=3, signal_id=400)
            )

            assert len(approved_events) == 0
            mock_notifier.notify_all.assert_awaited_once()
            msg = mock_notifier.notify_all.call_args[0][0]
            assert "TỰ ĐỘNG TỪ CHỐI" in msg or "🔴" in msg
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        PENDING_TRADES.clear()


@pytest.mark.asyncio
async def test_zero_confidence_auto_rejects():
    """Confidence = 0 (edge case) should also auto-reject."""
    from hub.notification_hub import (
        PENDING_TRADES,
        notify_signal_rejected,
        process_analysis_complete,
        set_bus,
    )

    PENDING_TRADES.clear()

    test_bus = EventBus()
    set_bus(test_bus)
    approved_events = []

    test_bus.on(SignalRejected)(notify_signal_rejected)

    @test_bus.on(TradeApproved)
    async def on_approved(event):
        approved_events.append(event)

    try:
        with (
            patch("hub.notification_hub.notifier") as mock_notifier,
            patch("hub.notification_hub._get_vbs_metadata", AsyncMock(return_value={})),
        ):
            mock_notifier.notify_all = AsyncMock()
            await process_analysis_complete(
                _make_analysis_event(confidence=0, signal_id=401)
            )
            assert len(approved_events) == 0
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        PENDING_TRADES.clear()


# ═══════════════════════════════════════════════════════════════
# APPROVAL TIMEOUT
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_approval_timeout_removes_pending_trade():
    """TradeApprovalTimeout should remove trade from PENDING_TRADES and notify."""
    from hub.notification_hub import (
        PENDING_TRADES,
        get_pending_trade,
        handle_approval_timeout,
        set_bus,
    )

    PENDING_TRADES.clear()

    # Pre-seed a pending trade
    dummy_event = _make_analysis_event(confidence=6, signal_id=500)
    PENDING_TRADES[500] = dummy_event

    test_bus = EventBus()
    set_bus(test_bus)

    try:
        with patch("hub.notification_hub.notifier") as mock_notifier:
            mock_notifier.notify_all = AsyncMock()

            timeout_event = TradeApprovalTimeout(
                signal_id=500, symbol="BTCUSDT", reason="Timeout exceeded (5 mins)"
            )
            await handle_approval_timeout(timeout_event)

            # Trade should be removed
            assert get_pending_trade(500) is None
            # User should be notified
            mock_notifier.notify_all.assert_awaited_once()
            msg = mock_notifier.notify_all.call_args[0][0]
            assert "500" in msg or "⏰" in msg
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        PENDING_TRADES.clear()


@pytest.mark.asyncio
async def test_approval_timeout_noop_if_no_pending():
    """TradeApprovalTimeout for unknown signal_id should log debug but NOT notify."""
    from hub.notification_hub import PENDING_TRADES, handle_approval_timeout, set_bus

    PENDING_TRADES.clear()

    test_bus = EventBus()
    set_bus(test_bus)

    try:
        with patch("hub.notification_hub.notifier") as mock_notifier:
            mock_notifier.notify_all = AsyncMock()

            timeout_event = TradeApprovalTimeout(signal_id=999, symbol="BTCUSDT")
            await handle_approval_timeout(timeout_event)

            # Should NOT notify — nothing was pending
            mock_notifier.notify_all.assert_not_awaited()
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


# ═══════════════════════════════════════════════════════════════
# TRADE EXECUTED NOTIFICATION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_trade_executed_notification_includes_symbol_and_exchange():
    """TradeExecuted → notify_all message must include symbol, exchange, and execution price."""
    from hub.notification_hub import notify_trade_executed, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    try:
        with patch("hub.notification_hub.notifier") as mock_notifier:
            mock_notifier.notify_all = AsyncMock()

            event = TradeExecuted(
                signal_id=600,
                trade_id=1,
                symbol="SOLUSDT",
                side="BUY",
                order_id="ORD-001",
                status="FILLED",
                executed_qty=10.0,
                executed_price=150.5,
                quote_qty=1505.0,
                stop_loss_price=140.0,
                take_profit_price=165.0,
                order_type="OCO",
                exchange="bybit",
            )
            await notify_trade_executed(event)

            mock_notifier.notify_all.assert_awaited_once()
            msg = mock_notifier.notify_all.call_args[0][0]
            assert "SOLUSDT" in msg
            assert "bybit" in msg.lower() or "Bybit" in msg
            assert "150.5" in msg
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


@pytest.mark.asyncio
async def test_dry_run_trade_executed_labeled():
    """A DRY_RUN trade execution should include the DRY_RUN label in notification."""
    from hub.notification_hub import notify_trade_executed, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    try:
        with patch("hub.notification_hub.notifier") as mock_notifier:
            mock_notifier.notify_all = AsyncMock()

            event = TradeExecuted(
                signal_id=601,
                trade_id=2,
                symbol="BTCUSDT",
                side="BUY",
                order_id="DRY-001",
                status="FILLED",
                executed_qty=0.001,
                executed_price=68000.0,
                quote_qty=68.0,
                order_type="DRY_RUN",
                exchange="binance",
            )
            await notify_trade_executed(event)

            msg = mock_notifier.notify_all.call_args[0][0]
            assert "DRY_RUN" in msg
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


# ═══════════════════════════════════════════════════════════════
# TRADE FAILED NOTIFICATION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_trade_failed_notification_includes_error():
    """TradeFailed → notify_all message must include the error string and signal_id."""
    from hub.notification_hub import notify_trade_failed, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    try:
        with patch("hub.notification_hub.notifier") as mock_notifier:
            mock_notifier.notify_all = AsyncMock()

            event = TradeFailed(
                signal_id=700,
                symbol="ETHUSDT",
                side="SELL",
                error="Insufficient balance for ETHUSDT",
                quote_qty=50.0,
                exchange="binance",
            )
            await notify_trade_failed(event)

            mock_notifier.notify_all.assert_awaited_once()
            msg = mock_notifier.notify_all.call_args[0][0]
            assert "Insufficient balance" in msg
            assert "700" in msg
            assert "ETHUSDT" in msg
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


# ═══════════════════════════════════════════════════════════════
# POSITION CLOSED P&L NOTIFICATION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_position_closed_profit_uses_green_emoji():
    """Positive PnL should use 🟢 emoji in the notification."""
    from hub.notification_hub import notify_position_closed, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    try:
        with patch("hub.notification_hub.notifier") as mock_notifier:
            mock_notifier.notify_all = AsyncMock()

            event = PositionClosed(
                symbol="BTCUSDT",
                side="BUY",
                entry_price=68000.0,
                exit_price=72000.0,
                quantity=0.001,
                pnl=4.0,
                pnl_pct=5.88,
                exit_reason="TAKE_PROFIT",
                exchange="binance",
            )
            await notify_position_closed(event)

            msg = mock_notifier.notify_all.call_args[0][0]
            assert "🟢" in msg
            assert "+4.0000" in msg or "4.0" in msg
            assert "TAKE_PROFIT" in msg or "Chốt lời" in msg
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


@pytest.mark.asyncio
async def test_position_closed_loss_uses_red_emoji():
    """Negative PnL should use 🔴 emoji in the notification."""
    from hub.notification_hub import notify_position_closed, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    try:
        with patch("hub.notification_hub.notifier") as mock_notifier:
            mock_notifier.notify_all = AsyncMock()

            event = PositionClosed(
                symbol="ETHUSDT",
                side="BUY",
                entry_price=3500.0,
                exit_price=3300.0,
                quantity=0.01,
                pnl=-2.0,
                pnl_pct=-5.71,
                exit_reason="STOP_LOSS",
                exchange="binance",
            )
            await notify_position_closed(event)

            msg = mock_notifier.notify_all.call_args[0][0]
            assert "🔴" in msg
            assert "STOP_LOSS" in msg or "Cắt lỗ" in msg
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


# ═══════════════════════════════════════════════════════════════
# PENDING TRADES STATE HELPERS
# ═══════════════════════════════════════════════════════════════


def test_get_pending_trade_returns_none_for_unknown():
    """get_pending_trade should return None for untracked signal IDs."""
    from hub.notification_hub import PENDING_TRADES, get_pending_trade

    PENDING_TRADES.clear()
    assert get_pending_trade(9999) is None


def test_remove_pending_trade_returns_event_and_cleans_up():
    """remove_pending_trade should return the stored event and remove it from the dict."""
    from hub.notification_hub import (
        PENDING_TRADES,
        get_pending_trade,
        remove_pending_trade,
    )

    PENDING_TRADES.clear()

    dummy = _make_analysis_event(confidence=6, signal_id=800)
    PENDING_TRADES[800] = dummy

    removed = remove_pending_trade(800)
    assert removed is dummy
    assert get_pending_trade(800) is None


def test_remove_pending_trade_noop_on_missing():
    """remove_pending_trade on missing signal_id should return None gracefully."""
    from hub.notification_hub import PENDING_TRADES, remove_pending_trade

    PENDING_TRADES.clear()
    result = remove_pending_trade(7777)
    assert result is None
