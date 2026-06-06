import os

# Force Hugging Face offline mode to load local models instantly (0.1s instead of 3.5m)
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import logging
import sys
import io
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import (
    FastAPI,
    Request,
    HTTPException,
    BackgroundTasks,
    Query,
    status,
)
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

import aiosqlite

import config
import notifier
import database
import rag

# SEC-4: Runtime guard for path traversal prevention (CWE-22)
try:
    from security.runtime_guard import (
        safe_path,
        safe_screenshot_path,
        SecurityError as _SecurityError,
    )
except ImportError:
    # Graceful fallback if security module not installed
    def safe_screenshot_path(raw_path) -> Path:  # type: ignore[misc]
        p = Path(raw_path)
        if not p.exists():
            raise FileNotFoundError(f"Not found: {p}") from None
        return p

    def safe_path(raw_path, base_dir: Path, **kwargs) -> Path:  # type: ignore[misc]
        return Path(raw_path).resolve()

    class _SecurityError(ValueError):
        pass  # type: ignore[misc]


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

# ── SSE: Server-Sent Events hub ──────────────────────────────────────────────
import asyncio
import json as _json

_sse_clients: set[asyncio.Queue] = set()  # one Queue per connected browser tab

# ── Stats TTL cache (30s) — avoids repeated full-table GROUP BY scans ─────────
import time as _time  # noqa: E402

_stats_cache: dict[tuple, tuple] = {}  # key=(symbol,ind_name) → (result, expire_at)
_STATS_TTL = 30.0  # seconds


def _stats_cache_get(key: tuple):
    entry = _stats_cache.get(key)
    if entry and _time.monotonic() < entry[1]:
        return entry[0]
    _stats_cache.pop(key, None)
    return None


def _stats_cache_set(key: tuple, value: dict) -> None:
    _stats_cache[key] = (value, _time.monotonic() + _STATS_TTL)
    # Prune stale entries (keep cache small)
    if len(_stats_cache) > 50:
        now = _time.monotonic()
        for k in [k for k, (_, exp) in list(_stats_cache.items()) if exp < now]:
            _stats_cache.pop(k, None)


def push_sse_event(event_type: str, data: dict) -> None:
    """Broadcast an SSE event to ALL currently connected browser clients.

    Non-blocking: if a client queue is full we skip it to avoid back-pressure.
    Called from webhook handler or any background task.

    Args:
        event_type: e.g. 'new_signal', 'scan_complete', 'heartbeat'
        data:       JSON-serialisable dict
    """
    msg = f"event: {event_type}\ndata: {_json.dumps(data)}\n\n"
    dead = set()
    for q in _sse_clients:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.add(q)
        except Exception:
            dead.add(q)
    _sse_clients.difference_update(dead)


# ── P9: Claude SDK package ────────────────────────────────────────────────────
from claude_cli import SdkClient, ClaudeService  # noqa: E402
import claude_cli.telegram_commands as _claude_tg  # noqa: E402
import claude_cli.event_handler as _claude_eh  # noqa: E402

# ── Phase 4: EventBus imports ────────────────────────────────────────────────
from core.event_bus import bus as _event_bus  # noqa: E402

# ── Phase 5: WebhookGateway (Component 8/8) ──────────────────────────────────
from gateway.webhook import router as _webhook_router  # noqa: E402

from auth.routes import auth_router as _auth_router  # noqa: E402
from auth.middleware import AuthMiddleware  # noqa: E402

_claude_service: Optional[ClaudeService] = None


