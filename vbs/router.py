import asyncio
import logging
import platform
import secrets
import time
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Header, HTTPException, Query, status, Request, Body

import config
import database
import models
import notifier

log = logging.getLogger(__name__)
router = APIRouter()

# Server start time for health check uptime
_START_TIME = time.time()

# ── Long Polling: In-memory event for waking blocked consumers ──────────────
# When a new signal is ingested, _new_signal_event.set() is called to
# immediately unblock any /consume-long request that is currently waiting.
_new_signal_event: asyncio.Event = asyncio.Event()

def verify_buffer_secret(x_buffer_secret: str = Header(None, alias="X-Buffer-Secret"), secret_query: Optional[str] = Query(None, alias="secret")):
    """Verify buffer secret via header or query parameter."""
    if not config.BUFFER_SECRET:
        return
        
    actual_secret = x_buffer_secret or secret_query
    if not actual_secret or not secrets.compare_digest(str(actual_secret), str(config.BUFFER_SECRET)):
        log.warning("VBS: Unauthorized attempt (secret mismatch)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Secret mismatch"
        )

@router.post("/ingest", response_model=models.IngestResponse)
async def ingest_signal(request: Request, x_buffer_secret: Optional[str] = Header(None, alias="X-Buffer-Secret")):
    """
    Ingest endpoint to receive webhook signals from TradingView.
    Supports secret verification via header, query param, or JSON body.
    """
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Resolve secret from header, query param, or JSON body
    secret = (
        x_buffer_secret 
        or request.query_params.get("secret") 
        or payload.get("secret")
    )
    
    if config.BUFFER_SECRET:
        if not secret or not secrets.compare_digest(str(secret), str(config.BUFFER_SECRET)):
            log.warning("VBS Ingest: Unauthorized webhook attempt (secret mismatch)")
            raise HTTPException(status_code=401, detail="Unauthorized")

    # Remove secret from payload before database persistence
    payload.pop("secret", None)

    # ── Dedup check: reject same (symbol, action) within DEDUP_WINDOW_SECONDS ──
    symbol = payload.get("symbol", "UNKNOWN")
    if ":" in symbol:
        symbol = symbol.split(":")[-1]
    action = payload.get("action") or payload.get("side") or "alert"
    price = payload.get("price")
    try:
        price_float = float(str(price).replace(",", "")) if price else 0.0
    except (ValueError, TypeError):
        price_float = 0.0

    existing_id = await database.check_duplicate(
        symbol, action, price_float, config.DEDUP_WINDOW_SECONDS
    )
    if existing_id is not None:
        exchange = (payload.get("exchange") or "binance").upper()
        log.info(
            f"VBS Dedup: {symbol} {action} @ {price} is duplicate of #{existing_id} "
            f"(within {config.DEDUP_WINDOW_SECONDS}s window)"
        )
        return {
            "queued": False,
            "duplicate_of": existing_id,
            "status": "DUPLICATE"
        }

    # Insert signal
    queue_id, expires_at = await database.insert_signal(payload)
    
    # Notify Telegram asynchronously
    exchange = (payload.get("exchange") or "binance").upper()
    
    msg = (
        f"📥 <b>VBS Signal Queued</b>\n"
        f"Queue ID: #{queue_id}\n"
        f"Symbol: <b>{symbol}</b>\n"
        f"Action: <b>{action.upper()}</b>\n"
        f"Exchange: {exchange}\n"
        f"Expires: {expires_at}"
    )
    
    # [SCAR] Lược bỏ nút Approve/Cancel ở VBS để nhường quyền xử lý cho Server B (TradeEngine).
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "📈 Xem Chart", "url": f"https://www.tradingview.com/chart/?symbol={exchange}:{symbol}"}
            ]
        ]
    }
    
    # Gửi thông báo ẩn (Silent) để không làm phiền người dùng trước khi Server B gửi thông báo phân tích AI.
    sent_msgs = await notifier.send_telegram_alert(msg, reply_markup=reply_markup, silent=True)
    if sent_msgs:
        await database.update_signal_payload(queue_id, {"tg_messages": sent_msgs})

    # ── V2: Wake up any Long Poll waiters ──
    # Set the event so /consume-long endpoints waiting for a new signal
    # are unblocked immediately instead of waiting out the full timeout.
    # Woken up only after the VBS Telegram message coordinates are persisted.
    _new_signal_event.set()

    return {
        "queued": True,
        "queue_id": queue_id,
        "expires_at": expires_at,
        "status": "PENDING"
    }


