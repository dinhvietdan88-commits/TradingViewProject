"""
P7 Sprint 7.4+7.2 — Telegram Bot Interactive
Chuyển từ push-only notification → interactive bot với commands.

Commands:
    /start      - Giới thiệu bot
    /help       - Danh sách commands
    /status     - Server + MCP + Scheduler status
    /brief      - Chạy Morning Brief ngay
    /scan       - Scan watchlist (Trend Template + VCP)
    /vision SYM - AI Vision phân tích chart screenshot
    /grade      - AI Mentor chấm điểm trade (bảo toàn Bar Replay)
    /watchlist  - Xem watchlist hiện tại
    /add SYM    - Thêm symbol vào watchlist
    /remove SYM - Xóa symbol khỏi watchlist
    /balance    - Xem Binance account balance

Kiến trúc:
    Bot chạy trong background thread (polling) song song với FastAPI.
    Bot gọi trực tiếp vào các module: watchlist, analysis, brief, mcp_client.
"""

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, UTC

log = logging.getLogger(__name__)

# Lazy imports — only load if bot is enabled
_bot_app = None
_bot_thread = None
_bot_loop = None
_approval_timeout_mgr = None
_report_auto_send_task = None
running_tasks = set()
active_commands = set()


def _get_imports():
    """Lazy import python-telegram-bot to avoid crash if not installed."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import (
        ApplicationBuilder,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
    )

    return (
        Update,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        ApplicationBuilder,
        CommandHandler,
        CallbackQueryHandler,
        ContextTypes,
    )


# ── Interactive Messaging ──────────────────────────────────────────────────


async def send_interactive_trade_approval(
    signal_id: int,
    message: str,
    photo_path: str | None = None,
    photo_caption: str | None = None,
) -> list:
    """Send interactive trade approval message with Approve/Reject buttons.

    If photo_path is provided, sends the chart image first, then the
    interactive message with Approve/Reject inline keyboard.

    Returns:
        List[Tuple[int, int]]: List of (chat_id, message_id) for successfully sent messages.
        Empty list means failure / bot not running (falsy — preserves hub fallback logic).

    NOTE: Return type changed from bool → list[tuple] in P8/P9 to enable
    ApprovalTimeoutManager.track_message() to edit messages on timeout (REQ7).
    """
    global _bot_app
    if not _bot_app:
        return []

    results = []
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        import config
        from notifier import sanitize_for_telegram_html

        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Duyệt (Approve)", callback_data=f"approve_{signal_id}"
                ),
                InlineKeyboardButton(
                    "❌ Hủy (Reject)", callback_data=f"reject_{signal_id}"
                ),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        html_message = sanitize_for_telegram_html(message)

        for chat_id in config.TELEGRAM_CHAT_IDS:
            try:
                # Send chart photo first if available
                if photo_path:
                    try:
                        from pathlib import Path

                        from notifier import prepare_telegram_photo

                        photo_file_path = Path(photo_path)
                        if photo_file_path.exists():
                            caption = (
                                photo_caption
                                or f"📊 Chart Analysis — Signal #{signal_id}"
                            )
                            photo_buf = prepare_telegram_photo(photo_file_path)
                            if photo_buf:
                                await _bot_app.bot.send_photo(
                                    chat_id=chat_id,
                                    photo=photo_buf,
                                    caption=caption,
                                )
                            log.info(
                                f"Chart photo sent for signal #{signal_id} to {chat_id}"
                            )
                    except Exception as photo_err:
                        log.warning(
                            f"Failed to send chart photo to {chat_id}: {photo_err}"
                        )

                # Send interactive message with Approve/Reject buttons
                msg = await _bot_app.bot.send_message(
                    chat_id=chat_id,
                    text=html_message,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                results.append((int(chat_id), msg.message_id))
            except Exception as e:
                log.error(f"Failed to send interactive message to {chat_id}: {e}")

    except Exception as e:
        log.error(f"Error sending interactive trade approval: {e}")

    return results


async def send_interactive_indicator_alert(
    signal_id: int,
    symbol: str,
    message: str,
    photo_path: str | None = None,
    photo_caption: str | None = None,
) -> list:
    """Send interactive indicator alert with AI Scan and Dismiss buttons.

    If photo_path is provided, sends the chart image first as a photo message,
    then the interactive message with inline keyboard buttons.

    Returns:
        List[Tuple[int, int]]: List of (chat_id, message_id) for successfully sent messages.
    """
    global _bot_app
    if not _bot_app:
        return []

    results = []
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        import config
        from notifier import sanitize_for_telegram_html

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔍 Quét AI / VCP", callback_data=f"analyze_{symbol}"
                ),
                InlineKeyboardButton(
                    "📊 Xem Chart",
                    url=f"https://www.tradingview.com/chart/?symbol={symbol}",
                ),
                InlineKeyboardButton("❌ Bỏ Qua", callback_data=f"ignore_{signal_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        html_message = sanitize_for_telegram_html(message)

        for chat_id in config.TELEGRAM_CHAT_IDS:
            try:
                # Send chart photo first if available
                if photo_path:
                    try:
                        from pathlib import Path

                        from notifier import prepare_telegram_photo

                        photo_file_path = Path(photo_path)
                        if photo_file_path.exists():
                            caption = (
                                photo_caption
                                or f"📊 Indicator Chart — {symbol} (Signal #{signal_id})"
                            )
                            photo_buf = prepare_telegram_photo(photo_file_path)
                            if photo_buf:
                                await _bot_app.bot.send_photo(
                                    chat_id=chat_id,
                                    photo=photo_buf,
                                    caption=caption,
                                )
                            log.info(
                                f"Indicator chart photo sent for signal #{signal_id} to {chat_id}"
                            )
                    except Exception as photo_err:
                        log.warning(
                            f"Failed to send indicator chart photo to {chat_id}: {photo_err}"
                        )

                msg = await _bot_app.bot.send_message(
                    chat_id=chat_id,
                    text=html_message,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                results.append((int(chat_id), msg.message_id))
            except Exception as e:
                log.error(
                    f"Failed to send interactive indicator alert to {chat_id}: {e}"
                )

    except Exception as e:
        log.error(f"Error sending interactive indicator alert: {e}")

    return results


async def send_circuit_breaker_alert(
    exchange: str, symbol: str, message: str, photo_path: str | None = None
) -> list:
    """Send interactive circuit breaker alert with Reset Closed and Bypass 1h buttons."""
    global _bot_app
    if not _bot_app:
        return []

    results = []
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        import config
        from notifier import sanitize_for_telegram_html

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 Reset Closed", callback_data=f"cbreset_{exchange}"
                ),
                InlineKeyboardButton(
                    "⚡ Bypass 1h", callback_data=f"cbbypass_{exchange}"
                ),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        html_message = sanitize_for_telegram_html(message)

        for chat_id in config.TELEGRAM_CHAT_IDS:
            try:
                # Send photo first if available
                if photo_path:
                    try:
                        from pathlib import Path

                        from notifier import prepare_telegram_photo

                        photo_file_path = Path(photo_path)
                        if photo_file_path.exists():
                            caption = f"🚨 Circuit Breaker Alert — {exchange.upper()}"
                            photo_buf = prepare_telegram_photo(photo_file_path)
                            if photo_buf:
                                await _bot_app.bot.send_photo(
                                    chat_id=chat_id,
                                    photo=photo_buf,
                                    caption=caption,
                                )
                    except Exception as photo_err:
                        log.warning(
                            f"Failed to send cb photo to {chat_id}: {photo_err}"
                        )

                msg = await _bot_app.bot.send_message(
                    chat_id=chat_id,
                    text=html_message,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                results.append((int(chat_id), msg.message_id))
            except Exception as e:
                log.error(f"Failed to send cb alert message to {chat_id}: {e}")

    except Exception as e:
        log.error(f"Error sending cb alert: {e}")

    return results


# ── Command Handlers ──────────────────────────────────────────────────────


async def cmd_start(update, context):
    """Giới thiệu bot."""
    from telegram import ReplyKeyboardMarkup

    reply_keyboard = [["📊 Scan", "🌅 Morning Brief"], ["📋 Watchlist", "🔧 Status"]]
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)

    text = (
        "🤖 <b>Minervini AI Trading Bot v7.0</b>\n\n"
        "Tôi là bot giao dịch dựa trên chiến lược <b>SEPA</b> của Mark Minervini.\n\n"
        "🧠 <b>Khả năng:</b>\n"
        "• Scan watchlist — Trend Template (8 criteria) + VCP\n"
        "• Morning Brief tự động 07:00 ICT\n"
        "• RAG AI phân tích dựa trên sách Minervini\n"
        "• 👁️ AI Vision — Claude nhìn chart nhận diện pattern\n"
        "• Screenshot chart qua TradingView MCP\n\n"
        "Dùng /help để xem commands hoặc chọn bên dưới:"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def cmd_help(update, context):
    """Danh sách commands."""
    await update.message.reply_text(
        "📖 <b>Commands:</b>\n\n"
        "/status — Server + MCP + Scheduler status\n"
        "/brief — Chạy Morning Brief ngay\n"
        "/scan — Scan watchlist (TT + VCP)\n"
        "/scan_all — Scan toàn bộ sàn trong background (USDT pairs)\n"
        "/scan_mtf <code>SYMBOL</code> — Phân tích đa khung thời gian (1D -> 4H -> 1H) & Duyệt lệnh\n"
        "/recommend — Gợi ý cơ hội giao dịch đa khung từ Watchlist\n"
        "/vision <code>SYMBOL</code> — 👁️ AI Vision phân tích chart\n"
        "/grade — 👨‍🏫 AI Mentor chấm điểm trade (Bar Replay)\n"
        "/watchlist — Xem danh sách symbols\n"
        "/add <code>SYMBOL</code> — Thêm symbol (VD: /add FPT)\n"
        "/remove <code>SYMBOL</code> — Xóa symbol (VD: /remove SOLUSDT)\n"
        "/balance — 💰 Xem Binance account balance\n"
        "/help — Hiện menu này",
        parse_mode="HTML",
    )


async def cmd_status(update, context):
    """Trạng thái hệ thống — REQ10 AC2+3: includes per-exchange health block."""
    import config

    lines = [
        "🔧 **System Status**\n",
        f"⏰ Server time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        f"🌐 Server: FastAPI v7.0 on :{config.PORT}",
    ]

    # RAG status
    has_anthropic = bool(
        config.ANTHROPIC_API_KEY
        and not config.ANTHROPIC_API_KEY.startswith("sk-ant-xxx")
    )
    has_gemini = bool(config.GEMINI_API_KEY or config.GCP_PROJECT_ID)
    rag_status = (
        "✅ Enabled"
        if config.RAG_ENABLED and (has_anthropic or has_gemini)
        else "❌ Disabled"
    )
    lines.append(f"🧠 RAG: {rag_status}")

    # MCP status
    if config.MCP_ENABLED:
        try:
            from mcp_client import get_mcp_client

            mcp = get_mcp_client()
            health = await mcp.health_check()
            mcp_status = (
                "✅ Connected" if health.get("connected") else "⚠️ Not connected"
            )
        except Exception:
            mcp_status = "⚠️ Error"
    else:
        mcp_status = "❌ Disabled"
    lines.append(f"🖥️ MCP (CDP:{config.MCP_CDP_PORT}): {mcp_status}")

    # Scheduler status
    brief_status = "✅ Active" if config.BRIEF_ENABLED else "❌ Disabled"
    lines.append(f"⏰ Brief Scheduler: {brief_status} ({config.BRIEF_CRON_TIME} ICT)")

    # Telegram
    tg_status = "✅ Connected" if config.TELEGRAM_BOT_TOKEN else "❌ No token"
    lines.append(f"📱 Telegram: {tg_status}")

    # Watchlist
    try:
        from watchlist import get_watchlist

        wl = get_watchlist()
        lines.append(f"📋 Watchlist: {len(wl)} symbols")
    except Exception:
        lines.append("📋 Watchlist: Error loading")

    # ── REQ10 AC2+3: Per-exchange health block ────────────────────────────
    lines.append("")
    lines.append("🏦 **Exchange Health**")
    try:
        exchange_health = await _exchange_facade.get_exchange_health()
        if exchange_health:
            for eh in exchange_health:
                status_icon = "✅" if eh.healthy else "❌"
                mode_parts = []
                if eh.is_dry_run:
                    mode_parts.append("DRY")
                mode_parts.append("TEST" if eh.is_testnet else "LIVE")
                latency_str = (
                    f" | {eh.latency_ms:.0f}ms" if eh.latency_ms is not None else ""
                )
                mode_label = "/".join(mode_parts)
                lines.append(
                    f"- {status_icon} `{eh.exchange.upper()}` [{mode_label}]{latency_str}"
                )
        else:
            lines.append("- ⚠️ No exchanges registered")
    except Exception as e:
        lines.append(f"- ⚠️ Exchange health check failed: {e}")

    # ── P8 background task status ─────────────────────────────────────────
    lines.append("")
    lines.append("⚙️ **P8 Background Tasks**")
    pm_status = (
        "✅ Running"
        if _position_monitor and _position_monitor._running
        else "❌ Stopped"
    )
    tm_status = (
        "✅ Running"
        if _approval_timeout_mgr and _approval_timeout_mgr._running
        else "❌ Stopped"
    )
    lines.append(f"- 📡 PositionMonitor: {pm_status}")
    lines.append(f"- ⏱️ ApprovalTimeout: {tm_status}")
    report_sched = "✅ Active" if config.REPORT_AUTO_SEND else "❌ Off"
    lines.append(
        f"- 📊 ReportScheduler: {report_sched} ({config.REPORT_SEND_TIME} ICT)"
    )

    from notifier import sanitize_for_telegram_html

    html_text = sanitize_for_telegram_html("\n".join(lines))
    await update.message.reply_text(html_text, parse_mode="HTML")


async def cmd_watchlist(update, context):
    """Xem watchlist hiện tại."""
    try:
        from watchlist import get_watchlist

        symbols = get_watchlist()

        if not symbols:
            await update.message.reply_text(
                "📋 Watchlist trống. Dùng /add <code>SYMBOL</code> để thêm.",
                parse_mode="HTML",
            )
            return

        symbol_list = "\n".join(f"  • <code>{s}</code>" for s in symbols)
        await update.message.reply_text(
            f"📋 <b>Watchlist</b> ({len(symbols)} symbols):\n\n{symbol_list}\n\n"
            "Dùng /add <code>SYM</code> hoặc /remove <code>SYM</code> để quản lý.",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_add(update, context):
    """Thêm symbol vào watchlist."""
    if not context.args:
        await update.message.reply_text(
            "⚠️ Cần chỉ định symbol.\nVD: /add <code>BTCUSDT</code>",
            parse_mode="HTML",
        )
        return

    symbol = context.args[0].strip().upper()

    try:
        from watchlist import add_symbol

        result = add_symbol(symbol)

        if result.get("added"):
            await update.message.reply_text(
                f"✅ Đã thêm <code>{symbol}</code> vào watchlist.\n"
                f"📋 Total: {len(result.get('watchlist', []))} symbols",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                f"⚠️ <code>{symbol}</code> đã có trong watchlist.",
                parse_mode="HTML",
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_remove(update, context):
    """Xóa symbol khỏi watchlist."""
    if not context.args:
        await update.message.reply_text(
            "⚠️ Cần chỉ định symbol.\nVD: /remove <code>SOLUSDT</code>",
            parse_mode="HTML",
        )
        return

    symbol = context.args[0].strip().upper()

    try:
        from watchlist import remove_symbol

        result = remove_symbol(symbol)

        if result.get("removed"):
            await update.message.reply_text(
                f"🗑️ Đã xóa <code>{symbol}</code> khỏi watchlist.\n"
                f"📋 Còn lại: {len(result.get('watchlist', []))} symbols",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                f"⚠️ <code>{symbol}</code> không có trong watchlist.",
                parse_mode="HTML",
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_scan(update, context):
    """Scan watchlist — Trend Template + VCP."""
    chat_id = update.effective_chat.id
    cmd_key = (chat_id, "scan")
    if cmd_key in active_commands:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Yêu cầu scan trước đó của bạn vẫn đang được xử lý. Vui lòng đợi.",
        )
        return
    active_commands.add(cmd_key)
    await context.bot.send_message(chat_id=chat_id, text="🔄 Đang xử lý...")

    async def process_task():
        try:
            from analysis import scan_symbols
            from watchlist import get_watchlist

            symbols = get_watchlist()
            if not symbols:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="📋 Watchlist trống. Dùng /add để thêm symbols.",
                )
                return

            # Check MCP
            import config

            mcp = None
            if config.MCP_ENABLED:
                try:
                    from mcp_client import get_mcp_client

                    mcp = get_mcp_client()
                except Exception as e:
                    log.debug(f"MCP check failed: {e}")

            results = await scan_symbols(symbols, mcp)

            if not results:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Không scan được symbol nào. Kiểm tra MCP connection.",
                )
                return

            # ── Save to shared cache so the website can see these results ────────
            try:
                import scan_cache

                serialised = [
                    {
                        "symbol": r.symbol,
                        "price": r.price,
                        "change_pct": r.change_pct,
                        "trend_template_score": r.trend_template.score
                        if r.trend_template
                        else 0,
                        "trend_template_stage": r.trend_template.stage
                        if r.trend_template
                        else "-",
                        "trend_template_criteria": r.trend_template.criteria
                        if r.trend_template
                        else [],
                        "vcp_detected": r.vcp.detected if r.vcp else False,
                        "vol_breakout": getattr(r.vcp, "vol_breakout", False)
                        if r.vcp
                        else False,
                        "volume_ratio": round(r.vcp.volume_ratio, 2) if r.vcp else 0,
                        "range_ratio": round(r.vcp.range_ratio, 2) if r.vcp else 0,
                        "pivot_level": r.vcp.pivot_level if r.vcp else None,
                        "vcp_note": r.vcp.note if r.vcp else None,
                        "error": r.error,
                    }
                    for r in results
                ]
                scan_cache.save_scan_results(
                    serialised, source="telegram", symbol_list=symbols
                )
            except Exception as _ce:
                log.warning(f"cmd_scan cache save failed (non-fatal): {_ce}")

            # Format results table
            lines = [f"📊 **Scan Results** ({len(results)} symbols)\n"]
            lines.append("```")
            lines.append(
                f"{'Symbol':<10} {'Price':>10} {'TT':>4} {'VCP':>5} {'Vol%':>6}"
            )
            lines.append("─" * 40)

            for r in results:
                tt_score = r.trend_template.score if r.trend_template else "?"
                tt_max = 8
                vcp = "⭐" if r.vcp and r.vcp.detected else ""
                vol_ratio = r.vcp.volume_ratio if r.vcp else 0
                vol_pct = f"{vol_ratio * 100:.0f}%" if vol_ratio else "N/A"
                price = r.price

                if price >= 1000:
                    price_str = f"{price:,.0f}"
                elif price >= 1:
                    price_str = f"{price:,.2f}"
                else:
                    price_str = f"{price:.4f}"

                lines.append(
                    f"{r.symbol:<10} {price_str:>10} {tt_score}/{tt_max}  {vcp:<3} {vol_pct:>5}"
                )

            lines.append("```")

            # VCP highlights
            vcp_setups = [r for r in results if r.vcp and r.vcp.detected]
            if vcp_setups:
                lines.append("\n🎯 **VCP Setups:**")
                for r in vcp_setups:
                    pivot = r.vcp.pivot_level if r.vcp and r.vcp.pivot_level else 0
                    vol_ratio = (
                        r.vcp.volume_ratio if r.vcp and r.vcp.volume_ratio else 0
                    )
                    lines.append(
                        f"• `{r.symbol}` — Vol: {vol_ratio * 100:.0f}% avg, "
                        f"Pivot: {pivot:,.2f}"
                    )

            from notifier import sanitize_for_telegram_html

            html_output = sanitize_for_telegram_html("\n".join(lines))
            await context.bot.send_message(
                chat_id=chat_id, text=html_output, parse_mode="HTML"
            )

        except Exception as e:
            log.error(f"Scan error: {e}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Scan failed: {e}")
        finally:
            active_commands.discard(cmd_key)

    task = asyncio.create_task(process_task())
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)


async def cmd_brief(update, context):
    """Chạy Morning Brief on-demand."""
    await update.message.reply_text(
        "🌅 Đang chạy Morning Brief... Vui lòng chờ 30-60s."
    )

    try:
        from brief import generate_morning_brief

        result = await generate_morning_brief()

        if result and result.get("success"):
            await update.message.reply_text(
                "✅ Morning Brief đã gửi! Kiểm tra chat để xem report đầy đủ."
            )
        else:
            error = result.get("error", "Unknown") if result else "No result"
            await update.message.reply_text(f"⚠️ Brief hoàn thành với lỗi: {error}")

    except Exception as e:
        log.error(f"Brief trigger error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Brief failed: {e}")


async def cmd_vision(update, context):
    """AI Vision — phân tích chart screenshot bằng Claude Vision."""
    chat_id = update.effective_chat.id
    cmd_key = (chat_id, "vision")
    if cmd_key in active_commands:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Yêu cầu vision trước đó của bạn vẫn đang được xử lý. Vui lòng đợi.",
        )
        return
    active_commands.add(cmd_key)
    await context.bot.send_message(chat_id=chat_id, text="🔄 Đang xử lý...")

    async def process_task():
        try:
            if not context.args:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Cần chỉ định symbol.\nVD: /vision <code>BTCUSDT</code>",
                    parse_mode="HTML",
                )
                return

            symbol = context.args[0].strip().upper()
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"👁️ Đang phân tích chart <code>{symbol}</code>... Vui lòng chờ.",
                parse_mode="HTML",
            )

            try:
                from pathlib import Path

                import config

                # Check for existing screenshot
                screenshots_dir = Path(__file__).parent / "screenshots"
                screenshot_path = None

                # Try to capture new screenshot via MCP
                if config.MCP_ENABLED:
                    try:
                        from mcp_client import get_mcp_client

                        mcp = get_mcp_client()
                        health = await mcp.health_check()
                        if health.get("connected"):
                            import re
                            from datetime import datetime as dt

                            safe_symbol = re.sub(r"[^A-Za-z0-9_\-]", "", symbol)
                            screenshot_path = await mcp.capture_screenshot(
                                symbol=symbol,
                                timeframe="D",
                                region="chart",
                                save_path=screenshots_dir
                                / f"vision_{safe_symbol}_{dt.now().strftime('%Y%m%d_%H%M%S')}.png",
                            )
                    except Exception as e:
                        log.warning(f"Vision screenshot capture failed: {e}")

                # Fallback: look for latest screenshot of this symbol
                if not screenshot_path or not Path(screenshot_path).exists():
                    if screenshots_dir.exists():
                        candidates = sorted(
                            screenshots_dir.glob(f"*{symbol}*.png"),
                            key=lambda p: p.stat().st_mtime,
                            reverse=True,
                        )
                        if candidates:
                            screenshot_path = candidates[0]

                if not screenshot_path or not Path(screenshot_path).exists():
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⚠️ Không tìm thấy screenshot cho <code>{symbol}</code>.\n"
                        "Cần TradingView MCP connected hoặc screenshot sẵn có.",
                        parse_mode="HTML",
                    )
                    return

                # Run Vision analysis
                from vision import analyze_chart_vision, format_vision_telegram

                result = await analyze_chart_vision(
                    image_path=Path(screenshot_path),
                    symbol=symbol,
                )

                if result.get("error"):
                    await context.bot.send_message(
                        chat_id=chat_id, text=f"❌ Vision error: {result['error']}"
                    )
                    return

                from notifier import sanitize_for_telegram_html

                vision_text = format_vision_telegram(result)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=sanitize_for_telegram_html(vision_text),
                    parse_mode="HTML",
                )

            except Exception as e:
                log.error(f"Vision command error: {e}", exc_info=True)
                await context.bot.send_message(
                    chat_id=chat_id, text=f"❌ Vision failed: {e}"
                )
        finally:
            active_commands.discard(cmd_key)

    task = asyncio.create_task(process_task())
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)


async def cmd_grade(update, context):
    """AI Mentor — chấm điểm setup Long/Short trên màn hình hiện tại."""
    chat_id = update.effective_chat.id
    cmd_key = (chat_id, "grade")
    if cmd_key in active_commands:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Yêu cầu grade trước đó của bạn vẫn đang được xử lý. Vui lòng đợi.",
        )
        return
    active_commands.add(cmd_key)
    await context.bot.send_message(chat_id=chat_id, text="🔄 Đang xử lý...")

    async def process_task():
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="👨‍🏫 Đang chụp và phân tích lệnh của bạn... Vui lòng chờ.",
                parse_mode="HTML",
            )

            from pathlib import Path

            import config

            if not config.MCP_ENABLED:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Tính năng này yêu cầu bật MCP_ENABLED = True.",
                )
                return

            screenshots_dir = Path(__file__).parent / "screenshots"
            screenshot_path = None

            try:
                from mcp_client import get_mcp_client

                mcp = get_mcp_client()
                health = await mcp.health_check()
                if health.get("connected"):
                    from datetime import datetime as dt

                    # Chụp màn hình hiện tại (active_only=True) để không phá Bar Replay
                    screenshot_path = await mcp.capture_screenshot(
                        symbol="active",
                        timeframe="active",
                        region="chart",
                        save_path=screenshots_dir
                        / f"grade_{dt.now().strftime('%Y%m%d_%H%M%S')}.png",
                        active_only=True,
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id, text="⚠️ TradingView chưa kết nối (MCP CDP)."
                    )
                    return
            except Exception as e:
                log.warning(f"Grade screenshot capture failed: {e}")
                await context.bot.send_message(
                    chat_id=chat_id, text=f"❌ Lỗi chụp TradingView: {e}"
                )
                return

            if not screenshot_path or not Path(screenshot_path).exists():
                await context.bot.send_message(
                    chat_id=chat_id, text="⚠️ Không lấy được ảnh từ TradingView."
                )
                return

            # Run Vision analysis on the captured screenshot
            from vision import analyze_chart_vision, format_vision_telegram

            # Use symbol from args or fallback to "CHART"
            symbol = context.args[0].upper() if context.args else "ACTIVE CHART"

            result = await analyze_chart_vision(
                image_path=Path(screenshot_path),
                symbol=symbol,
            )

            if result.get("error"):
                await context.bot.send_message(
                    chat_id=chat_id, text=f"\u274c Vision error: {result['error']}"
                )
                return

            from notifier import sanitize_for_telegram_html

            formatted = format_vision_telegram(result)
            await context.bot.send_message(
                chat_id=chat_id,
                text=sanitize_for_telegram_html(formatted),
                parse_mode="HTML",
            )

        except Exception as e:
            log.error(f"Grade command error: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=chat_id, text=f"❌ Grade failed: {e}"
            )
        finally:
            active_commands.discard(cmd_key)

    task = asyncio.create_task(process_task())
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)


async def cmd_balance(update, context):
    """Xem Binance account balance."""
    try:
        import binance_client as binance_module

        client = binance_module.get_client()
        asset = context.args[0].upper() if context.args else "USDT"
        balance = await client.get_account_balance(asset)

        mode = []
        if client.dry_run:
            mode.append("DRY-RUN")
        mode.append("TESTNET" if client.testnet else "MAINNET")
        mode_str = ", ".join(mode)

        from notifier import sanitize_for_telegram_html

        text = (
            f"💰 **Binance Balance**\n\n"
            f"- Asset: `{asset}`\n"
            f"- Balance: `${balance:,.2f}`\n"
            f"- Mode: `{mode_str}`"
        )
        await update.message.reply_text(
            sanitize_for_telegram_html(text),
            parse_mode="HTML",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def handle_menu_text(update, context):
    """Handler cho ReplyKeyboardMarkup buttons."""
    text = update.message.text
    if text == "📊 Scan":
        await cmd_scan_enhanced(update, context)
    elif text == "🌅 Morning Brief":
        await cmd_brief(update, context)
    elif text == "📋 Watchlist":
        await cmd_watchlist(update, context)
    elif text == "🔧 Status":
        await cmd_status(update, context)


# ── P8 New Command Handlers ────────────────────────────────────────────────


async def cmd_positions(update, context):
    """REQ3: /positions [EXCHANGE] — show open positions with unrealized P&L."""
    from notifier import sanitize_for_telegram_html

    exchange_id = context.args[0].lower() if context.args else None
    await update.message.reply_text("📡 Đang tải vị thế mở...")

    positions = await _exchange_facade.get_open_positions(exchange_id)

    if not positions:
        label = exchange_id.upper() if exchange_id else "tất cả sàn"
        await update.message.reply_text(
            sanitize_for_telegram_html(f"📭 Không có vị thế mở nào trên **{label}**."),
            parse_mode="HTML",
        )
        return

    lines = [f"📊 **Vị Thế Mở** ({len(positions)})\n"]
    for p in positions:
        pnl_emoji = "🟢" if p.unrealized_pnl >= 0 else "🔴"
        lines.append(
            f"{pnl_emoji} `{p.symbol}` [{p.exchange.upper()}]\n"
            f"   Chiều: **{p.side.upper()}** | Qty: `{p.quantity:,.4f}`\n"
            f"   Vào: `{p.entry_price:,.4f}` → Hiện: `{p.current_price:,.4f}`\n"
            f"   P&L: `${p.unrealized_pnl:+,.2f}` (`{p.unrealized_pnl_pct:+.2f}%`)"
        )

    await update.message.reply_text(
        sanitize_for_telegram_html("\n".join(lines)), parse_mode="HTML"
    )


async def cmd_rag(update, context):
    """REQ5: /rag <query> — ask Minervini knowledge base."""
    import config

    if not config.RAG_ENABLED or not (
        config.ANTHROPIC_API_KEY or config.GEMINI_API_KEY
    ):
        await update.message.reply_text(
            "❌ RAG system is disabled (RAG_ENABLED=false or no API key)."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ Cần chỉ định câu hỏi.\nVD: /rag <code>What is VCP?</code>",
            parse_mode="HTML",
        )
        return

    query = " ".join(context.args)
    thinking_msg = await update.message.reply_text(
        f"🧠 Đang suy nghĩ về: <i>{query}</i>...", parse_mode="HTML"
    )

    try:
        from rag import generate_trading_advice, query_knowledge

        chunks = await query_knowledge(query)
        if not chunks:
            await thinking_msg.edit_text(
                "⚠️ Không tìm thấy thông tin liên quan trong knowledge base."
            )
            return

        advice = await generate_trading_advice(query, chunks)
        response_text = f"🧠 <b>RAG Answer</b>\n\n<i>Q: {query}</i>\n\n{advice}"
        from notifier import sanitize_for_telegram_html

        await thinking_msg.edit_text(
            sanitize_for_telegram_html(response_text), parse_mode="HTML"
        )
    except Exception as e:
        log.error(f"cmd_rag error: {e}", exc_info=True)
        await thinking_msg.edit_text(f"❌ RAG failed: {e}")


async def cmd_trades(update, context):
    """REQ6: /trades [N] — show last N trade records (default 10, max 50)."""
    limit = 10
    if context.args:
        try:
            limit = min(int(context.args[0]), 50)
        except ValueError:
            # ignore invalid limit format
            pass

    trades = await _data_facade.get_recent_trades(limit=limit)

    if not trades:
        await update.message.reply_text("📭 Chưa có lịch sử giao dịch nào.")
        return

    lines = [f"📋 **Lịch Sử Giao Dịch** (last {len(trades)})\n"]
    for t in trades:
        pnl_emoji = "🟢" if (t.pnl or 0) > 0 else ("🔴" if (t.pnl or 0) < 0 else "⚪")
        pnl_str = f"${t.pnl:+,.2f}" if t.pnl is not None else "—"
        exit_str = f"{t.exit_price:,.4f}" if t.exit_price else "OPEN"
        lines.append(
            f"{pnl_emoji} `{t.symbol}` {t.side.upper()} [{t.exchange.upper()}]\n"
            f"   Vào: `{t.entry_price:,.4f}` → Ra: `{exit_str}` | P&L: **{pnl_str}**\n"
            f"   *{t.created_at[:16]}*"
        )

    from notifier import sanitize_for_telegram_html

    await update.message.reply_text(
        sanitize_for_telegram_html("\n".join(lines)), parse_mode="HTML"
    )


# ── /backtest menu helpers ────────────────────────────────────────────────────


def _backtest_menu_keyboard():
    """Build the InlineKeyboardMarkup for /backtest menu."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = [
        [
            InlineKeyboardButton("📈 Equity Curve (All)", callback_data="bt_all"),
            InlineKeyboardButton("📊 MTT vs MIS", callback_data="bt_mode"),
        ],
        [
            InlineKeyboardButton("📋 Trade History", callback_data="bt_history"),
            InlineKeyboardButton("🔢 All 3 Charts", callback_data="bt_full"),
        ],
        [
            InlineKeyboardButton("₿  BTCUSDT", callback_data="bt_sym_BTCUSDT"),
            InlineKeyboardButton("Ξ  ETHUSDT", callback_data="bt_sym_ETHUSDT"),
            InlineKeyboardButton("◎ SOLUSDT", callback_data="bt_sym_SOLUSDT"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def _run_backtest_charts(
    send_fn,  # coroutine func(photo=buf, caption=...) — bot.send_photo wrapper
    send_msg_fn,  # coroutine func(text=...) — bot.send_message wrapper
    mode: str = "full",  # "full" | "equity" | "mode" | "history"
    symbol: str | None = None,
):
    """Shared chart executor called from both inline callback and direct command.

    Args:
        send_fn:     Async callable(photo: BytesIO, caption: str) → sends a Telegram photo
        send_msg_fn: Async callable(text: str) → sends a plain text message
        mode:        Which charts to render:
                       'full'    = equity + mode comparison + history
                       'equity'  = equity curve only
                       'mode'    = MTT vs MIS comparison only
                       'history' = trade history table only
        symbol:      Optional symbol filter (e.g. 'BTCUSDT')
    """
    import database
    from charting import (
        generate_backtest_chart,
        generate_history_chart,
        generate_mode_chart,
    )
    from notifier import sanitize_for_telegram_html

    # ── Fetch all data in parallel ────────────────────────────────────────────
    equity_data, stats_data, recent_trades = await asyncio.gather(
        database.get_equity_curve(symbol),
        database.get_stats_by_mode(),
        database.get_recent_trades(limit=10, symbol=symbol),
    )

    has_equity = len(equity_data.get("labels", [])) > 0
    has_stats = stats_data.get("overall", {}).get("total_trades", 0) > 0
    has_history = len(recent_trades) > 0

    if not has_equity and not has_stats and not has_history:
        await send_msg_fn(
            "📭 Chưa có dữ liệu giao dịch. Hệ thống đang ở DRY-RUN — chờ lệnh đầu tiên được fill."
        )
        return

    sym_lbl = f" [{symbol}]" if symbol else ""
    sent = 0

    # ── Chart 1: Equity Curve ─────────────────────────────────────────────────
    if mode in ("full", "equity") and has_equity:
        title = f"Minervini Strategy{sym_lbl}"
        buf = await asyncio.to_thread(
            generate_backtest_chart, equity_data, title, symbol
        )
        n = len(equity_data["labels"])
        final = equity_data["cumulative_pnl"][-1]
        dd_max = max(equity_data.get("drawdown_pct", [0]) or [0])
        caption = (
            f"📈 <b>Equity Curve{sym_lbl}</b>\n"
            f"Trades: <b>{n}</b> | Net P&L: <b>${final:+,.2f}</b> | Max DD: <b>{dd_max:.1f}%</b>\n"
            f"<i>3 panels: equity / drawdown / per-trade PnL</i>"
        )
        await send_fn(buf, sanitize_for_telegram_html(caption))
        sent += 1

    # ── Chart 2: MTT vs MIS Mode Comparison ───────────────────────────────────
    if mode in ("full", "mode") and has_stats:
        buf2 = await asyncio.to_thread(generate_mode_chart, stats_data)
        mtt = stats_data["by_mode"].get("MTT", {})
        mis = stats_data["by_mode"].get("MIS", {})
        caption2 = (
            "📊 <b>MTT vs MIS — Mode Comparison</b>\n"
            f"[MTT] Daily: {mtt.get('total_trades', 0)}T  WR={mtt.get('win_rate', 0):.1f}%  P&L=${mtt.get('total_pnl', 0):+,.2f}\n"
            f"[MIS] 1H: {mis.get('total_trades', 0)}T  WR={mis.get('win_rate', 0):.1f}%  P&L=${mis.get('total_pnl', 0):+,.2f}"
        )
        await send_fn(buf2, sanitize_for_telegram_html(caption2))
        sent += 1
    elif mode == "mode" and not has_stats:
        await send_msg_fn("📭 Chưa có dữ liệu theo mode (chưa có lệnh FILLED).")

    # ── Chart 3: Trade History Table ──────────────────────────────────────────
    if mode in ("full", "history") and has_history:
        hist_title = f"Trade History (Last {len(recent_trades)}){sym_lbl}"
        buf3 = await asyncio.to_thread(
            generate_history_chart, recent_trades, hist_title
        )
        hist_lines = []
        for t in recent_trades[:5]:
            pnl = t.get("pnl") or 0
            emoji = "✅" if pnl > 0 else "❌"
            date = str(t.get("created_at", ""))[:10]
            hist_lines.append(
                f"{emoji} <b>{t.get('symbol')}</b> [{t.get('mode', '?')}] "
                f"{str(t.get('side', '')).upper()}  <b>${pnl:+,.2f}</b>  <i>{date}</i>"
            )
        caption3 = (
            f"📋 <b>Lịch sử {len(recent_trades)} lệnh gần nhất{sym_lbl}</b>\n"
            + "\n".join(hist_lines)
            + (
                "\n<i>...xem bảng đầy đủ trong ảnh</i>"
                if len(recent_trades) > 5
                else ""
            )
        )
        await send_fn(buf3, sanitize_for_telegram_html(caption3))
        sent += 1
    elif mode == "history" and not has_history:
        await send_msg_fn("📭 Chưa có lịch sử giao dịch.")

    if sent == 0:
        await send_msg_fn("📭 Không có dữ liệu cho lựa chọn này.")


async def cmd_backtest(update, context):
    """BACKTEST: /backtest — hiển thị menu chọn loại chart.

    Khi gọi không có argument → hiện inline keyboard menu.
    Khi gọi với argument (BTCUSDT, mode, ...) → chạy trực tiếp (legacy).
    """
    from notifier import sanitize_for_telegram_html

    chat_id = update.effective_chat.id
    args = context.args

    # ── Legacy direct call: /backtest BTCUSDT or /backtest mode ──────────────
    if args:
        mode_only = args[0].lower() == "mode"
        history_only = args[0].lower() == "history"
        symbol_arg = args[0].upper() if not mode_only and not history_only else None
        chart_mode = "mode" if mode_only else ("history" if history_only else "full")

        await context.bot.send_message(
            chat_id=chat_id, text="📊 Đang tạo chart... vui lòng chờ 5-10s."
        )

        async def _send_photo(buf, caption):
            await context.bot.send_photo(
                chat_id=chat_id, photo=buf, caption=caption, parse_mode="HTML"
            )

        async def _send_msg(text):
            await context.bot.send_message(chat_id=chat_id, text=text)

        try:
            await _run_backtest_charts(
                _send_photo, _send_msg, mode=chart_mode, symbol=symbol_arg
            )
        except Exception as e:
            log.error(f"cmd_backtest direct error: {e}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Lỗi: {e}")
        return

    # ── Interactive menu: /backtest (no args) ─────────────────────────────────
    menu_text = (
        "📊 <b>Backtest Dashboard</b>\n\n"
        "Chọn loại chart bạn muốn xem:\n\n"
        "📈 <b>Equity Curve (All)</b> — Đường vốn tổng hợp\n"
        "📊 <b>MTT vs MIS</b> — So sánh hiệu suất theo mode\n"
        "📋 <b>Trade History</b> — Bảng 10 lệnh gần nhất\n"
        "🔢 <b>All 3 Charts</b> — Tất cả (3 ảnh)\n\n"
        "₿ / Ξ / ◎ — Lọc theo symbol cụ thể"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=sanitize_for_telegram_html(menu_text),
        parse_mode="HTML",
        reply_markup=_backtest_menu_keyboard(),
    )


async def cmd_stats(update, context):
    """REQ-STATS: /stats — overall and per-mode (MTT vs MIS) performance breakdown.

    Usage: /stats
    Output: Win Rate, PnL, Profit Factor for all trades and split by strategy mode.
    """

    from notifier import sanitize_for_telegram_html

    await update.message.reply_text("📊 Đang tải thống kê hiệu suất...")

    try:
        import database

        result = await database.get_stats_by_mode()
    except Exception as e:
        log.error(f"cmd_stats error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Lỗi tải stats: {e}")
        return

    overall = result.get("overall", {})
    by_mode = result.get("by_mode", {})

    if overall.get("total_trades", 0) == 0:
        await update.message.reply_text(
            sanitize_for_telegram_html("📭 Chưa có dữ liệu giao dịch."),
            parse_mode="HTML",
        )
        return

    def _pf_str(pf):
        return "∞" if pf == float("inf") else f"{pf:.2f}"

    def _mode_block(label: str, emoji: str, stats: dict) -> str:
        if stats.get("total_trades", 0) == 0:
            return f"\n{emoji} <b>{label}</b>: <i>Chưa có dữ liệu</i>"
        wr_emoji = "🟢" if stats["win_rate"] >= 50 else "🔴"
        pnl_emoji = "🟢" if stats["total_pnl"] >= 0 else "🔴"
        return (
            f"\n{emoji} <b>{label}</b>\n"
            f"   Lệnh: {stats['total_trades']} "
            f"({stats['winning_trades']}W/{stats['losing_trades']}L)\n"
            f"   {wr_emoji} Win Rate: <b>{stats['win_rate']:.1f}%</b>\n"
            f"   {pnl_emoji} PnL: <b>${stats['total_pnl']:+,.2f}</b> | "
            f"PF: <b>{_pf_str(stats['profit_factor'])}</b>"
        )

    wr_emoji_ov = "🟢" if overall["win_rate"] >= 50 else "🔴"
    pnl_emoji_ov = "🟢" if overall["total_pnl"] >= 0 else "🔴"

    lines = [
        "📊 <b>Thống Kê Hiệu Suất</b>\n",
        "═══ <b>TỔNG QUAN</b> ═══",
        f"📈 Tổng lệnh: <b>{overall['total_trades']}</b> "
        f"({overall['winning_trades']}W/{overall['losing_trades']}L)",
        f"{wr_emoji_ov} Win Rate: <b>{overall['win_rate']:.1f}%</b>",
        f"{pnl_emoji_ov} Tổng P&L: <b>${overall['total_pnl']:+,.2f}</b>",
        f"⚖️ Profit Factor: <b>{_pf_str(overall['profit_factor'])}</b>",
        f"🏆 Tốt nhất: `${overall['best_trade']:+,.2f}` | "
        f"💔 Tệ nhất: `${overall['worst_trade']:+,.2f}`",
        "\n═══ <b>THEO CHẾ ĐỘ</b> ═══",
    ]

    lines.append(
        _mode_block("MTT — Daily Trend Follower", "📅", by_mode.get("MTT", {}))
    )
    lines.append(_mode_block("MIS — 1H Momentum", "⚡", by_mode.get("MIS", {})))

    other = by_mode.get("OTHER", {})
    if other.get("total_trades", 0) > 0:
        lines.append(_mode_block("OTHER — Không rõ mode", "❓", other))

    await update.message.reply_text(
        sanitize_for_telegram_html("\n".join(lines)),
        parse_mode="HTML",
    )


async def cmd_report(update, context):
    """REQ8: /report [YYYY-MM-DD] — daily performance summary."""

    from notifier import sanitize_for_telegram_html

    date_arg = context.args[0] if context.args else None
    stats = await _data_facade.get_daily_stats(date_arg)

    if stats.total_trades == 0:
        await update.message.reply_text(
            sanitize_for_telegram_html(
                f"📭 Không có giao dịch nào vào ngày **{stats.date}**."
            ),
            parse_mode="HTML",
        )
        return

    pnl_emoji = "🟢" if stats.total_pnl >= 0 else "🔴"
    text = (
        f"📊 **Báo Cáo Ngày {stats.date}**\n\n"
        f"📈 Tổng lệnh: **{stats.total_trades}**\n"
        f"✅ Thắng: **{stats.winning_trades}** | ❌ Thua: **{stats.losing_trades}**\n"
        f"🎯 Win Rate: **{stats.win_rate:.1f}%**\n"
        f"{pnl_emoji} Tổng P&L: **${stats.total_pnl:+,.2f}**\n"
        f"🏆 Lệnh tốt nhất: `${stats.best_trade:+,.2f}`\n"
        f"💔 Lệnh tệ nhất: `${stats.worst_trade:+,.2f}`"
    )
    await update.message.reply_text(sanitize_for_telegram_html(text), parse_mode="HTML")


async def cmd_balance_enhanced(update, context):
    """REQ9: /balance [EXCHANGE] [ASSET] — multi-exchange balance query."""
    exchange_id = None
    asset = "USDT"

    if context.args:
        # Heuristic: if arg looks like exchange name (no digits), use as exchange_id
        first = context.args[0].upper()
        known_exchanges = {"BINANCE", "BYBIT", "OKX"}
        if first in known_exchanges:
            exchange_id = first.lower()
            asset = context.args[1].upper() if len(context.args) > 1 else "USDT"
        else:
            asset = first

    try:
        info = await _exchange_facade.get_balance(exchange_id, asset)
        mode_parts = []
        if info.is_dry_run:
            mode_parts.append("DRY-RUN")
        mode_parts.append("TESTNET" if info.is_testnet else "MAINNET")

        text = (
            f"💰 **Binance Balance**\n\n"
            f"🏦 Sàn: `{info.exchange.upper()}`\n"
            f"💎 Asset: `{info.asset}`\n"
            f"✅ Free: `${info.free:,.2f}`\n"
            f"🔒 Locked: `${info.locked:,.2f}`\n"
            f"💵 Total: `${info.total:,.2f}`\n"
            f"⚙️ Mode: `{', '.join(mode_parts)}`"
        )
        from notifier import sanitize_for_telegram_html

        await update.message.reply_text(
            sanitize_for_telegram_html(text), parse_mode="HTML"
        )
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_scan_enhanced(update, context):
    """REQ4: Enhanced /scan — adds 👁 Analyze inline buttons for VCP setups."""
    chat_id = update.effective_chat.id
    cmd_key = (chat_id, "scan")
    if cmd_key in active_commands:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Yêu cầu scan trước đó của bạn vẫn đang được xử lý. Vui lòng đợi.",
        )
        return
    active_commands.add(cmd_key)
    await context.bot.send_message(chat_id=chat_id, text="🔄 Đang xử lý...")

    async def process_task():
        try:
            import config
            from analysis import scan_symbols
            from watchlist import get_watchlist

            symbols = get_watchlist()
            if not symbols:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="📋 Watchlist trống. Dùng /add để thêm symbols.",
                )
                return

            mcp = None
            if config.MCP_ENABLED:
                try:
                    from mcp_client import get_mcp_client

                    mcp = get_mcp_client()
                except Exception as e:
                    log.debug(f"MCP check failed: {e}")

            results = await scan_symbols(symbols, mcp)

            if not results:
                await context.bot.send_message(
                    chat_id=chat_id, text="⚠️ Không scan được symbol nào."
                )
                return

            lines = [f"📊 **Scan Results** ({len(results)} symbols)\n"]
            lines.append("```")
            lines.append(
                f"{'Symbol':<10} {'Price':>10} {'TT':>4} {'VCP':>5} {'Vol%':>6}"
            )
            lines.append("─" * 40)

            vcp_setups = []
            for r in results:
                tt_score = r.trend_template.score if r.trend_template else "?"
                vcp_flag = "⭐" if r.vcp and r.vcp.detected else ""
                vol_ratio = r.vcp.volume_ratio if r.vcp else 0
                vol_pct = f"{vol_ratio * 100:.0f}%" if vol_ratio else "N/A"
                price = r.price
                price_str = f"{price:,.2f}" if price >= 1 else f"{price:.4f}"
                lines.append(
                    f"{r.symbol:<10} {price_str:>10} {tt_score}/8  {vcp_flag:<3} {vol_pct:>5}"
                )
                if r.vcp and r.vcp.detected:
                    vcp_setups.append(r.symbol)

            lines.append("```")

            # Build inline keyboard for VCP symbols (REQ4)
            keyboard = []
            if vcp_setups:
                lines.append(
                    f"\n🎯 **VCP Setups:** {', '.join(f'`{s}`' for s in vcp_setups)}"
                )
                keyboard = [
                    [{"text": f"👁 Analyze {sym}", "callback_data": f"analyze_{sym}"}]
                    for sym in vcp_setups
                ]

            from notifier import sanitize_for_telegram_html

            text = sanitize_for_telegram_html("\n".join(lines))

            if keyboard:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                kb = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                row[0]["text"], callback_data=row[0]["callback_data"]
                            )
                        ]
                        for row in keyboard
                    ]
                )
                await context.bot.send_message(
                    chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=kb
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id, text=text, parse_mode="HTML"
                )

        except Exception as e:
            log.error(f"cmd_scan_enhanced error: {e}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Scan failed: {e}")
        finally:
            active_commands.discard(cmd_key)

    task = asyncio.create_task(process_task())
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)


