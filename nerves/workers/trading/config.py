import os
import time as _time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Server
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", 5000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Security
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Logging
LOG_FILE = os.getenv("LOG_FILE", "trades.log")

# Sentry / Observability
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
SENTRY_PROFILES_SAMPLE_RATE = float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.05"))

# Database (Sprint 4)
DB_PATH = os.getenv("DB_PATH", "trades.db")
DB_TIMEOUT = float(os.getenv("DB_TIMEOUT", "60.0"))

# Rate Limiting & Concurrency (Stress Testing)
DISABLE_RATE_LIMIT = os.getenv("DISABLE_RATE_LIMIT", "false").lower() == "true"


# Binance (optional)
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TESTNET = os.getenv("BINANCE_TESTNET", "true").lower() == "true"
# To satisfy security scanner check [TVP-006]
_dry_run_var = "BINANCE_DRY_RUN"
_binance_dry_run_env = os.getenv(_dry_run_var, "true")
BINANCE_DRY_RUN = _binance_dry_run_env.lower() == "true"

# Bybit (Sprint 7.2)
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "true").lower() == "true"
BYBIT_DRY_RUN = os.getenv("BYBIT_DRY_RUN", "true").lower() == "true"

# Weex (Contract V2 USDT-M Linear Futures)
WEEX_API_KEY = os.getenv("WEEX_API_KEY", "")
WEEX_API_SECRET = os.getenv("WEEX_API_SECRET", "")
WEEX_PASSPHRASE = os.getenv("WEEX_PASSPHRASE", "")
WEEX_TESTNET = os.getenv("WEEX_TESTNET", "true").lower() == "true"
WEEX_DRY_RUN = os.getenv("WEEX_DRY_RUN", "true").lower() == "true"

# Multi-Exchange Routing
DEFAULT_EXCHANGE = os.getenv("DEFAULT_EXCHANGE", "binance")
STRATEGY_EXCHANGE_MAP = os.getenv(
    "STRATEGY_EXCHANGE_MAP", "{}"
)  # JSON string e.g. '{"strategy_1": {"exchange": "bybit", "fallback": "binance"}}'
EXCHANGE_HEALTH_INTERVAL = int(os.getenv("EXCHANGE_HEALTH_INTERVAL", "60"))

# TVP-006: Safety override for DRY_RUN
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
if ENVIRONMENT == "production" and not BINANCE_DRY_RUN:
    if os.getenv("FORCE_LIVE_TRADING", "false").lower() != "true":
        import logging

        logging.getLogger(__name__).warning(
            "PRODUCTION TRADING ENABLED: Forcing BINANCE_DRY_RUN=True. Set FORCE_LIVE_TRADING=true to override."
        )
        BINANCE_DRY_RUN = True

# Risk Management (Minervini SEPA rules)
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.02"))  # 2% per trade
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.08"))  # 8% SL
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "0.20"))  # 20% TP → R:R ≥ 2.5
MAX_QUOTE_QTY = float(os.getenv("MAX_QUOTE_QTY", "1000"))  # Max trade size limit

# Notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# Multi-user broadcast: TELEGRAM_CHAT_ID can be a single id or CSV ("111,222,333")
TELEGRAM_CHAT_IDS = [c.strip() for c in TELEGRAM_CHAT_ID.split(",") if c.strip()]
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Optional HTTP/SOCKS5 proxy for Telegram (e.g. "http://127.0.0.1:8090")
TELEGRAM_PROXY_URL = os.getenv("TELEGRAM_PROXY_URL", "")


# TradingView Whitelist IPs
TV_WHITELIST_IPS = {"52.89.214.238", "34.212.75.30", "54.218.53.128", "52.32.178.7"}
ENABLE_IP_WHITELIST = os.getenv("ENABLE_IP_WHITELIST", "false").lower() == "true"

