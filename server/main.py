import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
import secrets

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Query, status, Body
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

import config
import notifier
import database
import rag

# ── P6 imports ───────────────────────────────────────────────────────────────
import mcp_client as _mcp_module
import watchlist as wl_module
import analysis as analysis_module
import brief as brief_module
import scheduler as scheduler_module

# ── P7 imports ───────────────────────────────────────────────────────────────
import telegram_bot as tg_bot_module
import vision as vision_module
import binance_client as binance_module

# ── Phase 4: EventBus imports ────────────────────────────────────────────────
from core.event_bus import bus as _event_bus
from core.events import SignalReceived

# ── Phase 5: WebhookGateway (Component 8/8) ──────────────────────────────────
from gateway.webhook import router as _webhook_router


# ── Fix Windows cp1252 UnicodeEncodeError for emoji in log messages ──────────
# Guard: Only replace stdout/stderr when NOT running under pytest capture.
# pytest replaces sys.stdout with an internal capture object that has no .buffer,
# so checking for 'buffer' is the safe sentinel. Direct replacement would
# destroy pytest's capture file handle and cause ValueError on teardown.
import sys, io
_is_pytest = "pytest" in sys.modules
if not _is_pytest and sys.stdout and hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if not _is_pytest and sys.stderr and hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Setup logging — StreamHandler explicitly UTF-8 to avoid cp1252 crash on Windows
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        _stream_handler,
    ],
)
log = logging.getLogger(__name__)


STATIC_DIR = Path(__file__).parent / "static"

# ── Rate limiting state moved to gateway.webhook (Phase 5) ──
# ═══ LIFESPAN (startup/shutdown) ═════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Khoi tao database, RAG Vector DB, MCP client va Scheduler khi server start."""
    await database.init_db()
    log.info("Database ready.")

    # ── P10: Initialize Auth Service ──────────────────────────────────────────
    try:
        from auth.auth_config import AuthConfig
        from auth.service import AuthService
        auth_cfg = AuthConfig()
        auth_svc = AuthService(auth_cfg)
        app.state.auth_service = auth_svc
        log.info(f"Auth: ✅ Initialized (allowed_users={len(auth_cfg.allowed_users)}, "
                 f"expiry={auth_cfg.session_expiry_hours or 'never'}h, "
                 f"widget={'ON' if auth_cfg.widget_enabled else 'OFF'})")
    except Exception as auth_err:
        log.warning(f"Auth: ⚠️ Init failed ({auth_err}). Dashboard auth disabled.")
        app.state.auth_service = None

    # ── Phase 4: Register EventBus components (triggers @bus.on() decorators) ──
    import processor.signal_processor  # noqa: F401 — @bus.on(SignalReceived)
    import engine.trade_engine          # noqa: F401 — @bus.on(SignalValidated)
    import analyzer.ai_analyzer         # noqa: F401 — @bus.on(AlertTriggered)
    import hub.notification_hub          # noqa: F401 — @bus.on(SignalRejected)
    log.info(
        f"EventBus: {_event_bus.metrics['total_handlers']} handlers registered "
        f"across {_event_bus.metrics['registered_topics']} topics."
    )

    # ── Sprint 7.2: Multi-Exchange Initialization ─────────────────────────────
    from exchanges.registry import init_registry
    from exchanges.health_monitor import start_health_monitor
    init_registry()
    start_health_monitor()
    log.info("Exchange Registry initialized and Health Monitor started.")

    # ── RAG ───────────────────────────────────────────────────
    if config.RAG_ENABLED:
        log.info("RAG: Khởi tạo Vector DB từ Minervini Knowledge Base...")
        success = await rag.init_vector_db()
        if success:
            log.info("RAG: ✅ Vector DB sẵn sàng.")
        else:
            log.warning("RAG: ⚠️ Khởi tạo Vector DB thất bại. Server vẫn hoạt động bình thường.")
    else:
        log.info("RAG: Tính năng RAG đang TẮT (RAG_ENABLED=false).")

    # ── MCP (P6) ──────────────────────────────────────────────
    if config.MCP_ENABLED:
        mcp = _mcp_module.get_mcp_client()
        health = await mcp.health_check()
        if health.get("connected"):
            log.info("MCP: ✅ TradingView Desktop connected (CDP:9222).")
        else:
            log.warning(f"MCP: ⚠️ TradingView not connected — {health.get('error', 'unknown')}. Brief will retry at runtime.")
    else:
        log.info("MCP: Tính năng MCP đang TẮT (MCP_ENABLED=false).")

    # ── Scheduler (P6) ────────────────────────────────────────
    if config.BRIEF_ENABLED:
        scheduler_module.start_scheduler()
        log.info(f"Scheduler: ✅ Morning Brief scheduled at {config.BRIEF_CRON_TIME} ICT daily.")
    else:
        log.info("Scheduler: Morning Brief TẮT (BRIEF_ENABLED=false).")
    # ── Telegram Bot (P7) ────────────────────────────────────
    if config.TELEGRAM_BOT_ENABLED:
        tg_bot_module.start_bot()
        log.info("Telegram Bot: ✅ Interactive bot started (polling mode).")
    else:
        log.info("Telegram Bot: TẮT (TELEGRAM_BOT_ENABLED=false).")

    yield

    # ── Shutdown ──────────────────────────────────────────────
    tg_bot_module.stop_bot()
    scheduler_module.stop_scheduler()
    from exchanges.health_monitor import stop_health_monitor
    stop_health_monitor()
    log.info("Server shutting down.")


