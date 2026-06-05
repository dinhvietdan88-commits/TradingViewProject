import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import notifier
from core.events import SignalRejected
from hub.notification_hub import notify_signal_rejected


@pytest.mark.asyncio
async def test_sanitize_strikethrough():
    """Verify that sanitize_for_telegram_html converts ~~ text ~~ into <s> text </s>."""
    text = "Double tildes: ~~BUY~~ and normal text."
    sanitized = notifier.sanitize_for_telegram_html(text)
    assert "<s>BUY</s>" in sanitized
    assert "~~" not in sanitized

    # Check that manual <s> tags are preserved
    text_manual = "Manual tag: <s>SELL</s>"
    sanitized_manual = notifier.sanitize_for_telegram_html(text_manual)
    assert "<s>SELL</s>" in sanitized_manual


@pytest.mark.asyncio
async def test_edit_telegram_message_fallback_direct_http():
    """Verify edit_telegram_message falls back to direct HTTP when bot daemon is None."""
    # Mock bot daemon to return None
    with patch("telegram_bot.get_sender", return_value=None):
        # Mock httpx/aiohttp ClientSession.post context manager correctly
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value="OK")

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_context)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch("config.TELEGRAM_BOT_TOKEN", "mock_token"):
                success = await notifier.edit_telegram_message(
                    chat_id=12345, message_id=67890, text="Updated text"
                )
                assert success is True
                # Confirm post was called on correct endpoint
                mock_session.post.assert_called_once()
                call_args = mock_session.post.call_args
                url = call_args[0][0]
                payload = call_args[1]["json"]
                assert "editMessageText" in url
                assert payload["chat_id"] == 12345
                assert payload["message_id"] == 67890


@pytest.mark.asyncio
async def test_notification_hub_edits_queue_message_on_rejection():
    """Verify notification_hub edits original message if VBS coordinates exist in payload."""
    event = SignalRejected(
        signal_id=1001,
        symbol="BTCUSDT",
        action="buy",
        reason="invalid_timeframe",
        exchange="binance",
    )

    # Mock the database helper to return message coordinates
    vbs_meta = {
        "tg_messages": [{"chat_id": 999, "message_id": 888}],
        "vbs_received_at": "2026-06-01 13:00:00",
        "vbs_queue_id": 193,
    }

    # Mock notifier functions
    with patch(
        "hub.notification_hub._get_vbs_metadata", AsyncMock(return_value=vbs_meta)
    ):
        with patch(
            "notifier.edit_telegram_message", AsyncMock(return_value=True)
        ) as mock_edit:
            with patch("notifier.send_discord_alert", AsyncMock()) as mock_discord:
                with patch("notifier.notify_all", AsyncMock()) as mock_notify_all:
                    await notify_signal_rejected(event)

                    # Verify edit_telegram_message was called instead of notify_all
                    mock_edit.assert_called_once()
                    mock_discord.assert_called_once()
                    mock_notify_all.assert_not_called()

                    # Verify edit message content contains queue details and strikethrough
                    edit_text = mock_edit.call_args[0][2]
                    assert "VBS Signal Queued" in edit_text
                    assert "ID: #193" in edit_text
                    assert (
                        "~~BUY~~" in edit_text
                        or "<s>BUY</s>" in edit_text
                        or "~~" in edit_text
                        or "<s>" in edit_text
                    )