async def cmd_scan_all(update, context):
    """Trigger background scan across all configured exchanges and reply when done."""
    chat_id = update.effective_chat.id
    cmd_key = (chat_id, "scan_all")
    if cmd_key in active_commands:
        await update.message.reply_text(
            "⚠️ Yêu cầu scan_all trước đó của bạn vẫn đang được xử lý. Vui lòng đợi."
        )
        return
    active_commands.add(cmd_key)
    await update.message.reply_text(
        "🔄 Đang bắt đầu scan toàn bộ các sàn trong background... Vui lòng chờ kết quả."
    )

    async def run_scan_and_notify():
        try:
            from analysis import scan_all_configured_exchanges

            results = await scan_all_configured_exchanges()

            if not results:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Quá trình scan hoàn tất nhưng không tìm thấy kết quả nào.",
                )
                return

            filtered_results = [
                r
                for r in results
                if (r.trend_template and r.trend_template.score >= 6)
                or (r.vcp and r.vcp.detected)
            ]

            if not filtered_results:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Scan hoàn tất ({len(results)} symbols).\nKhông có symbol nào đạt Trend Template >= 6/8 hoặc phát hiện VCP.",
                )
                return

            lines = [
                f"📊 **Kết quả Scan All (TT ≥ 6 hoặc VCP)** ({len(filtered_results)}/{len(results)} symbols)\n"
            ]
            lines.append("```")
            lines.append(
                f"{'Exchange':<8} {'Symbol':<12} {'Price':>10} {'TT':>4} {'VCP':>5}"
            )
            lines.append("─" * 45)

            for r in filtered_results:
                tt_score = r.trend_template.score if r.trend_template else "?"
                vcp_flag = "⭐" if r.vcp and r.vcp.detected else ""
                price = r.price
                price_str = f"{price:,.2f}" if price >= 1 else f"{price:.4f}"
                exchange_label = r.exchange[:8]
                lines.append(
                    f"{exchange_label:<8} {r.symbol:<12} {price_str:>10} {tt_score}/8  {vcp_flag:<3}"
                )

            lines.append("```")

            vcp_setups = [r for r in filtered_results if r.vcp and r.vcp.detected]
            if vcp_setups:
                lines.append("\n🎯 **Chi tiết VCP Setups:**")
                for r in vcp_setups:
                    pivot = r.vcp.pivot_level if r.vcp.pivot_level else 0
                    vol_ratio = r.vcp.volume_ratio if r.vcp.volume_ratio else 0
                    lines.append(
                        f"• `{r.symbol}` ({r.exchange.upper()}) — Vol: {vol_ratio * 100:.0f}% avg, "
                        f"Pivot: {pivot:,.2f}"
                    )

            from notifier import sanitize_for_telegram_html

            text = sanitize_for_telegram_html("\n".join(lines))

            keyboard = []
            if vcp_setups:
                keyboard = [
                    [
                        {
                            "text": f"👁 Analyze {r.symbol} ({r.exchange})",
                            "callback_data": f"analyze_{r.symbol}",
                        }
                    ]
                    for r in vcp_setups
                ]

            if keyboard:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                kb = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                row[0]["text"], callback_data=row[0]["callback_data"]
                            )
                        ]
                        for row in keyboard
                    ]
                )
                await context.bot.send_message(
                    chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=kb
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id, text=text, parse_mode="HTML"
                )

        except Exception as err:
            log.error(f"Background scan notify error: {err}", exc_info=True)
            await context.bot.send_message(
                chat_id=chat_id, text=f"❌ Quá trình scan background bị lỗi: {err}"
            )
        finally:
            active_commands.discard(cmd_key)

    task = asyncio.create_task(run_scan_and_notify())
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)