app = FastAPI(
    title="TradingView Webhook Server",
    version="7.6",
    lifespan=lifespan,
)

# ── WebhookGateway router (Component 8/8) ────────────────────────────────────
app.include_router(_webhook_router)

# ── P10: Auth router ─────────────────────────────────────────────────────────
from auth.routes import auth_router as _auth_router
app.include_router(_auth_router)

# ── P10: AuthMiddleware (replaces legacy dashboard_auth_middleware) ───────────
from auth.middleware import AuthMiddleware
app.add_middleware(AuthMiddleware, auth_service=getattr(app.state, 'auth_service', None))

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ═══ MIDDLEWARE: IP WHITELISTING ══════════════════════════════
# SEC-001 fix: Use the RIGHTMOST entry of X-Forwarded-For (appended by our
# trusted reverse proxy) instead of the FIRST entry (attacker-controlled).
# This prevents IP spoofing bypasses for both whitelist and rate limiting.
def _get_real_client_ip(request: Request) -> str:
    """Extract real client IP, trusting the rightmost XFF hop (proxy-appended)."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # Rightmost entry is appended by our trusted reverse proxy — cannot be spoofed
        return forwarded_for.split(",")[-1].strip()
    return request.client.host


@app.middleware("http")
async def ip_whitelist_middleware(request: Request, call_next):
    if config.ENABLE_IP_WHITELIST:
        client_ip = _get_real_client_ip(request)
        if client_ip not in config.TV_WHITELIST_IPS and client_ip != "127.0.0.1":
            log.warning(f"Blocked request from unauthorized IP: {client_ip}")
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"error": "IP not whitelisted"}
            )
    return await call_next(request)


# ═══ DASHBOARD AUTH MIDDLEWARE (P10: Replaced by AuthMiddleware) ═══════════
# Legacy middleware replaced by auth.AuthMiddleware which supports both
# Bearer tokens (backward compatible) and Telegram session cookies.
# See server/auth/ package for full implementation.

# Initialize AuthMiddleware after app creation (below)



# ═══ HEALTH CHECK (Sprint 7.3) ════════════════════════════════
@app.get("/health")
async def health_check():
    """Docker/K8s health probe — unauthenticated, lightweight."""
    import time as _t
    uptime_s = int(_t.time() - config.SERVER_START_TIME)
    hours, remainder = divmod(uptime_s, 3600)
    minutes, seconds = divmod(remainder, 60)

    status_data = {
        "status": "healthy",
        "version": "7.3",
        "uptime": f"{hours}h {minutes}m {seconds}s",
        "uptime_seconds": uptime_s,
    }

    # DB check
    try:
        import aiosqlite
        async with aiosqlite.connect(config.DB_PATH) as db:
            await db.execute("SELECT 1")
        status_data["database"] = "ok"
    except Exception as e:
        status_data["database"] = f"error: {e}"
        status_data["status"] = "degraded"

    # Binance client mode
    status_data["binance"] = {
        "dry_run": config.BINANCE_DRY_RUN,
        "testnet": config.BINANCE_TESTNET,
    }

    # Feature flags
    status_data["features"] = {
        "rag": config.RAG_ENABLED,
        "mcp": config.MCP_ENABLED,
        "brief": config.BRIEF_ENABLED,
        "telegram_bot": config.TELEGRAM_BOT_ENABLED,
    }

    return status_data


# ═══ DASHBOARD ════════════════════════════════════════════════
@app.get("/dashboard")
async def dashboard():
    """Serve Performance Dashboard UI."""
    return FileResponse(str(STATIC_DIR / "dashboard.html"))


@app.get("/")
async def root():
    """Redirect to dashboard."""
    return FileResponse(str(STATIC_DIR / "dashboard.html"))


# ═══ HEALTH CHECK ═════════════════════════════════════════════
@app.get("/tv_health_check")
async def tv_health_check():
    return {
        "status": "ok",
        "service": "TradingView Webhook Server (FastAPI)",
        "version": "6.0",
        "rag_enabled": config.RAG_ENABLED,
        "mcp_enabled": config.MCP_ENABLED,
        "brief_enabled": config.BRIEF_ENABLED,
        "time": datetime.now(timezone.utc).isoformat(),
    }


# ═══ P6: MCP STATUS ═══════════════════════════════════════════
@app.get("/api/mcp/status")
async def mcp_status():
    """Kiểm tra kết nối TradingView Desktop qua CDP."""
    if not config.MCP_ENABLED:
        return {"enabled": False, "status": "disabled"}
    mcp = _mcp_module.get_mcp_client()
    health = await mcp.health_check()
    return {"enabled": True, **health}


# ═══ P6: WATCHLIST CRUD ═══════════════════════════════════════
@app.get("/api/watchlist")
async def get_watchlist_endpoint():
    """Lấy danh sách watchlist hiện tại."""
    symbols = wl_module.get_watchlist()
    return {"symbols": symbols, "count": len(symbols)}


@app.post("/api/watchlist")
async def add_watchlist_endpoint(body: dict = Body(...)):
    """Thêm symbol vào watchlist. Body: {\"symbol\": \"BTCUSDT\"}"""
    symbol = body.get("symbol", "").strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="'symbol' field required")
    return wl_module.add_symbol(symbol)


