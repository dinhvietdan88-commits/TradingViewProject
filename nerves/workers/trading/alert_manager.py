import logging
import os
import sqlite3
from typing import Optional
import config

logger = logging.getLogger(__name__)

# Configure a file logger specifically for test runs
test_runs_logger = logging.getLogger("test_runs")
log_file_path = os.path.join(os.path.dirname(__file__), "test_runs.log")

# Setup custom file handler if not already present
if not test_runs_logger.handlers:
    test_runs_logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    formatter = logging.Formatter(
        "[%(asctime)s] | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    test_runs_logger.addHandler(file_handler)

def log_test_run(success: bool, summary: str, error_log: str = ""):
    """Log test runs to nerves/workers/trading/test_runs.log."""
    status_str = "PASSED" if success else "FAILED"
    log_level = logging.INFO if success else logging.ERROR
    msg = f"Test Run {status_str}: {summary}"
    if error_log:
        msg += f"\nError Details:\n{error_log}"
    test_runs_logger.log(log_level, msg)

def get_setting_sync(key: str, default: Optional[str] = None) -> Optional[str]:
    """Synchronously get setting from the DB."""
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default
    except Exception as e:
        logger.error(f"Error reading setting {key} sync: {e}")
        return default

def set_setting_sync(key: str, value: str) -> None:
    """Synchronously set setting in the DB."""
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error setting setting {key} sync to {value}: {e}")

async def set_setting_async(key: str, value: str) -> None:
    """Asynchronously set setting in the DB."""
    import aiosqlite
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Error setting setting {key} async to {value}: {e}")

async def get_setting_async(key: str, default: Optional[str] = None) -> Optional[str]:
    """Asynchronously get setting from the DB."""
    import aiosqlite
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            query = "SELECT value FROM settings WHERE key = ?"
            async with db.execute(query, (key,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else default
    except Exception as e:
        logger.error(f"Error getting setting {key} async: {e}")
        return default

async def handle_test_failure_alert(filename: str, traceback_short: str):
    """
    Sends a Telegram alert for a test failure.
    Includes the filename and a shortened traceback (e.g. last 8 lines).
    """
    message = (
        f"🚨 <b>Test Failure Detected!</b>\n\n"
        f"<b>File:</b> <code>{filename}</code>\n"
        f"<b>Traceback (Last 8 lines):</b>\n"
        f"<pre>{traceback_short}</pre>"
    )
    try:
        from notifier import send_telegram_alert
        await send_telegram_alert(message)
    except Exception as e:
        logger.error(f"Failed to send Telegram alert for test failure: {e}")

async def handle_health_check_transition(
    check_name: str, status: str, error_message: str = ""
):
    """
    Checks if a health check transitioned from "OK" (or non-ERROR) to "ERROR".
    Updates the setting key and sends a Telegram alert if a transition occurs.
    """
    setting_key = f"health_{check_name}"
    prev_status = await get_setting_async(setting_key)

    # Update status in settings table
    await set_setting_async(setting_key, status)

    # Only alert if previous status was OK (or not ERROR) and new is ERROR
    if prev_status != "ERROR" and status == "ERROR":
        message = (
            f"🚨 <b>System Health Check Failed!</b>\n\n"
            f"<b>Component:</b> <code>{check_name}</code>\n"
            f"<b>Status:</b> {status}\n"
            f"<b>Details:</b> <code>{error_message}</code>"
        )
        try:
            # Send alert
            from notifier import send_telegram_alert
            await send_telegram_alert(message)
            # Log transition to log file
            test_runs_logger.error(
                f"Health check '{check_name}' failed: {error_message}"
            )
        except Exception as e:
            logger.error(f"Failed to send Telegram alert for health check failure: {e}")
