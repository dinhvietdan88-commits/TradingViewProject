"""
Sprint 4: Trade Logging Database Module
SQLite + aiosqlite for async I/O with FastAPI

V8.0 REFACTOR: This module now acts as a backward-compatible facade.
- Schema + init_db() remain here (single source of truth).
- Write operations are delegated to data.persistence_store.
- Read operations are delegated to data.query_service.
- All public symbols are re-exported so existing `import database` still works.
"""
import aiosqlite
import json
import logging
from typing import Optional, Dict, Any

import config

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# SCHEMA (Single Source of Truth)
# ═══════════════════════════════════════════════════════════════

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    symbol      TEXT    NOT NULL,
    action      TEXT    NOT NULL,
    price       REAL,
    quote_qty   REAL,
    source_ip   TEXT,
    payload     TEXT,
    processed   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trades (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id      INTEGER NOT NULL REFERENCES signals(id),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    symbol         TEXT    NOT NULL,
    side           TEXT    NOT NULL,
    order_id       TEXT,
    status         TEXT,
    requested_qty  REAL,
    executed_qty   REAL,
    executed_price REAL,
    commission     REAL,
    error_message  TEXT,
    pnl            REAL,
    combined_score TEXT
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol  ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);
CREATE INDEX IF NOT EXISTS idx_trades_symbol   ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_signal   ON trades(signal_id);

CREATE TABLE IF NOT EXISTS briefs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    symbols_scanned INTEGER,
    scan_data       TEXT,
    ai_analysis     TEXT,
    vision_data     TEXT,
    screenshot      TEXT,
    brief_text      TEXT,
    success         INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_briefs_created ON briefs(created_at);

CREATE TABLE IF NOT EXISTS exchange_health (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    latency_ms  REAL    DEFAULT 0.0,
    error_msg   TEXT,
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS auth_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,
    telegram_id INTEGER NOT NULL,
    username    TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT    NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_auth_codes_code ON auth_codes(code);
CREATE INDEX IF NOT EXISTS idx_auth_codes_tg   ON auth_codes(telegram_id);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL UNIQUE,
    telegram_id INTEGER NOT NULL,
    username    TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_sid ON auth_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_tg  ON auth_sessions(telegram_id);
"""


# ═══════════════════════════════════════════════════════════════
# INIT (stays here — schema owner)
# ═══════════════════════════════════════════════════════════════

async def init_db():
    """Tao bang khi khoi dong server."""
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()

        # Sprint 7.2: Extend trades table (backward-compatible)
        for col_def in [
            "ALTER TABLE trades ADD COLUMN stop_loss_price REAL",
            "ALTER TABLE trades ADD COLUMN take_profit_price REAL",
            "ALTER TABLE trades ADD COLUMN oco_order_id TEXT",
            "ALTER TABLE trades ADD COLUMN order_type TEXT DEFAULT 'MARKET'",
            "ALTER TABLE trades ADD COLUMN combined_score TEXT",
            "ALTER TABLE trades ADD COLUMN exchange TEXT DEFAULT 'binance'",
        ]:
            try:
                await db.execute(col_def)
                await db.commit()
            except Exception:
                pass  # Column already exists

    log.info(f"Database initialized: {config.DB_PATH}")


# ═══════════════════════════════════════════════════════════════
# BACKWARD-COMPATIBLE FACADE
# Re-export all public symbols from the new data layer so that
# existing `import database; database.insert_signal(...)` code
# continues to work without any changes.
# ═══════════════════════════════════════════════════════════════

# Write operations (PersistenceStore)
from data.persistence_store import (  # noqa: E402, F401
    insert_signal,
    update_signal_status,
    insert_trade,
    update_trade_oco,
    insert_brief,
)

# Read operations (QueryService)
from data.query_service import (  # noqa: E402, F401
    get_trades,
    get_stats,
    get_equity_curve,
    get_briefs,
    get_brief_by_id,
    get_db_counts,
)


# ═══════════════════════════════════════════════════════════════
# AUTH HELPERS (synchronous — used by auth routes)
# ═══════════════════════════════════════════════════════════════

import sqlite3


def _sync_conn():
    """Get a synchronous SQLite connection for auth operations."""
    return sqlite3.connect(config.DB_PATH)


def get_auth_code(code: str) -> Optional[Dict[str, Any]]:
    """Fetch a one-time auth code record."""
    conn = _sync_conn()
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT code, telegram_id, username, created_at, expires_at, used "
            "FROM auth_codes WHERE code = ?",
            (code,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def store_auth_code(
    code: str, telegram_id: int, username: Optional[str],
    created_at: str, expires_at: str,
) -> None:
    """Store a new one-time auth code."""
    conn = _sync_conn()
    try:
        conn.execute(
            "INSERT INTO auth_codes (code, telegram_id, username, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (code, telegram_id, username, created_at, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def mark_auth_code_used(code: str) -> None:
    """Mark a one-time code as used."""
    conn = _sync_conn()
    try:
        conn.execute("UPDATE auth_codes SET used = 1 WHERE code = ?", (code,))
        conn.commit()
    finally:
        conn.close()


def store_auth_session(
    session_id: str, telegram_id: int, username: Optional[str],
    created_at: str, expires_at: Optional[str],
) -> None:
    """Store a new auth session."""
    conn = _sync_conn()
    try:
        conn.execute(
            "INSERT INTO auth_sessions (session_id, telegram_id, username, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, telegram_id, username, created_at, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def delete_auth_session(session_id: str) -> None:
    """Deactivate a session."""
    conn = _sync_conn()
    try:
        conn.execute(
            "UPDATE auth_sessions SET active = 0 WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()
    finally:
        conn.close()


def delete_all_user_sessions(telegram_id: int) -> int:
    """Deactivate all sessions for a user. Returns count of affected rows."""
    conn = _sync_conn()
    try:
        cursor = conn.execute(
            "UPDATE auth_sessions SET active = 0 WHERE telegram_id = ? AND active = 1",
            (telegram_id,),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def cleanup_expired_auth_codes() -> int:
    """Delete expired auth codes (housekeeping)."""
    conn = _sync_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM auth_codes WHERE expires_at < datetime('now')"
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