@app.delete("/api/watchlist/{symbol}")
async def remove_watchlist_endpoint(symbol: str):
    """Xóa symbol khỏi watchlist."""
    result = wl_module.remove_symbol(symbol)
    if not result["removed"]:
        raise HTTPException(status_code=404, detail=f"{symbol} not in watchlist")
    return result


@app.put("/api/watchlist/sync")
async def sync_watchlist_endpoint():
    """Sync watchlist từ TradingView Desktop (qua MCP)."""
    if not config.MCP_ENABLED:
        raise HTTPException(status_code=503, detail="MCP_ENABLED=false")
    mcp = _mcp_module.get_mcp_client()
    return await wl_module.sync_from_tradingview(mcp)


# ═══ P6: WATCHLIST SCAN ═══════════════════════════════════════
@app.get("/api/scan/watchlist")
async def scan_watchlist_endpoint(
    symbols: Optional[str] = Query(None, description="Comma-separated, e.g. BTCUSDT,ETHUSDT. Mặc định dùng watchlist."),
    timeframe: str = Query("D", description="Timeframe: D, W, 60..."),
):
    """Scan symbols theo Trend Template + VCP. Trả về kết quả đã sort."""
    if not config.MCP_ENABLED:
        raise HTTPException(status_code=503, detail="MCP_ENABLED=false")

    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else wl_module.get_watchlist()
    if not symbol_list:
        raise HTTPException(status_code=400, detail="Watchlist empty")

    mcp = _mcp_module.get_mcp_client()
    results = await analysis_module.scan_symbols(symbol_list, mcp)

    return {
        "scanned": len(results),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": [
            {
                "symbol": r.symbol,
                "price": r.price,
                "change_pct": r.change_pct,
                "trend_template_score": r.trend_template.score,
                "trend_template_stage": r.trend_template.stage,
                "trend_template_criteria": r.trend_template.criteria,
                "vcp_detected": r.vcp.detected,
                "vol_breakout": getattr(r.vcp, "vol_breakout", False),
                "volume_ratio": round(r.vcp.volume_ratio, 2),
                "range_ratio": round(r.vcp.range_ratio, 2),
                "pivot_level": r.vcp.pivot_level,
                "vcp_note": r.vcp.note,
                "error": r.error,
            }
            for r in results
        ],
    }