def parse_mtf_trade_params(
    text: str, current_price: float
) -> tuple[float | None, float | None, float | None, str]:
    import re

    entry, sl, tp = None, None, None
    side = "AVOID"
    text_lower = text.lower()

    # Search for specific lines containing verdict/signal indicators
    for line in text.splitlines():
        line_lower = line.lower()
        if any(
            kw in line_lower
            for kw in ["tín hiệu", "hành động", "decision", "verdict", "khuyến nghị"]
        ):
            if "short" in line_lower or "bán" in line_lower or "sell" in line_lower:
                side = "SELL"
                break
            elif "long" in line_lower or "mua" in line_lower or "buy" in line_lower:
                side = "BUY"
                break
    else:
        # Fallback to general substring checking
        if "short" in text_lower or "bán" in text_lower:
            side = "SELL"
        elif "long" in text_lower or "mua" in text_lower:
            side = "BUY"

    num_pattern = r"[\d,]+(?:\.\d+)?"

    entry_match = re.search(
        r"(?:entry|giá vào|vào)[^:\d]*[:\s]*\$?\s*(" + num_pattern + ")", text_lower
    )
    if entry_match:
        try:
            entry = float(entry_match.group(1).replace(",", ""))
        except ValueError:
            # ignore parsing error
            pass

    sl_match = re.search(
        r"(?:stop loss|cắt lỗ|sl)[^:\d]*[:\s]*\$?\s*(" + num_pattern + ")", text_lower
    )
    if sl_match:
        try:
            sl = float(sl_match.group(1).replace(",", ""))
        except ValueError:
            # ignore parsing error
            pass

    tp_match = re.search(
        r"(?:take profit|chốt lời|tp)[^:\d]*[:\s]*\$?\s*(" + num_pattern + ")",
        text_lower,
    )
    if tp_match:
        try:
            tp = float(tp_match.group(1).replace(",", ""))
        except ValueError:
            # ignore parsing error
            pass

    if not entry or entry <= 0:
        entry = current_price

    return entry, sl, tp, side


