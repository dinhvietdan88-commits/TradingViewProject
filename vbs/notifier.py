import logging
import re
from typing import List

import httpx

import config

log = logging.getLogger(__name__)

# Parse multiple chat IDs
TELEGRAM_CHAT_IDS: list[str] = [
    c.strip() for c in config.TELEGRAM_CHAT_ID.split(",") if c.strip()
]


def sanitize_for_telegram_html(text: str) -> str:
    """Converts basic Markdown to Telegram-compatible HTML."""
    if not text:
        return ""
    # Escape HTML special chars first
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Restore safe tags
    text = text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    text = text.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    text = text.replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>")
    text = text.replace("&lt;pre&gt;", "<pre>").replace("&lt;/pre&gt;", "</pre>")

    # Simple Bold / Code transformations
    text = re.compile(r"\*\*(.*?)\*\*").sub(r"<b>\1</b>", text)
    text = re.compile(r"`([^`]+)`").sub(r"<code>\1</code>", text)

    return text


async def send_telegram_alert(
    message: str, reply_markup: dict = None, silent: bool = False
) -> list:
    """Sends a Telegram alert to all configured chat IDs. Returns sent message metadata."""
    sent_messages = []
    if not config.TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_IDS:
        return sent_messages

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    html_message = sanitize_for_telegram_html(message)

    async with httpx.AsyncClient(timeout=10.0) as client:
        for chat_id in TELEGRAM_CHAT_IDS:
            payload = {
                "chat_id": chat_id,
                "text": html_message,
                "parse_mode": "HTML",
                "disable_notification": silent,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup

            try:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    try:
                        resp_json = response.json()
                        msg_id = resp_json.get("result", {}).get("message_id")
                        if msg_id:
                            sent_messages.append(
                                {"chat_id": chat_id, "message_id": msg_id}
                            )
                    except Exception as parse_err:
                        log.error(
                            f"Failed to parse Telegram sendMessage response: {parse_err}"
                        )
                else:
                    log.error(f"Telegram Alert Error (chat={chat_id}): {response.text}")
            except Exception as e:
                log.error(f"Failed to send Telegram alert to {chat_id}: {e}")
    return sent_messages