# ── Fix Windows cp1252 UnicodeEncodeError for emoji in log messages ──────────
# Guard: Only replace stdout/stderr when NOT running under pytest capture.
# pytest replaces sys.stdout with an internal capture object that has no .buffer,
# so checking for 'buffer' is the safe sentinel. Direct replacement would
# destroy pytest's capture file handle and cause ValueError on teardown.
_is_pytest = "pytest" in sys.modules
if not _is_pytest and sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if not _is_pytest and sys.stderr and hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Setup logging — StreamHandler explicitly UTF-8 to avoid cp1252 crash on Windows
Path(config.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)s  %(message)s")
)

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
    # Dynamic rate limit toggle for testing/stress-testing
    limiter.enabled = not getattr(config, "DISABLE_RATE_LIMIT", False)

    await database.init_db()
    log.info("Database ready.")

    # ── Angati SRA Server Integration ─────────────────────────────────────────
    try:
        import sys
        import os
        import threading

        # Add the nerves parent path to sys.path so hook_service can find local core
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        # Add nerves/core to sys.path
        core_path = project_root / "nerves" / "core"
        if str(core_path) not in sys.path:
            sys.path.insert(0, str(core_path))

        import hook_service

        def run_sra_server():
            bind_addr = os.getenv("ANGATI_BUS_BIND", "127.0.0.1:9105")
            port = 9105
            if ":" in bind_addr:
                try:
                    port = int(bind_addr.split(":")[-1])
                except ValueError as e:
                    import logging

                    logging.getLogger(__name__).warning("Ignored: %s", e)
            server_address = ("", port)
            try:
                hook_service.AGENTS_ROOT = project_root
                if hasattr(hook_service, "scar_memory") and hook_service.scar_memory:
                    hook_service.scar_memory.AGENTS_ROOT = project_root

                httpd = hook_service.ThreadingHTTPServer(
                    server_address, hook_service.SRAHookHandler
                )
                log.info(f"SRA Server: ✅ Starting local Hook Server on port {port}...")
                httpd.serve_forever()
            except Exception as sra_err:
                log.warning(
                    f"SRA Server: ⚠️ Failed to run local Hook Server ({sra_err}). Port might be in use."
                )

        sra_thread = threading.Thread(target=run_sra_server, daemon=True)
        sra_thread.start()
        app.state.sra_thread = sra_thread
    except Exception as sra_init_err:
        log.warning(f"SRA Server: ⚠️ Init failed ({sra_init_err})")

    # ── P10: Initialize Auth Service ──────────────────────────────────────────
    try:
        from auth.auth_config import AuthConfig
        from auth.service import AuthService

        auth_cfg = AuthConfig()
        auth_svc = AuthService(auth_cfg)
        app.state.auth_service = auth_svc
        log.info(
            f"Auth: ✅ Initialized (allowed_users={len(auth_cfg.allowed_users)}, "
            f"expiry={auth_cfg.session_expiry_hours or 'never'}h, "
            f"widget={'ON' if auth_cfg.widget_enabled else 'OFF'})"
        )
    except Exception as auth_err:
        log.warning(f"Auth: ⚠️ Init failed ({auth_err}). Dashboard auth disabled.")
        app.state.auth_service = None

    # ── Phase 4: Register EventBus components (triggers @bus.on() decorators) ──
    import processor.signal_processor  # noqa: F401 — @bus.on(SignalReceived)
    import processor.signal_enricher  # noqa: F401 — @bus.on(IndicatorSignalValidated)
    import engine.trade_engine  # noqa: F401 — @bus.on(SignalValidated)
    import analyzer.ai_analyzer  # noqa: F401 — @bus.on(AlertTriggered)
    import hub.notification_hub  # noqa: F401 — @bus.on(SignalRejected)
    import data.indicator_persistence  # noqa: F401 — @bus.on(IndicatorSignalReceived) DI-1

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
            log.warning(
                "RAG: ⚠️ Khởi tạo Vector DB thất bại. Server vẫn hoạt động bình thường."
            )
    else:
        log.info("RAG: Tính năng RAG đang TẮT (RAG_ENABLED=false).")

    # ── MCP (P6) ──────────────────────────────────────────────
    if config.MCP_ENABLED:
        mcp = _mcp_module.get_mcp_client()
        health = await mcp.health_check()
        if health.get("connected"):
            log.info("MCP: ✅ TradingView Desktop connected (CDP:9222).")
        else:
            log.warning(
                f"MCP: ⚠️ TradingView not connected — {health.get('error', 'unknown')}. Brief will retry at runtime."
            )
    else:
        log.info("MCP: Tính năng MCP đang TẮT (MCP_ENABLED=false).")

    # ── Stealth Capture Daemon (P11) ──────────────────────────────────────────
    if config.CAPTURE_DAEMON_ENABLED:
        try:
            from capture_daemon import DaemonLifecycleManager
            from capture_hooks import HookDispatcher
            from capture_client import PythonCaptureClient

            daemon_mgr = DaemonLifecycleManager()
            await daemon_mgr.start()

            capture_client = PythonCaptureClient()
            hook_dispatcher = HookDispatcher(capture_client)
            hook_dispatcher.register_hooks(config.CAPTURE_HOOKS)

            app.state.daemon_manager = daemon_mgr
            app.state.capture_client = capture_client
            app.state.hook_dispatcher = hook_dispatcher
            log.info(
                f"Capture Daemon: ✅ Started (port {config.CAPTURE_DAEMON_PORT}, "
                f"hooks={config.CAPTURE_HOOKS})"
            )
        except Exception as daemon_err:
            log.warning(
                f"Capture Daemon: ⚠️ Init failed ({daemon_err}). "
                "Falling back to subprocess mode."
            )
    else:
        log.info("Capture Daemon: TẮT (CAPTURE_DAEMON_ENABLED=false).")

    # ── Scheduler (P6) ────────────────────────────────────────
    if config.BRIEF_ENABLED:
        scheduler_module.start_scheduler()
        log.info(
            f"Scheduler: ✅ Morning Brief scheduled at {config.BRIEF_CRON_TIME} ICT daily."
        )
    else:
        log.info("Scheduler: Morning Brief TẮT (BRIEF_ENABLED=false).")
    # ── Telegram Bot (P7) ────────────────────────────────────
    if config.TELEGRAM_BOT_ENABLED:
        tg_bot_module.start_bot()
        log.info("Telegram Bot: ✅ Interactive bot started (polling mode).")
    else:
        log.info("Telegram Bot: TẮT (TELEGRAM_BOT_ENABLED=false).")

    # ── Claude SDK (P9) ──────────────────────────────────────────────────────
    global _claude_service
    if config.CLAUDE_CLI_ENABLED:
        _sdk = SdkClient()
        sdk_ok = await _sdk.check_availability()
        if not sdk_ok:
            log.warning(
                "Claude SDK: ANTHROPIC_API_KEY not configured or anthropic package missing. "
                "SDK calls will fail."
            )
        _claude_service = ClaudeService(_sdk)
        await _claude_service.initialize()
        log.info("Claude SDK: ✅ ClaudeService initialized (SDK-Headless mode).")

        # Register EventBus handler only when AI_PROVIDER=claude_cli
        if getattr(config, "AI_PROVIDER", "").lower() == "claude_cli":
            _claude_eh.register_handler(_claude_service)
            log.info("Claude SDK: EventBus handler registered for SignalValidated.")

        # Register Telegram commands only when bot is running
        if config.TELEGRAM_BOT_ENABLED:
            _app = tg_bot_module.get_application()
            if _app is not None:
                _claude_tg.register_commands(_app, _claude_service)
                log.info(
                    "Claude SDK: Telegram commands /claude /analyze /claude_reset /claude_status registered."
                )
            else:
                log.warning(
                    "Claude SDK: Telegram application not available — commands not registered."
                )
    else:
        log.info(
            "Claude SDK: TẮT (CLAUDE_CLI_ENABLED=false). Property 8 — no SDK, no handlers."
        )

    # ── VPS Buffer Consumer (VBS) ──────────────────────────────────
    if config.VPS_BUFFER_ENABLED:
        try:
            from workers.vps_consumer import VpsSignalConsumer

            vps_consumer = VpsSignalConsumer()
            app.state.vps_consumer = vps_consumer

            # Startup recovery: drains queue
            await vps_consumer.on_startup()

            # Start background polling loop
            app.state.vps_consumer_task = asyncio.create_task(vps_consumer.poll_loop())
            log.info("VPS Buffer Consumer: ✅ Running background poller.")
        except Exception as vbs_err:
            log.exception(f"VPS Buffer Consumer: ⚠️ Initialization failed: {vbs_err}")

    yield

    # ── Shutdown ──────────────────────────────────────────────
    # Stop VBS Consumer background task
    if hasattr(app.state, "vps_consumer_task"):
        app.state.vps_consumer_task.cancel()
        try:
            await app.state.vps_consumer_task
        except asyncio.CancelledError:
            pass
    if hasattr(app.state, "vps_consumer"):
        await app.state.vps_consumer.close()

    # Stop Capture Daemon first (long-running child process)
    if hasattr(app.state, "daemon_manager"):
        await app.state.daemon_manager.stop()
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

from slowapi import Limiter, _rate_limit_exceeded_handler  # noqa: E402
from slowapi.util import get_remote_address  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from slowapi.middleware import SlowAPIMiddleware  # noqa: E402

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],
    enabled=not getattr(config, "DISABLE_RATE_LIMIT", False),
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── WebhookGateway router (Component 8/8) ────────────────────────────────────
app.include_router(_webhook_router)

# ── P10: Auth router ─────────────────────────────────────────────────────────
app.include_router(_auth_router)

# ── P10: AuthMiddleware (replaces legacy dashboard_auth_middleware) ───────────
app.add_middleware(
    AuthMiddleware, auth_service=getattr(app.state, "auth_service", None)
)


# ── No-cache override for JS files — MUST be declared BEFORE app.mount ───────
@app.get("/static/js/{filename:path}")
async def serve_js_nocache(filename: str):
    """Serve JS with no-cache headers so browser always fetches latest version."""
    js_path = STATIC_DIR / "js" / filename
    if not js_path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(
        path=str(js_path),
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# Mount static files (AFTER specific routes so /static/js/* route wins)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Mount reports files (for backtests, sizing and validation analysis)
# Dynamic resolution: supports local repo layout, CI runner, and Docker environment safely
REPORTS_DIR = Path(__file__).parent.parent.parent.parent / "reports"
if not REPORTS_DIR.exists():
    # Fallback to local sibling path if run inside deep subdirectory / Docker
    REPORTS_DIR = Path(__file__).parent / "reports"

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")


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
                content={"error": "IP not whitelisted"},
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


@app.get("/daemon_dashboard")
async def daemon_dashboard():
    """Serve Capture Daemon Test Dashboard."""
    return FileResponse(str(STATIC_DIR / "capture_dashboard.html"))


@app.get("/studio")
async def studio():
    """Serve Custom Trading View Studio & Telegram Template Editor."""
    return FileResponse(str(STATIC_DIR / "studio.html"))


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


# ═══ V3: SERVER HEALTH ANNOUNCE ═══════════════════════════════
@app.post("/api/server-announce")
async def server_announce(body: dict):
    """Server B calls this when it starts up to resume health monitoring.

    Body: {"server": "SERVER_B"} or {"server": "Execution"}
    """
    from workers.liveness_monitor import announce_server_online

    server_name = body.get("server", "")
    if not server_name:
        raise HTTPException(status_code=400, detail="'server' field required")
    result = announce_server_online(server_name)
    if result.get("status") == "ok":
        # Send recovery notification
        try:
            from notifier import notify_all

            await notify_all(
                f"🟢 <b>SERVER ONLINE</b>\n\n"
                f"Server: <b>{result['server']}</b>\n"
                f"Health monitoring resumed."
            )
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)
    return result


@app.get("/api/server-status")
async def server_status():
    """Get current health monitoring status of all servers."""
    from workers.liveness_monitor import get_server_status

    return {"servers": get_server_status()}