# ═══ P6: MORNING BRIEF ════════════════════════════════════════
@app.post("/api/brief/trigger")
async def trigger_brief_endpoint(background_tasks: BackgroundTasks):
    """Chạy Morning Brief ngay lập tức (non-blocking)."""
    background_tasks.add_task(brief_module.generate_morning_brief)
    return {"triggered": True, "message": "Morning Brief đang chạy... Kiểm tra Telegram trong 30-60 giây."}


@app.get("/api/brief/latest")
async def get_latest_brief_endpoint():
    """Lấy Morning Brief mới nhất đã generate."""
    brief = brief_module.get_latest_brief()
    if brief is None:
        return {"available": False, "message": "Chưa có brief nào. Dùng POST /api/brief/trigger để tạo."}
    return {"available": True, **brief}


# ═══ RAG TEST ENDPOINT ════════════════════════════════════════
@app.get("/api/rag/query")
async def rag_query_endpoint(
    q: str = Query(..., description="Câu truy vấn ngữ nghĩa (vd: 'Quy tắc VCP breakout')"),
    n: int = Query(3, ge=1, le=5, description="Số chunks trả về"),
):
    """
    Test endpoint để truy vấn Knowledge Base trực tiếp.
    Hữu ích để debug và verify RAG hoạt động đúng.
    """
    if not config.RAG_ENABLED:
        raise HTTPException(status_code=503, detail="RAG chưa được bật (RAG_ENABLED=false)")

    chunks = rag.query_knowledge(q, n_results=n)
    return {
        "query": q,
        "n_results": len(chunks),
        "chunks": [
            {
                "topic": c["metadata"].get("topic", ""),
                "chapter": c["metadata"].get("chunk_id", c["metadata"].get("filename", "")),
                "relevance": c["relevance_score"],
                "preview": c["content"][:300] + "..." if len(c["content"]) > 300 else c["content"],
            }
            for c in chunks
        ],
    }


@app.get("/api/rag/status")
async def rag_status_endpoint():
    """Kiểm tra trạng thái Vector DB."""
    if not config.RAG_ENABLED:
        return {"enabled": False, "status": "disabled"}

    collection = rag._collection
    if collection is None:
        return {"enabled": True, "status": "not_initialized", "count": 0}

    count = collection.count()
    return {
        "enabled": True,
        "status": "ready" if count > 0 else "empty",
        "vectors_count": count,
        "knowledge_dir": config.KNOWLEDGE_DIR,
        "chroma_db_path": config.CHROMA_DB_PATH,
    }


# ═══ WEBHOOK ENDPOINT — moved to gateway/webhook.py (Phase 5) ═══════════════
# Registered via app.include_router(_webhook_router) above.
# See: server/gateway/webhook.py