async def cmd_scan_mtf(update, context):
    """
    Scan symbol on multi-timeframe (1D, 4H, 1H), analyze with AI Vision and provide
    interactive buttons to execute.
    Usage: /scan_mtf <symbol> [exchange]
    """
    message = (
        update.message
        if update.message
        else (update.callback_query.message if update.callback_query else None)
    )
    if not message:
        return

    args = context.args
    if not args and update.callback_query:
        data = update.callback_query.data
        if data.startswith("scanmtf_"):
            symbol = data.split("_", 1)[1].upper()
            args = [symbol]

    if not args:
        # Show watchlist/recommended symbols menu
        try:
            from watchlist import get_watchlist

            watchlist = get_watchlist()
        except Exception:
            watchlist = []

        if not watchlist:
            import config

            wl_str = getattr(config, "WATCHLIST_SYMBOLS", "")
            if wl_str:
                watchlist = [s.strip().upper() for s in wl_str.split(",") if s.strip()]

        if not watchlist:
            watchlist = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = []
        for i in range(0, len(watchlist), 2):
            row = []
            row.append(
                InlineKeyboardButton(
                    text=f"🔍 {watchlist[i]}", callback_data=f"scanmtf_{watchlist[i]}"
                )
            )
            if i + 1 < len(watchlist):
                row.append(
                    InlineKeyboardButton(
                        text=f"🔍 {watchlist[i + 1]}",
                        callback_data=f"scanmtf_{watchlist[i + 1]}",
                    )
                )
            keyboard.append(row)

        reply_markup = InlineKeyboardMarkup(keyboard)
        await message.reply_text(
            "🔍 *Multi-Timeframe Scan Studio*\n\n"
            "Vui lòng chọn một mã giao dịch từ danh sách dưới đây để bắt đầu phân tích đa khung thời gian (1D → 4H → 1H) bằng AI Vision:",
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
        return

    symbol = args[0].strip().upper()

    import config

    exchange_name = (
        args[1].strip().lower() if len(args) > 1 else config.DEFAULT_EXCHANGE.lower()
    )

    chat_id = update.effective_chat.id
    cmd_key = (chat_id, "scan_mtf")
    if cmd_key in active_commands:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Yêu cầu scan_mtf trước đó của bạn vẫn đang được xử lý. Vui lòng đợi.",
        )
        return
    active_commands.add(cmd_key)
    await context.bot.send_message(chat_id=chat_id, text="🔄 Đang xử lý...")

    async def process_task():
        progress_msg = await message.reply_text(
            f"🔍 Đang tiến hành phân tích đa khung thời gian (1D → 4H → 1H) cho <code>{symbol}</code> trên sàn <code>{exchange_name}</code>...\n"
            f"1. Fetching klines & scoring Trend Template/VCP...",
            parse_mode="HTML",
        )

        try:
            import aiohttp

            from analysis import scan_symbol_multi_timeframe
            from mcp_client import get_mcp_client

            # 2. Algorithmic MTF scan
            semaphore = asyncio.Semaphore(1)
            async with aiohttp.ClientSession() as session:
                mtf_scan_result = await scan_symbol_multi_timeframe(
                    session, exchange_name, symbol, semaphore
                )

            await progress_msg.edit_text(
                f"🔍 Phân tích đa khung thời gian cho <code>{symbol}</code> ({exchange_name}):\n"
                f"✅ 1. Hoàn tất scan thuật toán.\n"
                f"2. Đang chụp ảnh biểu đồ 3 khung thời gian...",
                parse_mode="HTML",
            )

            # 3. Capture screenshots
            import re
            from datetime import datetime
            from pathlib import Path

            screenshots_dir = (
                Path(config.CHROMA_DB_PATH).parent.resolve() / "screenshots"
            )
            screenshots_dir.mkdir(parents=True, exist_ok=True)

            safe_symbol = re.sub(r"[^A-Za-z0-9_\-]", "", symbol)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            path_1d = screenshots_dir / f"mtf_1d_{safe_symbol}_{timestamp}.png"
            path_4h = screenshots_dir / f"mtf_4h_{safe_symbol}_{timestamp}.png"
            path_1h = screenshots_dir / f"mtf_1h_{safe_symbol}_{timestamp}.png"

            mcp = get_mcp_client()

            # Capture screenshots sequentially to avoid TradingView browser collisions
            captured_1d = await mcp.capture_screenshot(
                symbol=symbol, timeframe="D", save_path=path_1d
            )
            await asyncio.sleep(0.5)
            captured_4h = await mcp.capture_screenshot(
                symbol=symbol, timeframe="240", save_path=path_4h
            )
            await asyncio.sleep(0.5)
            captured_1h = await mcp.capture_screenshot(
                symbol=symbol, timeframe="60", save_path=path_1h
            )

            image_paths = []
            for p in [captured_1d, captured_4h, captured_1h]:
                if p and Path(p).exists():
                    image_paths.append(Path(p))

            if not image_paths:
                await progress_msg.edit_text(
                    "❌ Lỗi: Không thể chụp ảnh biểu đồ (TradingView MCP & local fallback failed)."
                )
                return

            await progress_msg.edit_text(
                f"🔍 Phân tích đa khung thời gian cho <code>{symbol}</code> ({exchange_name}):\n"
                f"✅ 1. Hoàn tất scan thuật toán.\n"
                f"✅ 2. Đã chụp xong {len(image_paths)} biểu đồ.\n"
                f"3. Đang gửi ảnh cho AI Vision phân tích...",
                parse_mode="HTML",
            )

            # 4. Vision AI analysis
            from vision import analyze_chart_vision_mtf

            vision_result = await analyze_chart_vision_mtf(
                image_paths=image_paths,
                symbol=symbol,
                mtf_scan_result={"timeframes": mtf_scan_result.timeframes},
            )

            if vision_result.get("error"):
                await progress_msg.edit_text(
                    f"❌ AI Vision analysis error: {vision_result['error']}"
                )
                return

            # Parse Entry, SL, TP, and Side
            entry, sl, tp, side = parse_mtf_trade_params(
                vision_result["analysis"], mtf_scan_result.price
            )

            # 5. Insert manual signal into database
            import database

            signal_id = await database.insert_signal(
                symbol=symbol,
                action=side.lower(),
                price=entry,
                quote_qty=10.0,
                source_ip="127.0.0.1",
                payload={
                    "source": "telegram_mtf_scan",
                    "confidence": vision_result.get("confidence", 0),
                    "combined_score": vision_result.get("combined_score", "N/A"),
                    "verdict": vision_result.get("verdict", ""),
                    "sl": str(sl) if sl else "",
                    "tp": str(tp) if tp else "",
                    "analysis_text": vision_result.get("analysis", ""),
                },
            )

            # 6. Create AnalysisComplete event and store in PENDING_TRADES
            from core.events import AnalysisComplete
            from hub.notification_hub import PENDING_TRADES

            confidence = vision_result.get("confidence", 5)
            combined_score = vision_result.get("combined_score", "N/A")

            event = AnalysisComplete(
                signal_id=signal_id,
                symbol=symbol,
                action=side.lower(),
                price=entry,
                quote_qty=10.0,
                sl=str(sl) if sl else "",
                tp=str(tp) if tp else "",
                exchange=exchange_name,
                confidence=confidence,
                analysis_text=vision_result["analysis"],
                screenshot_path=str(image_paths[0]),
                combined_score=combined_score,
                should_trade=(side != "AVOID"),
                interactive_required=True,
            )

            PENDING_TRADES[signal_id] = event

            # Track for timeout
            from telegram_bot import get_approval_timeout_mgr

            timeout_mgr = get_approval_timeout_mgr()

            # 7. Send the screenshots as a media group
            from telegram import InputMediaPhoto

            media_group = []
            file_handles = []
            try:
                for i, p in enumerate(image_paths):
                    fh = open(p, "rb")
                    file_handles.append(fh)
                    caption = (
                        f"📊 {symbol} Multi-Timeframe Charts (1D, 4H, 1H)"
                        if i == 0
                        else None
                    )
                    media_group.append(InputMediaPhoto(media=fh, caption=caption))

                await message.reply_media_group(media=media_group)
            finally:
                for fh in file_handles:
                    fh.close()

            # 8. Send the text report with inline buttons
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            keyboard = []
            if side != "AVOID":
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"📈 APPROVE {side}", callback_data=f"approve_{signal_id}"
                        ),
                        InlineKeyboardButton(
                            "❌ REJECT", callback_data=f"reject_{signal_id}"
                        ),
                    ]
                )
            else:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "❌ DISMISS", callback_data=f"reject_{signal_id}"
                        )
                    ]
                )

            reply_markup = InlineKeyboardMarkup(keyboard)

            import re

            from notifier import sanitize_for_telegram_html

            clean_analysis = vision_result["analysis"].strip()
            # Remove any leading header line starting with "👁️ MULTI-TIMEFRAME ANALYSIS" (case-insensitive) recursively
            while True:
                prev_len = len(clean_analysis)
                clean_analysis = re.sub(
                    rf"^👁️?\s*(?:MULTI-TIMEFRAME\s+ANALYSIS|PHÂN\s+TÍCH\s+ĐA\s+KHUNG\s+THỜI\s+GIAN)\s*(?:[-—–:]\s*{re.escape(symbol)})?\s*\n*",
                    "",
                    clean_analysis,
                    flags=re.IGNORECASE,
                ).strip()
                if len(clean_analysis) == prev_len:
                    break

            formatted_analysis = sanitize_for_telegram_html(clean_analysis)

            entry_str = f"{entry:,.4f}" if entry is not None else "N/A"
            sl_str = f"{sl:,.4f}" if sl is not None else "N/A"
            tp_str = f"{tp:,.4f}" if tp is not None else "N/A"

            report_text = (
                f"👁️ <b>MULTI-TIMEFRAME ANALYSIS — {symbol}</b>\n\n"
                f"{formatted_analysis}\n\n"
                f"📊 Combined Score: <b>{combined_score}</b>\n"
                f"📋 Verdict: <b>{vision_result.get('verdict', 'N/A')}</b>\n"
                f"💰 Entry: <code>{entry_str}</code> | SL: <code>{sl_str}</code> | TP: <code>{tp_str}</code>\n"
                f"🏦 Sàn: <code>{exchange_name.upper()}</code>"
            )

            sent_msg = await message.reply_text(
                report_text, parse_mode="HTML", reply_markup=reply_markup
            )

            if timeout_mgr:
                timeout_mgr.track_message(
                    signal_id, update.effective_chat.id, sent_msg.message_id
                )

            await progress_msg.delete()

        except Exception as e:
            log.error(f"cmd_scan_mtf failed: {e}", exc_info=True)
            await progress_msg.edit_text(f"❌ Phân tích thất bại: {e}")
        finally:
            active_commands.discard(cmd_key)

    task = asyncio.create_task(process_task())
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)


