import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Server Settings
PORT = int(os.getenv("PORT", "5000"))
HOST = os.getenv("HOST", "127.0.0.1")

# Security
# This secret MUST match the VPS_BUFFER_SECRET set in the Local Bot
BUFFER_SECRET = os.getenv("BUFFER_SECRET", "")

# Queue Configs
SIGNAL_TTL_HOURS = float(os.getenv("SIGNAL_TTL_HOURS", "4.0"))
DISPATCH_TIMEOUT_MINUTES = float(os.getenv("DISPATCH_TIMEOUT_MINUTES", "5.0"))
MAX_QUEUE_SIZE = int(os.getenv("MAX_QUEUE_SIZE", "1000"))

# Telegram Notifications
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Scheduler Configs
CLEANUP_INTERVAL_MINUTES = int(os.getenv("CLEANUP_INTERVAL_MINUTES", "15"))
AUDIT_RETENTION_DAYS = int(os.getenv("AUDIT_RETENTION_DAYS", "7"))

# Database
DB_PATH = os.getenv("DB_PATH", "signal_queue.db")

# Dedup: reject same (symbol, action, price) within this window
DEDUP_WINDOW_SECONDS = int(os.getenv("DEDUP_WINDOW_SECONDS", "10"))