@app.get("/trades")
async def get_trades_endpoint(
    symbol: Optional[str] = Query(None, description="Filter theo cap giao dich"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    from_date: Optional[str] = Query(None, description="ISO format: 2026-01-01"),
    to_date: Optional[str] = Query(None, description="ISO format: 2026-12-31"),
):
    """Truy van lich su giao dich."""
    return await database.get_trades(
        symbol=symbol, limit=limit, offset=offset,
        from_date=from_date, to_date=to_date,
    )


# ═══ PERFORMANCE STATS ENDPOINT ═══════════════════════════════
@app.get("/trades/stats")
async def get_stats_endpoint(
    symbol: Optional[str] = Query(None, description="Filter theo cap giao dich"),
):
    """Tinh metrics hieu suat: Win Rate, Profit Factor, Drawdown."""
    return await database.get_stats(symbol=symbol)


# ═══ EQUITY CURVE ENDPOINT ════════════════════════════════════
@app.get("/trades/equity")
async def get_equity_endpoint(
    symbol: Optional[str] = Query(None, description="Filter theo cap giao dich"),
):
    """Tra ve equity curve data cho Chart.js."""
    return await database.get_equity_curve(symbol=symbol)


# ═══ BINANCE ACCOUNT ENDPOINT (Sprint 7.2) ═══════════════════

@app.get("/api/binance/account")
async def binance_account_endpoint(
    asset: str = Query("USDT", description="Asset to check balance"),
):
    """Get Binance account balance."""
    client = binance_module.get_client()
    balance = await client.get_account_balance(asset)
    return {
        "asset": asset.upper(),
        "balance": balance,
        "dry_run": client.dry_run,
        "testnet": client.testnet,
    }


# ═══ VISION ENDPOINTS (P7) ═══════════════════════════════════════════

@app.post("/api/vision/analyze")
async def api_vision_analyze(symbol: str = Query(...), image_path: str = Query(...)):
    """Analyze a chart screenshot using Claude Vision API.

    SEC-002 fix: Restrict image_path to the designated screenshots directory
    to prevent path traversal attacks (e.g. image_path=../../server/.env).
    """
    from pathlib import Path
    # SEC-002: Resolve the screenshot base directory and validate path is within it
    screenshot_base = Path(config.CHROMA_DB_PATH).parent.resolve() / "screenshots"
    screenshot_base.mkdir(parents=True, exist_ok=True)
    # Accept only the filename portion — strip any directory components from input
    safe_filename = Path(image_path).name
    path = (screenshot_base / safe_filename).resolve()
    # Double-check the resolved path is still inside screenshot_base (symlink guard)
    if not str(path).startswith(str(screenshot_base)):
        log.warning(f"Path traversal attempt blocked: image_path={image_path!r}")
        raise HTTPException(status_code=403, detail="Access denied: path traversal detected")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Image not found: {safe_filename}")

    result = await vision_module.analyze_chart_vision(
        image_path=path,
        symbol=symbol.upper(),
    )
    return result


@app.post("/api/vision/capture")
async def api_vision_capture(symbol: str = Query("BTCUSDT", description="Symbol to capture")):
    """
    Dashboard-callable Stealth Capture endpoint.
    Combines: MCP CDP screenshot → crop → AI Vision → DB persist.
    Returns structured result with screenshot_url for immediate display.
    """
    import json as _json
    from pathlib import Path

    sym = symbol.upper()

    # ── Step 1: MCP Screenshot ───────────────────────────────────
    if not config.MCP_ENABLED:
        raise HTTPException(status_code=503, detail="MCP_ENABLED=false — TradingView CDP not configured")

    mcp = _mcp_module.get_mcp_client()
    health = await mcp.health_check()
    if not health.get("connected"):
        raise HTTPException(status_code=503, detail="TradingView CDP not connected — launch_tv_msix_cdp.ps1 phải đang chạy")

    screenshot_path = await mcp.capture_screenshot(symbol=sym)
    if not screenshot_path or not screenshot_path.exists():
        raise HTTPException(status_code=500, detail="Screenshot capture failed — CDP may be busy")

    # ── Step 2: AI Vision Analysis ───────────────────────────────
    try:
        vision_result = await vision_module.analyze_chart_vision(
            image_path=Path(screenshot_path),
            symbol=sym,
        )
    except Exception as e:
        vision_result = {"error": str(e), "verdict": "ERROR", "confidence": 0, "analysis": "", "patterns": []}

    # Normalize fields (vision module uses 'analysis' not 'ai_analysis')
    analysis_text = vision_result.get("analysis", "")
    confidence    = vision_result.get("confidence", 0)
    patterns      = vision_result.get("patterns", [])
    # Derive verdict from confidence when scan_result=None (vision module returns '' in that case)
    verdict = vision_result.get("verdict") or ""
    if not verdict:
        if confidence >= 8:
            verdict = "STRONG SETUP — High Visual Confidence"
        elif confidence >= 6:
            verdict = "WATCHLIST — Monitor for breakout"
        elif confidence >= 4:
            verdict = "NEUTRAL — Base building"
        else:
            verdict = "WEAK SETUP — Low confidence"

    # ── Step 3: Persist to DB ────────────────────────────────────
    import time as _time  # noqa: F401
    brief_text = (
        f"[Stealth Capture] {sym} @ {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n"
        f"Verdict: {verdict}\n"
        f"Confidence: {confidence}/10\n"
        f"Analysis: {analysis_text[:500]}"
    )
    vision_data_json = _json.dumps({
        "symbol":         sym,
        "verdict":        verdict,
        "confidence":     confidence,
        "patterns":       patterns,
        "combined_score": vision_result.get("combined_score", f"{confidence}/10"),
    }, ensure_ascii=False)
    brief_id = await database.insert_brief(
        symbols_scanned=1,
        brief_text=brief_text,
        ai_analysis=analysis_text,
        screenshot=str(screenshot_path),
        vision_data=vision_data_json,
    )

    # ── Step 4: Telegram notification ───────────────────────────
    import asyncio as _asyncio
    try:
        tg_caption = f"\U0001f441 Stealth Capture \u2014 {sym}\nVerdict: {verdict}\nConfidence: {confidence}/10"
        await _asyncio.to_thread(notifier.send_telegram_photo, screenshot_path, tg_caption)
    except Exception as _tg_err:
        log.warning(f"Telegram photo send failed: {_tg_err}")

    return {
        "status":         "ok",
        "brief_id":       brief_id,
        "symbol":         sym,
        "verdict":        verdict,
        "confidence":     confidence,
        "patterns":       patterns,
        "ai_analysis":    analysis_text,
        "screenshot_url": f"/api/vision/screenshot/{brief_id}" if brief_id else None,
        "has_screenshot": screenshot_path.exists() if screenshot_path else False,
    }


@app.get("/api/vision/stats")
async def get_vision_stats():
    """Stats for Capture Studio header: total captures, last capture time, avg confidence."""
    import json as _json
    data = await database.get_briefs(limit=100, offset=0)
    items = data.get("briefs", [])
    total = data.get("total", 0)
    stealth = [b for b in items if "[Stealth Capture]" in (b.get("brief_text") or "")]
    confidences = []
    for b in items:
        if b.get("vision_data"):
            try:
                vd = _json.loads(b["vision_data"])
                c = vd.get("confidence", 0)
                if c: confidences.append(c)
            except Exception:
                pass
    avg_conf = round(sum(confidences) / len(confidences), 1) if confidences else 0
    last_capture = items[0]["created_at"] if items else None
    return {
        "total_captures": total,
        "stealth_count": len(stealth),
        "avg_confidence": avg_conf,
        "last_capture": last_capture,
    }


# ═══ BRIEFS ENDPOINTS (P7.6) ═════════════════════════════════════════

@app.get("/api/briefs")
async def get_briefs_endpoint(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List historical morning briefs with pagination."""
    return await database.get_briefs(limit=limit, offset=offset)


@app.get("/api/briefs/{brief_id}")
async def get_brief_detail_endpoint(brief_id: int):
    """Get a specific brief by ID."""
    brief = await database.get_brief_by_id(brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail=f"Brief #{brief_id} not found")
    return brief


@app.get("/api/vision/history")
async def get_vision_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """
    List vision analysis history (Stealth Captures + Morning Briefs with vision data).
    Returns items with screenshot path, ai_analysis, vision_data JSON.
    """
    import json as _json
    data = await database.get_briefs(limit=limit, offset=offset)
    items = data.get("briefs", [])

    result = []
    for b in items:
        vision_data = {}
        if b.get("vision_data"):
            try:
                vision_data = _json.loads(b["vision_data"])
            except Exception:
                pass

        screenshot = b.get("screenshot", "")
        # Determine if screenshot is accessible (serve from /api/vision/screenshot/<id>)
        result.append({
            "id": b["id"],
            "created_at": b["created_at"],
            "symbol": vision_data.get("symbol", "—"),
            "ai_analysis": b.get("ai_analysis", ""),
            "confidence": vision_data.get("confidence", 0),
            "patterns": vision_data.get("patterns", []),
            "combined_score": vision_data.get("combined_score", "—"),
            "verdict": vision_data.get("verdict", ""),
            "has_screenshot": bool(screenshot),
            "screenshot_url": f"/api/vision/screenshot/{b['id']}" if screenshot else None,
            "source": "stealth" if "[Stealth Capture]" in (b.get("brief_text") or "") else "morning_brief",
        })
    return {"items": result, "total": data.get("total", 0)}


@app.get("/api/vision/screenshot/{brief_id}")
async def get_vision_screenshot(brief_id: int):
    """Serve screenshot image for a vision analysis entry."""
    from fastapi.responses import FileResponse
    brief = await database.get_brief_by_id(brief_id)
    if not brief or not brief.get("screenshot"):
        raise HTTPException(status_code=404, detail="No screenshot for this brief")
    img_path = Path(brief["screenshot"])
    if not img_path.exists():
        raise HTTPException(status_code=404, detail=f"Screenshot file not found: {img_path}")
    return FileResponse(img_path, media_type="image/png")


# ═══ SYSTEM STATUS (P7.6) ════════════════════════════════════════════

@app.get("/api/system/status")
async def system_status_endpoint():
    """Aggregated system status for dashboard."""
    import time as _time

    # MCP status
    mcp_status = {"enabled": False, "connected": False}
    if config.MCP_ENABLED:
        try:
            mcp = _mcp_module.get_mcp_client()
            health = await mcp.health_check()
            mcp_status = {"enabled": True, "connected": health.get("connected", False)}
        except Exception:
            mcp_status = {"enabled": True, "connected": False}

    # RAG status
    rag_status = {"enabled": False, "vectors_count": 0}
    if config.RAG_ENABLED:
        try:
            collection = rag._collection
            count = collection.count() if collection else 0
            rag_status = {"enabled": True, "vectors_count": count}
        except Exception:
            rag_status = {"enabled": True, "vectors_count": 0}

    # DB counts
    try:
        db_counts = await database.get_db_counts()
    except Exception:
        db_counts = {"signals_count": 0, "trades_count": 0, "briefs_count": 0}

    # Latest brief
    latest_brief = brief_module.get_latest_brief()
    last_brief_time = latest_brief.get("timestamp") if latest_brief else None

    # Uptime
    uptime_seconds = int(_time.time() - config.SERVER_START_TIME)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    return {
        "server": {
            "version": "7.6",
            "uptime": uptime_str,
            "uptime_seconds": uptime_seconds,
            "time": datetime.now(timezone.utc).isoformat(),
        },
        "mcp": mcp_status,
        "scheduler": {
            "enabled": config.BRIEF_ENABLED,
            "cron_time": config.BRIEF_CRON_TIME,
            "last_brief": last_brief_time,
        },
        "rag": rag_status,
        "telegram_bot": {
            "enabled": config.TELEGRAM_BOT_ENABLED,
        },
        "database": db_counts,
        "auth_required": bool(config.DASHBOARD_TOKEN),
    }


# ═══ SCAN TRIGGER (P7.6) ═════════════════════════════════════════════

@app.post("/api/scan/trigger")
async def trigger_scan_endpoint(
    background_tasks: BackgroundTasks,
    timeframe: str = Query("D", description="Timeframe: D, W, 60..."),
):
    """Run an on-demand watchlist scan."""
    if not config.MCP_ENABLED:
        raise HTTPException(status_code=503, detail="MCP_ENABLED=false")

    symbol_list = wl_module.get_watchlist()
    if not symbol_list:
        raise HTTPException(status_code=400, detail="Watchlist empty")

    mcp = _mcp_module.get_mcp_client()
    results = await analysis_module.scan_symbols(symbol_list, mcp)

    return {
        "scanned": len(results),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": [
            {
                "symbol": r.symbol,
                "price": r.price,
                "change_pct": r.change_pct,
                "trend_template_score": r.trend_template.score,
                "trend_template_stage": r.trend_template.stage,
                "trend_template_criteria": r.trend_template.criteria,
                "vcp_detected": r.vcp.detected,
                "vol_breakout": getattr(r.vcp, "vol_breakout", False),
                "volume_ratio": round(r.vcp.volume_ratio, 2),
                "range_ratio": round(r.vcp.range_ratio, 2),
                "pivot_level": r.vcp.pivot_level,
                "vcp_note": r.vcp.note,
                "error": r.error,
            }
            for r in results
        ],
    }


if __name__ == "__main__":
    import uvicorn
    log.info(f"Starting FastAPI Webhook Server v7.6 on {config.HOST}:{config.PORT}")
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=config.DEBUG)
