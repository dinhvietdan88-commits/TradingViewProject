"""
Unit tests for Telegram Bot lifecycle thread safety and event loop management.
"""

import asyncio
import threading
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import telegram_bot


@pytest.mark.asyncio
async def test_telegram_bot_lifecycle_start_stop():
    """Test that starting and stopping the Telegram bot manages event loop thread-safely."""
    # Reset bot state before test
    telegram_bot._bot_app = None
    telegram_bot._bot_thread = None
    telegram_bot._bot_loop = None

    thread_exception = None

    def hook(args):
        nonlocal thread_exception
        thread_exception = args.exc_value

    threading.excepthook = hook

    mock_app = MagicMock()
    mock_app.updater = AsyncMock()
    mock_app.stop = AsyncMock()

    # When updater.stop() is called, do nothing
    async def mock_updater_stop():
        pass

    # When app.stop() is called, stop the background thread's event loop safely after completion
    async def mock_app_stop():
        loop = asyncio.get_event_loop()
        loop.call_soon(loop.stop)

    mock_app.updater.stop.side_effect = mock_updater_stop
    mock_app.stop.side_effect = mock_app_stop

    # Mock run_polling to run the event loop forever so it keeps running in the background thread
    def mock_run_polling(drop_pending_updates=False, close_loop=False):
        loop = asyncio.get_event_loop()
        loop.run_forever()

    mock_app.run_polling = MagicMock(side_effect=mock_run_polling)

    mock_builder = MagicMock()
    mock_builder.token.return_value = mock_builder
    mock_builder.request.return_value = mock_builder
    mock_builder.build.return_value = mock_app

    mock_request = MagicMock()
    mock_request._client_kwargs = {}
    mock_request._build_client.return_value = MagicMock()

    # Patch dependencies to avoid real networking or imports during start
    with (
        patch("telegram.ext.ApplicationBuilder", return_value=mock_builder),
        patch("telegram.request.HTTPXRequest", return_value=mock_request),
        patch("config.TELEGRAM_BOT_TOKEN", "mock_token"),
        patch(
            "telegram_bot._get_imports",
            return_value=(None, None, None, None, None, None, None),
        ),
        patch("telegram_bot._register_trade_lifecycle_handlers"),
        patch("telegram_bot.TelegramSender"),
    ):
        # Start the bot
        telegram_bot.start_bot()

        # Wait until bot is initialized or timeout (up to 5 seconds)
        for _ in range(100):
            if (
                telegram_bot._bot_app is not None
                and telegram_bot._bot_loop is not None
                and telegram_bot._bot_loop.is_running()
            ):
                break
            await asyncio.sleep(0.05)

        if thread_exception:
            raise thread_exception

        # Check that bot app and thread are registered
        assert telegram_bot._bot_app == mock_app
        assert telegram_bot._bot_thread is not None
        assert telegram_bot._bot_loop is not None
        assert telegram_bot._bot_loop.is_running()

        # Stop the bot gracefully
        telegram_bot.stop_bot()

        # Wait until bot resources are cleaned up or timeout (up to 5 seconds)
        for _ in range(100):
            if telegram_bot._bot_app is None and telegram_bot._bot_loop is None:
                break
            await asyncio.sleep(0.05)

        # Verify bot resources are cleaned up
        assert telegram_bot._bot_app is None
        assert telegram_bot._bot_thread is None
        assert telegram_bot._bot_loop is None
