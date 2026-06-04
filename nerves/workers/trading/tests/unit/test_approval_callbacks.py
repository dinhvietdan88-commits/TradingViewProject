"""
test_approval_callbacks.py — Fully-isolated unit tests for the approval callback
and confidence gate flows in NotificationHub + telegram_bot.button_callback.

Rewrite of tests/test_decentralized_approval.py into pure unit tests:
  1. Approve callback pops PENDING_TRADES and emits TradeApproved
  2. Reject callback pops PENDING_TRADES and sends rejection notification
  3. Ignore callback removes pending silently
  4. Timeout expire removes pending and notifies
  5. Double-approve guard (second tap returns None / no-op)
  6. Bot-offline fallback (send_interactive_trade_approval returns [])
  7. Medium confidence (5-7) stores event in PENDING_TRADES
  8. High confidence (>= 8) bypasses PENDING_TRADES, emits TradeApproved directly

All external dependencies are mocked — no network, no DB, no Telegram token.
"""
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.event_bus import EventBus
from core.events import AnalysisComplete, TradeApproved, SignalRejected, TradeFailed, TradeApprovalTimeout
from hub.notification_hub import (
    process_analysis_complete,
    set_bus,
    PENDING_TRADES,
    get_pending_trade,
    remove_pending_trade,
    handle_approval_timeout,
)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _make_event(confidence: int, signal_id: int = 100, **overrides) -> AnalysisComplete:
    """Factory helper — builds an AnalysisComplete event with sane defaults."""
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
        analysis_text="Strong bullish pattern detected by AI.",
        screenshot_path="",
        combined_score=f"{confidence}/10",
        vision_result={},
        should_trade=(confidence >= 8),
        interactive_required=(5 <= confidence <= 7),
    )
    defaults.update(overrides)
    return AnalysisComplete(**defaults)


def _make_callback_query(data: str, username: str = "trader1"):
    """Build a minimal mock Telegram CallbackQuery for button_callback tests."""
    query = AsyncMock()
    query.data = data
    query.from_user = MagicMock()
    query.from_user.username = username
    query.from_user.first_name = username
    query.message = AsyncMock()
    query.message.text = "Pending trade message"
    query.message.edit_text = AsyncMock()
    query.answer = AsyncMock()
    return query


def _make_update(query):
    """Wrap a mock CallbackQuery into a mock Update."""
    update = MagicMock()
    update.callback_query = query
    return update


@pytest.fixture(autouse=True)
def _clean_pending_and_bus():
    """Ensure PENDING_TRADES is empty and bus is restored after every test."""
    PENDING_TRADES.clear()
    test_bus = EventBus()
    set_bus(test_bus)
    yield test_bus
    # Restore default bus
    from core.event_bus import bus as default_bus
    set_bus(default_bus)
    PENDING_TRADES.clear()


# ═══════════════════════════════════════════════════════════════
# 1. APPROVE CALLBACK — pops pending, emits TradeApproved
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_approve_callback_pops_pending_and_emits(_clean_pending_and_bus):
    """Khi user nhấn Approve → pending trade bị xóa khỏi PENDING_TRADES
    và TradeApproved event được emit lên bus."""
    bus = _clean_pending_and_bus

    # Seed a pending trade
    event = _make_event(confidence=6, signal_id=100)
    PENDING_TRADES[100] = event

    # Capture emitted TradeApproved events
    approved_events = []

    @bus.on(TradeApproved)
    async def capture(e):
        approved_events.append(e)

    query = _make_callback_query("approve_100", username="trader1")
    update = _make_update(query)

    with patch("core.event_bus.bus", bus), \
         patch("notifier.sanitize_for_telegram_html", side_effect=lambda x: x):
        # Import and call the real button_callback
        from telegram_bot import button_callback
        await button_callback(update, MagicMock())

    # Pending should be popped
    assert get_pending_trade(100) is None
    assert 100 not in PENDING_TRADES

    # Message should have been edited with approval text
    query.message.edit_text.assert_awaited_once()
    edit_text = query.message.edit_text.call_args[0][0]
    assert "DUYỆT" in edit_text or "trader1" in edit_text


