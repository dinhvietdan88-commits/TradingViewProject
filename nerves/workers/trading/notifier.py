import io
import logging
import re
from typing import Optional

import aiohttp

import config

# SEC-4: Import runtime guard for ReDoS prevention
try:
    from security.runtime_guard import safe_regex_input
except ImportError:
    # Graceful fallback if security module not available
    def safe_regex_input(
        text: str, max_len: int = 10000, *, truncate: bool = True
    ) -> str:  # type: ignore[misc]
        return text[:max_len] if len(text) > max_len else text


log = logging.getLogger(__name__)

# ── SEC-4 R3: Pre-compiled module-level patterns (avoids ReDoS via module cache) ──
# All patterns are compiled once at import; avoid recompiling inside hot paths.
_RE_BOLD = re.compile(r"\*\*([^*]{1,2000}?)\*\*")  # **text** -> <b>text</b>
_RE_STRIKETHROUGH = re.compile(r"~~([^~]{1,2000}?)~~")  # ~~text~~ -> <s>text</s>
_RE_ITALIC = re.compile(
    r"(?<!\w)\*(?!\s)([^*]{1,2000}?)(?<!\s)\*(?!\w)"
)  # *text* -> <i>text</i>
_RE_CODE_BLOCK = re.compile(
    r"```(?:[a-zA-Z]{0,20}\n)?([\s\S]{1,5000}?)```"
)  # ``` blocks
_RE_CODE_INLINE = re.compile(r"`([^`]{1,500})`")  # `code`
_RE_HEADING = re.compile(r"^#{1,6}\s+(.{1,500})$", re.MULTILINE)  # # Heading
_RE_LIST_ITEM = re.compile(r"^[*-]\s+", re.MULTILINE)  # * item / - item

# Maximum input length before applying markdown conversion (ReDoS guard)
_MAX_TELEGRAM_MSG_LEN = (
    10_000  # Telegram hard-limits messages to 4096, but we guard at 10K
)


def sanitize_for_telegram_html(text: str) -> str:
    """
    Converts Gemini-style Markdown to Telegram-compatible HTML.
    Handles bold, italic, monospace, headings, and basic escaping.
    """
    if not text:
        return ""

    # SEC-4 R3: Guard input length before applying backtracking regex patterns
    # Prevents ReDoS (CWE-400) on adversarial or unexpectedly large inputs.
    # Truncate to _MAX_TELEGRAM_MSG_LEN (10K) rather than raise, since this is
    # a best-effort formatting function — data loss is preferable to denial-of-service.
    text = safe_regex_input(text, max_len=_MAX_TELEGRAM_MSG_LEN, truncate=True)

    # First, recursively unescape HTML entities to get raw HTML tags
    # This prevents double-escaping if the AI model already returned escaped HTML tags (like &lt;b&gt;)
    for _ in range(3):
        new_text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        if new_text == text:
            break
        text = new_text

    # 1. Escape HTML special chars first
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Restore safe, valid Telegram HTML tags that might have been present in the input
    text = text.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    text = text.replace("&lt;strong&gt;", "<strong>").replace(
        "&lt;/strong&gt;", "</strong>"
    )
    text = text.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    text = text.replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>")
    text = text.replace("&lt;pre&gt;", "<pre>").replace("&lt;/pre&gt;", "</pre>")
    text = text.replace("&lt;s&gt;", "<s>").replace("&lt;/s&gt;", "</s>")
    text = text.replace("&lt;strike&gt;", "<strike>").replace(
        "&lt;/strike&gt;", "</strike>"
    )

    # 2. Convert Bold: **text** -> <b>text</b> (SEC-4: use pre-compiled _RE_BOLD)
    text = _RE_BOLD.sub(r"<b>\1</b>", text)

    # Convert ~~text~~ -> <s>text</s> (SEC-4: use pre-compiled _RE_STRIKETHROUGH)
    text = _RE_STRIKETHROUGH.sub(r"<s>\1</s>", text)

    # 3. Convert Italic: *text* -> <i>text</i> (SEC-4: use pre-compiled _RE_ITALIC)
    # Note: Using a more restrictive regex for italics to avoid catching lone asterisks or sub-parts of words
    text = _RE_ITALIC.sub(r"<i>\1</i>", text)

    # 4. Convert Code Blocks: ```code``` -> <pre>code</pre> (SEC-4: use pre-compiled _RE_CODE_BLOCK)
    # Note: Telegram HTML uses <pre><code>...</code></pre> for full blocks
    text = _RE_CODE_BLOCK.sub(r"<pre>\1</pre>", text)

    # 5. Convert Monospace: `text` -> <code>text</code> (SEC-4: use pre-compiled _RE_CODE_INLINE)
    text = _RE_CODE_INLINE.sub(r"<code>\1</code>", text)

    # 6. Convert Headings: # Heading -> <b>Heading</b> (SEC-4: use pre-compiled _RE_HEADING)
    text = _RE_HEADING.sub(r"<b>\1</b>", text)

    # 7. Convert Lists: * item or - item -> • item (SEC-4: use pre-compiled _RE_LIST_ITEM)
    text = _RE_LIST_ITEM.sub(r"• ", text)

    return text