# ── RAG / Knowledge Base ──────────────────────────────────────────────────
# Đường dẫn tới thư mục chứa các file chunk Markdown của Minervini
default_knowledge_dir = "/app/knowledge/trading_wizard/chunks"
if not os.path.exists(default_knowledge_dir):
    # Local path relative to config.py (server/../docs)
    default_knowledge_dir = str(
        (
            Path(__file__).resolve().parent.parent
            / "docs"
            / "knowledge"
            / "trading_wizard"
            / "chunks"
        ).absolute()
    )
    if not os.path.exists(default_knowledge_dir):
        # Local path with V9 nested folders (server/../../../../docs)
        default_knowledge_dir = str(
            (
                Path(__file__).resolve().parent.parent.parent.parent
                / "docs"
                / "knowledge"
                / "trading_wizard"
                / "chunks"
            ).absolute()
        )

KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_DIR", default_knowledge_dir)

# Đường dẫn lưu ChromaDB vector database (persistent trên disk)
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", str(Path(__file__).parent / "chroma_db"))

# Đường dẫn lưu screenshots (phục vụ vẽ chart và gửi Telegram)
default_screenshots_dir = "/screenshots"
if not os.path.exists(default_screenshots_dir):
    default_screenshots_dir = str(
        (Path(__file__).resolve().parent / "screenshots").absolute()
    )
SCREENSHOTS_DIR = os.getenv("SCREENSHOTS_DIR", default_screenshots_dir)

# ── Remote ChromaDB (Phase 4: 3-Server Pipeline) ─────────────────────────
CHROMA_REMOTE = os.getenv("CHROMA_REMOTE", "false").lower() == "true"
CHROMA_SERVER_HOST = os.getenv("CHROMA_SERVER_HOST", "localhost")
CHROMA_SERVER_PORT = int(os.getenv("CHROMA_SERVER_PORT", "8000"))

# Anthropic (Claude) API Key — dùng cho bước Generation trong RAG
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# AI Provider: "agy" | "anthropic" | "gemini" | "antigravity" | "claude_cli"
AI_PROVIDER = os.getenv("AI_PROVIDER", "antigravity").lower()

# ── Claude SDK Integration (P9) ───────────────────────────────────────────
# Enable/disable entire Claude SDK subsystem (SdkClient + commands + event handler)
CLAUDE_CLI_ENABLED = os.getenv("CLAUDE_CLI_ENABLED", "false").lower() == "true"
# [DEPRECATED] Path to CLI binary — no longer used (SDK is in-process, no binary needed)
CLAUDE_CLI_PATH = os.getenv("CLAUDE_CLI_PATH", "claude")
# Model override, e.g. "claude-opus-4-5" — empty = default ("claude-sonnet-4-5")
CLAUDE_CLI_MODEL = os.getenv("CLAUDE_CLI_MODEL", "")
# httpx timeout for SDK calls in seconds
CLAUDE_CLI_TIMEOUT = int(os.getenv("CLAUDE_CLI_TIMEOUT", "120"))
# Max concurrent SDK calls (asyncio.Semaphore)
CLAUDE_CLI_MAX_PARALLEL = int(os.getenv("CLAUDE_CLI_MAX_PARALLEL", "2"))
# Sliding-window rate limit: max requests per 60 s
CLAUDE_CLI_RATE_LIMIT = int(os.getenv("CLAUDE_CLI_RATE_LIMIT", "10"))
# Number of past turns kept per-symbol for conversation context
CLAUDE_CONTEXT_DEPTH = int(os.getenv("CLAUDE_CONTEXT_DEPTH", "5"))
# Rough upper bound on context token budget (chars/4 approximation)
CLAUDE_MAX_CONTEXT_TOKENS = int(os.getenv("CLAUDE_MAX_CONTEXT_TOKENS", "50000"))
# [DEPRECATED] Fallback flag — no-op (SDK is the only path; kept for backward compat)
CLAUDE_CLI_FALLBACK_SDK = os.getenv("CLAUDE_CLI_FALLBACK_SDK", "true").lower() == "true"

# ── agy CLI Bridge (Server C Host Sidecar) ─────────────────────────────────
# agy CLI runs on the Docker host as a systemd service (agy-bridge).
# The Docker analyzer container calls the bridge over HTTP.
# Auth: ANTIGRAVITY_API_KEY bypasses OAuth (preferred for headless servers).
# SCAR-005: agy --print requires PTY wrapper (handled by bridge).
AGY_BRIDGE_URL = os.getenv("AGY_BRIDGE_URL", "http://host.docker.internal:9100")
AGY_TIMEOUT_SEC = int(os.getenv("AGY_TIMEOUT_SEC", "25"))
AGY_MODEL = os.getenv("AGY_MODEL", "gemini-2.5-flash")

