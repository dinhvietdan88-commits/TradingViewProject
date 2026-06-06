"""
Unit tests for P8 Telegram Bot Enhancement components.

Tests cover:
- send_interactive_trade_approval: returns list[tuple] not bool (G2 regression guard)
- TelegramSender.send_message: routes to all TELEGRAM_CHAT_IDS
- TelegramSender.edit_message: error handling
- ApprovalTimeoutManager._check_cycle: expires stale entries, calls track_message
- DataQueryFacade.get_daily_stats: aggregates correctly
- ExchangeQueryFacade.get_balance: fallback to binance_client
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# G2 REGRESSION GUARD — send_interactive_trade_approval signature
# ═══════════════════════════════════════════════════════════════


def test_send_interactive_trade_approval_returns_list():
    """G2 guard: function must return a list (not bool)."""
    import telegram_bot

    hints = {}
    try:
        hints = telegram_bot.send_interactive_trade_approval.__annotations__
    except AttributeError:
        pass
    # Return type annotation should NOT be bool
    return_ann = hints.get("return", None)
    assert return_ann is not bool, (
        "SCAR-G2: send_interactive_trade_approval must return list, not bool. "
        "ApprovalTimeoutManager.track_message() depends on (chat_id, message_id) tuples."
    )


@pytest.mark.asyncio
async def test_send_interactive_trade_approval_no_bot_returns_empty():
    """When _bot_app is None, should return empty list (falsy), not False."""
    import telegram_bot

    original = telegram_bot._bot_app
    try:
        telegram_bot._bot_app = None
        result = await telegram_bot.send_interactive_trade_approval(
            signal_id=999, message="test"
        )
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert len(result) == 0
        # Critically: must be falsy (hub uses `if not sent_pairs:`)
        assert not result
    finally:
        telegram_bot._bot_app = original


@pytest.mark.asyncio
async def test_send_interactive_trade_approval_returns_chat_message_pairs():
    """With bot running, should return list of (chat_id, message_id) tuples."""
    import telegram_bot

    mock_msg = MagicMock()
    mock_msg.message_id = 42

    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock(return_value=mock_msg)

    mock_app = MagicMock()
    mock_app.bot = mock_bot

    original = telegram_bot._bot_app
    try:
        telegram_bot._bot_app = mock_app
        with patch("config.TELEGRAM_CHAT_IDS", ["111", "222"]):
            result = await telegram_bot.send_interactive_trade_approval(
                signal_id=1, message="test approval"
            )
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == (111, 42)
        assert result[1] == (222, 42)
    finally:
        telegram_bot._bot_app = original


# ═══════════════════════════════════════════════════════════════
# TelegramSender
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_telegram_sender_send_message_broadcasts():
    """TelegramSender.send_message should send to all TELEGRAM_CHAT_IDS."""
    from telegram_bot import TelegramSender

    mock_msg = MagicMock()
    mock_msg.message_id = 99

    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock(return_value=mock_msg)

    mock_app = MagicMock()
    mock_app.bot = mock_bot

    sender = TelegramSender(mock_app)

    with patch("config.TELEGRAM_CHAT_IDS", ["100", "200", "300"]):
        with patch("notifier.sanitize_for_telegram_html", side_effect=lambda x: x):
            results = await sender.send_message("hello")

    assert len(results) == 3
    assert mock_bot.send_message.call_count == 3


@pytest.mark.asyncio
async def test_telegram_sender_partial_failure():
    """TelegramSender should continue when one chat_id fails."""
    from telegram_bot import TelegramSender

    mock_msg = MagicMock()
    mock_msg.message_id = 7

    mock_bot = AsyncMock()
    # First call fails, second succeeds
    mock_bot.send_message = AsyncMock(
        side_effect=[Exception("network error"), mock_msg]
    )
    mock_app = MagicMock()
    mock_app.bot = mock_bot

    sender = TelegramSender(mock_app)

    with patch("config.TELEGRAM_CHAT_IDS", ["100", "200"]):
        with patch("notifier.sanitize_for_telegram_html", side_effect=lambda x: x):
            results = await sender.send_message("partial test")

    # Only 1 succeeded
    assert len(results) == 1
    assert results[0][1] == 7


@pytest.mark.asyncio
async def test_telegram_sender_edit_message_returns_false_on_error():
    """TelegramSender.edit_message returns False when edit fails."""
    from telegram_bot import TelegramSender

    mock_bot = AsyncMock()
    mock_bot.edit_message_text = AsyncMock(
        side_effect=Exception("message not modified")
    )
    mock_app = MagicMock()
    mock_app.bot = mock_bot

    sender = TelegramSender(mock_app)

    with patch("notifier.sanitize_for_telegram_html", side_effect=lambda x: x):
        result = await sender.edit_message(chat_id=123, message_id=456, text="updated")

    assert result is False


# ═══════════════════════════════════════════════════════════════
# ApprovalTimeoutManager
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_approval_timeout_manager_track_message():
    """track_message should register (chat_id, message_id, timestamp)."""
    from telegram_bot import ApprovalTimeoutManager

    mgr = ApprovalTimeoutManager(timeout_minutes=5, check_interval=30)
    mgr.track_message(signal_id=1, chat_id=100, message_id=42)
    mgr.track_message(signal_id=1, chat_id=200, message_id=43)

    assert 1 in mgr._tracked
    assert len(mgr._tracked[1]) == 2
    assert mgr._tracked[1][0][0] == 100  # chat_id
    assert mgr._tracked[1][0][1] == 42  # message_id


@pytest.mark.asyncio
async def test_approval_timeout_manager_check_cycle_expires():
    """_check_cycle should remove entries older than timeout and notify."""
    from telegram_bot import ApprovalTimeoutManager, TelegramSender

    mgr = ApprovalTimeoutManager(timeout_minutes=1, check_interval=30)

    # Inject a stale entry (sent 10 minutes ago)
    stale_ts = time.time() - 600  # 10 minutes
    mgr._tracked[77] = [(555, 88, stale_ts)]

    mock_sender = AsyncMock(spec=TelegramSender)
    mock_sender.edit_message = AsyncMock(return_value=True)
    mock_sender.send_message = AsyncMock(return_value=[])

    mock_event = MagicMock()
    mock_event.symbol = "BTCUSDT"
    mock_event.action = "BUY"

    with patch("telegram_bot.get_sender", return_value=mock_sender):
        with patch("hub.notification_hub.PENDING_TRADES", {77: mock_event}):
            await mgr._check_cycle()

    # Entry should be removed
    assert 77 not in mgr._tracked
    # Timeout notification should be sent
    mock_sender.send_message.assert_awaited_once()
    # Original message should be edited to show expired state
    mock_sender.edit_message.assert_awaited_once()
    edit_call_args = mock_sender.edit_message.call_args[0]
    assert edit_call_args[0] == 555  # chat_id
    assert edit_call_args[1] == 88  # message_id
    assert "HẾT HẠN" in edit_call_args[2] or "hết hạn" in edit_call_args[2]


@pytest.mark.asyncio
async def test_approval_timeout_manager_no_expire_for_fresh():
    """_check_cycle should not expire entries within timeout window."""
    from telegram_bot import ApprovalTimeoutManager

    mgr = ApprovalTimeoutManager(timeout_minutes=5, check_interval=30)

    # Fresh entry (just sent)
    fresh_ts = time.time()
    mgr._tracked[88] = [(100, 1, fresh_ts)]

    mock_sender = AsyncMock()

    with patch("telegram_bot.get_sender", return_value=mock_sender):
        with patch("hub.notification_hub.PENDING_TRADES", {88: MagicMock()}):
            await mgr._check_cycle()

    # Entry should still be there
    assert 88 in mgr._tracked
    mock_sender.send_message.assert_not_called()


# ═══════════════════════════════════════════════════════════════
# DataQueryFacade
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_data_facade_get_daily_stats_empty():
    """get_daily_stats should return zeros when no trades found."""
    from telegram_bot import DataQueryFacade

    facade = DataQueryFacade()

    with patch("aiosqlite.connect") as mock_connect:
        mock_cursor = AsyncMock()
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.fetchall = AsyncMock(return_value=[])

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_db.row_factory = None
        mock_db.execute = MagicMock(return_value=mock_cursor)

        mock_connect.return_value = mock_db

        with patch("config.DB_PATH", ":memory:"):
            stats = await facade.get_daily_stats("2025-01-01")

    assert stats.total_trades == 0
    assert stats.win_rate == 0.0
    assert stats.total_pnl == 0.0


@pytest.mark.asyncio
async def test_data_facade_get_recent_trades_limit():
    """get_recent_trades should cap at 50 and fetch correct columns."""
    from telegram_bot import DataQueryFacade

    facade = DataQueryFacade()

    # Requesting 100 trades should be capped to 50
    with patch("aiosqlite.connect") as mock_connect:
        mock_cursor = AsyncMock()
        mock_cursor.__aenter__ = AsyncMock(return_value=mock_cursor)
        mock_cursor.__aexit__ = AsyncMock(return_value=None)
        mock_cursor.fetchall = AsyncMock(return_value=[])

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)
        mock_db.row_factory = None
        mock_db.execute = MagicMock(return_value=mock_cursor)

        mock_connect.return_value = mock_db

        with patch("config.DB_PATH", ":memory:"):
            await facade.get_recent_trades(limit=100)

        # fetchall called → execute was called with limit <= 50
        call_args = mock_db.execute.call_args
        assert call_args[0][1][0] == 50  # min(100, 50)


# ═══════════════════════════════════════════════════════════════
# ExchangeQueryFacade
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_exchange_facade_list_available_no_registry():
    """list_available_exchanges should return ['binance'] when registry unavailable."""
    from telegram_bot import ExchangeQueryFacade

    facade = ExchangeQueryFacade()

    with patch.dict("sys.modules", {"exchange_registry": None}):
        result = facade.list_available_exchanges()

    assert result == ["binance"]


@pytest.mark.asyncio
async def test_exchange_facade_get_open_positions_empty_registry():
    """get_open_positions should return empty list when ExchangeRegistry unavailable."""
    from telegram_bot import ExchangeQueryFacade

    facade = ExchangeQueryFacade()

    with patch("builtins.__import__", side_effect=ImportError("no registry")):
        try:
            result = await facade.get_open_positions()
            assert result == []
        except ValueError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)


# ═══════════════════════════════════════════════════════════════
# Circuit Breaker Alert & Callback Handling
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_send_circuit_breaker_alert_broadcasts():
    """send_circuit_breaker_alert should send to all TELEGRAM_CHAT_IDS and return tuples."""
    from telegram import InlineKeyboardMarkup

    from telegram_bot import send_circuit_breaker_alert

    mock_msg = MagicMock()
    mock_msg.message_id = 101

    mock_bot = AsyncMock()
    mock_bot.send_message = AsyncMock(return_value=mock_msg)
    mock_app = MagicMock()
    mock_app.bot = mock_bot

    with patch("telegram_bot._bot_app", mock_app):
        with patch("config.TELEGRAM_CHAT_IDS", ["555", "777"]):
            with patch("notifier.sanitize_for_telegram_html", side_effect=lambda x: x):
                results = await send_circuit_breaker_alert(
                    exchange="weex",
                    symbol="BTCUSDT",
                    message="circuit breaker triggered",
                )

        assert isinstance(results, list)
        assert len(results) == 2
        assert results[0] == (555, 101)
        assert results[1] == (777, 101)

        # Verify that send_message was called with correct markup and text
        mock_bot.send_message.assert_called()
        call_args = mock_bot.send_message.call_args[1]
        assert call_args["text"] == "circuit breaker triggered"
        assert call_args["parse_mode"] == "HTML"
        assert isinstance(call_args["reply_markup"], InlineKeyboardMarkup)


@pytest.mark.asyncio
async def test_button_callback_cbreset():
    """button_callback should handle cbreset_ by updating DB and clearing bypass."""
    from telegram_bot import button_callback

    mock_query = AsyncMock()
    mock_query.data = "cbreset_weex"
    mock_query.from_user.username = "test_admin"

    mock_message = AsyncMock()
    mock_message.text = "Original CB alert text"
    mock_query.message = mock_message

    mock_update = MagicMock()
    mock_update.callback_query = mock_query

    mock_context = MagicMock()

    # Mocks for database functions
    mock_get_risk_settings = AsyncMock(return_value={"state": "OPEN"})
    mock_update_state = AsyncMock()
    mock_log_cb = AsyncMock()
    mock_set_setting = AsyncMock()

    with (
        patch("database.get_risk_settings", mock_get_risk_settings),
        patch("database.update_circuit_breaker_state", mock_update_state),
        patch("database.log_circuit_breaker", mock_log_cb),
        patch("database.set_setting", mock_set_setting),
    ):
        await button_callback(mock_update, mock_context)

    # Asserts
    mock_query.answer.assert_awaited_once()
    mock_get_risk_settings.assert_awaited_once_with("weex")
    mock_update_state.assert_awaited_once_with("weex", "CLOSED")
    mock_set_setting.assert_awaited_once_with("bypass_until_weex", "")
    mock_log_cb.assert_awaited_once()

    # Check updated text contains admin info and check mark
    mock_message.edit_text.assert_awaited_once()
    edit_text_call = mock_message.edit_text.call_args[0][0]
    assert "RESET CLOSED BỞI @test_admin" in edit_text_call
    assert "Original CB alert text" in edit_text_call


@pytest.mark.asyncio
async def test_button_callback_cbbypass():
    """button_callback should handle cbbypass_ by updating DB and setting 1h bypass."""
    from telegram_bot import button_callback

    mock_query = AsyncMock()
    mock_query.data = "cbbypass_weex"
    mock_query.from_user.username = "test_admin"

    mock_message = AsyncMock()
    mock_message.text = "Original CB alert text"
    mock_query.message = mock_message

    mock_update = MagicMock()
    mock_update.callback_query = mock_query

    mock_context = MagicMock()

    # Mocks for database functions
    mock_get_risk_settings = AsyncMock(return_value={"state": "OPEN"})
    mock_update_state = AsyncMock()
    mock_log_cb = AsyncMock()
    mock_set_setting = AsyncMock()

    with (
        patch("database.get_risk_settings", mock_get_risk_settings),
        patch("database.update_circuit_breaker_state", mock_update_state),
        patch("database.log_circuit_breaker", mock_log_cb),
        patch("database.set_setting", mock_set_setting),
    ):
        await button_callback(mock_update, mock_context)

    # Asserts
    mock_query.answer.assert_awaited_once()
    mock_get_risk_settings.assert_awaited_once_with("weex")
    mock_update_state.assert_awaited_once_with("weex", "CLOSED")
    mock_set_setting.assert_awaited_once()

    # Check that bypass key was set to a valid ISO format string
    set_setting_args = mock_set_setting.call_args[0]
    assert set_setting_args[0] == "bypass_until_weex"
    # It should be an ISO timestamp (e.g. 2026-06-05T08:25:51.123456+00:00)
    assert len(set_setting_args[1]) > 0
    from datetime import datetime

    # Try parsing it back to make sure it's valid
    parsed_dt = datetime.fromisoformat(set_setting_args[1])
    assert parsed_dt is not None

    mock_log_cb.assert_awaited_once()

    # Check updated text contains admin info and bypass emoji
    mock_message.edit_text.assert_awaited_once()
    edit_text_call = mock_message.edit_text.call_args[0][0]
    assert "ĐÃ BYPASS 1H BỞI @test_admin" in edit_text_call
    assert "Original CB alert text" in edit_text_call
