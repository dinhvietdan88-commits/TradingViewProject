"""
execution_server.py — Lightweight Execution Server for SERVER B (Execution Vault).

Receives pre-analyzed trade payloads from SERVER C via POST /api/execute-trade,
validates the X-Server-B-Secret header, executes trades via TradeEngine,
and returns results.

Runs on Tailscale VPN only (not exposed to WAN).
"""

import hmac
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# Ensure server/ is in path for imports
sys.path.insert(0, str(Path(__file__).parent))

import config
import database

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and exchange registry on startup."""
    await database.init_db()
    from exchanges.registry import init_registry

    init_registry()
    from exchanges.health_monitor import start_health_monitor

    start_health_monitor()
    if config.TELEGRAM_BOT_ENABLED:
        import telegram_bot

        telegram_bot.start_bot()
    log.info("Execution Server started. Listening for trade commands.")
    yield
    if config.TELEGRAM_BOT_ENABLED:
        import telegram_bot

        telegram_bot.stop_bot()
    from exchanges.health_monitor import stop_health_monitor

    stop_health_monitor()
    log.info("Execution Server shutting down.")


app = FastAPI(
    title="TradingView Bot — Execution Server",
    description="SERVER B: Receives approved trades from SERVER C and executes on exchanges.",
    lifespan=lifespan,
)


def _validate_secret(request: Request) -> None:
    """Validate X-Server-B-Secret header using constant-time comparison."""
    expected = config.SERVER_B_SECRET
    if not expected:
        raise HTTPException(status_code=500, detail="SERVER_B_SECRET not configured")

    provided = request.headers.get("X-Server-B-Secret", "")
    # Decoded by ASGI servers like uvicorn using latin-1. We encode it back to
    # latin-1 to retrieve original bytes, then compare against UTF-8 expected secret.
    if not hmac.compare_digest(provided.encode("latin-1"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _parse_trade_params(body: dict) -> dict:
    """Extract and sanitize trade parameters from body."""

    def safe_float(val, default=None):
        if val is None or val == "":
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    qty = safe_float(body.get("qty"))
    price = safe_float(body.get("price"))
    quote_qty = safe_float(body.get("quote_qty"))

    if quote_qty is None and qty is not None and price is not None:
        quote_qty = qty * price

    if quote_qty is None:
        quote_qty = 10.0

    return {
        "qty": qty,
        "price": price,
        "quote_qty": quote_qty,
        "sl": body.get("sl", ""),
        "tp": body.get("tp", ""),
        "exchange": body.get("exchange", config.DEFAULT_EXCHANGE),
        "analysis_text": body.get("analysis_text") or body.get("analysis", ""),
        "combined_score": str(body.get("combined_score"))
        if body.get("combined_score") is not None
        else None,
    }


def _resolve_confidence(body: dict) -> int:
    """Resolve and validate confidence score."""
    has_confidence = "ai_confidence" in body or "confidence" in body
    confidence_val = body.get("ai_confidence")
    if confidence_val is None:
        confidence_val = body.get("confidence")

    confidence = 0
    if has_confidence and confidence_val is not None:
        try:
            confidence = int(confidence_val)
        except (ValueError, TypeError):
            confidence = 0
    return confidence


def _calculate_sl_tp_pct(price: float | None, sl: str, tp: str) -> tuple[str, str]:
    """Calculate stop loss and take profit percentages relative to entry price."""
    sl_pct = "N/A"
    tp_pct = "N/A"
    if not price or not isinstance(price, (int, float)):
        return sl_pct, tp_pct
    try:
        if sl and float(sl) > 0:
            sl_pct = f"{((float(sl) - price) / price) * 100:+.1f}"
    except (ValueError, TypeError):
        pass
    try:
        if tp and float(tp) > 0:
            tp_pct = f"{((float(tp) - price) / price) * 100:+.1f}"
    except (ValueError, TypeError):
        pass
    return sl_pct, tp_pct


def _format_price_val(price: float | None) -> str:
    """Format price to string representation."""
    if price and isinstance(price, (int, float)):
        return f"{price:,.2f}"
    return price or "Market"


async def _handle_pending_approval(
    request: Request,
    body: dict,
    signal_id: int,
    symbol: str,
    action: str,
    price: float | None,
    quote_qty: float,
    sl: str,
    tp: str,
    exchange: str,
    confidence: int,
    analysis_text: str,
):
    """Handle interactive approval path for confidence 50-79 or hold_for_approval."""
    import hub.notification_hub as notification_hub
    import telegram_bot
    from core.events import AnalysisComplete
    from utils.telegram_templates import render_template

    # 1. Create AnalysisComplete event
    event = AnalysisComplete(
        signal_id=signal_id,
        symbol=symbol,
        action=action,
        price=price,
        quote_qty=quote_qty,
        sl=str(sl),
        tp=str(tp),
        exchange=exchange,
        confidence=confidence,
        analysis_text=analysis_text,
        should_trade=True,
        interactive_required=True,
    )

    # 2. Save event to PENDING_TRADES
    notification_hub.PENDING_TRADES[signal_id] = event

    # 3. Render message template
    symbol_val = symbol
    action_val = action.upper()
    price_val = _format_price_val(price)

    vcp_status = body.get("vcp_status", "N/A")
    tt_score = str(body.get("trend_template_score", body.get("tt_score", "N/A")))
    volume_ratio = str(body.get("volume_ratio", "N/A"))
    timeframe = body.get("timeframe", body.get("interval", "1D"))

    sl_val = sl or "N/A"
    tp_val = tp or "N/A"
    sl_pct, tp_pct = _calculate_sl_tp_pct(price, sl, tp)

    msg_text = render_template(
        "A",
        symbol=symbol_val,
        action=action_val,
        price=price_val,
        timeframe=timeframe,
        tt_score=tt_score,
        stage="N/A",
        vcp_status=vcp_status,
        volume_ratio=volume_ratio,
        ai_provider="Claude RAG",
        ai_advice=analysis_text[:800],
        stop_loss=sl_val,
        sl_pct=sl_pct,
        take_profit=tp_val,
        tp_pct=tp_pct,
    )

    # Send interactive trade approval message
    sent_pairs = await telegram_bot.send_interactive_trade_approval(
        signal_id=signal_id,
        message=msg_text,
    )
    if sent_pairs and isinstance(sent_pairs, list):
        timeout_mgr = telegram_bot.get_approval_timeout_mgr()
        if timeout_mgr:
            for chat_id, message_id in sent_pairs:
                timeout_mgr.track_message(signal_id, chat_id, message_id)

    return JSONResponse(
        {
            "success": True,
            "status": "pending_approval",
            "signal_id": signal_id,
        }
    )


async def _execute_immediate_trade(
    signal_id: int,
    symbol: str,
    action: str,
    price: float | None,
    quote_qty: float,
    sl: str,
    tp: str,
    exchange: str,
    analysis_text: str,
    combined_score: str | None,
) -> JSONResponse:
    """Execute immediate trade through TradeEngine."""
    import asyncio
    from core.event_bus import EventBus
    from core.events import (
        TradeApproved,
        TradeExecuted,
        TradeFailed,
        TradeApprovalTimeout,
    )
    from engine import trade_engine

    exec_bus = EventBus()
    result_holder = {}
    execution_done = asyncio.Event()

    @exec_bus.on(TradeExecuted)
    async def on_executed(event: TradeExecuted):
        result_holder["success"] = True
        result_holder["order_id"] = event.order_id
        result_holder["fill_price"] = event.executed_price
        result_holder["status"] = event.status
        result_holder["executed_qty"] = event.executed_qty
        execution_done.set()

    @exec_bus.on(TradeFailed)
    async def on_failed(event: TradeFailed):
        result_holder["success"] = False
        result_holder["error"] = event.error
        execution_done.set()

    @exec_bus.on(TradeApprovalTimeout)
    async def on_timeout(event: TradeApprovalTimeout):
        result_holder["success"] = False
        result_holder["error"] = f"Approval timeout: {event.reason}"
        execution_done.set()

    if config.TELEGRAM_BOT_ENABLED:

        @exec_bus.on(TradeExecuted)
        async def forward_executed(event: TradeExecuted):
            from core.event_bus import bus as _default_bus

            await _default_bus.emit(event)

        @exec_bus.on(TradeFailed)
        async def forward_failed(event: TradeFailed):
            from core.event_bus import bus as _default_bus

            await _default_bus.emit(event)

    original_bus = trade_engine.get_bus()
    trade_engine.set_bus(exec_bus)

    try:
        approved = TradeApproved(
            signal_id=signal_id,
            symbol=symbol,
            action=action,
            price=price,
            quote_qty=quote_qty,
            sl=str(sl),
            tp=str(tp),
            exchange=exchange,
            approved_by="ServerC-Analyzer",
            analysis_text=analysis_text,
            combined_score=combined_score,
        )
        await trade_engine.execute_trade(approved)
        await execution_done.wait()
    finally:
        trade_engine.set_bus(original_bus)

    if result_holder.get("success"):
        try:
            from notifier import notify_all

            msg = (
                f"✅ **Pipeline Trade Executed on {config.EXECUTION_TARGET_NAME}**\n"
                f"- Symbol: `{symbol}`\n"
                f"- Action: `{action.upper()}`\n"
                f"- Order ID: `{result_holder.get('order_id', 'N/A')}`\n"
                f"- Fill Price: `{result_holder.get('fill_price', 'N/A')}`\n"
                f"- Status: `{result_holder.get('status', 'N/A')}`"
            )
            await notify_all(msg)
        except Exception as e:
            log.warning(f"Telegram notification failed: {e}")

        return JSONResponse(
            {
                "success": True,
                "order_id": result_holder.get("order_id"),
                "fill_price": result_holder.get("fill_price"),
                "status": result_holder.get("status"),
                "executed_qty": result_holder.get("executed_qty"),
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": result_holder.get("error", "Trade execution failed"),
            },
        )


@app.post("/api/execute-trade")
async def execute_trade(request: Request):
    """Execute a pre-analyzed trade from SERVER C."""
    _validate_secret(request)
    body = await request.json()

    # Validate required fields
    symbol = body.get("symbol")
    action = body.get("action")
    if not symbol or not action:
        raise HTTPException(
            status_code=400, detail="Missing required fields: symbol, action"
        )

    # Parse parameters
    params = _parse_trade_params(body)
    price = params["price"]
    quote_qty = params["quote_qty"]
    sl = params["sl"]
    tp = params["tp"]
    exchange = params["exchange"]
    analysis_text = params["analysis_text"]
    combined_score = params["combined_score"]

    confidence = _resolve_confidence(body)
    if "ai_confidence" in body or "confidence" in body:
        if confidence < 50:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "status": "auto_rejected",
                    "error": f"Auto-rejected: confidence score {confidence} is below minimum threshold 50",
                },
            )

    # Save signal to DB
    signal_id = await database.insert_signal(
        symbol=symbol,
        action=action,
        price=price,
        quote_qty=quote_qty,
        source_ip=request.client.host if request.client else "127.0.0.1",
        payload=body,
    )

    hold_for_approval = body.get("hold_for_approval")
    is_holding = (hold_for_approval is True) or (50 <= confidence <= 79)

    try:
        if is_holding:
            return await _handle_pending_approval(
                request=request,
                body=body,
                signal_id=signal_id,
                symbol=symbol,
                action=action,
                price=price,
                quote_qty=quote_qty,
                sl=sl,
                tp=tp,
                exchange=exchange,
                confidence=confidence,
                analysis_text=analysis_text,
            )
        else:
            return await _execute_immediate_trade(
                signal_id=signal_id,
                symbol=symbol,
                action=action,
                price=price,
                quote_qty=quote_qty,
                sl=sl,
                tp=tp,
                exchange=exchange,
                analysis_text=analysis_text,
                combined_score=combined_score,
            )
    except HTTPException:
        raise
    except Exception as e:
        log.exception(f"Execute trade error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "Internal server error during trade execution",
            },
        )


@app.get("/health")
async def health():
    return {"status": "ok", "server": "execution-vault-b"}
