"""
server/logging_config.py — Production-grade logging with rotation (V2 Hardened).

Replaces ad-hoc basicConfig() calls throughout the codebase with a single
setup_logging() function that should be called once at application startup
(e.g. from server/main.py or server/start_server.py).

Features:
  - RotatingFileHandler: splits log files at LOG_MAX_SIZE_MB, keeps LOG_BACKUP_COUNT
  - Console handler: always INFO (human-readable)
  - File handler: respects LOG_LEVEL env var (INFO in production, DEBUG when needed)
  - Optional JSON structured logging (set LOG_JSON_FORMAT=true)
  - Noise suppression for verbose third-party loggers

Environment variables (all have defaults — zero config required):
  LOG_LEVEL         = INFO          # DEBUG | INFO | WARNING | ERROR | CRITICAL
  LOG_FILE          = logs/trading.log
  LOG_MAX_SIZE_MB   = 10            # Max size of each rotating file (MB)
  LOG_BACKUP_COUNT  = 5             # Number of backup files to keep
  LOG_JSON_FORMAT   = false         # true → JSON lines; false → human-readable
"""

import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone

# ── Defaults ──────────────────────────────────────────────────────────────────
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_LOG_FILE = os.getenv("LOG_FILE", "logs/trading.log")
_LOG_MAX_SIZE_MB = int(os.getenv("LOG_MAX_SIZE_MB", "10"))
_LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))
_LOG_JSON_FORMAT = os.getenv("LOG_JSON_FORMAT", "false").lower() == "true"


# ── JSON structured formatter ─────────────────────────────────────────────────


class StructuredFormatter(logging.Formatter):
    """JSON Lines formatter — one JSON object per log line.

    Useful for ingestion by log aggregation tools (Loki, ELK, Datadog).
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


# ── Setup function ────────────────────────────────────────────────────────────


def setup_logging(
    log_level: str = _LOG_LEVEL,
    log_file: str = _LOG_FILE,
    max_size_mb: int = _LOG_MAX_SIZE_MB,
    backup_count: int = _LOG_BACKUP_COUNT,
    json_format: bool = _LOG_JSON_FORMAT,
) -> None:
    """Configure root logger with rotating file handler and console handler.

    Safe to call multiple times (idempotent — handlers are cleared first).

    Args:
        log_level    : Python logging level string.
        log_file     : Path to the log file (parent directories are created).
        max_size_mb  : Maximum size in MB before log rotation.
        backup_count : Number of rotated backup files to retain.
        json_format  : If True, use JSON Lines format; otherwise human-readable.
    """
    # Ensure log directory exists
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    numeric_level = getattr(logging, log_level, logging.INFO)
    root.setLevel(numeric_level)

    # Remove any pre-existing handlers (prevents duplicate output on re-call)
    root.handlers.clear()

    # ── Console handler ───────────────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    if json_format:
        console.setFormatter(StructuredFormatter())
    else:
        console.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    root.addHandler(console)

    # ── Rotating file handler ─────────────────────────────────────────────────
    max_bytes = max_size_mb * 1024 * 1024
    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    if json_format:
        file_handler.setFormatter(StructuredFormatter())
    else:
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d — %(message)s"
            )
        )
    root.addHandler(file_handler)

    # ── Suppress noisy third-party loggers ────────────────────────────────────
    for noisy_logger in (
        "uvicorn.access",
        "httpx",
        "httpcore",
        "chromadb",
        "aiohttp",
        "anthropic",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    total_max_mb = max_size_mb * (backup_count + 1)
    logging.info(
        f"Logging configured: level={log_level}, file={log_file}, "
        f"rotation={max_size_mb}MB × {backup_count} backups "
        f"(max total: {total_max_mb} MB), json={json_format}"
    )
