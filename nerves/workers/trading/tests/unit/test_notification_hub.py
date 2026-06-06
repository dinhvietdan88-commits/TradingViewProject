"""
Unit tests for NotificationHub component (Phase 4).

Tests verify:
- SignalRejected event triggers Telegram/Discord notification.
- Notification message contains rejection reason.
- set_bus() pattern works for test isolation.
"""

from unittest.mock import AsyncMock, patch

import pytest

from core.event_bus import EventBus
from core.events import SignalRejected


@pytest.mark.asyncio
async def test_rejected_signal_notified():
    """A rejected signal should trigger notification with reason."""
    from hub.notification_hub import notify_signal_rejected, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    try:
        with patch("hub.notification_hub.notifier") as mock_notifier:
            mock_notifier.notify_all = AsyncMock()

            event = SignalRejected(
                signal_id=300,
                symbol="BTCUSDT",
                action="buy",
                reason="invalid_timeframe",
                interval="4h",
            )
            await notify_signal_rejected(event)

            # Notification should have been sent
            mock_notifier.notify_all.assert_awaited_once()
            call_args = mock_notifier.notify_all.call_args[0][0]

            # Verify message content
            assert "BTCUSDT" in call_args
            assert "BUY" in call_args
            assert "4h" in call_args
            assert "Từ Chối" in call_args or "⛔" in call_args
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


@pytest.mark.asyncio
async def test_duplicate_rejection_notified():
    """A duplicate signal rejection should have the correct reason text."""
    from hub.notification_hub import notify_signal_rejected, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    try:
        with patch("hub.notification_hub.notifier") as mock_notifier:
            mock_notifier.notify_all = AsyncMock()

            event = SignalRejected(
                signal_id=301,
                symbol="ETHUSDT",
                action="sell",
                reason="duplicate_signal",
            )
            await notify_signal_rejected(event)

            mock_notifier.notify_all.assert_awaited_once()
            call_args = mock_notifier.notify_all.call_args[0][0]

            assert "ETHUSDT" in call_args
            assert "SELL" in call_args
            assert "trùng lặp" in call_args or "dedup" in call_args
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)


@pytest.mark.asyncio
async def test_bus_isolation():
    """set_bus() should allow independent test instances."""
    from hub.notification_hub import get_bus, set_bus

    test_bus = EventBus()
    set_bus(test_bus)

    assert get_bus() is test_bus

    from core.event_bus import bus as default_bus

    set_bus(default_bus)
    assert get_bus() is default_bus
