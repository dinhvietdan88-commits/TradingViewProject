"""
WebhookGateway — HTTP ingress for TradingView webhook signals.

Component 8/8 in the Event-Driven architecture.

Responsibilities:
1. Parse JSON payload from TradingView
2. Authenticate (secret check + dashboard bypass)
3. Rate limiting (15 req/min per IP)
4. Safe price/qty parsing (TVP-001, TVP-002)
5. Insert signal to DB
6. RAG analysis (if enabled)
7. Dispatch via EventBus → SignalReceived

Does NOT own:
- IP whitelist middleware (stays in main.py, applies to all routes)
- Dashboard auth middleware (stays in main.py, applies to all routes)
- Trade execution (TradeEngine)
- Vision analysis (AIAnalyzer)
- Notifications (NotificationHub)
"""
import logging
import time
import secrets

from fastapi import APIRouter, Request, HTTPException

import config
import database

from core.event_bus import bus as _event_bus
from core.events import SignalReceived, IndicatorSignalReceived
from data.tv_models import TradingViewAlertPayload

log = logging.getLogger(__name__)

router = APIRouter()

# ── Rate Limiting State ──────────────────────────────────────────────────────
_WEBHOOK_RATE_LIMITS: dict = {}

# ═══ WEBHOOK ENDPOINT ═════════════════════════════════════════════════════════
@router.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Xac thuc bao mat
    # BUG-06 fix: Use .get() instead of .pop() — do NOT mutate payload before the
    # empty-payload check below. Removing the only key ("secret") would leave
    # payload={} and trigger a misleading 400 Empty payload instead of a
    # proper 400 for missing signal fields.
    secret = (
        request.headers.get("X-TV-Secret")
        or request.query_params.get("secret")
        or payload.get("secret", None)
        or ""
    )
    # Strip secret from payload after auth so it isn't stored in DB
    payload.pop("secret", None)

    # Allow dashboard users (authenticated via DASHBOARD_TOKEN) to bypass webhook secret
    dashboard_auth = request.headers.get("Authorization", "")
    is_dashboard_user = (
        config.DASHBOARD_TOKEN
        and dashboard_auth.startswith("Bearer ")
        and secrets.compare_digest(dashboard_auth[7:], config.DASHBOARD_TOKEN)
    )

    if not is_dashboard_user and not secrets.compare_digest(
        str(secret), str(config.WEBHOOK_SECRET)
    ):
        log.warning("Unauthorized webhook attempt (secret mismatch)")
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not payload:
        raise HTTPException(status_code=400, detail="Empty payload")

    # Parse with Pydantic for validation and structured access
    try:
        tv_alert = TradingViewAlertPayload.model_validate(payload)
    except Exception as e:
        log.warning(f"Pydantic validation error: {e}")
        # Fallback to empty model to not break completely
        tv_alert = TradingViewAlertPayload()

    action = (tv_alert.action or "").lower()
    symbol = tv_alert.symbol or ""
    if ":" in symbol:
        symbol = symbol.split(":")[-1]
    price = tv_alert.price
    ts = tv_alert.time or ""
    quote_qty = tv_alert.quoteQty
    interval = str(tv_alert.interval or "").strip().lower()
    mode = (getattr(tv_alert, "mode", None) or payload.get("mode", "") or "").strip().upper()

    sl_str = tv_alert.sl or ""
    tp_str = tv_alert.tp or ""

    # Keep default exchange handling from payload
    exchange = tv_alert.exchange or config.DEFAULT_EXCHANGE
    payload["exchange"] = exchange

    # Source IP — SEC-001 fix: use rightmost XFF hop (set by trusted proxy, not spoofable)
    source_ip = request.client.host
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        source_ip = forwarded.split(",")[-1].strip()

    # TVP-004: Basic Rate Limiting
    now = time.time()
    count, first_req = _WEBHOOK_RATE_LIMITS.get(source_ip, (0, now))
    if now - first_req < 60:
        if count >= 15:
            log.warning(f"Rate limit exceeded for {source_ip}")
            raise HTTPException(status_code=429, detail="Too Many Requests")
        _WEBHOOK_RATE_LIMITS[source_ip] = (count + 1, first_req)
    else:
        _WEBHOOK_RATE_LIMITS[source_ip] = (1, now)

    # TVP-001 & TVP-002: Safe parsing and Max limits
    try:
        price_float = float(str(price).replace(',', '')) if price else None
    except (ValueError, TypeError):
        price_float = None

    try:
        quote_qty_val = float(quote_qty) if quote_qty else 10.0
        quote_qty_val = min(quote_qty_val, config.MAX_QUOTE_QTY)
    except (ValueError, TypeError):
        quote_qty_val = 10.0

    source = payload.get("source", "")
    indicator_name = payload.get("indicator_name", "") or payload.get("indicator", "") or ""
    is_indicator = source == "indicator" or (
        indicator_name and action not in {"buy", "sell", "alert"}
    )

    # Guard before DB write (Prop 4): invalid indicator payloads must not persist
    if is_indicator:
        if not symbol:
            raise HTTPException(status_code=400, detail="Missing required field: symbol")
        if not indicator_name:
            raise HTTPException(status_code=400, detail="Missing required field: indicator_name")

    # Luu signal vao database
    signal_id = await database.insert_signal(
        symbol=symbol,
        action=action,
        price=price_float,
        quote_qty=quote_qty_val,
        source_ip=source_ip,
        payload=payload,
        mode=mode,
    )

    log.info(f"ALERT #{signal_id}  action={action}  symbol={symbol}  price={price}  qty={quote_qty_val}  time={ts}")

    # ── Angati Event-Driven Semantic Ingestion ────────────────────────────────
    try:
        from nerves.core.ingest_helper import ingest_semantic_event_bg
        ingest_semantic_event_bg(
            text=f"Signal Received: ID={signal_id}, Symbol={symbol}, Action={action}, "
                 f"Price={price_float}, Qty={quote_qty_val}, Exchange={exchange}, Interval={interval}",
            category="signal"
        )
    except Exception as sra_err:
        log.warning(f"SRA Ingestion warning: {sra_err}")


    # ── RAG Analysis (chuyển sang AIAnalyzer) ─────────────
    # WebhookGateway không gọi RAG đồng bộ để đảm bảo tốc độ phản hồi < 100ms

    # ══════════════════════════════════════════════════════════════════════
    # EventBus Dispatch
    # Gateway chỉ làm nhiệm vụ phát (emit) sự kiện, mọi business logic xử lý
    # action, config, và fallback đều được đẩy xuống downstream.
    # ══════════════════════════════════════════════════════════════════════

    if is_indicator:
        signal_type = payload.get("signal_type", "info")
        
        try:
            conf_score = int(payload.get("confidence_score", 0))
        except (ValueError, TypeError):
            conf_score = 0
            
        raw_conditions = payload.get("conditions_met", [])
        if isinstance(raw_conditions, list):
            conditions_met = tuple(str(c) for c in raw_conditions)
        else:
            conditions_met = ()
            
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        # Persistence is handled by data.indicator_persistence (DI-1: parallel listener)
        await _event_bus.emit_background(IndicatorSignalReceived(
            signal_id=signal_id,
            symbol=symbol,
            indicator_name=indicator_name,
            signal_type=signal_type,
            interval=interval,
            price=price_float,
            conditions_met=conditions_met,
            confidence_score=conf_score,
            metadata=metadata,
            source_ip=source_ip,
            exchange=exchange,
        ))

        # ── Push real-time SSE to all browser tabs ──────────────────────────
        try:
            import main as _main_mod
            _main_mod.push_sse_event("new_signal", {
                "signal_id":       signal_id,
                "symbol":          symbol,
                "indicator_name":  indicator_name,
                "signal_type":     signal_type,
                "price":           price_float,
                "confidence_score": conf_score,
                "exchange":        exchange,
                "interval":        interval,
            })
        except Exception as _sse_err:
            log.debug(f"SSE push skipped: {_sse_err}")

    else:
        await _event_bus.emit_background(SignalReceived(
            signal_id=signal_id,
            symbol=symbol,
            action=action,
            price=price_float,
            quote_qty=quote_qty_val,
            interval=interval,
            mode=mode,
            sl=sl_str,
            tp=tp_str,
            source_ip=source_ip,
            payload=payload,
            exchange=payload.get("exchange", config.DEFAULT_EXCHANGE),
        ))

    return {"received": True, "signal_id": signal_id, "status": "dispatched"}