@app.get("/api/telegram/templates")
async def get_telegram_templates():
    """Retrieve the current custom Telegram message templates."""
    from utils.telegram_templates import load_templates

    return load_templates()


@app.post("/api/telegram/templates")
async def update_telegram_templates(body: dict):
    """Save custom Telegram message templates after validating syntax."""
    from utils.telegram_templates import save_templates

    try:
        save_templates(body)
        return {
            "status": "success",
            "message": "Telegram templates updated successfully.",
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid template configuration.")
    except Exception as e:
        log.error(f"Failed to update telegram templates: {e}")
        raise HTTPException(
            status_code=500, detail="Internal server error saving templates."
        )


# ── VPS Buffer Queue Status ───────────────────────────────────
@app.get("/api/queue-status")
async def get_queue_status():
    """Proxy queue status request to VPS Buffer Service."""
    if not config.VPS_BUFFER_ENABLED or not config.VPS_BUFFER_URL:
        return {
            "enabled": False,
            "summary": {
                "pending": 0,
                "dispatched": 0,
                "acked_today": 0,
                "stale_today": 0,
            },
        }

    url = f"{config.VPS_BUFFER_URL}/queue-status"
    headers = {"X-Buffer-Secret": config.VPS_BUFFER_SECRET}

    import aiohttp
    import socket

    conn = aiohttp.TCPConnector(family=socket.AF_INET)
    try:
        async with aiohttp.ClientSession(connector=conn) as session:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return {"enabled": True, **data}
                else:
                    return {
                        "enabled": True,
                        "error": f"VPS HTTP {response.status}",
                        "summary": {
                            "pending": 0,
                            "dispatched": 0,
                            "acked_today": 0,
                            "stale_today": 0,
                        },
                    }
    except Exception as e:
        return {
            "enabled": True,
            "error": str(e),
            "summary": {
                "pending": 0,
                "dispatched": 0,
                "acked_today": 0,
                "stale_today": 0,
            },
        }


# ═══ P6: WATCHLIST CRUD ═══════════════════════════════════════
@app.get("/api/watchlist")
async def get_watchlist_endpoint():
    """Lấy danh sách watchlist hiện tại."""
    symbols = wl_module.get_watchlist()
    return {"symbols": symbols, "count": len(symbols)}


@app.post("/api/watchlist")
async def add_watchlist_endpoint(body: dict):
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
    symbols: Optional[str] = Query(
        None,
        description="Comma-separated, e.g. BTCUSDT,ETHUSDT. Mặc định dùng watchlist.",
    ),
    timeframe: str = Query("D", description="Timeframe: D, W, 60..."),
):
    """Scan symbols theo Trend Template + VCP. Trả về kết quả đã sort."""
    if not config.MCP_ENABLED:
        raise HTTPException(status_code=503, detail="MCP_ENABLED=false")

    symbol_list = (
        [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if symbols
        else wl_module.get_watchlist()
    )
    if not symbol_list:
        raise HTTPException(status_code=400, detail="Watchlist empty")

    mcp = _mcp_module.get_mcp_client()
    results = await analysis_module.scan_symbols(symbol_list, mcp)

    # ── Save to shared cache ──────────────────────────────────────────────────
    import scan_cache

    serialised = [
        {
            "symbol": r.symbol,
            "price": r.price,
            "change_pct": r.change_pct,
            "trend_template_score": r.trend_template.score if r.trend_template else 0,
            "trend_template_stage": r.trend_template.stage if r.trend_template else "-",
            "trend_template_criteria": r.trend_template.criteria
            if r.trend_template
            else [],
            "vcp_detected": r.vcp.detected if r.vcp else False,
            "vol_breakout": getattr(r.vcp, "vol_breakout", False) if r.vcp else False,
            "volume_ratio": round(r.vcp.volume_ratio, 2) if r.vcp else 0,
            "range_ratio": round(r.vcp.range_ratio, 2) if r.vcp else 0,
            "pivot_level": r.vcp.pivot_level if r.vcp else None,
            "vcp_note": r.vcp.note if r.vcp else None,
            "error": r.error,
        }
        for r in results
    ]
    scan_cache.save_scan_results(serialised, source="web", symbol_list=symbol_list)

    return {
        "scanned": len(results),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": serialised,
    }


@app.get("/api/scan/all")
async def scan_all_endpoint(
    background_tasks: BackgroundTasks,
    force: bool = Query(
        False,
        description="Nếu True, bắt buộc chạy scan mới trong background kể cả khi đang có kết quả cũ.",
    ),
):
    """Trigger hoặc lấy kết quả scan toàn bộ sàn được cấu hình."""
    trigger_new = force or (
        analysis_module._scan_status == "idle"
        and not analysis_module._latest_scan_results
    )

    if trigger_new and analysis_module._scan_status != "running":
        background_tasks.add_task(analysis_module.scan_all_configured_exchanges)

    results = analysis_module._latest_scan_results
    return {
        "status": analysis_module._scan_status,
        "start_time": analysis_module._scan_start_time,
        "end_time": analysis_module._scan_end_time,
        "error": analysis_module._scan_error,
        "scanned": len(results),
        "results": [
            {
                "symbol": r.symbol,
                "price": r.price,
                "change_pct": r.change_pct,
                "exchange": r.exchange,
                "trend_template_score": r.trend_template.score,
                "trend_template_stage": r.trend_template.stage,
                "trend_template_criteria": r.trend_template.criteria,
                "vcp_detected": r.vcp.detected,
                "vol_breakout": getattr(r.vcp, "vol_breakout", False),
                "volume_ratio": round(r.vcp.volume_ratio, 2)
                if r.vcp.volume_ratio is not None
                else 1.0,
                "range_ratio": round(r.vcp.range_ratio, 2)
                if r.vcp.range_ratio is not None
                else 1.0,
                "pivot_level": r.vcp.pivot_level,
                "vcp_note": r.vcp.note,
                "error": r.error,
            }
            for r in results
        ],
    }


@app.get("/api/scan/mtf")
async def scan_mtf_endpoint(
    symbol: str = Query(..., description="Symbol to scan, e.g. BTCUSDT"),
    exchange: Optional[str] = Query(
        None,
        description="Exchange name, e.g. binance, weex. Default is config.DEFAULT_EXCHANGE",
    ),
):
    """
    Perform multi-timeframe scan (1D, 4H, 1H) for a symbol, capture screenshots,
    run Vision AI analysis, and return scorecard + analysis report.
    """
    import aiohttp
    import asyncio
    from pathlib import Path
    import re
    from datetime import datetime
    import config
    import mcp_client as _mcp_module
    import vision as vision_module
    import analysis as analysis_module

    sym = symbol.upper()
    exch = (exchange or config.DEFAULT_EXCHANGE).lower()

    # 1. Algorithmic scan
    semaphore = asyncio.Semaphore(1)
    async with aiohttp.ClientSession() as session:
        try:
            mtf_res = await analysis_module.scan_symbol_multi_timeframe(
                session=session, exchange_name=exch, symbol=sym, semaphore=semaphore
            )
        except Exception as e:
            log.exception(f"Algorithmic scan failed in endpoint for {sym}: {e}")
            raise HTTPException(
                status_code=500,
                detail="MTF Scan failed due to an internal algorithmic error.",
            )

    # 2. Capture screenshots
    screenshots_dir = Path(config.CHROMA_DB_PATH).parent.resolve() / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    safe_symbol = re.sub(r"[^A-Za-z0-9_\-]", "", sym)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    path_1d = screenshots_dir / f"mtf_1d_{safe_symbol}_{timestamp}.png"
    path_4h = screenshots_dir / f"mtf_4h_{safe_symbol}_{timestamp}.png"
    path_1h = screenshots_dir / f"mtf_1h_{safe_symbol}_{timestamp}.png"

    mcp = _mcp_module.get_mcp_client()

    captured_1d = await mcp.capture_screenshot(
        symbol=sym, timeframe="D", save_path=path_1d
    )
    await asyncio.sleep(0.5)
    captured_4h = await mcp.capture_screenshot(
        symbol=sym, timeframe="240", save_path=path_4h
    )
    await asyncio.sleep(0.5)
    captured_1h = await mcp.capture_screenshot(
        symbol=sym, timeframe="60", save_path=path_1h
    )

    image_paths = []
    for p in [captured_1d, captured_4h, captured_1h]:
        if p and Path(p).exists():
            image_paths.append(Path(p))

    # 3. Vision AI analysis
    vision_result = {}
    if image_paths:
        try:
            vision_result = await vision_module.analyze_chart_vision_mtf(
                image_paths=image_paths,
                symbol=sym,
                mtf_scan_result={"timeframes": mtf_res.timeframes},
            )
        except Exception as e:
            log.error(f"Vision analysis failed in endpoint for {sym}: {e}")
            vision_result = {"error": str(e)}
    else:
        vision_result = {"error": "Failed to capture any charts for vision analysis."}

    # Helper to serialize ScanResult
    def serialize_scan(r):
        if not r:
            return None
        return {
            "symbol": r.symbol,
            "price": r.price,
            "change_pct": r.change_pct,
            "trend_template_score": r.trend_template.score if r.trend_template else 0,
            "trend_template_stage": r.trend_template.stage
            if r.trend_template
            else "Unknown",
            "trend_template_criteria": r.trend_template.criteria
            if r.trend_template
            else {},
            "vcp_detected": r.vcp.detected if r.vcp else False,
            "vol_breakout": getattr(r.vcp, "vol_breakout", False) if r.vcp else False,
            "volume_ratio": round(r.vcp.volume_ratio, 2)
            if r.vcp and r.vcp.volume_ratio is not None
            else 1.0,
            "range_ratio": round(r.vcp.range_ratio, 2)
            if r.vcp and r.vcp.range_ratio is not None
            else 1.0,
            "pivot_level": r.vcp.pivot_level if r.vcp else None,
            "vcp_note": r.vcp.note if r.vcp else "",
            "error": r.error,
        }

    return {
        "symbol": sym,
        "exchange": exch,
        "price": mtf_res.price,
        "aligned_long": mtf_res.aligned_long,
        "aligned_short": mtf_res.aligned_short,
        "verdict": mtf_res.verdict,
        "timeframes": {
            tf: serialize_scan(scan) for tf, scan in mtf_res.timeframes.items()
        },
        "vision": {
            "analysis": vision_result.get("analysis", ""),
            "confidence": vision_result.get("confidence", 0),
            "patterns": vision_result.get("patterns", []),
            "combined_score": vision_result.get("combined_score", "N/A"),
            "verdict": vision_result.get("verdict", ""),
            "error": vision_result.get("error"),
        },
        "screenshots": {
            "1d": str(path_1d) if path_1d.exists() else None,
            "4h": str(path_4h) if path_4h.exists() else None,
            "1h": str(path_1h) if path_1h.exists() else None,
        },
    }


# ═══ P6: MORNING BRIEF ════════════════════════════════════════
@app.post("/api/brief/trigger")
async def trigger_brief_endpoint(background_tasks: BackgroundTasks):
    """Chạy Morning Brief ngay lập tức (non-blocking)."""
    background_tasks.add_task(brief_module.generate_morning_brief)
    return {
        "triggered": True,
        "message": "Morning Brief đang chạy... Kiểm tra Telegram trong 30-60 giây.",
    }


@app.get("/api/brief/latest")
async def get_latest_brief_endpoint():
    """Lấy Morning Brief mới nhất đã generate."""
    brief = brief_module.get_latest_brief()
    if brief is None:
        return {
            "available": False,
            "message": "Chưa có brief nào. Dùng POST /api/brief/trigger để tạo.",
        }
    return {"available": True, **brief}


# ═══ INDICATOR SIGNALS API ═══════════════════════════════════
@app.get("/api/indicator-signals")
async def get_indicator_signals(
    symbol: Optional[str] = Query(None, description="Filter by symbol, e.g. BTCUSDT"),
    signal_type: Optional[str] = Query(
        None, description="Filter by type: entry|exit|info"
    ),
    indicator_name: Optional[str] = Query(None, description="Filter by indicator name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Fetch indicator signals with optional filters for the Signals dashboard tab."""
    conditions: list[str] = []
    params: list = []

    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol.upper())
    if signal_type:
        conditions.append("signal_type = ?")
        params.append(signal_type.lower())
    if indicator_name:
        # PREFIX match (not '%x%') so idx_indicator_signals_name index is usable
        conditions.append("indicator_name LIKE ?")
        params.append(f"{indicator_name}%")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    import aiosqlite
    import json as _json

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        query = (
            "SELECT id, signal_id, created_at, symbol, indicator_name, "
            "signal_type, interval, price, confidence_score, "
            "conditions_met, metadata, source_ip, exchange, "
            "COUNT(*) OVER() AS _total "
            "FROM indicator_signals\n"
        )
        query += where_clause + "\n"
        query += "ORDER BY created_at DESC\nLIMIT ? OFFSET ?"

        # Single query: window function gives total count + paginated rows in one pass
        rows = await db.execute_fetchall(
            query,
            params + [limit, offset],
        )

    total = rows[0]["_total"] if rows else 0
    signals = []
    for r in rows:
        try:
            conditions_list = (
                _json.loads(r["conditions_met"]) if r["conditions_met"] else []
            )
        except Exception:
            conditions_list = [r["conditions_met"]] if r["conditions_met"] else []
        try:
            meta = _json.loads(r["metadata"]) if r["metadata"] else {}
        except Exception:
            meta = {}

        signals.append(
            {
                "id": r["id"],
                "signal_id": r["signal_id"],
                "created_at": r["created_at"],
                "symbol": r["symbol"],
                "indicator_name": r["indicator_name"],
                "signal_type": r["signal_type"],
                "interval": r["interval"] or "—",
                "price": r["price"],
                "confidence_score": r["confidence_score"] or 0,
                "conditions_met": conditions_list,
                "metadata": meta,
                "source_ip": r["source_ip"] or "—",
                "exchange": r["exchange"] or "binance",
            }
        )

    return {"total": total, "limit": limit, "offset": offset, "signals": signals}


@app.get("/api/chart-markers")
async def get_chart_markers(
    symbol: str = Query(..., description="Symbol e.g. BTCUSDT"),
    interval: Optional[str] = Query(None, description="Timeframe e.g. 1h, 4h, 1d"),
    from_ts: Optional[int] = Query(None, alias="from", description="Start time ms"),
    to_ts: Optional[int] = Query(None, alias="to", description="End time ms"),
    limit: int = Query(200, ge=1, le=500),
):
    """
    Chart markers for LightweightCharts — MIS/MTT buy/sell arrows.
    Queries signals table (mode=MTT|MIS) and indicator_signals table.
    Returns markers sorted by time (unix seconds) for candleSeries.setMarkers().
    """
    import aiosqlite
    import json as _json

    sym = symbol.upper().split(":")[1] if ":" in symbol else symbol.upper()
    markers: list[dict] = []

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # ── Source 1: signals table (MTT/MIS from webhook alerts) ──
        sig_conds = ["symbol = ?"]
        sig_params: list = [sym]

        if from_ts:
            sig_conds.append("created_at >= datetime(?, 'unixepoch', 'localtime')")
            sig_params.append(from_ts // 1000)
        if to_ts:
            sig_conds.append("created_at <= datetime(?, 'unixepoch', 'localtime')")
            sig_params.append(to_ts // 1000)

        sig_where = "WHERE " + " AND ".join(sig_conds) + " AND mode IN ('MTT','MIS')"
        query = "SELECT created_at, action, mode, price, payload\nFROM signals\n"
        query += sig_where + "\n"
        query += "ORDER BY created_at DESC\nLIMIT ?"
        rows = await db.execute_fetchall(
            query,
            tuple(sig_params) + (limit,),
        )
        for r in rows:
            try:
                ts_str = r["created_at"]  # "2024-05-29 08:00:00"
                # Parse to unix timestamp
                from datetime import datetime

                dt = datetime.fromisoformat(ts_str)
                unix_ts = int(dt.timestamp())
            except ValueError as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)
                continue

            action = (r["action"] or "").lower()
            if action not in ("buy", "sell"):
                continue

            # Extract confidence from payload JSON if available
            conf = 0
            try:
                payload = _json.loads(r["payload"]) if r["payload"] else {}
                conf = int(payload.get("confidence_score", 0))
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)

            markers.append(
                {
                    "time": unix_ts,
                    "action": action,
                    "mode": r["mode"] or "MTT",
                    "price": r["price"],
                    "confidence": conf,
                    "source": "webhook",
                }
            )

        # ── Source 2: indicator_signals table (from Pine indicator alerts) ──
        ind_conds = ["symbol = ?"]
        ind_params: list = [sym]

        if interval:
            # normalize: "1h" → "60" or keep as-is
            ind_conds.append("(interval = ? OR interval = ?)")
            tf_map = {"1h": "60", "4h": "240", "1d": "D", "15m": "15"}
            alt = tf_map.get(interval, interval)
            ind_params.extend([interval, alt])
        if from_ts:
            ind_conds.append("created_at >= datetime(?, 'unixepoch', 'localtime')")
            ind_params.append(from_ts // 1000)
        if to_ts:
            ind_conds.append("created_at <= datetime(?, 'unixepoch', 'localtime')")
            ind_params.append(to_ts // 1000)

        ind_conds.append("signal_type IN ('entry','exit')")
        ind_where = "WHERE " + " AND ".join(ind_conds)

        query = (
            "SELECT created_at, signal_type, price, confidence_score, metadata\n"
            "FROM indicator_signals\n"
        )
        query += ind_where + "\n"
        query += "ORDER BY created_at DESC\nLIMIT ?"
        ind_rows = await db.execute_fetchall(
            query,
            tuple(ind_params) + (limit,),
        )
        for r in ind_rows:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(r["created_at"])
                unix_ts = int(dt.timestamp())
            except ValueError as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)
                continue

            # Derive action from metadata
            try:
                meta = _json.loads(r["metadata"]) if r["metadata"] else {}
                direction = meta.get("direction", "long")
            except Exception:
                direction = "long"

            sig_type = r["signal_type"] or "entry"
            # entry long = buy, entry short = sell, exit long = sell, exit short = buy
            if sig_type == "entry":
                action = "buy" if direction == "long" else "sell"
            else:
                action = "sell" if direction == "long" else "buy"

            markers.append(
                {
                    "time": unix_ts,
                    "action": action,
                    "mode": "MIS",  # indicator_signals are MIS (1H momentum)
                    "price": r["price"],
                    "confidence": int(r["confidence_score"] or 0),
                    "source": "indicator",
                }
            )

    # Sort by time ascending (LightweightCharts requirement)
    markers.sort(key=lambda m: m["time"])

    return {"markers": markers, "total": len(markers)}


@app.get("/api/indicator-signals/stats")
async def get_indicator_signals_stats(
    symbol: Optional[str] = Query(None), indicator_name: Optional[str] = Query(None)
):
    """KPI stats for the Signals dashboard: total, by type, avg confidence, top indicators, direction mix."""
    import aiosqlite

    sym_key = (symbol or "").upper()
    ind_key = (indicator_name or "").strip()
    cache_key = (sym_key, ind_key)

    # ── Fast path: return cached result if fresh ──────────────────────────────
    cached = _stats_cache_get(cache_key)
    if cached is not None:
        # direction_mix is always live (last-5-min window) — refresh it quickly
        try:
            async with aiosqlite.connect(config.DB_PATH) as _db:
                _db.row_factory = aiosqlite.Row
                dir_q = (
                    "SELECT json_extract(metadata, '$.direction') AS direction, "
                    "signal_type, COUNT(*) AS cnt, AVG(price) AS avg_price "
                    "FROM indicator_signals WHERE created_at >= datetime('now', '-5 minutes') "
                )
                dir_p: list = []
                if symbol:
                    dir_q += "AND symbol = ? "
                    dir_p.append(symbol.upper())
                if indicator_name:
                    dir_q += "AND indicator_name = ? "
                    dir_p.append(indicator_name)
                dir_q += "GROUP BY direction, signal_type LIMIT 20"
                dir_rows = await _db.execute_fetchall(dir_q, dir_p)

            direction_mix = {
                "long": {
                    "entry": {"count": 0, "avg_price": 0.0},
                    "exit": {"count": 0, "avg_price": 0.0},
                },
                "short": {
                    "entry": {"count": 0, "avg_price": 0.0},
                    "exit": {"count": 0, "avg_price": 0.0},
                },
            }
            for r in dir_rows:
                d = (r["direction"] or "long").lower()
                if d not in ("long", "short"):
                    d = "long"
                st = r["signal_type"]
                if st in ("entry", "exit"):
                    direction_mix[d][st] = {
                        "count": r["cnt"],
                        "avg_price": round(r["avg_price"] or 0.0, 2),
                    }
            return {**cached, "direction_mix": direction_mix}
        except Exception:
            return cached  # fallback to fully-cached response on error

    # Build shared WHERE clause once
    conditions: list[str] = []
    params: list = []
    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol.upper())
    if indicator_name:
        conditions.append("indicator_name = ?")
        params.append(indicator_name)

    where_str = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # ── All queries in ONE connection, executed sequentially but without
        #    re-opening the connection (aiosqlite overhead is connection open) ──

        query_totals = "SELECT signal_type, COUNT(*) AS cnt, AVG(confidence_score) AS avg_conf FROM indicator_signals"
        query_totals += where_str + " GROUP BY signal_type"
        totals = await db.execute_fetchall(
            query_totals,
            params,
        )

        query_top = "SELECT indicator_name, COUNT(*) AS cnt FROM indicator_signals"
        query_top += where_str + " GROUP BY indicator_name ORDER BY cnt DESC LIMIT 5"
        top_indicators = await db.execute_fetchall(
            query_top,
            params,
        )

        # Recent high-confidence (last 24h)
        hp_where = (
            where_str + " AND" if where_str else " WHERE"
        ) + " confidence_score > 80 AND created_at >= datetime('now', '-24 hours')"
        query_high = "".join(
            ["SELECT COUNT(*) AS cnt FROM indicator_signals", hp_where]
        )
        recent_high = await db.execute_fetchall(
            query_high,
            params,
        )

        # Top symbols — global (no filter)
        top_symbols = await db.execute_fetchall(
            "SELECT symbol, COUNT(*) AS cnt FROM indicator_signals "
            "GROUP BY symbol ORDER BY cnt DESC LIMIT 6"
        )

        # Market regime from settings
        regime_row = await db.execute_fetchall(
            "SELECT value FROM settings WHERE key = 'market_regime' LIMIT 1"
        )
        market_regime = regime_row[0]["value"] if regime_row else "CHOP"

        # Direction mix — last 5 minutes only (capped for speed)
        dir_base = (
            "SELECT json_extract(metadata, '$.direction') AS direction, "
            "       signal_type, COUNT(*) AS cnt, AVG(price) AS avg_price "
            "FROM indicator_signals "
            "WHERE created_at >= datetime('now', '-5 minutes') "
        )
        dir_params: list = []
        if symbol:
            dir_base += "AND symbol = ? "
            dir_params.append(symbol.upper())
        if indicator_name:
            dir_base += "AND indicator_name = ? "
            dir_params.append(indicator_name)
        dir_base += "GROUP BY direction, signal_type LIMIT 20"

        dir_rows = await db.execute_fetchall(dir_base, dir_params)

    # ── Assemble response ──
    by_type = {
        r["signal_type"]: {"count": r["cnt"], "avg_conf": round(r["avg_conf"] or 0, 1)}
        for r in totals
    }
    total_all = sum(v["count"] for v in by_type.values())
    overall_conf = round(
        sum(v["avg_conf"] * v["count"] for v in by_type.values()) / max(total_all, 1), 1
    )

    direction_mix = {
        "long": {
            "entry": {"count": 0, "avg_price": 0.0},
            "exit": {"count": 0, "avg_price": 0.0},
        },
        "short": {
            "entry": {"count": 0, "avg_price": 0.0},
            "exit": {"count": 0, "avg_price": 0.0},
        },
    }
    for r in dir_rows:
        direction = (r["direction"] or "long").lower()
        if direction not in ("long", "short"):
            direction = "long"
        sig_type = r["signal_type"]
        if sig_type in ("entry", "exit"):
            direction_mix[direction][sig_type] = {
                "count": r["cnt"],
                "avg_price": round(r["avg_price"] or 0.0, 2),
            }

    result = {
        "total": total_all,
        "by_type": by_type,
        "avg_confidence": overall_conf,
        "high_priority_24h": recent_high[0]["cnt"] if recent_high else 0,
        "top_indicators": [
            {"name": r["indicator_name"], "count": r["cnt"]} for r in top_indicators
        ],
        "top_symbols": [
            {"symbol": r["symbol"], "count": r["cnt"]} for r in top_symbols
        ],
        "direction_mix": direction_mix,
        "market_regime": market_regime,
    }
    # Cache everything except direction_mix (direction_mix is live on cache hits)
    _stats_cache_set(
        cache_key, {k: v for k, v in result.items() if k != "direction_mix"}
    )
    return result


# ═══ RAG TEST ENDPOINT ════════════════════════════════════════
@app.get("/api/rag/query")
async def rag_query_endpoint(
    q: str = Query(
        ..., description="Câu truy vấn ngữ nghĩa (vd: 'Quy tắc VCP breakout')"
    ),
    n: int = Query(3, ge=1, le=5, description="Số chunks trả về"),
):
    """
    Test endpoint để truy vấn Knowledge Base trực tiếp.
    Hữu ích để debug và verify RAG hoạt động đúng.
    """
    if not config.RAG_ENABLED:
        raise HTTPException(
            status_code=503, detail="RAG chưa được bật (RAG_ENABLED=false)"
        )

    chunks = rag.query_knowledge(q, n_results=n)
    return {
        "query": q,
        "n_results": len(chunks),
        "chunks": [
            {
                "topic": c["metadata"].get("topic", ""),
                "chapter": c["metadata"].get(
                    "chunk_id", c["metadata"].get("filename", "")
                ),
                "relevance": c["relevance_score"],
                "preview": c["content"][:300] + "..."
                if len(c["content"]) > 300
                else c["content"],
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
    demo: bool = Query(False, description="Include mock/demo trades"),
):
    """Truy van lich su giao dich."""
    return await database.get_trades(
        symbol=symbol,
        limit=limit,
        offset=offset,
        from_date=from_date,
        to_date=to_date,
        demo=demo,
    )


# ═══ PERFORMANCE STATS ENDPOINT ═══════════════════════════════
@app.get("/trades/stats")
async def get_stats_endpoint(
    symbol: Optional[str] = Query(None, description="Filter theo cap giao dich"),
    demo: bool = Query(False, description="Include mock/demo trades"),
):
    """Tinh metrics hieu suat: Win Rate, Profit Factor, Drawdown."""
    return await database.get_stats(symbol=symbol, demo=demo)


# ═══ EQUITY CURVE ENDPOINT ════════════════════════════════════
@app.get("/trades/equity")
async def get_equity_endpoint(
    symbol: Optional[str] = Query(None, description="Filter theo cap giao dich"),
    demo: bool = Query(False, description="Include mock/demo trades"),
):
    """Tra ve equity curve data cho Chart.js."""
    return await database.get_equity_curve(symbol=symbol, demo=demo)


# ═══ TRADE ANALYSIS ENDPOINT ═════════════════════════════════
@app.get("/trades/analysis")
async def get_trade_analysis_endpoint(
    symbol: Optional[str] = Query(None, description="Filter theo cap giao dich"),
    trade_status: Optional[str] = Query(
        None,
        alias="status",
        description="Filter theo status: FILLED, REJECTED, PENDING",
    ),
    from_date: Optional[str] = Query(None, description="ISO format: 2026-01-01"),
    to_date: Optional[str] = Query(None, description="ISO format: 2026-12-31"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    demo: bool = Query(False, description="Include mock/demo trades"),
):
    """Trade analysis with advanced filtering — powers Trade Analysis tab."""
    # Build filter conditions
    conditions = []
    params: list = []

    if symbol:
        conditions.append("t.symbol = ?")
        params.append(symbol.upper())
    if trade_status:
        conditions.append("t.status = ?")
        params.append(trade_status.upper())
    if from_date:
        conditions.append("t.created_at >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("t.created_at <= ?")
        params.append(to_date)
    if not demo:
        conditions.append(
            "(LOWER(t.exchange) = 'weex' OR (t.order_type != 'DRY_RUN' AND t.order_id IS NOT NULL AND t.order_id NOT LIKE 'DRY-%' AND t.order_id NOT LIKE 'ORD%'))"
        )

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Total count
        query_count = "".join(["SELECT COUNT(*) as cnt FROM trades t ", where])
        row = await db.execute_fetchall(query_count, params)
        total = row[0][0] if row else 0

        # Fetch trades
        query_fetch = (
            "SELECT t.*, s.action as signal_action\n"
            "FROM trades t\n"
            "LEFT JOIN signals s ON s.id = t.signal_id\n"
        )
        query_fetch += where + "\n"
        query_fetch += "ORDER BY t.created_at DESC\nLIMIT ? OFFSET ?"
        rows = await db.execute_fetchall(
            query_fetch,
            params + [min(limit, 500), offset],
        )
        trades = [dict(r) for r in rows]

        # Compute analysis stats from FILLED trades in the filter set
        filled_where = f"{where} AND" if where else "WHERE"
        query_stats = "".join(
            [
                "SELECT pnl, symbol FROM trades t ",
                filled_where,
                " t.status = 'FILLED' AND t.pnl IS NOT NULL",
            ]
        )
        stats_rows = await db.execute_fetchall(
            query_stats,
            params,
        )
        pnl_list = [r[0] for r in stats_rows]
        symbol_set = list(set(r[1] for r in stats_rows))

        wins = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p <= 0]

        # Streak calculation
        max_win_streak = 0
        max_loss_streak = 0
        cur_streak = 0
        for p in pnl_list:
            if p > 0:
                if cur_streak > 0:
                    cur_streak += 1
                else:
                    cur_streak = 1
                max_win_streak = max(max_win_streak, cur_streak)
            else:
                if cur_streak < 0:
                    cur_streak -= 1
                else:
                    cur_streak = -1
                max_loss_streak = max(max_loss_streak, abs(cur_streak))

        total_win = sum(wins) if wins else 0.0
        total_loss = abs(sum(losses)) if losses else 0.0

        stats = {
            "total_trades": len(pnl_list),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / len(pnl_list) * 100, 1) if pnl_list else 0.0,
            "total_pnl": round(sum(pnl_list), 2) if pnl_list else 0.0,
            "avg_win": round(total_win / len(wins), 2) if wins else 0.0,
            "avg_loss": round(-total_loss / len(losses), 2) if losses else 0.0,
            "best_trade": round(max(pnl_list), 2) if pnl_list else 0.0,
            "worst_trade": round(min(pnl_list), 2) if pnl_list else 0.0,
            "profit_factor": round(total_win / total_loss, 2)
            if total_loss > 0
            else 999.99,
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
            "symbols_traded": symbol_set,
        }

    return {
        "trades": trades,
        "stats": stats,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


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
        raise HTTPException(
            status_code=403, detail="Access denied: path traversal detected"
        )
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Image not found: {safe_filename}")

    result = await vision_module.analyze_chart_vision(
        image_path=path,
        symbol=symbol.upper(),
    )
    return result


@app.post("/api/vision/capture")
async def api_vision_capture(
    symbol: str = Query("BTCUSDT", description="Symbol to capture"),
    timeframe: str = Query("1h", description="Timeframe to capture"),
    show_parent: str = Query("yes", description="Show parent timeframe inset chart"),
    inset_position: str = Query(
        "bottom-right", description="Position of inset chart: bottom-right or top-left"
    ),
):
    """
    Dashboard-callable Stealth Capture endpoint.
    Combines: MCP CDP screenshot or local rendering → crop → AI Vision → DB persist.
    Returns structured result with screenshot_url for immediate display.
    """
    import json as _json
    from pathlib import Path

    sym = symbol.upper()
    tf = timeframe.upper()

    # ── Step 1: Screenshot Capture ───────────────────────────────
    screenshot_path = None

    if config.MCP_ENABLED:
        try:
            mcp = _mcp_module.get_mcp_client()
            health = await mcp.health_check()
            if health.get("connected"):
                screenshot_path = await mcp.capture_screenshot(symbol=sym, timeframe=tf)
        except Exception as e:
            log.warning(f"MCP CDP capture failed, attempting fallback: {e}")

    if not screenshot_path or not screenshot_path.exists():
        log.info(
            "CDP/MCP capture not available or failed. Falling back to native local capture..."
        )
        try:
            from capture_client import get_capture_client

            client = get_capture_client()
            res = await client.capture_screenshot(
                symbol=sym,
                timeframe=tf,
                method="lightweight-charts",  # Fallback to local rendering
                show_parent_chart=(show_parent.lower() == "yes"),
                inset_position=inset_position.lower(),
            )
            if res.success and res.file_path:
                screenshot_path = Path(res.file_path)
        except Exception as e:
            log.error(f"Local capture failed: {e}")

    if not screenshot_path or not screenshot_path.exists():
        raise HTTPException(
            status_code=500,
            detail="Chart capture failed — both CDP and local rendering are unavailable",
        )

    # ── Step 2: AI Vision Analysis ───────────────────────────────
    try:
        vision_result = await vision_module.analyze_chart_vision(
            image_path=Path(screenshot_path),
            symbol=sym,
        )
    except Exception as e:
        log.error(f"Vision analysis failed: {e}")
        vision_result = {
            "error": "Internal error during vision analysis.",
            "verdict": "ERROR",
            "confidence": 0,
            "analysis": "",
            "patterns": [],
        }

    # Normalize fields (vision module uses 'analysis' not 'ai_analysis')
    analysis_text = vision_result.get("analysis", "")
    confidence = vision_result.get("confidence", 0)
    patterns = vision_result.get("patterns", [])
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
    vision_data_json = _json.dumps(
        {
            "symbol": sym,
            "verdict": verdict,
            "confidence": confidence,
            "patterns": patterns,
            "combined_score": vision_result.get("combined_score", f"{confidence}/10"),
        },
        ensure_ascii=False,
    )
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
        await _asyncio.to_thread(
            notifier.send_telegram_photo, screenshot_path, tg_caption
        )
    except Exception as _tg_err:
        log.warning(f"Telegram photo send failed: {_tg_err}")

    return {
        "status": "ok",
        "brief_id": brief_id,
        "symbol": sym,
        "verdict": verdict,
        "confidence": confidence,
        "patterns": patterns,
        "ai_analysis": analysis_text,
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
                if c:
                    confidences.append(c)
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)
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
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning("Ignored: %s", e)

        screenshot = b.get("screenshot", "")
        # Determine if screenshot is accessible (serve from /api/vision/screenshot/<id>)
        result.append(
            {
                "id": b["id"],
                "created_at": b["created_at"],
                "symbol": vision_data.get("symbol", "—"),
                "ai_analysis": b.get("ai_analysis", ""),
                "confidence": vision_data.get("confidence", 0),
                "patterns": vision_data.get("patterns", []),
                "combined_score": vision_data.get("combined_score", "—"),
                "verdict": vision_data.get("verdict", ""),
                "has_screenshot": bool(screenshot),
                "screenshot_url": f"/api/vision/screenshot/{b['id']}"
                if screenshot
                else None,
                "source": "stealth"
                if "[Stealth Capture]" in (b.get("brief_text") or "")
                else "morning_brief",
            }
        )
    return {"items": result, "total": data.get("total", 0)}


@app.get("/api/vision/screenshot/{brief_id}")
async def get_vision_screenshot(brief_id: int):
    """Serve screenshot image for a vision analysis entry."""
    from fastapi.responses import FileResponse

    brief = await database.get_brief_by_id(brief_id)
    if not brief or not brief.get("screenshot"):
        raise HTTPException(status_code=404, detail="No screenshot for this brief")

    # SEC-4 R2: Use safe_screenshot_path to prevent path traversal (CWE-22).
    # The raw path comes from the database; we must canonicalize before serving.
    try:
        img_path = safe_screenshot_path(brief["screenshot"])
    except _SecurityError as e:
        raise HTTPException(status_code=403, detail=f"Access denied: {e}") from e
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404, detail=f"Screenshot file not found: {brief['screenshot']}"
        ) from e

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

    # Retrieve health checks and test status from DB settings
    try:
        health_api_server = await database.get_setting("health_api_server", "UNKNOWN")
    except Exception:
        health_api_server = "ERROR"

    try:
        health_cdp = await database.get_setting("health_cdp", "UNKNOWN")
    except Exception:
        health_cdp = "ERROR"

    try:
        health_database = await database.get_setting("health_database", "UNKNOWN")
    except Exception:
        health_database = "ERROR"

    try:
        test_runner_status = await database.get_setting("test_runner_status", "UNKNOWN")
    except Exception:
        test_runner_status = "UNKNOWN"

    import json as _json

    last_test_run = None
    try:
        last_test_run_str = await database.get_setting("last_test_run")
        if last_test_run_str:
            last_test_run = _json.loads(last_test_run_str)
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Ignored: %s", e)

    # VBS status
    vbs_status = {"enabled": False, "connected": False, "pending_count": 0}
    if config.VPS_BUFFER_ENABLED and config.VPS_BUFFER_URL:
        try:
            url = f"{config.VPS_BUFFER_URL}/health"
            headers = {"X-Buffer-Secret": config.VPS_BUFFER_SECRET}
            import aiohttp
            import socket

            conn = aiohttp.TCPConnector(family=socket.AF_INET)
            async with aiohttp.ClientSession(connector=conn) as session:
                async with session.get(url, headers=headers, timeout=2.0) as resp:
                    if resp.status == 200:
                        h_data = await resp.json()
                        vbs_status = {
                            "enabled": True,
                            "connected": True,
                            "pending_count": h_data.get("pending_count", 0),
                            "db": h_data.get("db", "unknown"),
                            "uptime": h_data.get("uptime_seconds", 0),
                        }
                    else:
                        vbs_status = {
                            "enabled": True,
                            "connected": False,
                            "error": f"HTTP {resp.status}",
                        }
        except Exception as e:
            vbs_status = {"enabled": True, "connected": False, "error": str(e)}

    try:
        regime = await database.get_setting("market_regime", "TRENDING")
    except Exception:
        regime = "TRENDING"

    try:
        safe_mode_str = await database.get_setting("safe_mode_active", "false")
        safe_mode_active = safe_mode_str.lower() == "true"
    except Exception:
        safe_mode_active = False

    try:
        dd_str = await database.get_setting("safe_mode_drawdown", "0.0")
        safe_mode_drawdown = float(dd_str)
    except Exception:
        safe_mode_drawdown = 0.0

    protection = {
        "market_regime": regime,
        "safe_mode_active": safe_mode_active,
        "safe_mode_drawdown": safe_mode_drawdown,
    }

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
        "health_api_server": health_api_server,
        "health_cdp": health_cdp,
        "health_database": health_database,
        "test_runner_status": test_runner_status,
        "last_test_run": last_test_run,
        "vbs": vbs_status,
        "protection": protection,
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

    # ── Serialise ──────────────────────────────────────────────────────────────
    serialised = [
        {
            "symbol": r.symbol,
            "price": r.price,
            "change_pct": r.change_pct,
            "trend_template_score": r.trend_template.score if r.trend_template else 0,
            "trend_template_stage": r.trend_template.stage if r.trend_template else "-",
            "trend_template_criteria": r.trend_template.criteria
            if r.trend_template
            else [],
            "vcp_detected": r.vcp.detected if r.vcp else False,
            "vol_breakout": getattr(r.vcp, "vol_breakout", False) if r.vcp else False,
            "volume_ratio": round(r.vcp.volume_ratio, 2) if r.vcp else 0,
            "range_ratio": round(r.vcp.range_ratio, 2) if r.vcp else 0,
            "pivot_level": r.vcp.pivot_level if r.vcp else None,
            "vcp_note": r.vcp.note if r.vcp else None,
            "error": r.error,
        }
        for r in results
    ]

    # ── Save to shared cache ──────────────────────────────────────────────────
    import scan_cache

    scan_cache.save_scan_results(serialised, source="web", symbol_list=symbol_list)

    # ── Notify Telegram ───────────────────────────────────────────────────────
    try:
        from notifier import send_scan_summary_to_telegram
        import asyncio

        asyncio.create_task(send_scan_summary_to_telegram(serialised))
    except Exception as _te:
        log.warning(f"Telegram scan notify failed (non-fatal): {_te}")

    ts = datetime.now(timezone.utc).isoformat()

    # ── Push scan_complete SSE to all browser tabs ────────────────────────────
    push_sse_event(
        "scan_complete", {"scanned": len(results), "timestamp": ts, "source": "web"}
    )

    return {"scanned": len(results), "timestamp": ts, "results": serialised}


@app.get("/api/scan/last")
async def get_last_scan_endpoint():
    """Return the most recent scan results from the shared in-memory cache.

    Used by the dashboard to restore last scan without re-running.
    Returns 204 if no scan has been run yet.
    """
    import scan_cache

    if not scan_cache.has_results():
        return JSONResponse(status_code=204, content=None)
    return scan_cache.get_last_scan()


# \u2550\u2550\u2550 SSE EVENTS STREAM \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550


@app.get("/api/events")
async def sse_events(request: Request):
    """Server-Sent Events stream.

    Browser connects once; server pushes events (new_signal, scan_complete,
    heartbeat) without polling.  Each tab opens its own connection.
    """
    client_q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_clients.add(client_q)

    async def _stream():
        try:
            # Initial handshake
            yield "event: connected\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(client_q.get(), timeout=15)
                    yield msg
                except asyncio.TimeoutError:
                    # Heartbeat — keeps proxy/browser from closing idle connection
                    yield "event: heartbeat\ndata: {}\n\n"
        finally:
            _sse_clients.discard(client_q)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


from pydantic import BaseModel  # noqa: E402


class OverrideRequest(BaseModel):
    exchange: str
    action: str


class RiskSettingsUpdateRequest(BaseModel):
    exchange: str
    daily_loss_cap: float
    drawdown_cap: float
    max_quote_qty: float
    slippage_limit: float
    safe_mode: int


@app.get("/api/risk/status")
async def get_risk_status():
    """Get dynamic status and circuit breaker state of security gates."""
    try:
        return await database.get_all_risk_statuses()
    except Exception as e:
        log.exception(f"Settings retrieval error: {e}")
        raise HTTPException(
            status_code=500,
            detail="An internal server error occurred while retrieving settings.",
        )


@app.get("/api/risk/logs")
async def get_risk_logs(limit: int = Query(10, ge=1, le=50)):
    """Get recent circuit breaker logs."""
    try:
        return await database.get_recent_circuit_breaker_logs(limit)
    except Exception as e:
        log.exception(f"Settings update error: {e}")
        raise HTTPException(
            status_code=500,
            detail="An internal server error occurred while updating settings.",
        )


@app.post("/api/risk/override")
async def post_risk_override(req: OverrideRequest):
    """Manually trip, reset or override the circuit breaker for an exchange."""
    try:
        ex = req.exchange.lower()
        act = req.action.lower()

        if act == "reset":
            prev_status = await database.get_risk_settings(ex)
            prev_state = prev_status.get("state", "CLOSED")
            await database.update_circuit_breaker_state(ex, "CLOSED")
            await database.log_circuit_breaker(
                ex,
                "*",
                prev_state,
                "CLOSED",
                "Manual override reset via dashboard",
                {"action": "reset"},
            )
            return {
                "status": "success",
                "message": f"Circuit breaker for {ex} reset to CLOSED",
            }
        elif act == "trip":
            prev_status = await database.get_risk_settings(ex)
            prev_state = prev_status.get("state", "CLOSED")
            await database.update_circuit_breaker_state(ex, "OPEN")
            await database.log_circuit_breaker(
                ex,
                "*",
                prev_state,
                "OPEN",
                "Manual override trip via dashboard",
                {"action": "trip"},
            )
            return {
                "status": "success",
                "message": f"Circuit breaker for {ex} tripped to OPEN",
            }
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported override action: {act}"
            )
    except Exception as e:
        log.exception(f"Overrides save error: {e}")
        raise HTTPException(
            status_code=500,
            detail="An internal server error occurred while updating overrides.",
        )


@app.get("/api/risk/settings")
async def get_risk_settings_endpoint(exchange: str = Query(...)):
    """Get the current risk settings for an exchange."""
    try:
        return await database.get_risk_settings(exchange)
    except Exception as e:
        log.exception(f"Risk settings retrieval error: {e}")
        raise HTTPException(
            status_code=500,
            detail="An internal server error occurred while retrieving risk settings.",
        )


@app.post("/api/risk/settings")
async def update_risk_settings_endpoint(req: RiskSettingsUpdateRequest):
    """Update risk settings thresholds for an exchange."""
    try:
        await database.save_risk_settings(
            exchange=req.exchange,
            daily_loss_cap=req.daily_loss_cap,
            drawdown_cap=req.drawdown_cap,
            max_quote_qty=req.max_quote_qty,
            slippage_limit=req.slippage_limit,
            safe_mode=req.safe_mode,
        )
        return {
            "status": "success",
            "message": f"Risk settings updated for {req.exchange}",
        }
    except Exception as e:
        log.exception(f"Risk settings update error: {e}")
        raise HTTPException(
            status_code=500,
            detail="An internal server error occurred while updating risk settings.",
        )


if __name__ == "__main__":
    import uvicorn

    log.info(f"Starting FastAPI Webhook Server v7.6 on {config.HOST}:{config.PORT}")
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=config.DEBUG)