async def send_telegram_alert(message: str):
    """Broadcast tin nhắn tới tất cả chat_id trong TELEGRAM_CHAT_IDS (CSV)."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_IDS:
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    html_message = sanitize_for_telegram_html(message)

    import socket

    conn = aiohttp.TCPConnector(family=socket.AF_INET)
    try:
        async with aiohttp.ClientSession(connector=conn) as session:
            for chat_id in config.TELEGRAM_CHAT_IDS:
                payload = {
                    "chat_id": chat_id,
                    "text": html_message,
                    "parse_mode": "HTML",
                }
                try:
                    async with session.post(url, json=payload) as response:
                        if response.status != 200:
                            log.error(
                                f"Telegram API Error (chat={chat_id}): {await response.text()}"
                            )
                except Exception as e:
                    log.error(f"Failed to send Telegram alert to {chat_id}: {e}")
    except Exception as e:
        log.error(f"Telegram session error: {e}")


async def edit_telegram_message(chat_id: int, message_id: int, text: str) -> bool:
    """Edit an existing Telegram message. Returns True on success."""
    if not config.TELEGRAM_BOT_TOKEN:
        return False

    # Try using active Telegram bot sender first if available
    try:
        import telegram_bot

        sender = telegram_bot.get_sender()
        if sender:
            # chat_id and message_id must be integers for TelegramBot API
            return await sender.edit_message(
                chat_id=int(chat_id), message_id=int(message_id), text=text
            )
    except Exception as e:
        log.warning(f"Failed to edit via telegram_bot: {e}")

    # Fallback to direct HTTP request if bot daemon is not running or fails
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/editMessageText"
    html_message = sanitize_for_telegram_html(text)
    payload = {
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "text": html_message,
        "parse_mode": "HTML",
    }
    import socket

    conn = aiohttp.TCPConnector(family=socket.AF_INET)
    try:
        async with aiohttp.ClientSession(connector=conn) as session:
            async with session.post(url, json=payload, timeout=10) as response:
                if response.status == 200:
                    return True
                else:
                    log.error(
                        f"Telegram Edit API Error (chat={chat_id}, msg={message_id}): {await response.text()}"
                    )
    except Exception as e:
        log.error(f"Failed to edit Telegram message directly: {e}")
    return False


async def send_discord_alert(message: str):
    """Gửi tin nhắn báo cáo qua Discord Webhook (Bất đồng bộ)"""
    if not config.DISCORD_WEBHOOK_URL:
        return

    payload = {"content": message}

    import socket

    conn = aiohttp.TCPConnector(family=socket.AF_INET)
    try:
        async with aiohttp.ClientSession(connector=conn) as session:
            async with session.post(
                config.DISCORD_WEBHOOK_URL, json=payload
            ) as response:
                if response.status not in (200, 204):
                    log.error(f"Discord API Error: {await response.text()}")
    except Exception as e:
        log.error(f"Failed to send Discord alert: {e}")


# ── P6: Sync wrappers + Photo support ────────────────────────────────────


def send_telegram_message(message: str):
    """
    Synchronous wrapper cho Telegram message.
    Dùng bởi brief.py qua asyncio.to_thread().

    BUG-07 fix: When called from a thread while the main event loop is running,
    we must schedule the coroutine ON the existing loop via run_coroutine_threadsafe,
    NOT by creating a second nested loop via asyncio.run (which raises
    'This event loop is already running' on Python 3.10+).
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Schedule on the existing loop and block until done
        future = asyncio.run_coroutine_threadsafe(send_telegram_alert(message), loop)
        future.result(timeout=30)
    else:
        asyncio.run(send_telegram_alert(message))


