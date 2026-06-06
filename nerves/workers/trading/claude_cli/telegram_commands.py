"""
telegram_commands.py — TelegramInterface for Claude CLI integration.

Registers /claude, /analyze, /claude_reset, /claude_status commands.

Design invariants (Interface Layer):
- Stateless: never mutates context directly. All state changes go through ClaudeService.
- Only depends on ClaudeService (never on CliInfrastructure directly).
- Truncates all responses at 4096 chars (Property 7).
- All commands guarded by CLAUDE_CLI_ENABLED feature flag (Property 8).

Usage (from telegram_bot.py setup):
    from claude_cli import telegram_commands
    telegram_commands.register_commands(application, claude_service)
"""

import logging
from typing import TYPE_CHECKING, Optional

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

import config

from .service import AnalysisRequest, ClaudeService

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# Maximum Telegram message length
_MAX_TELEGRAM_CHARS = 4096

# Singleton reference injected at register time
_service: ClaudeService | None = None


# ─── Command handlers ──────────────────────────────────────────────────────────


async def cmd_claude(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/claude <query> — Ad-hoc Claude query with optional [SYMBOL] prefix."""
    if not _service:
        await update.effective_message.reply_text("⚠️ Claude service not initialized.")
        return

    args = context.args or []
    if not args:
        await update.effective_message.reply_text(
            "📖 <b>Usage:</b> /claude &lt;query&gt;\n"
            "Example: /claude Giải thích VCP pattern cho BTCUSDT",
            parse_mode="HTML",
        )
        return

    # Optional leading symbol token: /claude BTCUSDT Is this a VCP?
    symbol = ""
    query_parts = list(args)
    if query_parts and query_parts[0].isupper() and len(query_parts[0]) >= 3:
        symbol = query_parts[0].upper()
        query_parts = query_parts[1:]

    query = " ".join(query_parts).strip()
    if not query:
        query = symbol
        symbol = ""

    await update.effective_message.reply_text("🔄 Đang phân tích, vui lòng chờ…")

    trading_ctx = _gather_trading_context(symbol)
    resp = await _service.analyze(
        AnalysisRequest(
            query=query,
            symbol=symbol,
            trading_context=trading_ctx,
            include_rag_context=True,
        )
    )

    text = _format_response(
        resp.text, resp.source, resp.confidence, resp.duration_seconds
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/analyze <SYMBOL> — Comprehensive SEPA analysis for a trading symbol."""
    if not _service:
        await update.effective_message.reply_text("⚠️ Claude service not initialized.")
        return

    args = context.args or []
    if not args:
        await update.effective_message.reply_text(
            "📖 <b>Usage:</b> /analyze &lt;SYMBOL&gt;\nExample: /analyze BTCUSDT",
            parse_mode="HTML",
        )
        return

    symbol = args[0].upper()
    query = (
        f"Phân tích toàn diện {symbol} theo tiêu chí SEPA Minervini: "
        "Trend Template, VCP setup, volume confirmation, và khuyến nghị hành động."
    )

    await update.effective_message.reply_text(
        f"🔬 Đang phân tích <b>{symbol}</b>…", parse_mode="HTML"
    )

    trading_ctx = _gather_trading_context(symbol)
    resp = await _service.analyze(
        AnalysisRequest(
            query=query,
            symbol=symbol,
            action="analyze",
            trading_context=trading_ctx,
            include_rag_context=True,
        )
    )

    text = _format_response(
        resp.text, resp.source, resp.confidence, resp.duration_seconds
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def cmd_claude_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/claude_reset [SYMBOL] — Clear conversation context for a symbol or all."""
    if not _service:
        await update.effective_message.reply_text("⚠️ Claude service not initialized.")
        return

    args = context.args or []
    symbol = args[0].upper() if args else ""
    _service.reset_context(symbol)

    if symbol:
        await update.effective_message.reply_text(
            f"🗑️ Đã xóa context hội thoại cho <b>{symbol}</b>.", parse_mode="HTML"
        )
    else:
        await update.effective_message.reply_text("🗑️ Đã xóa toàn bộ context hội thoại.")


async def cmd_claude_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/claude_status — Show SDK availability and current context stats."""
    sdk_available = False
    sdk_stats: dict = {}

    if _service:
        sdk = getattr(_service, "_sdk", None)
        if sdk is not None:
            sdk_available = sdk.available
            sdk_stats = sdk.get_stats()
        ctx_stats = _service.get_context_stats()
    else:
        ctx_stats = {"total_symbols": 0, "total_turns": 0, "total_estimated_tokens": 0}

    status_icon = "✅" if sdk_available else "❌"
    provider = getattr(config, "AI_PROVIDER", "anthropic")

    lines = [
        "<b>🤖 Claude SDK Status</b>",
        "",
        f"SDK Client: {status_icon} {'Available' if sdk_available else 'Unavailable'}",
        f"AI Provider: <code>{provider}</code>",
        "",
        "<b>📊 Context Stats</b>",
        f"Active symbols: {ctx_stats.get('total_symbols', 0)}",
        f"Total turns: {ctx_stats.get('total_turns', 0)}",
        f"Est. tokens: {ctx_stats.get('total_estimated_tokens', 0):,}",
    ]

    if sdk_stats:
        lines += [
            "",
            "<b>⚙️ Rate Limit</b>",
            f"Requests in window: {sdk_stats.get('requests_in_window', 0)}/{sdk_stats.get('rate_limit', 10)}",
            f"Timeout: {sdk_stats.get('timeout_seconds', 120)}s",
            f"Max parallel: {sdk_stats.get('max_parallel', 2)}",
            f"Model: <code>{sdk_stats.get('model', '(default)')}</code>",
        ]

    # Per-symbol breakdown
    symbol_data = ctx_stats.get("symbols", {})
    if symbol_data:
        lines.append("\n<b>💾 Per-Symbol</b>")
        for sym, info in symbol_data.items():
            lines.append(
                f"• {sym}: {info['turns']} turns ({info['estimated_tokens']:,} tok)"
            )

    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")


# ─── Registration ──────────────────────────────────────────────────────────────


def register_commands(application, claude_service: ClaudeService) -> None:
    """
    Register all Claude CLI Telegram commands.
    Must only be called if CLAUDE_CLI_ENABLED=True (Property 8).

    Args:
        application: The python-telegram-bot Application instance.
        claude_service: Initialized ClaudeService singleton.
    """
    global _service
    _service = claude_service

    application.add_handler(CommandHandler("claude", cmd_claude))
    application.add_handler(CommandHandler("analyze", cmd_analyze))
    application.add_handler(CommandHandler("claude_reset", cmd_claude_reset))
    application.add_handler(CommandHandler("claude_status", cmd_claude_status))

    log.info(
        "Claude CLI Telegram commands registered: "
        "/claude, /analyze, /claude_reset, /claude_status"
    )


# ─── Formatting helpers ────────────────────────────────────────────────────────


def _format_response(text: str, source: str, confidence: int, duration: float) -> str:
    """
    Format analysis response for Telegram HTML.
    Property 7: never exceeds 4096 characters.
    """
    source_label = {
        "anthropic_api": "🔵 Anthropic SDK",
        "none": "🔴 Unavailable",
    }.get(source, source)

    conf_bar = "⭐" * max(0, min(10, confidence)) + "☆" * (
        10 - max(0, min(10, confidence))
    )
    header = (
        f"<b>🤖 AI Analysis</b> | {source_label}\n"
        f"Confidence: {conf_bar} ({confidence}/10) | {duration:.1f}s\n"
        f"{'─' * 30}\n"
    )

    max_body = _MAX_TELEGRAM_CHARS - len(header) - 20  # 20 chars safety buffer
    if len(text) > max_body:
        text = text[:max_body] + "\n<i>… (truncated)</i>"

    return header + text


def _gather_trading_context(symbol: str = "") -> dict:
    """
    Collect basic trading context to inject into prompt.
    Non-fatal — returns empty dict on any error.
    """
    ctx: dict = {}
    try:
        if symbol:
            ctx["symbol"] = symbol
        ctx["ai_provider"] = getattr(config, "AI_PROVIDER", "unknown")
        ctx["environment"] = getattr(config, "ENVIRONMENT", "development")
    except ValueError as e:
        import logging

        logging.getLogger(__name__).warning("Ignored: %s", e)
    return ctx
