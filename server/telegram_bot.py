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

import logging
import asyncio
import threading
from datetime import datetime

log = logging.getLogger(__name__)

# Lazy imports — only load if bot is enabled
_bot_app = None
_bot_thread = None


def _get_imports():
    """Lazy import python-telegram-bot to avoid crash if not installed."""
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        CallbackQueryHandler,
        ContextTypes,
    )
    return Update, InlineKeyboardButton, InlineKeyboardMarkup, \
           ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes


# ── Interactive Messaging ──────────────────────────────────────────────────

async def send_interactive_trade_approval(
    signal_id: int, message: str
) -> list:
    """Send interactive trade approval message with Approve/Reject buttons.

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
                InlineKeyboardButton("✅ Duyệt (Approve)", callback_data=f"approve_{signal_id}"),
                InlineKeyboardButton("❌ Hủy (Reject)", callback_data=f"reject_{signal_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        html_message = sanitize_for_telegram_html(message)

        for chat_id in config.TELEGRAM_CHAT_IDS:
            try:
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


# ── Command Handlers ──────────────────────────────────────────────────────

async def cmd_start(update, context):
    """Giới thiệu bot."""
    from telegram import ReplyKeyboardMarkup

    reply_keyboard = [
        ["📊 Scan", "🌅 Morning Brief"],
        ["📋 Watchlist", "🔧 Status"]
    ]
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
        "🔧 <b>System Status</b>\n",
        f"⏰ Server time: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>",
        f"🌐 Server: FastAPI v7.0 on :{config.PORT}",
    ]

    # RAG status
    rag_status = "✅ Enabled" if config.RAG_ENABLED and config.ANTHROPIC_API_KEY else "❌ Disabled"
    lines.append(f"🧠 RAG: {rag_status}")

    # MCP status
    if config.MCP_ENABLED:
        try:
            from mcp_client import get_mcp_client
            mcp = get_mcp_client()
            health = await mcp.health_check()
            mcp_status = "✅ Connected" if health.get("connected") else "⚠️ Not connected"
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
    lines.append("🏦 <b>Exchange Health</b>")
    try:
        exchange_health = await _exchange_facade.get_exchange_health()
        if exchange_health:
            for eh in exchange_health:
                status_icon = "✅" if eh.healthy else "❌"
                mode_parts = []
                if eh.is_dry_run:
                    mode_parts.append("DRY")
                mode_parts.append("TEST" if eh.is_testnet else "LIVE")
                latency_str = f" | {eh.latency_ms:.0f}ms" if eh.latency_ms is not None else ""
                mode_label = "/".join(mode_parts)
                lines.append(
                    f"  {status_icon} <code>{eh.exchange.upper()}</code> [{mode_label}]{latency_str}"
                )
        else:
            lines.append("  ⚠️ No exchanges registered")
    except Exception as e:
        lines.append(f"  ⚠️ Exchange health check failed: {e}")

    # ── P8 background task status ─────────────────────────────────────────
    lines.append("")
    lines.append("⚙️ <b>P8 Background Tasks</b>")
    pm_status = "✅ Running" if _position_monitor and _position_monitor._running else "❌ Stopped"
    tm_status = "✅ Running" if _approval_timeout_mgr and _approval_timeout_mgr._running else "❌ Stopped"
    lines.append(f"  📡 PositionMonitor: {pm_status}")
    lines.append(f"  ⏱️ ApprovalTimeout: {tm_status}")
    report_sched = "✅ Active" if config.REPORT_AUTO_SEND else "❌ Off"
    lines.append(f"  📊 ReportScheduler: {report_sched} ({config.REPORT_SEND_TIME} ICT)")

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
    await update.message.reply_text("🔄 Đang scan watchlist... Vui lòng chờ.")

    try:
        from watchlist import get_watchlist
        from analysis import scan_symbols

        symbols = get_watchlist()
        if not symbols:
            await update.message.reply_text("📋 Watchlist trống. Dùng /add để thêm symbols.")
            return

        # Check MCP
        import config
        mcp = None
        if config.MCP_ENABLED:
            try:
                from mcp_client import get_mcp_client
                mcp = get_mcp_client()
            except Exception:
                pass

        results = await scan_symbols(symbols, mcp)

        if not results:
            await update.message.reply_text("⚠️ Không scan được symbol nào. Kiểm tra MCP connection.")
            return

        # Format results table
        lines = [f"📊 **Scan Results** ({len(results)} symbols)\n"]
        lines.append("```")
        lines.append(f"{'Symbol':<10} {'Price':>10} {'TT':>4} {'VCP':>5} {'Vol%':>6}")
        lines.append("─" * 40)

        for r in results:
            tt_score = r.trend_template.score if r.trend_template else "?"
            tt_max = 8
            vcp = "⭐" if r.vcp and r.vcp.detected else ""
            vol_ratio = r.vcp.volume_ratio if r.vcp else 0
            vol_pct = f"{vol_ratio*100:.0f}%" if vol_ratio else "N/A"
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
                vol_ratio = r.vcp.volume_ratio if r.vcp and r.vcp.volume_ratio else 0
                lines.append(
                    f"• `{r.symbol}` — Vol: {vol_ratio*100:.0f}% avg, "
                    f"Pivot: {pivot:,.2f}"
                )

        from notifier import sanitize_for_telegram_html
        html_output = sanitize_for_telegram_html("\n".join(lines))
        await update.message.reply_text(html_output, parse_mode="HTML")

    except Exception as e:
        log.error(f"Scan error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Scan failed: {e}")


async def cmd_brief(update, context):
    """Chạy Morning Brief on-demand."""
    await update.message.reply_text("🌅 Đang chạy Morning Brief... Vui lòng chờ 30-60s.")

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
    if not context.args:
        await update.message.reply_text(
            "⚠️ Cần chỉ định symbol.\nVD: /vision <code>BTCUSDT</code>",
            parse_mode="HTML",
        )
        return

    symbol = context.args[0].strip().upper()
    await update.message.reply_text(f"👁️ Đang phân tích chart <code>{symbol}</code>... Vui lòng chờ.", parse_mode="HTML")

    try:
        import config
        from pathlib import Path

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
                    from datetime import datetime as dt
                    import re
                    safe_symbol = re.sub(r'[^A-Za-z0-9_\-]', '', symbol)
                    screenshot_path = await mcp.capture_screenshot(
                        symbol=symbol,
                        timeframe="D",
                        region="chart",
                        save_path=screenshots_dir / f"vision_{safe_symbol}_{dt.now().strftime('%Y%m%d_%H%M%S')}.png"
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
            await update.message.reply_text(
                f"⚠️ Không tìm thấy screenshot cho <code>{symbol}</code>.\n"
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
            await update.message.reply_text(f"❌ Vision error: {result['error']}")
            return

        from notifier import sanitize_for_telegram_html
        vision_text = format_vision_telegram(result)
        await update.message.reply_text(sanitize_for_telegram_html(vision_text), parse_mode="HTML")

    except Exception as e:
        log.error(f"Vision command error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Vision failed: {e}")


async def cmd_grade(update, context):
    """AI Mentor — chấm điểm setup Long/Short trên màn hình hiện tại."""
    await update.message.reply_text("👨‍🏫 Đang chụp và phân tích lệnh của bạn... Vui lòng chờ.", parse_mode="HTML")

    try:
        import config
        from pathlib import Path

        if not config.MCP_ENABLED:
            await update.message.reply_text("⚠️ Tính năng này yêu cầu bật MCP_ENABLED = True.")
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
                    save_path=screenshots_dir / f"grade_{dt.now().strftime('%Y%m%d_%H%M%S')}.png",
                    active_only=True
                )
            else:
                await update.message.reply_text("⚠️ TradingView chưa kết nối (MCP CDP).")
                return
        except Exception as e:
            log.warning(f"Grade screenshot capture failed: {e}")
            await update.message.reply_text(f"❌ Lỗi chụp TradingView: {e}")
            return

        if not screenshot_path or not Path(screenshot_path).exists():
            await update.message.reply_text("⚠️ Không lấy được ảnh từ TradingView.")
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
            await update.message.reply_text(f"\u274c Vision error: {result['error']}")
            return

        from notifier import sanitize_for_telegram_html
        formatted = format_vision_telegram(result)
        await update.message.reply_text(sanitize_for_telegram_html(formatted), parse_mode="HTML")


    except Exception as e:
        log.error(f"Grade command error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Grade failed: {e}")


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
    exchange_id = context.args[0].lower() if context.args else None
    await update.message.reply_text("📡 Đang tải vị thế mở...")

    positions = await _exchange_facade.get_open_positions(exchange_id)

    if not positions:
        label = exchange_id.upper() if exchange_id else "tất cả sàn"
        await update.message.reply_text(
            f"📭 Không có vị thế mở nào trên <b>{label}</b>.",
            parse_mode="HTML",
        )
        return

    lines = [f"📊 <b>Vị Thế Mở</b> ({len(positions)})\n"]
    for p in positions:
        pnl_emoji = "🟢" if p.unrealized_pnl >= 0 else "🔴"
        lines.append(
            f"{pnl_emoji} <code>{p.symbol}</code> [{p.exchange.upper()}]\n"
            f"   Chiều: <b>{p.side.upper()}</b> | Qty: <code>{p.quantity:,.4f}</code>\n"
            f"   Vào: <code>{p.entry_price:,.4f}</code> → Hiện: <code>{p.current_price:,.4f}</code>\n"
            f"   P&L: <code>${p.unrealized_pnl:+,.2f}</code> ({p.unrealized_pnl_pct:+.2f}%)"
        )

    from notifier import sanitize_for_telegram_html
    await update.message.reply_text(
        sanitize_for_telegram_html("\n".join(lines)), parse_mode="HTML"
    )


async def cmd_rag(update, context):
    """REQ5: /rag <query> — ask Minervini knowledge base."""
    import config
    if not config.RAG_ENABLED or not (config.ANTHROPIC_API_KEY or config.GEMINI_API_KEY):
        await update.message.reply_text("❌ RAG system is disabled (RAG_ENABLED=false or no API key).")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ Cần chỉ định câu hỏi.\nVD: /rag <code>What is VCP?</code>",
            parse_mode="HTML",
        )
        return

    query = " ".join(context.args)
    thinking_msg = await update.message.reply_text(f"🧠 Đang suy nghĩ về: <i>{query}</i>...", parse_mode="HTML")

    try:
        from rag import query_knowledge, generate_trading_advice
        chunks = await query_knowledge(query)
        if not chunks:
            await thinking_msg.edit_text("⚠️ Không tìm thấy thông tin liên quan trong knowledge base.")
            return

        advice = await generate_trading_advice(query, chunks)
        response_text = f"🧠 <b>RAG Answer</b>\n\n<i>Q: {query}</i>\n\n{advice}"
        from notifier import sanitize_for_telegram_html
        await thinking_msg.edit_text(sanitize_for_telegram_html(response_text), parse_mode="HTML")
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
            pass

    trades = await _data_facade.get_recent_trades(limit=limit)

    if not trades:
        await update.message.reply_text("📭 Chưa có lịch sử giao dịch nào.")
        return

    lines = [f"📋 <b>Lịch Sử Giao Dịch</b> (last {len(trades)})\n"]
    for t in trades:
        pnl_emoji = "🟢" if (t.pnl or 0) > 0 else ("🔴" if (t.pnl or 0) < 0 else "⚪")
        pnl_str = f"${t.pnl:+,.2f}" if t.pnl is not None else "—"
        exit_str = f"{t.exit_price:,.4f}" if t.exit_price else "OPEN"
        lines.append(
            f"{pnl_emoji} <code>{t.symbol}</code> {t.side.upper()} [{t.exchange.upper()}]\n"
            f"   Vào: <code>{t.entry_price:,.4f}</code> → Ra: <code>{exit_str}</code> | P&L: <b>{pnl_str}</b>\n"
            f"   <i>{t.created_at[:16]}</i>"
        )

    from notifier import sanitize_for_telegram_html
    await update.message.reply_text(
        sanitize_for_telegram_html("\n".join(lines)), parse_mode="HTML"
    )


async def cmd_report(update, context):
    """REQ8: /report [YYYY-MM-DD] — daily performance summary."""
    date_arg = context.args[0] if context.args else None
    stats = await _data_facade.get_daily_stats(date_arg)

    if stats.total_trades == 0:
        await update.message.reply_text(
            f"📭 Không có giao dịch nào vào ngày <b>{stats.date}</b>.",
            parse_mode="HTML",
        )
        return

    pnl_emoji = "🟢" if stats.total_pnl >= 0 else "🔴"
    text = (
        f"📊 <b>Báo Cáo Ngày {stats.date}</b>\n\n"
        f"📈 Tổng lệnh: <b>{stats.total_trades}</b>\n"
        f"✅ Thắng: <b>{stats.winning_trades}</b> | ❌ Thua: <b>{stats.losing_trades}</b>\n"
        f"🎯 Win Rate: <b>{stats.win_rate:.1f}%</b>\n"
        f"{pnl_emoji} Tổng P&L: <b>${stats.total_pnl:+,.2f}</b>\n"
        f"🏆 Lệnh tốt nhất: <code>${stats.best_trade:+,.2f}</code>\n"
        f"💔 Lệnh tệ nhất: <code>${stats.worst_trade:+,.2f}</code>"
    )
    from notifier import sanitize_for_telegram_html
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
            f"💰 <b>Binance Balance</b>\n\n"
            f"🏦 Sàn: <code>{info.exchange.upper()}</code>\n"
            f"💎 Asset: <code>{info.asset}</code>\n"
            f"✅ Free: <code>${info.free:,.2f}</code>\n"
            f"🔒 Locked: <code>${info.locked:,.2f}</code>\n"
            f"💵 Total: <code>${info.total:,.2f}</code>\n"
            f"⚙️ Mode: <code>{', '.join(mode_parts)}</code>"
        )
        from notifier import sanitize_for_telegram_html
        await update.message.reply_text(sanitize_for_telegram_html(text), parse_mode="HTML")
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_scan_enhanced(update, context):
    """REQ4: Enhanced /scan — adds 👁 Analyze inline buttons for VCP setups."""
    await update.message.reply_text("🔄 Đang scan watchlist... Vui lòng chờ.")

    try:
        from watchlist import get_watchlist
        from analysis import scan_symbols
        import config

        symbols = get_watchlist()
        if not symbols:
            await update.message.reply_text("📋 Watchlist trống. Dùng /add để thêm symbols.")
            return

        mcp = None
        if config.MCP_ENABLED:
            try:
                from mcp_client import get_mcp_client
                mcp = get_mcp_client()
            except Exception:
                pass

        results = await scan_symbols(symbols, mcp)

        if not results:
            await update.message.reply_text("⚠️ Không scan được symbol nào.")
            return

        lines = [f"📊 <b>Scan Results</b> ({len(results)} symbols)\n"]
        lines.append("<pre>")
        lines.append(f"{'Symbol':<10} {'Price':>10} {'TT':>4} {'VCP':>5} {'Vol%':>6}")
        lines.append("─" * 40)

        vcp_setups = []
        for r in results:
            tt_score = r.trend_template.score if r.trend_template else "?"
            vcp_flag = "⭐" if r.vcp and r.vcp.detected else ""
            vol_ratio = r.vcp.volume_ratio if r.vcp else 0
            vol_pct = f"{vol_ratio*100:.0f}%" if vol_ratio else "N/A"
            price = r.price
            price_str = f"{price:,.2f}" if price >= 1 else f"{price:.4f}"
            lines.append(f"{r.symbol:<10} {price_str:>10} {tt_score}/8  {vcp_flag:<3} {vol_pct:>5}")
            if r.vcp and r.vcp.detected:
                vcp_setups.append(r.symbol)

        lines.append("</pre>")

        # Build inline keyboard for VCP symbols (REQ4)
        keyboard = []
        if vcp_setups:
            lines.append(f"\n🎯 <b>VCP Setups:</b> {', '.join(f'<code>{s}</code>' for s in vcp_setups)}")
            keyboard = [[
                {"text": f"👁 Analyze {sym}", "callback_data": f"analyze_{sym}"}
            ] for sym in vcp_setups]

        from notifier import sanitize_for_telegram_html
        text = sanitize_for_telegram_html("\n".join(lines))

        if keyboard:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(row[0]["text"], callback_data=row[0]["callback_data"])]
                for row in keyboard
            ])
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
        else:
            await update.message.reply_text(text, parse_mode="HTML")

    except Exception as e:
        log.error(f"cmd_scan_enhanced error: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Scan failed: {e}")



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
            import asyncio
            asyncio.create_task(_default_bus.emit_background(TradeApproved(
                signal_id=event.signal_id,
                symbol=event.symbol,
                action=event.action,
                price=event.price,
                quote_qty=event.quote_qty,
                sl=event.sl,
                tp=event.tp,
                approved_by=f"Human (@{user})",
                analysis_text=event.analysis_text
            )))
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
            PENDING_TRADES.pop(signal_id)
            user = query.from_user.username or query.from_user.first_name
            from notifier import sanitize_for_telegram_html
            safe_text = sanitize_for_telegram_html(query.message.text)
            new_text = safe_text + f"\n\n❌ <b>ĐÃ TỪ CHỐI BỞI @{user}</b>"
            await query.message.edit_text(new_text, parse_mode="HTML")
        else:
            from notifier import sanitize_for_telegram_html
            safe_text = sanitize_for_telegram_html(query.message.text)
            new_text = safe_text + "\n\n<i>(Lệnh đã hết hạn hoặc đã được xử lý)</i>"
            await query.message.edit_text(new_text, parse_mode="HTML")

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
        await query.message.reply_text("🌅 Đang chạy Morning Brief... Vui lòng chờ 30-60s.")
        await cmd_brief_inline(query.message)

    elif data.startswith("analyze_"):
        # REQ4: Inline Vision Pipeline Shortcut from /scan results
        symbol = data.split("_", 1)[1].upper()
        import re
        safe_symbol = re.sub(r'[^A-Za-z0-9_\-]', '', symbol)
        await query.message.reply_text(
            f"👁 Đang phân tích <code>{safe_symbol}</code>...",
            parse_mode="HTML",
        )
        try:
            import config
            from pathlib import Path
            screenshots_dir = Path(__file__).parent / "screenshots"
            screenshot_path = None

            if config.MCP_ENABLED:
                try:
                    from mcp_client import get_mcp_client
                    from datetime import datetime as dt
                    mcp = get_mcp_client()
                    health = await mcp.health_check()
                    if health.get("connected"):
                        screenshot_path = await mcp.capture_screenshot(
                            symbol=symbol,
                            timeframe="D",
                            region="chart",
                            save_path=screenshots_dir / f"vision_{safe_symbol}_{dt.now().strftime('%Y%m%d_%H%M%S')}.png",
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
            result = await analyze_chart_vision(image_path=Path(screenshot_path), symbol=symbol)
            if result.get("error"):
                await query.message.reply_text(f"❌ Vision error: {result['error']}")
                return

            from notifier import sanitize_for_telegram_html
            vision_text = format_vision_telegram(result)
            await query.message.reply_text(sanitize_for_telegram_html(vision_text), parse_mode="HTML")

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
    rag_status = "✅" if config.RAG_ENABLED and config.ANTHROPIC_API_KEY else "❌"
    mcp_status = "✅" if config.MCP_ENABLED else "❌"
    brief_status = "✅" if config.BRIEF_ENABLED else "❌"
    lines.append(f"🧠 RAG: {rag_status}  |  🖥️ MCP: {mcp_status}  |  ⏰ Brief: {brief_status}")

    try:
        from watchlist import get_watchlist
        wl = get_watchlist()
        lines.append(f"📋 Watchlist: {len(wl)} symbols")
    except Exception:
        pass

    from notifier import sanitize_for_telegram_html
    await message.reply_text(sanitize_for_telegram_html("\n".join(lines)), parse_mode="HTML")


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
        from watchlist import get_watchlist
        from analysis import scan_symbols
        import config

        symbols = get_watchlist()
        if not symbols:
            await message.reply_text("📋 Watchlist trống.")
            return

        mcp = None
        if config.MCP_ENABLED:
            try:
                from mcp_client import get_mcp_client
                mcp = get_mcp_client()
            except Exception:
                pass

        results = await scan_symbols(symbols, mcp)
        if results:
            summary = []
            for r in results:
                tt = r.trend_template.score if r.trend_template else "?"
                vcp = "⭐" if r.vcp and r.vcp.detected else ""
                summary.append(f"`{r.symbol}` TT:{tt}/8 {vcp}")
            from notifier import sanitize_for_telegram_html
            await message.reply_text(
                sanitize_for_telegram_html(f"📊 **Scan** ({len(results)} symbols):\n" + "\n".join(summary)),
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

from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict

@dataclass
class PositionSnapshot:
    """Tracked position state for change detection inside PositionMonitor."""
    symbol: str
    side: str
    entry_price: float
    quantity: float
    stop_loss_price: Optional[float]
    take_profit_price: Optional[float]
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
    exit_price: Optional[float]
    pnl: Optional[float]
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
    latency_ms: Optional[float]


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
    ) -> List[Tuple[int, int]]:
        """Send message to all TELEGRAM_CHAT_IDS.
        Returns list of (chat_id, message_id) tuples for later editing.
        """
        import config
        from notifier import sanitize_for_telegram_html
        results: List[Tuple[int, int]] = []
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
            log.warning(f"TelegramSender: edit_message failed ({chat_id}/{message_id}): {e}")
            return False

    async def send_typing_action(self, chat_id: int) -> None:
        """Send 'typing...' action indicator."""
        try:
            from telegram import ChatAction
            await self._app.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass


_sender: Optional[TelegramSender] = None


def get_sender() -> Optional[TelegramSender]:
    """Get the global TelegramSender singleton (None if bot not started)."""
    return _sender


# ── P8 ExchangeQueryFacade ─────────────────────────────────────────────────

class ExchangeQueryFacade:
    """Facade over ExchangeRegistry for read-only position/balance/health queries.

    Design Invariant: No component bypasses ExchangeRegistry to access adapters.
    """

    async def get_balance(
        self,
        exchange_id: Optional[str] = None,
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
                raise ValueError(f"Exchange '{exch_id}' not registered. Available: {available}")
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
        exchange_id: Optional[str] = None,
    ) -> List[PositionInfo]:
        """Get open positions from specified or all exchanges."""
        results: List[PositionInfo] = []
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
                    for p in (raw or []):
                        results.append(PositionInfo(
                            symbol=p.get("symbol", ""),
                            side=p.get("side", ""),
                            entry_price=float(p.get("entry_price", 0)),
                            current_price=float(p.get("current_price", 0)),
                            quantity=float(p.get("quantity", 0)),
                            unrealized_pnl=float(p.get("unrealized_pnl", 0)),
                            unrealized_pnl_pct=float(p.get("unrealized_pnl_pct", 0)),
                            exchange=eid,
                        ))
                except Exception as e:
                    log.warning(f"ExchangeQueryFacade: get_open_positions({eid}) failed: {e}")
        except ImportError:
            log.warning("ExchangeQueryFacade: ExchangeRegistry not available")
        return results

    async def get_exchange_health(self) -> List[ExchangeHealthInfo]:
        """Get health status of all registered exchanges."""
        results: List[ExchangeHealthInfo] = []
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
                    results.append(ExchangeHealthInfo(
                        exchange=eid,
                        healthy=bool(ok),
                        is_testnet=getattr(client, "testnet", False),
                        is_dry_run=getattr(client, "dry_run", True),
                        latency_ms=round(latency, 1),
                    ))
                except Exception as e:
                    results.append(ExchangeHealthInfo(
                        exchange=eid, healthy=False,
                        is_testnet=False, is_dry_run=True, latency_ms=None,
                    ))
        except ImportError:
            pass
        return results

    def list_available_exchanges(self) -> List[str]:
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
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> List[TradeRecord]:
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
                    async with db.execute("SELECT exchange FROM trades LIMIT 1") as _probe:
                        await _probe.fetchone()
                    has_exchange_col = True
                except Exception:
                    pass

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
                        exit_price=float(row["exit_price"]) if row["exit_price"] else None,
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

    async def get_daily_stats(self, date: Optional[str] = None) -> DailyStats:
        """Get aggregated performance stats for a given date (YYYY-MM-DD, default today UTC)."""
        from datetime import datetime as dt, timezone
        target = date or dt.now(timezone.utc).strftime("%Y-%m-%d")
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
                        date=target, total_trades=0, winning_trades=0,
                        losing_trades=0, win_rate=0.0, total_pnl=0.0,
                        best_trade=0.0, worst_trade=0.0,
                    )

                pnls = [float(r["pnl"]) for r in rows if r["pnl"] is not None]
                winners = [p for p in pnls if p > 0]
                losers  = [p for p in pnls if p <= 0]
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
                date=target, total_trades=0, winning_trades=0,
                losing_trades=0, win_rate=0.0, total_pnl=0.0,
                best_trade=0.0, worst_trade=0.0,
            )


_data_facade = DataQueryFacade()


# ── P8 TradeLifecycleHandler ───────────────────────────────────────────────

def _register_trade_lifecycle_handlers():
    """Register EventBus listeners for TradeExecuted, TradeFailed, PositionClosed.
    Called from start_bot() AFTER _sender is initialised.
    """
    from core.event_bus import bus as _bus
    from core.events import TradeExecuted, TradeFailed, PositionClosed

    @_bus.on(TradeExecuted)
    async def on_trade_executed(event: TradeExecuted) -> None:
        """REQ1 + REQ10: Push fill confirmation with exchange context."""
        sender = get_sender()
        if sender is None:
            return
        sl = f"{event.stop_loss_price:,.4f}" if event.stop_loss_price else "—"
        tp = f"{event.take_profit_price:,.4f}" if event.take_profit_price else "—"
        text = (
            f"✅ <b>LỆNH ĐÃ KHỚP</b>\n\n"
            f"🏦 Sàn: <code>{event.exchange.upper()}</code>\n"
            f"📌 Mã: <code>{event.symbol}</code>\n"
            f"📊 Chiều: <code>{event.side.upper()}</code>\n"
            f"💰 Giá khớp: <code>{event.executed_price:,.4f}</code>\n"
            f"📦 Khối lượng: <code>{event.executed_qty:,.4f}</code>\n"
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
        reason_map = {"STOP_LOSS": "🛡️ Stop-Loss", "TAKE_PROFIT": "🎯 Take-Profit", "MANUAL": "✋ Manual"}
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
        self._tracked: Dict[str, PositionSnapshot] = {}
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
                await _bus.emit(PositionClosed(
                    symbol=snap.symbol,
                    side=snap.side,
                    entry_price=snap.entry_price,
                    exit_price=0.0,  # not available without order history query
                    quantity=snap.quantity,
                    pnl=0.0,
                    pnl_pct=0.0,
                    exit_reason="UNKNOWN",
                    exchange=snap.exchange,
                ))
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
        self, exchange_id: Optional[str] = None
    ) -> List[PositionInfo]:
        return await _exchange_facade.get_open_positions(exchange_id)


_position_monitor: Optional[PositionMonitor] = None


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
        self._tracked: Dict[int, List[Tuple[int, int, float]]] = {}
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

    def track_message(
        self, signal_id: int, chat_id: int, message_id: int
    ) -> None:
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
            symbol = getattr(event, "symbol", f"Signal #{signal_id}") if event else f"Signal #{signal_id}"
            action = getattr(event, "action", "").upper() if event else ""
            elapsed_min = int(elapsed_sec // 60)

            log.warning(f"ApprovalTimeoutManager: signal #{signal_id} ({symbol}) timed out after {elapsed_min}m")

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
                    expired_suffix = "\n\n<i>⏰ Lệnh đã hết hạn — không thể duyệt/từ chối.</i>"
                    # Try to edit; swallow errors if message too old to edit
                    try:
                        await sender.edit_message(chat_id, message_id, f"<i>[HẾT HẠN]</i>{expired_suffix}")
                    except Exception:
                        pass
                await sender.send_message(timeout_text)

            del self._tracked[signal_id]


_approval_timeout_mgr: Optional[ApprovalTimeoutManager] = None


def get_approval_timeout_mgr() -> Optional[ApprovalTimeoutManager]:
    """Get the global ApprovalTimeoutManager singleton."""
    return _approval_timeout_mgr


# ── P9-B1: Daily Report Auto-Send Scheduler ───────────────────────────

async def _report_auto_send_loop() -> None:
    """Background loop that auto-sends the daily P&L report at REPORT_SEND_TIME (ICT).

    REQ8 AC4: Enabled via REPORT_AUTO_SEND=true, time via REPORT_SEND_TIME=HH:MM.
    ICT = UTC+7. Runs once per day at the configured wall-clock time.
    Singleton guard: task name 'report-auto-send' prevents duplicates on reload.
    """
    import config
    from datetime import timezone, timedelta
    from datetime import datetime as _dt

    ICT = timezone(timedelta(hours=7))
    log.info(f"📊 _report_auto_send_loop running (target={config.REPORT_SEND_TIME} ICT)")

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
        log.info(f"📊 ReportAutoSend: next send in {wait_seconds/3600:.1f}h ({target_today.strftime('%Y-%m-%d %H:%M')} ICT)")
        await asyncio.sleep(wait_seconds)

        # Send report for today (UTC date, which is ICT-1 day at 22:00)
        utc_date = _dt.now(timezone.utc).strftime("%Y-%m-%d")
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
        from auth.auth_config import AuthConfig
        from auth.service import AuthService
        import database as db
        import config

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
        if not dashboard_url.startswith("http://") and not dashboard_url.startswith("https://"):
            dashboard_url = f"http://{dashboard_url}"
            
        # ⚠️ BỘ LỌC CỦA TELEGRAM: Telegram tự động chặn KHÔNG CHO CLICK vào các link có chứa "localhost" hoặc "127.0.0.1".
        # Sử dụng Regex để thay thế linh hoạt mọi trường hợp localhost/127.0.0.1 thành 127.0.0.1.nip.io
        import re
        safe_dashboard_url = re.sub(r'(://)(localhost|127\.0\.0\.1)(:?\d*)', r'\g<1>127.0.0.1.nip.io\g<3>', dashboard_url, flags=re.IGNORECASE)
        
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
        await update.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
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
    global _bot_app, _bot_thread, _sender, _position_monitor, _approval_timeout_mgr

    import config
    if not config.TELEGRAM_BOT_TOKEN:
        log.warning("Telegram bot token not set — Telegram Bot disabled")
        return

    try:
        _get_imports()
    except ImportError:
        log.warning("python-telegram-bot not installed — run: pip install python-telegram-bot")
        return

    with _bot_thread_lock:
        # ── Singleton guard ────────────────────────────────────────────
        if _bot_thread is not None and _bot_thread.is_alive():
            log.info("🤖 Telegram Bot already running — skipping duplicate start (SCAR-TG-001)")
            return

        from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler

        def _run_bot():
            """Bot runner in separate thread with its own event loop."""
            global _bot_app, _sender, _position_monitor, _approval_timeout_mgr
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Build bot — force IPv4 to fix async httpx ConnectError on Windows
            from telegram.request import HTTPXRequest
            import httpx as _httpx

            _proxy = config.TELEGRAM_PROXY_URL or None
            request = HTTPXRequest(proxy=_proxy)
            # Inject IPv4-only transport (overrides default which allows IPv6)
            request._client_kwargs["transport"] = _httpx.AsyncHTTPTransport(
                local_address="0.0.0.0",
            )
            request._client = request._build_client()

            app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).request(request).build()
            log.info("🤖 Telegram Bot using IPv4-forced async transport (fix for Windows)")

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
                    log.warning("🤖 TG Conflict (409) — another instance terminated. Resuming...")
                elif isinstance(err, NetworkError):
                    log.warning(f"🤖 TG NetworkError: {err}")
                else:
                    log.error(f"🤖 TG Unhandled error: {err}", exc_info=err)

            app.add_error_handler(_on_error)

            # Register bot commands globally
            async def post_init(application):
                from telegram import BotCommand
                commands = [
                    BotCommand("start",     "Giới thiệu bot & Menu"),
                    BotCommand("help",      "Danh sách lệnh"),
                    BotCommand("status",    "Trạng thái hệ thống"),
                    BotCommand("scan",      "Scan watchlist (TT + VCP + 👁 Vision)"),
                    BotCommand("brief",     "Chạy Morning Brief"),
                    BotCommand("watchlist", "Xem watchlist"),
                    BotCommand("balance",   "Xem balance [EXCHANGE] [ASSET]"),
                    BotCommand("grade",     "Chấm điểm lệnh (Bar Replay)"),
                    BotCommand("positions", "Vị thế mở + Unrealized P&L"),
                    BotCommand("rag",       "Hỏi Minervini AI Knowledge Base"),
                    BotCommand("trades",    "Lịch sử giao dịch [N]"),
                    BotCommand("report",    "Báo cáo ngày [YYYY-MM-DD]"),
                    BotCommand("login",     "Đăng nhập Dashboard"),
                    BotCommand("logout",    "Huỷ phiên Dashboard"),
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
                    asyncio.create_task(
                        _report_auto_send_loop(), name="report-auto-send"
                    )
                    log.info(f"📊 ReportAutoSend scheduler started (time={config.REPORT_SEND_TIME} ICT)")
            
            app.post_init = post_init

            # Register command handlers
            app.add_handler(CommandHandler("start",     cmd_start))
            app.add_handler(CommandHandler("help",      cmd_help))
            app.add_handler(CommandHandler("status",    cmd_status))
            app.add_handler(CommandHandler("watchlist", cmd_watchlist))
            app.add_handler(CommandHandler("add",       cmd_add))
            app.add_handler(CommandHandler("remove",    cmd_remove))
            app.add_handler(CommandHandler("scan",      cmd_scan_enhanced))  # P8: replaces cmd_scan
            app.add_handler(CommandHandler("brief",     cmd_brief))
            app.add_handler(CommandHandler("vision",    cmd_vision))
            app.add_handler(CommandHandler("grade",     cmd_grade))
            app.add_handler(CommandHandler("balance",   cmd_balance_enhanced))  # P8: replaces cmd_balance
            # ── P8 new commands ──────────────────────────────────────
            app.add_handler(CommandHandler("positions", cmd_positions))
            app.add_handler(CommandHandler("rag",       cmd_rag))
            app.add_handler(CommandHandler("trades",    cmd_trades))
            app.add_handler(CommandHandler("report",    cmd_report))
            # ── P10: Dashboard auth commands ─────────────────────────────
            app.add_handler(CommandHandler("login",     cmd_login))
            app.add_handler(CommandHandler("logout",    cmd_logout))

            from telegram.ext import MessageHandler, filters
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text))

            app.add_handler(CallbackQueryHandler(button_callback))

            _bot_app = app
            log.info("🤖 Telegram Bot started (polling mode)")
            app.run_polling(drop_pending_updates=True, close_loop=False)

        _bot_thread = threading.Thread(target=_run_bot, daemon=True, name="telegram-bot")
        _bot_thread.start()
        log.info("🤖 Telegram Bot thread launched")


def stop_bot():
    """Stop Telegram bot gracefully."""
    global _bot_app, _bot_thread
    if _bot_app is not None:
        log.info("🤖 Telegram Bot stopping...")
        try:
            # stop_running() signals run_polling() to exit
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_bot_app.updater.stop())
            loop.run_until_complete(_bot_app.stop())
            loop.close()
        except Exception as e:
            log.warning(f"🤖 Bot stop error (non-fatal): {e}")
        _bot_app = None
    _bot_thread = None