def prepare_telegram_photo(photo_path) -> Optional["io.BytesIO"]:
    """
    Checks if the photo is WebP, converts it to PNG in-memory if needed,
    otherwise reads it into a BytesIO buffer. Always returns a seeked BytesIO buffer.
    """
    import io
    from pathlib import Path

    photo_path = Path(photo_path)
    bio = io.BytesIO()

    try:
        with open(photo_path, "rb") as f:
            data = f.read()
    except Exception as e:
        log.error(f"Failed to read photo file {photo_path}: {e}")
        return None

    # Check magic bytes of WebP or file extension
    is_webp = (len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP") or (
        photo_path.suffix.lower() == ".webp"
    )

    if is_webp:
        try:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as img:
                img.save(bio, format="PNG")
                bio.seek(0)
                bio.name = photo_path.with_suffix(".png").name
                log.info(
                    f"Converted WebP photo to PNG in-memory: {photo_path.name} -> {bio.name}"
                )
                return bio
        except Exception as e:
            log.error(f"Failed to convert WebP to PNG for Telegram: {e}")
            # Fallback to returning raw WebP data if PIL fails

    bio.write(data)
    bio.seek(0)
    bio.name = photo_path.name
    return bio


def send_telegram_photo(photo_path, caption: str = ""):
    """
    Gửi ảnh (screenshot chart) qua Telegram Bot API.
    Dùng bởi brief.py qua asyncio.to_thread().
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_IDS:
        return

    from pathlib import Path

    import requests

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"
    photo_path = Path(photo_path)

    if not photo_path.exists():
        log.warning(f"Photo not found: {photo_path}")
        return

    photo_buf = prepare_telegram_photo(photo_path)
    if not photo_buf:
        log.error(f"Failed to prepare photo for Telegram: {photo_path}")
        return

    html_caption = sanitize_for_telegram_html(caption)

    for chat_id in config.TELEGRAM_CHAT_IDS:
        try:
            photo_buf.seek(0)  # Reset buffer position for each recipient
            data = {
                "chat_id": chat_id,
                "caption": html_caption[:1024],  # Telegram caption limit
                "parse_mode": "HTML",
            }
            mime_type = (
                "image/jpeg"
                if photo_buf.name.lower().endswith((".jpg", ".jpeg"))
                else "image/png"
            )
            files = {"photo": (photo_buf.name, photo_buf, mime_type)}
            response = requests.post(url, data=data, files=files, timeout=30)

            if response.status_code != 200:
                log.error(f"Telegram Photo API Error (chat={chat_id}): {response.text}")
            else:
                log.info(f"Telegram photo sent to {chat_id}: {photo_buf.name}")
        except Exception as e:
            log.error(f"Failed to send Telegram photo to {chat_id}: {e}")


async def notify_all(message: str):
    """Gửi cảnh báo đến tất cả các kênh được cấu hình"""
    await send_telegram_alert(message)
    await send_discord_alert(message)


async def send_scan_summary_to_telegram(serialised_results: list) -> None:
    """Gửi tóm tắt kết quả scan từ website lên Telegram.

    Called by /api/scan/trigger so that when the user clicks "Run Scan"
    on the dashboard, a short summary is also forwarded to the bot chat.

    Args:
        serialised_results: List of scan result dicts (same shape as /api/scan/trigger response).
    """
    if not serialised_results:
        return

    from datetime import datetime

    from utils.telegram_templates import render_template

    results_lines = []
    for idx, r in enumerate(serialised_results, 1):
        symbol = r.get("symbol", "N/A")
        if r.get("error"):
            results_lines.append(
                f"{idx}. 🔴 <b>{symbol}</b> — <b>LỖI KẾT NỐI</b>\n   • <code>{r.get('error')}</code>"
            )
            continue

        vcp_detected = r.get("vcp_detected", False)
        tt_score = r.get("trend_template_score", 0)
        vcp_star = "⭐ " if vcp_detected else "🟢 "

        if tt_score >= 8:
            stage = "Stage 2"
        elif 5 <= tt_score <= 7:
            stage = "Stage 1/2"
        else:
            stage = "Stage 1"
            vcp_star = "🟡 " if not vcp_detected else "⭐ "

        price = r.get("price", 0)
        price_str = f"{price:,.2f}" if price >= 1 else f"{price:.4f}"
        vol_ratio = r.get("volume_ratio", 0)

        results_lines.append(
            f"{idx}. {vcp_star}<b>{symbol}</b> — <b>{stage}</b> (Score {tt_score}/8)\n"
            f"   • Giá: <code>{price_str}</code> | Vol: <code>{vol_ratio:.1f}x avg</code>"
        )
    scan_results_list = "\n".join(results_lines)
    scan_time = datetime.now().strftime("%H:%M:%S (UTC+7)")

    message = render_template(
        "B", scan_time=scan_time, scan_results_list=scan_results_list
    )
    await send_telegram_alert(message)