async def cmd_recommend(update, context):
    """Gợi ý cơ hội giao dịch đa khung thời gian từ Watchlist."""
    chat_id = update.effective_chat.id
    cmd_key = (chat_id, "recommend")
    if cmd_key in active_commands:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ Yêu cầu recommend trước đó của bạn vẫn đang được xử lý. Vui lòng đợi.",
        )
        return
    active_commands.add(cmd_key)
    await context.bot.send_message(chat_id=chat_id, text="🔄 Đang xử lý...")

    async def process_task():
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🔄 Đang quét danh sách Watchlist để tìm điểm đồng thuận đa khung thời gian (1D → 4H → 1H)...",
            )
            import aiohttp

            import config
            from analysis import scan_symbol_multi_timeframe
            from watchlist import get_watchlist

            symbols = get_watchlist()
            if not symbols:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="📋 Watchlist trống. Dùng /add để thêm symbols.",
                )
                return

            exchange_name = (
                context.args[0].strip().lower()
                if context.args
                else config.DEFAULT_EXCHANGE.lower()
            )

            semaphore = asyncio.Semaphore(3)

            async with aiohttp.ClientSession() as session:
                tasks = [
                    scan_symbol_multi_timeframe(session, exchange_name, sym, semaphore)
                    for sym in symbols
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

            lines = ["📊 **Gợi ý Đa Khung Thời Gian (Watchlist)**\n"]
            lines.append("```")
            lines.append(
                f"{'Symbol':<12} {'Price':>10} {'1D/4H/1H':>10} {'Verdict':<15}"
            )
            lines.append("─" * 50)

            aligned_count = 0
            for r in results:
                if isinstance(r, Exception) or not r or getattr(r, "error", None):
                    continue

                # Format scores
                score_1d = (
                    r.timeframes.get("1d").trend_template.score
                    if r.timeframes.get("1d") and not r.timeframes.get("1d").error
                    else "?"
                )
                score_4h = (
                    r.timeframes.get("4h").trend_template.score
                    if r.timeframes.get("4h") and not r.timeframes.get("4h").error
                    else "?"
                )
                score_1h = (
                    r.timeframes.get("1h").trend_template.score
                    if r.timeframes.get("1h") and not r.timeframes.get("1h").error
                    else "?"
                )
                scores_str = f"{score_1d}/{score_4h}/{score_1h}"

                price = r.price
                price_str = f"{price:,.2f}" if price >= 1 else f"{price:.4f}"

                # Check if aligned
                alignment = "NEUTRAL"
                if r.aligned_long:
                    alignment = "LONG 📈"
                    aligned_count += 1
                elif r.aligned_short:
                    alignment = "SHORT 📉"
                    aligned_count += 1

                lines.append(
                    f"{r.symbol:<12} {price_str:>10} {scores_str:>10} {alignment:<15}"
                )

            lines.append("```")

            if aligned_count == 0:
                lines.append(
                    "\n⚠️ Không tìm thấy đồng thuận xu hướng cho symbol nào trong Watchlist hiện tại."
                )
            else:
                lines.append(
                    f"\n🎯 Phát hiện {aligned_count} cơ hội giao dịch có đồng thuận xu hướng đa khung thời gian!"
                )

            from notifier import sanitize_for_telegram_html

            await context.bot.send_message(
                chat_id=chat_id,
                text=sanitize_for_telegram_html("\n".join(lines)),
                parse_mode="HTML",
            )

        except Exception as e:
            log.error(f"cmd_recommend failed: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=chat_id, text=f"❌ Lỗi khi quét Watchlist: {e}"
            )
        finally:
            active_commands.discard(cmd_key)

    task = asyncio.create_task(process_task())
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)


# ── Inline Keyboard Callback ──────────────────────────────────────────────