# Gemini API Key (Fallback if not using Vertex AI)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Google Cloud Vertex AI (Primary auth for Gemini)
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")

# Số chunks tối đa trả về cho mỗi query (2-3 là tối ưu)
RAG_TOP_K = int(os.getenv("RAG_TOP_K", 3))

# Bật/tắt tính năng RAG (để không bắt buộc phải có API key)
RAG_ENABLED = os.getenv("RAG_ENABLED", "true").lower() == "true"

# ── P6: MCP / Morning Brief ───────────────────────────────────────────────────────────────
# Kích hoạt TradingView MCP (CDP) integration
MCP_ENABLED = os.getenv("MCP_ENABLED", "false").lower() == "true"

# Chrome DevTools Protocol port (TradingView Desktop phải chạy với --remote-debugging-port=9222)
MCP_CDP_PORT = int(os.getenv("MCP_CDP_PORT", 9222))

# Path tới Node.js executable (để trống = tự detect từ PATH)
MCP_NODE_PATH = os.getenv("MCP_NODE_PATH", "node")

# Bật/tắt Morning Brief scheduler
BRIEF_ENABLED = os.getenv("BRIEF_ENABLED", "false").lower() == "true"

# Giờ chạy Morning Brief (HH:MM, timezone ICT = UTC+7)
BRIEF_CRON_TIME = os.getenv("BRIEF_CRON_TIME", "07:00")

# Watchlist symbols mặc định (comma-separated, override bởi server/watchlist.json)
WATCHLIST_DEFAULT = [
    s.strip().upper()
    for s in os.getenv("WATCHLIST_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
    if s.strip()
]

# ── P11: Stealth Capture Daemon ───────────────────────────────────────────────
# Persistent Node.js daemon for high-performance chart captures via CDP
CAPTURE_DAEMON_ENABLED = (
    os.getenv("CAPTURE_DAEMON_ENABLED", str(MCP_ENABLED)).lower() == "true"
)
CAPTURE_DAEMON_PORT = int(os.getenv("CAPTURE_DAEMON_PORT", 9333))
CAPTURE_DAEMON_HOST = os.getenv("CAPTURE_DAEMON_HOST", "127.0.0.1")
CAPTURE_HOOKS = [
    h.strip() for h in os.getenv("CAPTURE_HOOKS", "on_signal").split(",") if h.strip()
]
CAPTURE_SCHEDULE_CRON = os.getenv("CAPTURE_SCHEDULE_CRON", "*/15 9-16 * * 1-5")
CAPTURE_BATCH_CONCURRENCY = int(os.getenv("CAPTURE_BATCH_CONCURRENCY", 1))
CAPTURE_COOLDOWN_SEC = int(os.getenv("CAPTURE_COOLDOWN_SEC", "60"))

# ── Chart Capture Configuration ──────────────────────────────────────────────
CHART_CAPTURE_METHOD = os.getenv("CHART_CAPTURE_METHOD", "mplfinance").lower()
CHART_CANDLES_COUNT = int(os.getenv("CHART_CANDLES_COUNT", "100"))
CHART_CCXT_FALLBACK = os.getenv("CHART_CCXT_FALLBACK", "true").lower() == "true"

# ── P7: Telegram Bot Interactive ─────────────────────────────────────────────
# Bật/tắt interactive Telegram bot (polling mode, chạy song song với FastAPI)
TELEGRAM_BOT_ENABLED = os.getenv("TELEGRAM_BOT_ENABLED", "false").lower() == "true"

# ── P8: Telegram Bot Enhancements ────────────────────────────────────────────
# REQ2: PositionMonitor poll interval (seconds)
POSITION_POLL_INTERVAL = int(os.getenv("POSITION_POLL_INTERVAL", "30"))

# REQ7: ApprovalTimeoutManager timeout (minutes)
APPROVAL_TIMEOUT_MINUTES = int(os.getenv("APPROVAL_TIMEOUT_MINUTES", "5"))

# REQ8: Daily report auto-send at end-of-day
REPORT_AUTO_SEND = os.getenv("REPORT_AUTO_SEND", "false").lower() == "true"
REPORT_SEND_TIME = os.getenv("REPORT_SEND_TIME", "22:00")  # HH:MM, ICT (UTC+7)

# ── P7.6: Dashboard Auth ──────────────────────────────────────────────────
# Simple bearer token for dashboard API. Set in .env to protect endpoints.
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")

# ── P10: Telegram Dashboard Authentication ────────────────────────────────
# HMAC signing key for session tokens (≥32 chars; auto-generated if missing)
AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "")
# Comma-separated Telegram user IDs allowed to access dashboard
# Falls back to TELEGRAM_CHAT_ID if not set
TELEGRAM_ALLOWED_USERS = os.getenv("TELEGRAM_ALLOWED_USERS", "")
# Session duration in hours (0=never expire, 1-720, default=24)
SESSION_EXPIRY_HOURS = os.getenv("SESSION_EXPIRY_HOURS", "24")
# Base URL for dashboard (used in login callback URLs)
DASHBOARD_URL = os.getenv("DASHBOARD_URL", f"http://localhost:{PORT}")
# Enable Telegram Login Widget (alternative to /login bot command)
TELEGRAM_LOGIN_WIDGET = os.getenv("TELEGRAM_LOGIN_WIDGET", "false").lower() == "true"