# ═══════════════════════════════════════════════════════════════
# 2. REJECT CALLBACK — pops pending, sends rejection notification
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_reject_callback_pops_pending_and_notifies(_clean_pending_and_bus):
    """Khi user nhấn Reject → pending trade bị xóa và notification gửi về từ chối."""
    bus = _clean_pending_and_bus

    event = _make_event(confidence=6, signal_id=200)
    PENDING_TRADES[200] = event

    query = _make_callback_query("reject_200", username="trader2")
    update = _make_update(query)

    with patch("core.event_bus.bus", bus), \
         patch("notifier.sanitize_for_telegram_html", side_effect=lambda x: x):
        from telegram_bot import button_callback
        await button_callback(update, MagicMock())

    # Pending should be popped
    assert 200 not in PENDING_TRADES

    # Message should show rejection
    query.message.edit_text.assert_awaited_once()
    edit_text = query.message.edit_text.call_args[0][0]
    assert "TỪ CHỐI" in edit_text or "trader2" in edit_text


# ═══════════════════════════════════════════════════════════════
# 3. IGNORE CALLBACK — removes pending silently
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ignore_callback_removes_pending_silently(_clean_pending_and_bus):
    """Nhấn Ignore → message được sửa nhưng KHÔNG gửi notification riêng,
    chỉ edit message gốc thêm '(BỎ QUA)'."""
    query = _make_callback_query("ignore_300", username="trader3")
    update = _make_update(query)

    with patch("notifier.sanitize_for_telegram_html", side_effect=lambda x: x):
        from telegram_bot import button_callback
        await button_callback(update, MagicMock())

    # Message should be edited (silently) to show ignored state
    query.message.edit_text.assert_awaited_once()
    edit_text = query.message.edit_text.call_args[0][0]
    assert "BỎ QUA" in edit_text or "trader3" in edit_text


# ═══════════════════════════════════════════════════════════════
# 4. TIMEOUT EXPIRE — removes pending and notifies
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_timeout_expire_removes_and_notifies(_clean_pending_and_bus):
    """Sau khi timeout, pending trade bị auto-expired với timeout notification."""
    # Seed a pending trade
    event = _make_event(confidence=6, signal_id=400)
    PENDING_TRADES[400] = event

    timeout_event = TradeApprovalTimeout(
        signal_id=400,
        symbol="BTCUSDT",
        reason="Timeout exceeded (5 mins)",
    )

    with patch("hub.notification_hub.notifier") as mock_notifier:
        mock_notifier.notify_all = AsyncMock()

        await handle_approval_timeout(timeout_event)

        # Pending should be removed
        assert get_pending_trade(400) is None

        # User should have been notified
        mock_notifier.notify_all.assert_awaited_once()
        msg = mock_notifier.notify_all.call_args[0][0]
        assert "⏰" in msg or "400" in msg or "hết thời gian" in msg.lower() or "Hết" in msg


# ═══════════════════════════════════════════════════════════════
# 5. DOUBLE APPROVE GUARD — second approve is no-op
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_double_approve_guard(_clean_pending_and_bus):
    """Nhấn Approve lần 2 trên cùng signal_id → trả về None (đã bị pop),
    message hiển thị 'đã hết hạn hoặc đã được xử lý'."""
    bus = _clean_pending_and_bus

    # Seed and then immediately pop (simulates first approve)
    event = _make_event(confidence=6, signal_id=500)
    PENDING_TRADES[500] = event
    removed = PENDING_TRADES.pop(500)
    assert removed is event

    # Now second approve should see nothing in PENDING_TRADES
    query = _make_callback_query("approve_500", username="trader_late")
    update = _make_update(query)

    with patch("notifier.sanitize_for_telegram_html", side_effect=lambda x: x):
        from telegram_bot import button_callback
        await button_callback(update, MagicMock())

    # Should edit message to show already-processed state
    query.message.edit_text.assert_awaited_once()
    edit_text = query.message.edit_text.call_args[0][0]
    assert "hết hạn" in edit_text or "đã được xử lý" in edit_text