@router.get("/consume-long")
async def consume_long_poll(
    consumer_id: str = Query(..., description="Unique client worker identifier"),
    limit: int = Query(10, ge=1, le=100),
    timeout: int = Query(30, ge=5, le=60),
    source: Optional[str] = Query(None, description="Include only signals from this source"),
    exclude_source: Optional[str] = Query(None, description="Exclude signals from this source"),
    x_buffer_secret: Optional[str] = Header(None, alias="X-Buffer-Secret"),
):
    """
    Long Polling endpoint — SERVER C's VpsAnalyzerWorker calls this.

    Behaviour:
      1. If PENDING signals exist immediately → return them (0-wait).
      2. If empty → hold connection until a new signal arrives (via asyncio.Event)
         or the `timeout` seconds elapse, then return (possibly empty).

    This replaces short-polling (15s sleep loop) and cuts Server A CPU load by ~90%
    while reducing signal delivery latency from ~7.5 s average to <1 s.
    """
    verify_buffer_secret(x_buffer_secret)

    # 1. Immediate check
    signals = await database.consume_signals(consumer_id, limit, source, exclude_source)
    if signals:
        return {"signals": signals, "count": len(signals), "waited_seconds": 0}

    # 2. No signals — block on event up to `timeout` seconds
    #    Clear first so we don't catch a stale set() from a previous signal.
    _new_signal_event.clear()

    t_start = time.time()
    try:
        await asyncio.wait_for(_new_signal_event.wait(), timeout=float(timeout))
        # Event fired — a new signal was just ingested, fetch it now
        signals = await database.consume_signals(consumer_id, limit, source, exclude_source)
        waited = round(time.time() - t_start, 2)
        return {"signals": signals, "count": len(signals), "waited_seconds": waited}
    except asyncio.TimeoutError:
        # Timeout expired with no new signal — return empty (normal)
        return {"signals": [], "count": 0, "waited_seconds": timeout}

@router.get("/consume", response_model=models.ConsumeResponse)
async def consume_signals(
    consumer_id: str = Query(..., description="Unique client worker identifier"),
    limit: int = Query(10, ge=1, le=100),
    source: Optional[str] = Query(None, description="Include only signals from this source"),
    exclude_source: Optional[str] = Query(None, description="Exclude signals from this source"),
    x_buffer_secret: Optional[str] = Header(None, alias="X-Buffer-Secret")
):
    """Local Bot polls this endpoint to pull pending signals."""
    verify_buffer_secret(x_buffer_secret)
    
    signals = await database.consume_signals(consumer_id, limit, source, exclude_source)
    return {
        "signals": signals,
        "count": len(signals),
        "has_more": len(signals) >= limit
    }

@router.post("/ack", response_model=models.AckResponse)
async def ack_signals(
    body: models.AckRequest = Body(...),
    x_buffer_secret: Optional[str] = Header(None, alias="X-Buffer-Secret")
):
    """Local Bot calls this endpoint to confirm receipt and outcome of signals."""
    verify_buffer_secret(x_buffer_secret)
    
    acked, results = await database.ack_signals(body.acks)
    return {
        "acked": acked,
        "results": results
    }

@router.get("/queue-status", response_model=models.QueueStatusResponse)
async def queue_status(x_buffer_secret: Optional[str] = Header(None, alias="X-Buffer-Secret")):
    """Dashboard proxy reads queue metadata through this endpoint."""
    verify_buffer_secret(x_buffer_secret)
    
    status_data = await database.get_queue_status()
    return status_data

@router.get("/health")
async def health():
    """Comprehensive health check — supports external and internal monitoring.

    V2: server_time_epoch + server_time_iso for NTP drift monitoring.
    V2: hostname for multi-server identification in alerts.
    V2: optional psutil system metrics (cpu, memory, disk).
    """
    now = time.time()
    uptime_s = int(now - _START_TIME)

    status_data = {
        "status": "healthy",
        "uptime_seconds": uptime_s,
        "server_time_epoch": now,
        "server_time_iso": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
    }

    # Database check
    try:
        pending_count = await database.get_pending_count()
        status_data["db"] = "ok"
        status_data["pending_count"] = pending_count
    except Exception as e:
        status_data["status"] = "degraded"
        status_data["db"] = f"error: {str(e)}"
        status_data["pending_count"] = 0

    # System resources (psutil optional — not required in slim containers)
    try:
        import psutil
        status_data["system"] = {
            "cpu_percent":    psutil.cpu_percent(interval=0),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent":   psutil.disk_usage("/").percent,
        }
    except Exception:
        pass  # psutil not installed or platform unsupported

    return status_data