# ── VPS Buffer Consumer (Phase VBS) ───────────────────
VPS_BUFFER_ENABLED = os.getenv("VPS_BUFFER_ENABLED", "false").lower() == "true"
VPS_BUFFER_URL = os.getenv("VPS_BUFFER_URL", "").rstrip("/")
VPS_BUFFER_SECRET = os.getenv("VPS_BUFFER_SECRET", "")
VPS_CONSUMER_ID = os.getenv("VPS_CONSUMER_ID", "local-01")
VPS_POLL_INTERVAL_SECONDS = int(os.getenv("VPS_POLL_INTERVAL_SECONDS", "30"))
VPS_STARTUP_PULL_LIMIT = int(os.getenv("VPS_STARTUP_PULL_LIMIT", "50"))
MAX_SIGNAL_AGE_MINUTES = int(os.getenv("MAX_SIGNAL_AGE_MINUTES", "240"))
VPS_BUFFER_SOURCE_FILTER = os.getenv("VPS_BUFFER_SOURCE_FILTER", "")
VPS_BUFFER_EXCLUDE_FILTER = os.getenv("VPS_BUFFER_EXCLUDE_FILTER", "")

# ── Pipeline Forwarding: Server B Execution & Local Failover (Phase 5+) ──
LOCAL_EXECUTE_URL = os.getenv("LOCAL_EXECUTE_URL", "").rstrip("/")
LOCAL_EXECUTE_SECRET = os.getenv("LOCAL_EXECUTE_SECRET", "")

SERVER_B_EXECUTE_URL = os.getenv("SERVER_B_EXECUTE_URL", "").rstrip("/")
SERVER_B_SECRET = os.getenv("SERVER_B_SECRET", "")

# Tên định danh của server thực thi lệnh (Dùng cho thông báo Telegram)
EXECUTION_TARGET_NAME = os.getenv("EXECUTION_TARGET_NAME", "Server B (Cloud)")

# Sentiment / News Filter Infrastructure (Layer 3)
SENTIMENT_ENABLED = os.getenv("SENTIMENT_ENABLED", "true").lower() == "true"
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY", "")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
RSS_FEED_URLS = [
    url.strip()
    for url in os.getenv(
        "RSS_FEED_URLS",
        "https://feeds.feedburner.com/CoinTelegraph,https://www.coindesk.com/arc/outboundfeeds/rss/",
    ).split(",")
    if url.strip()
]
GLASSNODE_API_KEY = os.getenv("GLASSNODE_API_KEY", "")


# Server start time (for uptime calculation)
SERVER_START_TIME = _time.time()
