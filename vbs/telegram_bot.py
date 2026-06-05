import asyncio
import logging
import httpx

import config
from database import update_signal_status

log = logging.getLogger(__name__)


async def start_telegram_long_polling():
    """Starts a background loop to long-poll Telegram getUpdates for CallbackQueries."""
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not configured. Long polling disabled.")
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0

    log.info("Starting Telegram Long Polling for interactive buttons...")

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            try:
                # Long polling parameters: timeout=20s blocks the connection until an update arrives
                response = await client.post(
                    url,
                    json={
                        "offset": offset,
                        "timeout": 20,
                        "allowed_updates": ["message", "callback_query"],
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        updates = data.get("result", [])
                        for update in updates:
                            update_id = update.get("update_id")
                            offset = update_id + 1  # Acknowledge the update

                            if "callback_query" in update:
                                await handle_callback_query(
                                    client, update["callback_query"]
                                )
                else:
                    log.error(f"Telegram getUpdates failed: {response.text}")
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                log.info("Telegram Long Polling stopped.")
                break
            except Exception as e:
                log.error(f"Error in Telegram long polling: {e}")
                await asyncio.sleep(5)


async def handle_callback_query(client: httpx.AsyncClient, callback_query: dict):
    """Processes button clicks from Telegram inline keyboards."""
    callback_id = callback_query.get("id")
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")
    original_text = message.get("text", "")

    log.info(
        f"Received Telegram Callback: {data} from user {callback_query.get('from', {}).get('id')}"
    )

    alert_text = "Processing..."
    new_message_text = original_text

    try:
        if data.startswith("approve_"):
            queue_id = int(data.split("_")[1])
            success = await update_signal_status(
                queue_id, "APPROVED", detail="Approved via Telegram"
            )
            if success:
                alert_text = f"✅ Signal #{queue_id} Approved!"
                new_message_text = f"✅ <b>APPROVED</b>\n\n{original_text}"
            else:
                alert_text = f"⚠️ Signal #{queue_id} already processed or cancelled!"

        elif data.startswith("cancel_"):
            queue_id = int(data.split("_")[1])
            success = await update_signal_status(
                queue_id, "CANCELLED", detail="Cancelled via Telegram"
            )
            if success:
                alert_text = f"❌ Signal #{queue_id} Cancelled!"
                new_message_text = f"❌ <b>CANCELLED</b>\n\n{original_text}"
            else:
                alert_text = f"⚠️ Signal #{queue_id} already processed or cancelled!"

    except Exception as e:
        log.error(f"Failed to process callback {data}: {e}")
        alert_text = "Internal error!"

    # 1. Answer the callback query to stop the loading spinner on Telegram client
    answer_url = (
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    )
    await client.post(
        answer_url, json={"callback_query_id": callback_id, "text": alert_text}
    )

    # 2. Update the original message if it was successfully changed (remove inline keyboard and append status)
    if new_message_text != original_text and chat_id and message_id:
        edit_url = (
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/editMessageText"
        )
        await client.post(
            edit_url,
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": new_message_text,
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": []
                },  # Remove buttons after interaction
            },
        )