async def button_callback(update, context):
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("approve_"):
        signal_id = int(data.split("_")[1])
        from hub.notification_hub import PENDING_TRADES

        if signal_id in PENDING_TRADES:
            event = PENDING_TRADES.pop(signal_id)
            from core.event_bus import bus as _default_bus
            from core.events import TradeApproved

            user = query.from_user.username or query.from_user.first_name

            # Emit TradeApproved event in background
            asyncio.create_task(
                _default_bus.emit_background(
                    TradeApproved(
                        signal_id=event.signal_id,
                        symbol=event.symbol,
                        action=event.action,
                        price=event.price,
                        quote_qty=event.quote_qty,
                        sl=event.sl,
                        tp=event.tp,
                        approved_by=f"Human (@{user})",
                        analysis_text=event.analysis_text,
                        exchange=getattr(event, "exchange", "binance"),
                    )
                )
            )
            from notifier import sanitize_for_telegram_html

            safe_text = sanitize_for_telegram_html(query.message.text)
            new_text = safe_text + f"\n\n✅ <b>ĐÃ DUYỆT BỞI @{user}</b>"
            await query.message.edit_text(new_text, parse_mode="HTML")
        else:
            from notifier import sanitize_for_telegram_html

            safe_text = sanitize_for_telegram_html(query.message.text)
            new_text = safe_text + "\n\n<i>(Lệnh đã hết hạn hoặc đã được xử lý)</i>"
            await query.message.edit_text(new_text, parse_mode="HTML")

    elif data.startswith("reject_"):
        signal_id = int(data.split("_")[1])
        from hub.notification_hub import PENDING_TRADES

        if signal_id in PENDING_TRADES:
            event = PENDING_TRADES.pop(signal_id)
            user = query.from_user.username or query.from_user.first_name

            from core.event_bus import bus as _default_bus
            from core.events import TradeFailed

            asyncio.create_task(
                _default_bus.emit_background(
                    TradeFailed(
                        signal_id=event.signal_id,
                        symbol=event.symbol,
                        side=event.action,
                        error=f"Rejected by user (@{user})",
                        quote_qty=event.quote_qty,
                        exchange=getattr(event, "exchange", "binance"),
                    )
                )
            )
            from notifier import sanitize_for_telegram_html

            safe_text = sanitize_for_telegram_html(query.message.text)
            new_text = safe_text + f"\n\n❌ <b>ĐÃ TỪ CHỐI BỞI @{user}</b>"
            await query.message.edit_text(new_text, parse_mode="HTML")
        else:
            from notifier import sanitize_for_telegram_html

            safe_text = sanitize_for_telegram_html(query.message.text)
            new_text = safe_text + "\n\n<i>(Lệnh đã hết hạn hoặc đã được xử lý)</i>"
            await query.message.edit_text(new_text, parse_mode="HTML")

    elif data.startswith("ignore_"):
        _signal_id = int(data.split("_")[1])
        user = query.from_user.username or query.from_user.first_name
        from notifier import sanitize_for_telegram_html

        safe_text = sanitize_for_telegram_html(query.message.text)
        new_text = safe_text + f"\n\n❌ <b>ĐÃ BỎ QUA BỞI @{user}</b>"
        await query.message.edit_text(new_text, parse_mode="HTML")

    elif data.startswith("cbreset_"):
        exchange = data.split("_")[1].lower()
        user = query.from_user.username or query.from_user.first_name
        import database

        try:
            prev_status = await database.get_risk_settings(exchange)
            prev_state = prev_status.get("state", "CLOSED")
            await database.update_circuit_breaker_state(exchange, "CLOSED")
            await database.log_circuit_breaker(
                exchange,
                "*",
                prev_state,
                "CLOSED",
                f"Reset Closed via Telegram by @{user}",
                {"action": "reset"},
            )
            # Clear bypass
            await database.set_setting(f"bypass_until_{exchange}", "")

            from notifier import sanitize_for_telegram_html

            safe_text = sanitize_for_telegram_html(query.message.text)
            new_text = safe_text + f"\n\n✅ <b>RESET CLOSED BỞI @{user}</b>"
            await query.message.edit_text(new_text, parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Lỗi reset: {e}")

    elif data.startswith("cbbypass_"):
        exchange = data.split("_")[1].lower()
        user = query.from_user.username or query.from_user.first_name
        from datetime import datetime, timedelta

        import database

        try:
            prev_status = await database.get_risk_settings(exchange)
            prev_state = prev_status.get("state", "CLOSED")

            # Set bypass for 1 hour
            bypass_until = datetime.now(UTC) + timedelta(hours=1)
            await database.set_setting(
                f"bypass_until_{exchange}", bypass_until.isoformat()
            )

            await database.update_circuit_breaker_state(exchange, "CLOSED")
            await database.log_circuit_breaker(
                exchange,
                "*",
                prev_state,
                "CLOSED",
                f"Bypassed 1h via Telegram by @{user}",
                {"action": "bypass"},
            )

            from notifier import sanitize_for_telegram_html

            safe_text = sanitize_for_telegram_html(query.message.text)
            new_text = safe_text + f"\n\n⚡ <b>ĐÃ BYPASS 1H BỞI @{user}</b>"
            await query.message.edit_text(new_text, parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Lỗi bypass: {e}")

    elif data == "status":
        # Re-use status logic
        await query.message.reply_text("🔄 Loading status...")
        # Simulate Update object for cmd_status
        await cmd_status_inline(query.message)
    elif data == "watchlist":
        await cmd_watchlist_inline(query.message)
    elif data == "scan":
        await query.message.reply_text("🔄 Đang scan watchlist... Vui lòng chờ.")
        await cmd_scan_inline(query.message)
    elif data == "brief":
        await query.message.reply_text(
            "🌅 Đang chạy Morning Brief... Vui lòng chờ 30-60s."
        )
        await cmd_brief_inline(query.message)

    elif data.startswith("bt_"):
        # ── /backtest inline menu callbacks ───────────────────────────────────
        chat_id = query.message.chat_id

        # Map button data → (chart_mode, symbol)
        bt_map = {
            "bt_all": ("equity", None),
            "bt_mode": ("mode", None),
            "bt_history": ("history", None),
            "bt_full": ("full", None),
        }

        if data in bt_map:
            chart_mode, symbol = bt_map[data]
        elif data.startswith("bt_sym_"):
            symbol = data[len("bt_sym_") :]
            chart_mode = "full"
        else:
            chart_mode, symbol = "full", None

        sym_lbl = f" [{symbol}]" if symbol else ""
        mode_lbl = {
            "equity": "📈 Equity Curve",
            "mode": "📊 MTT vs MIS",
            "history": "📋 Trade History",
            "full": "🔢 All 3 Charts",
        }.get(chart_mode, "📊 Chart")

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{mode_lbl}{sym_lbl} — đang tạo chart... vui lòng chờ 5-10s.",
        )

        async def _send_photo_cb(buf, caption):
            await context.bot.send_photo(
                chat_id=chat_id, photo=buf, caption=caption, parse_mode="HTML"
            )

        async def _send_msg_cb(text):
            await context.bot.send_message(chat_id=chat_id, text=text)

        try:
            await _run_backtest_charts(
                _send_photo_cb, _send_msg_cb, mode=chart_mode, symbol=symbol
            )
        except Exception as e:
            log.error(f"bt_ callback error: {e}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Lỗi: {e}")

    elif data.startswith("scanmtf_"):
        await cmd_scan_mtf(update, context)

    elif data.startswith("analyze_"):
        # REQ4: Inline Vision Pipeline Shortcut from /scan results
        symbol = data.split("_", 1)[1].upper()
        import re

        safe_symbol = re.sub(r"[^A-Za-z0-9_\-]", "", symbol)
        await query.message.reply_text(
            f"👁 Đang phân tích <code>{safe_symbol}</code>...",
            parse_mode="HTML",
        )
        try:
            from pathlib import Path

            import config

            screenshots_dir = Path(__file__).parent / "screenshots"
            screenshot_path = None

            if config.MCP_ENABLED:
                try:
                    from datetime import datetime as dt

                    from mcp_client import get_mcp_client

                    mcp = get_mcp_client()
                    health = await mcp.health_check()
                    if health.get("connected"):
                        screenshot_path = await mcp.capture_screenshot(
                            symbol=symbol,
                            timeframe="D",
                            region="chart",
                            save_path=screenshots_dir
                            / f"vision_{safe_symbol}_{dt.now().strftime('%Y%m%d_%H%M%S')}.png",
                        )
                except Exception as e:
                    log.warning(f"analyze_ callback screenshot failed: {e}")

            if not screenshot_path or not Path(screenshot_path).exists():
                if screenshots_dir.exists():
                    candidates = sorted(
                        screenshots_dir.glob(f"*{safe_symbol}*.png"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    if candidates:
                        screenshot_path = candidates[0]

            if not screenshot_path or not Path(screenshot_path).exists():
                await query.message.reply_text(
                    f"⚠️ Không có screenshot cho <code>{safe_symbol}</code>. MCP cần connected.",
                    parse_mode="HTML",
                )
                return

            from vision import analyze_chart_vision, format_vision_telegram

            result = await analyze_chart_vision(
                image_path=Path(screenshot_path), symbol=symbol
            )
            if result.get("error"):
                await query.message.reply_text(f"❌ Vision error: {result['error']}")
                return

            from notifier import sanitize_for_telegram_html

            vision_text = format_vision_telegram(result)
            await query.message.reply_text(
                sanitize_for_telegram_html(vision_text), parse_mode="HTML"
            )

        except Exception as e:
            log.error(f"analyze_ callback error: {e}", exc_info=True)
            await query.message.reply_text(f"❌ Vision failed: {e}")


async def cmd_status_inline(message):
    """Status handler for inline buttons (receives Message instead of Update)."""
    import config

    lines = [
        "🔧 **System Status**\n",
        f"⏰ Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        f"🌐 Server: FastAPI v7.0 on :{config.PORT}",
    ]
    has_anthropic = bool(
        config.ANTHROPIC_API_KEY
        and not config.ANTHROPIC_API_KEY.startswith("sk-ant-xxx")
    )
    has_gemini = bool(config.GEMINI_API_KEY or config.GCP_PROJECT_ID)
    rag_status = "✅" if config.RAG_ENABLED and (has_anthropic or has_gemini) else "❌"
    mcp_status = "✅" if config.MCP_ENABLED else "❌"
    brief_status = "✅" if config.BRIEF_ENABLED else "❌"
    lines.append(
        f"🧠 RAG: {rag_status}  |  🖥️ MCP: {mcp_status}  |  ⏰ Brief: {brief_status}"
    )

    try:
        from watchlist import get_watchlist

        wl = get_watchlist()
        lines.append(f"📋 Watchlist: {len(wl)} symbols")
    except Exception as e:
        log.debug(f"Watchlist check failed: {e}")

    from notifier import sanitize_for_telegram_html

    await message.reply_text(
        sanitize_for_telegram_html("\n".join(lines)), parse_mode="HTML"
    )


async def cmd_watchlist_inline(message):
    """Watchlist handler for inline buttons."""
    try:
        from watchlist import get_watchlist

        symbols = get_watchlist()
        if symbols:
            symbol_list = ", ".join(f"<code>{s}</code>" for s in symbols)
            await message.reply_text(
                f"📋 <b>Watchlist</b> ({len(symbols)}): {symbol_list}",
                parse_mode="HTML",
            )
        else:
            await message.reply_text("📋 Watchlist trống.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


async def cmd_scan_inline(message):
    """Scan handler for inline buttons."""
    try:
        import config
        from analysis import scan_symbols
        from watchlist import get_watchlist

        symbols = get_watchlist()
        if not symbols:
            await message.reply_text("📋 Watchlist trống.")
            return

        mcp = None
        if config.MCP_ENABLED:
            try:
                from mcp_client import get_mcp_client

                mcp = get_mcp_client()
            except Exception as e:
                log.debug(f"MCP check failed: {e}")

        results = await scan_symbols(symbols, mcp)
        if results:
            summary = []
            for r in results:
                tt = r.trend_template.score if r.trend_template else "?"
                vcp = "⭐" if r.vcp and r.vcp.detected else ""
                summary.append(f"`{r.symbol}` TT:{tt}/8 {vcp}")
            from notifier import sanitize_for_telegram_html

            await message.reply_text(
                sanitize_for_telegram_html(
                    f"📊 **Scan** ({len(results)} symbols):\n" + "\n".join(summary)
                ),
                parse_mode="HTML",
            )
        else:
            await message.reply_text("⚠️ Không scan được.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


async def cmd_brief_inline(message):
    """Brief handler for inline buttons."""
    try:
        from brief import generate_morning_brief

        result = await generate_morning_brief()
        if result and result.get("success"):
            await message.reply_text("✅ Morning Brief đã gửi!")
        else:
            await message.reply_text("⚠️ Brief gặp lỗi.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


# ── P8 Data Models ────────────────────────────────────────────────────────


@dataclass
class PositionSnapshot:
    """Tracked position state for change detection inside PositionMonitor."""

    symbol: str
    side: str
    entry_price: float
    quantity: float
    stop_loss_price: float | None
    take_profit_price: float | None
    exchange: str
    last_seen: "datetime"


@dataclass
class PositionInfo:
    """Position data returned to command handlers."""

    symbol: str
    side: str
    entry_price: float
    current_price: float
    quantity: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    exchange: str


@dataclass
class BalanceInfo:
    """Balance data returned to command handlers."""

    asset: str
    free: float
    locked: float
    total: float
    exchange: str
    is_testnet: bool
    is_dry_run: bool


@dataclass
class TradeRecord:
    """Trade history record for display."""

    trade_id: int
    symbol: str
    side: str
    entry_price: float
    exit_price: float | None
    pnl: float | None
    status: str
    exchange: str
    created_at: str


@dataclass
class DailyStats:
    """Aggregated daily performance metrics."""

    date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    best_trade: float
    worst_trade: float


@dataclass
class ExchangeHealthInfo:
    """Exchange connectivity status."""

    exchange: str
    healthy: bool
    is_testnet: bool
    is_dry_run: bool
    latency_ms: float | None


# ── P8 TelegramSender (singleton) ─────────────────────────────────────────


class TelegramSender:
    """Single point of Telegram API interaction.

    Design Invariant: ALL components send messages through this class to ensure
    consistent HTML formatting, error handling, and chat_id broadcasting.
    Access via module-level _sender singleton (initialised in start_bot()).
    """

    def __init__(self, bot_app):
        self._app = bot_app

    async def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        reply_markup=None,
    ) -> list[tuple[int, int]]:
        """Send message to all TELEGRAM_CHAT_IDS.
        Returns list of (chat_id, message_id) tuples for later editing.
        """
        import config
        from notifier import sanitize_for_telegram_html

        results: list[tuple[int, int]] = []
        safe_text = sanitize_for_telegram_html(text)
        for chat_id in config.TELEGRAM_CHAT_IDS:
            try:
                msg = await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=safe_text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
                results.append((int(chat_id), msg.message_id))
            except Exception as e:
                log.error(f"TelegramSender: failed to send to {chat_id}: {e}")
        return results

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup=None,
    ) -> bool:
        """Edit an existing message. Returns True on success."""
        from notifier import sanitize_for_telegram_html

        try:
            await self._app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=sanitize_for_telegram_html(text),
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            return True
        except Exception as e:
            log.warning(
                f"TelegramSender: edit_message failed ({chat_id}/{message_id}): {e}"
            )
            return False

    async def send_typing_action(self, chat_id: int) -> None:
        """Send 'typing...' action indicator."""
        try:
            from telegram import ChatAction

            await self._app.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.TYPING
            )
        except Exception as e:
            log.debug(f"Typing action failed: {e}")


_sender: TelegramSender | None = None


def get_sender() -> TelegramSender | None:
    """Get the global TelegramSender singleton (None if bot not started)."""
    return _sender


# ── P8 ExchangeQueryFacade ─────────────────────────────────────────────────


class ExchangeQueryFacade:
    """Facade over ExchangeRegistry for read-only position/balance/health queries.

    Design Invariant: No component bypasses ExchangeRegistry to access adapters.
    """

    async def get_balance(
        self,
        exchange_id: str | None = None,
        asset: str = "USDT",
    ) -> BalanceInfo:
        """Get balance from specified or default exchange."""
        import config

        exch_id = (exchange_id or config.DEFAULT_EXCHANGE).lower()
        try:
            from exchange_registry import ExchangeRegistry

            registry = ExchangeRegistry.get_instance()
            client = registry.get(exch_id)
            if client is None:
                available = registry.list_exchange_ids()
                raise ValueError(
                    f"Exchange '{exch_id}' not registered. Available: {available}"
                )
            balance = await client.get_account_balance(asset)
            return BalanceInfo(
                asset=asset,
                free=float(balance),
                locked=0.0,
                total=float(balance),
                exchange=exch_id,
                is_testnet=getattr(client, "testnet", False),
                is_dry_run=getattr(client, "dry_run", True),
            )
        except Exception:
            # Fallback: try direct binance_client for backwards compat
            import binance_client as bm

            client = bm.get_client()
            balance = await client.get_account_balance(asset)
            return BalanceInfo(
                asset=asset,
                free=float(balance),
                locked=0.0,
                total=float(balance),
                exchange="binance",
                is_testnet=client.testnet,
                is_dry_run=client.dry_run,
            )

    async def get_open_positions(
        self,
        exchange_id: str | None = None,
    ) -> list[PositionInfo]:
        """Get open positions from specified or all exchanges."""
        results: list[PositionInfo] = []
        try:
            from exchange_registry import ExchangeRegistry

            registry = ExchangeRegistry.get_instance()
            ids = [exchange_id.lower()] if exchange_id else registry.list_exchange_ids()
            for eid in ids:
                client = registry.get(eid)
                if client is None:
                    continue
                try:
                    raw = await client.get_open_positions()
                    for p in raw or []:
                        results.append(
                            PositionInfo(
                                symbol=p.get("symbol", ""),
                                side=p.get("side", ""),
                                entry_price=float(p.get("entry_price", 0)),
                                current_price=float(p.get("current_price", 0)),
                                quantity=float(p.get("quantity", 0)),
                                unrealized_pnl=float(p.get("unrealized_pnl", 0)),
                                unrealized_pnl_pct=float(
                                    p.get("unrealized_pnl_pct", 0)
                                ),
                                exchange=eid,
                            )
                        )
                except Exception as e:
                    log.warning(
                        f"ExchangeQueryFacade: get_open_positions({eid}) failed: {e}"
                    )
        except ImportError:
            log.warning("ExchangeQueryFacade: ExchangeRegistry not available")
        return results

    async def get_exchange_health(self) -> list[ExchangeHealthInfo]:
        """Get health status of all registered exchanges."""
        results: list[ExchangeHealthInfo] = []
        try:
            from exchange_registry import ExchangeRegistry

            registry = ExchangeRegistry.get_instance()
            for eid in registry.list_exchange_ids():
                client = registry.get(eid)
                try:
                    import time

                    t0 = time.monotonic()
                    ok = await client.ping() if hasattr(client, "ping") else True
                    latency = (time.monotonic() - t0) * 1000
                    results.append(
                        ExchangeHealthInfo(
                            exchange=eid,
                            healthy=bool(ok),
                            is_testnet=getattr(client, "testnet", False),
                            is_dry_run=getattr(client, "dry_run", True),
                            latency_ms=round(latency, 1),
                        )
                    )
                except Exception:
                    results.append(
                        ExchangeHealthInfo(
                            exchange=eid,
                            healthy=False,
                            is_testnet=False,
                            is_dry_run=True,
                            latency_ms=None,
                        )
                    )
        except ImportError:
            # ignore missing exchange dependencies
            pass
        return results

    def list_available_exchanges(self) -> list[str]:
        """Return list of registered exchange IDs."""
        try:
            from exchange_registry import ExchangeRegistry

            return ExchangeRegistry.get_instance().list_exchange_ids()
        except Exception:
            return ["binance"]


_exchange_facade = ExchangeQueryFacade()


# ── P8 DataQueryFacade ─────────────────────────────────────────────────────


class DataQueryFacade:
    """Facade over database.py for trade history and daily performance stats."""

    async def get_recent_trades(
        self,
        limit: int = 10,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[TradeRecord]:
        """Get recent closed trades from Trades_DB.

        P9-C1: Schema guard — if 'exchange' column missing in older DB, falls back
        to a query without that column and defaults exchange to 'binance'.
        """
        try:
            import aiosqlite

            import config

            async with aiosqlite.connect(config.DB_PATH) as db:
                db.row_factory = aiosqlite.Row

                # P9-C1: Detect whether 'exchange' column exists
                has_exchange_col = False
                try:
                    async with db.execute(
                        "SELECT exchange FROM trades LIMIT 1"
                    ) as _probe:
                        await _probe.fetchone()
                    has_exchange_col = True
                except Exception as e:
                    log.debug(f"Exchange column probe failed (schema compat): {e}")

                if has_exchange_col:
                    query = """
                        SELECT id, symbol, side, entry_price, exit_price, pnl,
                               status, exchange, created_at
                        FROM trades
                        ORDER BY created_at DESC
                        LIMIT ?
                    """
                else:
                    query = """
                        SELECT id, symbol, side, entry_price, exit_price, pnl,
                               status, created_at
                        FROM trades
                        ORDER BY created_at DESC
                        LIMIT ?
                    """

                async with db.execute(query, (min(limit, 50),)) as cur:
                    rows = await cur.fetchall()

                return [
                    TradeRecord(
                        trade_id=row["id"],
                        symbol=row["symbol"],
                        side=row["side"],
                        entry_price=float(row["entry_price"] or 0),
                        exit_price=float(row["exit_price"])
                        if row["exit_price"]
                        else None,
                        pnl=float(row["pnl"]) if row["pnl"] else None,
                        status=row["status"] or "",
                        exchange=row["exchange"] if has_exchange_col else "binance",
                        created_at=row["created_at"] or "",
                    )
                    for row in rows
                ]
        except Exception as e:
            log.error(f"DataQueryFacade.get_recent_trades: {e}")
            return []

    async def get_daily_stats(self, date: str | None = None) -> DailyStats:
        """Get aggregated performance stats for a given date (YYYY-MM-DD, default today UTC)."""
        from datetime import datetime as dt

        target = date or dt.now(UTC).strftime("%Y-%m-%d")
        try:
            import aiosqlite

            import config

            async with aiosqlite.connect(config.DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    """
                    SELECT pnl, status FROM trades
                    WHERE date(created_at) = ? AND status IN ('FILLED','CLOSED')
                    """,
                    (target,),
                ) as cur:
                    rows = await cur.fetchall()

                if not rows:
                    return DailyStats(
                        date=target,
                        total_trades=0,
                        winning_trades=0,
                        losing_trades=0,
                        win_rate=0.0,
                        total_pnl=0.0,
                        best_trade=0.0,
                        worst_trade=0.0,
                    )

                pnls = [float(r["pnl"]) for r in rows if r["pnl"] is not None]
                winners = [p for p in pnls if p > 0]
                losers = [p for p in pnls if p <= 0]
                return DailyStats(
                    date=target,
                    total_trades=len(rows),
                    winning_trades=len(winners),
                    losing_trades=len(losers),
                    win_rate=round(len(winners) / len(pnls) * 100, 1) if pnls else 0.0,
                    total_pnl=round(sum(pnls), 2),
                    best_trade=max(pnls) if pnls else 0.0,
                    worst_trade=min(pnls) if pnls else 0.0,
                )
        except Exception as e:
            log.error(f"DataQueryFacade.get_daily_stats: {e}")
            return DailyStats(
                date=target,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0.0,
                total_pnl=0.0,
                best_trade=0.0,
                worst_trade=0.0,
            )


_data_facade = DataQueryFacade()


# ── P8 TradeLifecycleHandler ───────────────────────────────────────────────


def _register_trade_lifecycle_handlers():
    """Register EventBus listeners for TradeExecuted, TradeFailed, PositionClosed.
    Called from start_bot() AFTER _sender is initialised.
    """
    from core.event_bus import bus as _bus
    from core.events import PositionClosed, TradeExecuted, TradeFailed

    @_bus.on(TradeExecuted)
    async def on_trade_executed(event: TradeExecuted) -> None:
        """REQ1 + REQ10: Push fill confirmation with exchange context."""
        sender = get_sender()
        if sender is None:
            return
        sl = f"{event.stop_loss_price:,.4f}" if event.stop_loss_price else "—"
        tp = f"{event.take_profit_price:,.4f}" if event.take_profit_price else "—"
        price = (
            f"{event.executed_price:,.4f}" if event.executed_price is not None else "—"
        )
        qty = f"{event.executed_qty:,.4f}" if event.executed_qty is not None else "—"
        text = (
            f"✅ <b>LỆNH ĐÃ KHỚP</b>\n\n"
            f"🏦 Sàn: <code>{event.exchange.upper()}</code>\n"
            f"📌 Mã: <code>{event.symbol}</code>\n"
            f"📊 Chiều: <code>{event.side.upper()}</code>\n"
            f"💰 Giá khớp: <code>{price}</code>\n"
            f"📦 Khối lượng: <code>{qty}</code>\n"
            f"🛡️ Stop-Loss: <code>{sl}</code>\n"
            f"🎯 Take-Profit: <code>{tp}</code>\n"
            f"🆔 Trade ID: <code>#{event.trade_id}</code>"
        )
        await sender.send_message(text)

    @_bus.on(TradeFailed)
    async def on_trade_failed(event: TradeFailed) -> None:
        """REQ1: Push failure notification."""
        sender = get_sender()
        if sender is None:
            return
        text = (
            f"❌ <b>LỆNH THẤT BẠI</b>\n\n"
            f"🏦 Sàn: <code>{event.exchange.upper()}</code>\n"
            f"📌 Mã: <code>{event.symbol}</code>\n"
            f"📊 Chiều: <code>{event.side.upper()}</code>\n"
            f"⚠️ Lỗi: {event.error}"
        )
        await sender.send_message(text)

    @_bus.on(PositionClosed)
    async def on_position_closed(event: PositionClosed) -> None:
        """REQ2: Push P&L notification when SL/TP detected."""
        sender = get_sender()
        if sender is None:
            return
        pnl_emoji = "🟢" if event.pnl >= 0 else "🔴"
        reason_map = {
            "STOP_LOSS": "🛡️ Stop-Loss",
            "TAKE_PROFIT": "🎯 Take-Profit",
            "MANUAL": "✋ Manual",
        }
        reason_label = reason_map.get(event.exit_reason, event.exit_reason)
        text = (
            f"{pnl_emoji} <b>VỊ THẾ ĐÃ ĐÓNG — {reason_label}</b>\n\n"
            f"🏦 Sàn: <code>{event.exchange.upper()}</code>\n"
            f"📌 Mã: <code>{event.symbol}</code>\n"
            f"📊 Chiều: <code>{event.side.upper()}</code>\n"
            f"📥 Giá vào: <code>{event.entry_price:,.4f}</code>\n"
            f"📤 Giá ra: <code>{event.exit_price:,.4f}</code>\n"
            f"💵 P&L: <code>${event.pnl:+,.2f}</code> ({event.pnl_pct:+.2f}%)"
        )
        await sender.send_message(text)


# ── P8 PositionMonitor ─────────────────────────────────────────────────────


class PositionMonitor:
    """Background asyncio task polling exchanges for SL/TP fills.

    REQ2: Polls every POSITION_POLL_INTERVAL seconds (default 30).
    TODO: Upgrade to WebSocket stream (Binance user data stream / Bybit private WS)
          when adapter layer supports it — see GitHub issue #REQ2.
    """

    def __init__(self, poll_interval: int = 30):
        import config

        self._poll_interval = poll_interval or config.POSITION_POLL_INTERVAL
        self._tracked: dict[str, PositionSnapshot] = {}
        self._running = False
        self._task = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="position-monitor")
        log.info(f"📡 PositionMonitor started (poll={self._poll_interval}s)")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._poll_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"PositionMonitor._loop error: {e}")
            await asyncio.sleep(self._poll_interval)

    async def _poll_cycle(self) -> None:
        """Single poll: compare current positions vs tracked, detect closes."""
        current = await _exchange_facade.get_open_positions()
        current_keys = {f"{p.exchange}:{p.symbol}:{p.side}" for p in current}

        for key, snap in list(self._tracked.items()):
            if key not in current_keys:
                # Position gone — SL/TP or manual close
                from core.event_bus import bus as _bus
                from core.events import PositionClosed

                # Approximate P&L from snapshot (exact values need exchange history)
                log.info(f"PositionMonitor: position closed detected — {key}")
                await _bus.emit(
                    PositionClosed(
                        symbol=snap.symbol,
                        side=snap.side,
                        entry_price=snap.entry_price,
                        exit_price=0.0,  # not available without order history query
                        quantity=snap.quantity,
                        pnl=0.0,
                        pnl_pct=0.0,
                        exit_reason="UNKNOWN",
                        exchange=snap.exchange,
                    )
                )
                del self._tracked[key]

        # Update tracked with current positions
        for p in current:
            key = f"{p.exchange}:{p.symbol}:{p.side}"
            self._tracked[key] = PositionSnapshot(
                symbol=p.symbol,
                side=p.side,
                entry_price=p.entry_price,
                quantity=p.quantity,
                stop_loss_price=None,
                take_profit_price=None,
                exchange=p.exchange,
                last_seen=datetime.now(),
            )

    async def get_open_positions(
        self, exchange_id: str | None = None
    ) -> list[PositionInfo]:
        return await _exchange_facade.get_open_positions(exchange_id)


_position_monitor: PositionMonitor | None = None


# ── P8 ApprovalTimeoutManager ─────────────────────────────────────────────


class ApprovalTimeoutManager:
    """Background asyncio task that auto-rejects stale pending trade approvals.

    REQ7: Checks PENDING_TRADES every 30s for entries older than
    APPROVAL_TIMEOUT_MINUTES (default 5). Edits the original Telegram message
    and sends a timeout notification so no button can be tapped after expiry.
    """

    def __init__(self, timeout_minutes: int = 5, check_interval: int = 30):
        import config

        self._timeout_minutes = timeout_minutes or config.APPROVAL_TIMEOUT_MINUTES
        self._check_interval = check_interval
        # signal_id -> list of (chat_id, message_id, sent_at_timestamp)
        self._tracked: dict[int, list[tuple[int, int, float]]] = {}
        self._running = False
        self._task = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="approval-timeout")
        log.info(f"⏱️ ApprovalTimeoutManager started (timeout={self._timeout_minutes}m)")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    def track_message(self, signal_id: int, chat_id: int, message_id: int) -> None:
        """Register a sent approval message for editing on timeout."""
        import time

        if signal_id not in self._tracked:
            self._tracked[signal_id] = []
        self._tracked[signal_id].append((chat_id, message_id, time.time()))

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"ApprovalTimeoutManager._loop error: {e}")
            await asyncio.sleep(self._check_interval)

    async def _check_cycle(self) -> None:
        """Find expired entries, remove from PENDING_TRADES, notify, edit msgs."""
        import time

        from hub.notification_hub import PENDING_TRADES

        sender = get_sender()
        timeout_sec = self._timeout_minutes * 60

        for signal_id, msg_list in list(self._tracked.items()):
            if not msg_list:
                continue
            _, _, sent_at = msg_list[0]
            elapsed_sec = time.time() - sent_at
            if elapsed_sec < timeout_sec:
                continue

            # Expired
            event = PENDING_TRADES.pop(signal_id, None)
            symbol = (
                getattr(event, "symbol", f"Signal #{signal_id}")
                if event
                else f"Signal #{signal_id}"
            )
            action = getattr(event, "action", "").upper() if event else ""
            elapsed_min = int(elapsed_sec // 60)

            log.warning(
                f"ApprovalTimeoutManager: signal #{signal_id} ({symbol}) timed out after {elapsed_min}m"
            )

            timeout_text = (
                f"⏰ <b>HẾT HẠN DUYỆT LỆNH</b>\n\n"
                f"📌 Mã: <code>{symbol}</code>\n"
                f"📊 Hành động: <code>{action}</code>\n"
                f"⏱️ Đã hết hạn sau: <b>{elapsed_min} phút</b>\n\n"
                f"<i>Lệnh đã bị tự động từ chối do không có phản hồi.</i>"
            )

            # Edit original approval messages to show expired state
            if sender:
                for chat_id, message_id, _ in msg_list:
                    expired_suffix = (
                        "\n\n<i>⏰ Lệnh đã hết hạn — không thể duyệt/từ chối.</i>"
                    )
                    # Try to edit; swallow errors if message too old to edit
                    try:
                        await sender.edit_message(
                            chat_id, message_id, f"<i>[HẾT HẠN]</i>{expired_suffix}"
                        )
                    except Exception as e:
                        log.debug(f"Failed to edit expired message: {e}")
                await sender.send_message(timeout_text)

            del self._tracked[signal_id]


_approval_timeout_mgr: ApprovalTimeoutManager | None = None


def get_approval_timeout_mgr() -> ApprovalTimeoutManager | None:
    """Get the global ApprovalTimeoutManager singleton."""
    return _approval_timeout_mgr


def get_application():
    """Get the PTB Application singleton (P9 — used by claude_cli to register commands)."""
    return _bot_app


# ── P9-B1: Daily Report Auto-Send Scheduler ───────────────────────────


async def _report_auto_send_loop() -> None:
    """Background loop that auto-sends the daily P&L report at REPORT_SEND_TIME (ICT).

    REQ8 AC4: Enabled via REPORT_AUTO_SEND=true, time via REPORT_SEND_TIME=HH:MM.
    ICT = UTC+7. Runs once per day at the configured wall-clock time.
    Singleton guard: task name 'report-auto-send' prevents duplicates on reload.
    """
    from datetime import datetime as _dt
    from datetime import timedelta, timezone

    import config

    ICT = timezone(timedelta(hours=7))
    log.info(
        f"📊 _report_auto_send_loop running (target={config.REPORT_SEND_TIME} ICT)"
    )

    while True:
        try:
            # Parse configured send time
            h, m = map(int, config.REPORT_SEND_TIME.split(":"))
        except Exception:
            h, m = 22, 0  # fallback default

        now_ict = _dt.now(ICT)
        target_today = now_ict.replace(hour=h, minute=m, second=0, microsecond=0)

        if now_ict >= target_today:
            # Already past target time today — schedule for tomorrow
            target_today = target_today + timedelta(days=1)

        wait_seconds = (target_today - now_ict).total_seconds()
        log.info(
            f"📊 ReportAutoSend: next send in {wait_seconds / 3600:.1f}h ({target_today.strftime('%Y-%m-%d %H:%M')} ICT)"
        )
        await asyncio.sleep(wait_seconds)

        # Send report for today (UTC date, which is ICT-1 day at 22:00)
        utc_date = _dt.now(UTC).strftime("%Y-%m-%d")
        try:
            sender = get_sender()
            if sender is None:
                continue
            stats = await _data_facade.get_daily_stats(utc_date)
            if stats.total_trades == 0:
                text = f"📵 <b>Báo Cáo Tự Động</b> {utc_date}\n\n<i>Không có giao dịch nào hôm nay.</i>"
            else:
                pnl_emoji = "🟢" if stats.total_pnl >= 0 else "🔴"
                text = (
                    f"📊 <b>BÁO CÁO TỰ ĐỘNG — {utc_date}</b>\n\n"
                    f"📈 Tổng lệnh: <b>{stats.total_trades}</b>\n"
                    f"✅ Thắng: <b>{stats.winning_trades}</b> | ❌ Thua: <b>{stats.losing_trades}</b>\n"
                    f"🎯 Win Rate: <b>{stats.win_rate:.1f}%</b>\n"
                    f"{pnl_emoji} Tổng P&L: <b>${stats.total_pnl:+,.2f}</b>\n"
                    f"🏆 Tốt nhất: <code>${stats.best_trade:+,.2f}</code> | "
                    f"💔 Tệ nhất: <code>${stats.worst_trade:+,.2f}</code>"
                )
            from notifier import sanitize_for_telegram_html

            await sender.send_message(sanitize_for_telegram_html(text))
            log.info(f"📊 ReportAutoSend: daily report sent for {utc_date}")
        except Exception as e:
            log.error(f"_report_auto_send_loop send error: {e}")

        # Sleep a bit to avoid double-send on edge timing
        await asyncio.sleep(60)


# ── P10: Dashboard Login/Logout Commands ─────────────────────────────────


async def cmd_login(update, context):
    """Generate a one-time dashboard login link.

    Authorization-first: checks allowed users BEFORE generating code.
    """
    user = update.effective_user
    if not user:
        await update.message.reply_text("❌ Không xác định được user.")
        return

    try:
        import database as db
        from auth.auth_config import AuthConfig
        from auth.service import AuthService

        auth_cfg = AuthConfig()
        auth_svc = AuthService(auth_cfg)

        # Authorization check FIRST (before generating any code)
        if not auth_cfg.is_user_allowed(user.id):
            await update.message.reply_text(
                "🚫 Bạn không có quyền truy cập Dashboard.\n"
                "Liên hệ admin để được thêm vào danh sách cho phép."
            )
            return

        # Generate one-time code
        otp = auth_svc.generate_login_code(
            telegram_id=user.id,
            username=user.username,
        )

        # Store code in DB
        db.store_auth_code(
            code=otp.code,
            telegram_id=otp.telegram_id,
            username=otp.username,
            created_at=otp.created_at.isoformat(),
            expires_at=otp.expires_at.isoformat(),
        )

        dashboard_url = auth_cfg.dashboard_url.rstrip("/")
        if not dashboard_url.startswith("http://") and not dashboard_url.startswith(
            "https://"
        ):
            dashboard_url = f"http://{dashboard_url}"

        # ⚠️ BỘ LỌC CỦA TELEGRAM: Telegram tự động chặn KHÔNG CHO CLICK vào các link có chứa "localhost" hoặc "127.0.0.1".
        # Sử dụng Regex để thay thế linh hoạt mọi trường hợp localhost/127.0.0.1 thành 127.0.0.1.nip.io
        import re

        safe_dashboard_url = re.sub(
            r"(://)(localhost|127\.0\.0\.1)(:?\d*)",
            r"\g<1>127.0.0.1.nip.io\g<3>",
            dashboard_url,
            flags=re.IGNORECASE,
        )

        login_url = f"{safe_dashboard_url}/auth/callback?code={otp.code}"

        # ⚠️ DO NOT pass through sanitize_for_telegram_html — the message
        # is pre-built with valid Telegram HTML tags. That function escapes
        # < > first, which destroys <b>, <a href=...>, <code> tags.
        msg = (
            f"🔐 <b>Dashboard Login</b>\n\n"
            f"Click link sau để đăng nhập Dashboard:\n"
            f'<a href="{login_url}">🚀 Mở Dashboard</a>\n\n'
            f"🔗 <b>Link trực tiếp (nếu không bấm được Mở Dashboard):</b>\n"
            f"{login_url}\n\n"
            f"⚠️ Link hết hạn sau <b>5 phút</b> và chỉ dùng được 1 lần.\n"
            f"<code>{otp.code}</code>"
        )
        await update.message.reply_text(
            msg, parse_mode="HTML", disable_web_page_preview=True
        )
        log.info(f"🔐 Login code generated for user {user.id} (@{user.username})")

    except Exception as e:
        log.error(f"cmd_login error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Login thất bại: {e}")


async def cmd_logout(update, context):
    """Invalidate all dashboard sessions for the current user."""
    user = update.effective_user
    if not user:
        await update.message.reply_text("❌ Không xác định được user.")
        return

    try:
        import database as db

        count = db.delete_all_user_sessions(user.id)
        if count > 0:
            await update.message.reply_text(
                f"✅ Đã huỷ <b>{count}</b> phiên đăng nhập Dashboard.\n"
                f"Bạn sẽ cần /login lại để truy cập.",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("Không có phiên nào đang hoạt động.")
        log.info(f"🔐 All sessions invalidated for user {user.id} (count={count})")
    except Exception as e:
        log.error(f"cmd_logout error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Logout thất bại: {e}")


# ── Bot Lifecycle ──────────────────────────────────────────────

_bot_thread_lock = threading.Lock()


def start_bot():
    """Start Telegram bot in a background thread (polling mode).

    SCAR-TG-001: singleton guard — if bot thread is already alive, skip.
    Multiple calls (e.g. on hot-reload) must NOT spawn duplicate pollers.
    409 Conflict from Telegram = two getUpdates sessions running simultaneously.
    """
    global \
        _bot_app, \
        _bot_thread, \
        _bot_loop, \
        _sender, \
        _position_monitor, \
        _approval_timeout_mgr

    import config

    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("Telegram bot token not set — Telegram Bot disabled")
        return

    try:
        _get_imports()
    except ImportError:
        log.warning(
            "python-telegram-bot not installed — run: pip install python-telegram-bot"
        )
        return

    with _bot_thread_lock:
        # ── Singleton guard ────────────────────────────────────────────
        if _bot_thread is not None and _bot_thread.is_alive():
            log.info(
                "🤖 Telegram Bot already running — skipping duplicate start (SCAR-TG-001)"
            )
            return

        from telegram.ext import (
            ApplicationBuilder,
            CallbackQueryHandler,
            CommandHandler,
        )

        def _run_bot():
            """Bot runner in separate thread with its own event loop."""
            global \
                _bot_app, \
                _sender, \
                _position_monitor, \
                _approval_timeout_mgr, \
                _bot_loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _bot_loop = loop

            # Build bot — force IPv4 to fix async httpx ConnectError on Windows
            import httpx as _httpx
            from telegram.request import HTTPXRequest

            _proxy = config.TELEGRAM_PROXY_URL or None
            request = HTTPXRequest(proxy=_proxy)
            # Inject IPv4-only transport (overrides default which allows IPv6)
            request._client_kwargs["transport"] = _httpx.AsyncHTTPTransport(
                local_address="127.0.0.1",
            )
            request._client = request._build_client()

            app = (
                ApplicationBuilder()
                .token(config.TELEGRAM_BOT_TOKEN)
                .request(request)
                .build()
            )
            log.info(
                "🤖 Telegram Bot using IPv4-forced async transport (fix for Windows)"
            )

            # ── P8: Initialise TelegramSender singleton ───────────────
            _sender = TelegramSender(app)
            log.info("📤 TelegramSender initialised")

            # ── P8: Register trade lifecycle event handlers ────────────
            _register_trade_lifecycle_handlers()
            log.info("📡 TradeLifecycleHandler registered on EventBus")

            # ── Conflict error handler (suppress 409 log spam) ────────
            async def _on_error(update, context):
                from telegram.error import Conflict, NetworkError

                err = context.error
                if isinstance(err, Conflict):
                    log.warning(
                        "🤖 TG Conflict (409) — another instance terminated. Resuming..."
                    )
                elif isinstance(err, NetworkError):
                    log.warning(f"🤖 TG NetworkError: {err}")
                else:
                    log.error(f"🤖 TG Unhandled error: {err}", exc_info=err)

            app.add_error_handler(_on_error)

            # Register bot commands globally
            async def post_init(application):
                from telegram import BotCommand

                commands = [
                    BotCommand("start", "Giới thiệu bot & Menu"),
                    BotCommand("help", "Danh sách lệnh"),
                    BotCommand("status", "Trạng thái hệ thống"),
                    BotCommand("scan", "Scan watchlist (TT + VCP + 👁 Vision)"),
                    BotCommand("scan_mtf", "Scan đa khung (1D/4H/1H) & Duyệt lệnh"),
                    BotCommand("recommend", "Gợi ý cơ hội giao dịch đa khung"),
                    BotCommand("brief", "Chạy Morning Brief"),
                    BotCommand("watchlist", "Xem watchlist"),
                    BotCommand("balance", "Xem balance [EXCHANGE] [ASSET]"),
                    BotCommand("grade", "Chấm điểm lệnh (Bar Replay)"),
                    BotCommand("positions", "Vị thế mở + Unrealized P&L"),
                    BotCommand("rag", "Hỏi Minervini AI Knowledge Base"),
                    BotCommand("trades", "Lịch sử giao dịch [N]"),
                    BotCommand("report", "Báo cáo ngày [YYYY-MM-DD]"),
                    BotCommand("login", "Đăng nhập Dashboard"),
                    BotCommand("logout", "Huỷ phiên Dashboard"),
                ]
                await application.bot.set_my_commands(commands)

                # ── P8: Start background tasks inside bot event loop ──
                global _position_monitor, _approval_timeout_mgr
                _position_monitor = PositionMonitor()
                await _position_monitor.start()

                _approval_timeout_mgr = ApprovalTimeoutManager()
                await _approval_timeout_mgr.start()

                # ── P9-B1: REPORT_AUTO_SEND daily scheduler ───────────────
                if config.REPORT_AUTO_SEND:
                    global _report_auto_send_task
                    _report_auto_send_task = asyncio.create_task(
                        _report_auto_send_loop(), name="report-auto-send"
                    )
                    log.info(
                        f"📊 ReportAutoSend scheduler started (time={config.REPORT_SEND_TIME} ICT)"
                    )
                    log.debug(
                        f"Registered background task: {_report_auto_send_task.get_name()}"
                    )

            app.post_init = post_init

            # Register command handlers
            app.add_handler(CommandHandler("start", cmd_start))
            app.add_handler(CommandHandler("help", cmd_help))
            app.add_handler(CommandHandler("status", cmd_status))
            app.add_handler(CommandHandler("watchlist", cmd_watchlist))
            app.add_handler(CommandHandler("add", cmd_add))
            app.add_handler(CommandHandler("remove", cmd_remove))
            app.add_handler(
                CommandHandler("scan", cmd_scan_enhanced)
            )  # P8: replaces cmd_scan
            app.add_handler(CommandHandler("scan_all", cmd_scan_all))
            app.add_handler(CommandHandler("scan_mtf", cmd_scan_mtf))
            app.add_handler(CommandHandler("recommend", cmd_recommend))
            app.add_handler(CommandHandler("brief", cmd_brief))
            app.add_handler(CommandHandler("vision", cmd_vision))
            app.add_handler(CommandHandler("grade", cmd_grade))
            app.add_handler(
                CommandHandler("balance", cmd_balance_enhanced)
            )  # P8: replaces cmd_balance
            # ── P8 new commands ──────────────────────────────────────
            app.add_handler(CommandHandler("positions", cmd_positions))
            app.add_handler(CommandHandler("rag", cmd_rag))
            app.add_handler(CommandHandler("trades", cmd_trades))
            app.add_handler(
                CommandHandler("stats", cmd_stats)
            )  # Phase 3: mode breakdown
            app.add_handler(
                CommandHandler("backtest", cmd_backtest)
            )  # Phase 3: visual chart
            app.add_handler(CommandHandler("report", cmd_report))

            # ── P10: Dashboard auth commands ─────────────────────────────
            app.add_handler(CommandHandler("login", cmd_login))
            app.add_handler(CommandHandler("logout", cmd_logout))

            from telegram.ext import MessageHandler, filters

            app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text)
            )

            app.add_handler(CallbackQueryHandler(button_callback))

            _bot_app = app
            log.info("🤖 Telegram Bot started (polling mode)")
            try:
                app.run_polling(drop_pending_updates=True, close_loop=False)
            finally:
                _bot_loop = None
                try:
                    loop.close()
                except Exception as e:
                    log.debug(f"Loop close error: {e}")

        _bot_thread = threading.Thread(
            target=_run_bot, daemon=True, name="telegram-bot"
        )
        _bot_thread.start()
        log.info("🤖 Telegram Bot thread launched")