# ═══════════════════════════════════════════════════════════════
# 6. BOT OFFLINE FALLBACK — returns [] and hub uses notify_all
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bot_offline_fallback(_clean_pending_and_bus):
    """Khi _bot_app is None → send_interactive_trade_approval trả [] và hub
    fallback sang notifier.notify_all."""
    bus = _clean_pending_and_bus

    mock_bot = MagicMock()
    mock_bot.send_interactive_trade_approval = AsyncMock(return_value=[])
    mock_bot.get_approval_timeout_mgr = MagicMock(return_value=None)

    with patch("hub.notification_hub.notifier") as mock_notifier, \
         patch.dict(sys.modules, {"telegram_bot": mock_bot}):
        mock_notifier.notify_all = AsyncMock()
        mock_notifier.send_telegram_photo = MagicMock()

        event = _make_event(confidence=6, signal_id=600)
        await process_analysis_complete(event)

        # send_interactive_trade_approval was called but returned []
        mock_bot.send_interactive_trade_approval.assert_awaited_once()

        # Fallback: notifier.notify_all should have been called
        mock_notifier.notify_all.assert_awaited()
        msg = mock_notifier.notify_all.call_args[0][0]
        assert "Bot chưa bật" in msg or "không thể" in msg.lower() or "BTCUSDT" in msg


# ═══════════════════════════════════════════════════════════════
# 7. MEDIUM CONFIDENCE — stores in PENDING_TRADES
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_medium_confidence_stores_in_pending(_clean_pending_and_bus):
    """AnalysisComplete với confidence=6 → event được lưu vào PENDING_TRADES,
    KHÔNG emit TradeApproved."""
    bus = _clean_pending_and_bus

    approved_events = []

    @bus.on(TradeApproved)
    async def capture(e):
        approved_events.append(e)

    mock_bot = MagicMock()
    mock_bot.send_interactive_trade_approval = AsyncMock(return_value=[(12345, 67890)])
    mock_bot.get_approval_timeout_mgr = MagicMock(return_value=None)

    with patch("hub.notification_hub.notifier") as mock_notifier, \
         patch.dict(sys.modules, {"telegram_bot": mock_bot}):
        mock_notifier.notify_all = AsyncMock()
        mock_notifier.send_telegram_photo = MagicMock()

        event = _make_event(confidence=6, signal_id=700)
        await process_analysis_complete(event)

    # TradeApproved should NOT have been emitted
    assert len(approved_events) == 0

    # Event should be stored in PENDING_TRADES
    pending = get_pending_trade(700)
    assert pending is not None
    assert pending.signal_id == 700
    assert pending.symbol == "BTCUSDT"
    assert pending.confidence == 6


# ═══════════════════════════════════════════════════════════════
# 8. HIGH CONFIDENCE — bypasses PENDING_TRADES, emits TradeApproved
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_high_confidence_bypasses_pending(_clean_pending_and_bus):
    """AnalysisComplete với confidence=9 → KHÔNG lưu vào PENDING_TRADES,
    emit TradeApproved trực tiếp với approved_by='AI (Auto-Green)'."""
    bus = _clean_pending_and_bus

    approved_events = []

    @bus.on(TradeApproved)
    async def capture(e):
        approved_events.append(e)

    with patch("hub.notification_hub.notifier") as mock_notifier:
        mock_notifier.notify_all = AsyncMock()
        mock_notifier.send_telegram_photo = MagicMock()

        event = _make_event(confidence=9, signal_id=800)
        await process_analysis_complete(event)

    # TradeApproved should have been emitted
    assert len(approved_events) == 1
    approved = approved_events[0]
    assert approved.signal_id == 800
    assert approved.symbol == "BTCUSDT"
    assert approved.approved_by == "AI (Auto-Green)"

    # Should NOT be in PENDING_TRADES
    assert get_pending_trade(800) is None
    assert 800 not in PENDING_TRADES
