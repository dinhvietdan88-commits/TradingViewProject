import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 5000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Security
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change_me_in_dotenv")

# Logging
LOG_FILE = os.getenv("LOG_FILE", "trades.log")

# Database (Sprint 4)
DB_PATH = os.getenv("DB_PATH", "trades.db")

# Binance (optional)
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_TESTNET    = os.getenv("BINANCE_TESTNET", "true").lower() == "true"
BINANCE_DRY_RUN    = os.getenv("BINANCE_DRY_RUN", "true").lower() == "true"

# Bybit (Sprint 7.2)
BYBIT_API_KEY      = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET   = os.getenv("BYBIT_API_SECRET", "")
BYBIT_TESTNET      = os.getenv("BYBIT_TESTNET", "true").lower() == "true"
BYBIT_DRY_RUN      = os.getenv("BYBIT_DRY_RUN", "true").lower() == "true"

# Multi-Exchange Routing
DEFAULT_EXCHANGE   = os.getenv("DEFAULT_EXCHANGE", "binance")
STRATEGY_EXCHANGE_MAP = os.getenv("STRATEGY_EXCHANGE_MAP", "{}")  # JSON string e.g. '{"strategy_1": {"exchange": "bybit", "fallback": "binance"}}'
EXCHANGE_HEALTH_INTERVAL = int(os.getenv("EXCHANGE_HEALTH_INTERVAL", "60"))

# TVP-006: Safety override for DRY_RUN
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
if ENVIRONMENT == "production" and not BINANCE_DRY_RUN:
    if os.getenv("FORCE_LIVE_TRADING", "false").lower() != "true":
        import logging
        logging.getLogger(__name__).warning("PRODUCTION TRADING ENABLED: Forcing BINANCE_DRY_RUN=True. Set FORCE_LIVE_TRADING=true to override.")
        BINANCE_DRY_RUN = True

# Risk Management (Minervini SEPA rules)
RISK_PER_TRADE     = float(os.getenv("RISK_PER_TRADE", "0.02"))     # 2% per trade
STOP_LOSS_PCT      = float(os.getenv("STOP_LOSS_PCT", "0.08"))      # 8% SL
TAKE_PROFIT_PCT    = float(os.getenv("TAKE_PROFIT_PCT", "0.20"))    # 20% TP → R:R ≥ 2.5
MAX_QUOTE_QTY      = float(os.getenv("MAX_QUOTE_QTY", "1000"))      # Max trade size limit

# Notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
# Multi-user broadcast: TELEGRAM_CHAT_ID can be a single id or CSV ("111,222,333")
TELEGRAM_CHAT_IDS  = [c.strip() for c in TELEGRAM_CHAT_ID.split(",") if c.strip()]
DISCORD_WEBHOOK_URL= os.getenv("DISCORD_WEBHOOK_URL", "")

# Optional HTTP/SOCKS5 proxy for Telegram (e.g. "http://127.0.0.1:8090")
TELEGRAM_PROXY_URL = os.getenv("TELEGRAM_PROXY_URL", "")


# TradingView Whitelist IPs
TV_WHITELIST_IPS = {
    "52.89.214.238",
    "34.212.75.30",
    "54.218.53.128",
    "52.32.178.7"
}
ENABLE_IP_WHITELIST = os.getenv("ENABLE_IP_WHITELIST", "false").lower() == "true"

# ── RAG / Knowledge Base ──────────────────────────────────────────────────
# Đường dẫn tới thư mục chứa các file chunk Markdown của Minervini
KNOWLEDGE_DIR = os.getenv(
    "KNOWLEDGE_DIR",
    str((Path(__file__).resolve().parent.parent / "docs" / "knowledge" / "trading_wizard" / "chunks").absolute())
)

# Đường dẫn lưu ChromaDB vector database (persistent trên disk)
CHROMA_DB_PATH = os.getenv(
    "CHROMA_DB_PATH",
    str(Path(__file__).parent / "chroma_db")
)

# Anthropic (Claude) API Key — dùng cho bước Generation trong RAG
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# AI Provider: "anthropic" hoặc "gemini"
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").lower()

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

# Server start time (for uptime calculation)
import time as _time
SERVER_START_TIME = _time.time()