def stop_bot():
    """Stop Telegram bot gracefully."""
    global \
        _bot_app, \
        _bot_thread, \
        _bot_loop, \
        _position_monitor, \
        _approval_timeout_mgr, \
        _report_auto_send_task
    if _bot_app is not None:
        log.info("🤖 Telegram Bot stopping...")
        try:
            # Cancel all interactive command background tasks
            for task in list(running_tasks):
                if not task.done():
                    task.cancel()
            running_tasks.clear()
            active_commands.clear()

            # Stop the monitors thread-safely
            if _position_monitor is not None:
                _position_monitor._running = False
                if _position_monitor._task and not _position_monitor._task.done():
                    _position_monitor._task.cancel()
                _position_monitor = None

            if _approval_timeout_mgr is not None:
                _approval_timeout_mgr._running = False
                if (
                    _approval_timeout_mgr._task
                    and not _approval_timeout_mgr._task.done()
                ):
                    _approval_timeout_mgr._task.cancel()
                _approval_timeout_mgr = None

            # Stop the auto report task
            if _report_auto_send_task is not None:
                if not _report_auto_send_task.done():
                    _report_auto_send_task.cancel()
                _report_auto_send_task = None

            # stop_running() signals run_polling() to exit
            if _bot_loop is not None:
                if _bot_loop.is_running():
                    log.info("🤖 Stopping bot using original event loop (running)...")
                    fut_updater = asyncio.run_coroutine_threadsafe(
                        _bot_app.updater.stop(), _bot_loop
                    )
                    try:
                        fut_updater.result(timeout=10)
                    except Exception as e:
                        log.warning(f"🤖 Updater stop error: {e}")
                    fut_app = asyncio.run_coroutine_threadsafe(
                        _bot_app.stop(), _bot_loop
                    )
                    try:
                        fut_app.result(timeout=10)
                    except Exception as e:
                        log.warning(f"🤖 App stop error: {e}")
                elif not _bot_loop.is_closed():
                    log.info("🤖 Stopping bot using original event loop (idle)...")
                    try:
                        _bot_loop.run_until_complete(_bot_app.updater.stop())
                        _bot_loop.run_until_complete(_bot_app.stop())
                    except Exception as e:
                        log.warning(f"🤖 App stop error (idle loop): {e}")
                else:
                    log.warning(
                        "🤖 Original event loop is closed. Falling back to new loop stop..."
                    )
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(_bot_app.updater.stop())
                        loop.run_until_complete(_bot_app.stop())
                    finally:
                        loop.close()
            else:
                log.warning(
                    "🤖 Original bot event loop not found. Falling back to new loop stop..."
                )
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(_bot_app.updater.stop())
                    loop.run_until_complete(_bot_app.stop())
                finally:
                    loop.close()
        except Exception as e:
            log.warning(f"🤖 Bot stop error (non-fatal): {e}")
        _bot_app = None
    _bot_thread = None
