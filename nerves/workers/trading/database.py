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
import sqlite3
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
    mode        TEXT,
    processed   INTEGER NOT NULL DEFAULT 0,
    vbs_queue_id INTEGER
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
CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_vbs_queue_id ON signals(vbs_queue_id);
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

CREATE TABLE IF NOT EXISTS indicator_signals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id        INTEGER NOT NULL REFERENCES signals(id),
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    symbol           TEXT    NOT NULL,
    indicator_name   TEXT    NOT NULL,
    signal_type      TEXT    NOT NULL DEFAULT 'info',
    interval         TEXT,
    price            REAL,
    confidence_score INTEGER DEFAULT 0,
    conditions_met   TEXT,
    metadata         TEXT,
    source_ip        TEXT,
    exchange         TEXT    DEFAULT 'binance'
);

CREATE INDEX IF NOT EXISTS idx_indicator_signals_symbol ON indicator_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_indicator_signals_name   ON indicator_signals(indicator_name);
CREATE INDEX IF NOT EXISTS idx_indicator_signals_type   ON indicator_signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_indicator_signals_date   ON indicator_signals(created_at);
-- Composite indexes for frequent query patterns
CREATE INDEX IF NOT EXISTS idx_ind_sig_date_sym  ON indicator_signals(created_at, symbol);
CREATE INDEX IF NOT EXISTS idx_ind_sig_sym_type  ON indicator_signals(symbol, signal_type);
-- Covering index: feed query WHERE symbol=? ORDER BY created_at DESC LIMIT n
CREATE INDEX IF NOT EXISTS idx_ind_sig_sym_date  ON indicator_signals(symbol, created_at DESC);

CREATE TABLE IF NOT EXISTS sentiment_logs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    symbol         TEXT    NOT NULL,
    twitter_score  REAL,
    rss_score      REAL,
    glassnode_score REAL,
    combined_score  REAL,
    raw_data       TEXT
);

CREATE INDEX IF NOT EXISTS idx_sentiment_logs_symbol ON sentiment_logs(symbol);
CREATE INDEX IF NOT EXISTS idx_sentiment_logs_created ON sentiment_logs(created_at);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_settings (
    exchange        TEXT    NOT NULL,
    symbol          TEXT    NOT NULL DEFAULT '*',
    daily_loss_cap  REAL    NOT NULL DEFAULT 10.0,
    drawdown_cap    REAL    NOT NULL DEFAULT 5.0,
    max_quote_qty   REAL    NOT NULL DEFAULT 100.0,
    slippage_limit  REAL    NOT NULL DEFAULT 0.005,
    safe_mode       INTEGER NOT NULL DEFAULT 1,
    state           TEXT    NOT NULL DEFAULT 'CLOSED',
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (exchange, symbol)
);

CREATE TABLE IF NOT EXISTS circuit_breaker_logs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      TEXT    NOT NULL DEFAULT (datetime('now')),
    exchange       TEXT    NOT NULL,
    symbol         TEXT    NOT NULL,
    prev_state     TEXT    NOT NULL,
    new_state      TEXT    NOT NULL,
    trigger_reason TEXT    NOT NULL,
    current_metrics TEXT   NOT NULL
);
"""


# ═══════════════════════════════════════════════════════════════
# INIT (stays here — schema owner)
# ═══════════════════════════════════════════════════════════════

async def init_db():
    """Tao bang khi khoi dong server."""
    async with aiosqlite.connect(config.DB_PATH, timeout=config.DB_TIMEOUT) as db:
        await db.execute("PRAGMA journal_mode=WAL")
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
            "ALTER TABLE trades ADD COLUMN vbs_queue_id INTEGER",
        ]:
            try:
                await db.execute(col_def)
                await db.commit()
            except Exception:
                pass  # Column already exists

        # v6.1: Extend indicator_signals table (backward-compatible, REQ 7.1)
        for col_def in [
            "ALTER TABLE indicator_signals ADD COLUMN interval TEXT",
            "ALTER TABLE indicator_signals ADD COLUMN price REAL",
            "ALTER TABLE indicator_signals ADD COLUMN source_ip TEXT",
            "ALTER TABLE indicator_signals ADD COLUMN exchange TEXT DEFAULT 'binance'",
        ]:
            try:
                await db.execute(col_def)
                await db.commit()
            except Exception:
                pass  # Column already exists

        # v7.0: Add mode column to signals (backward-compatible — Phase 2 MTT/MIS tracking)
        try:
            await db.execute("ALTER TABLE signals ADD COLUMN mode TEXT")
            await db.commit()
        except Exception:
            pass  # Column already exists

        # VPS Buffer: Add vbs_queue_id column to signals
        try:
            await db.execute("ALTER TABLE signals ADD COLUMN vbs_queue_id INTEGER")
            await db.commit()
        except Exception:
            pass

        try:
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_vbs_queue_id ON signals(vbs_queue_id)")
            await db.commit()
        except Exception:
            pass

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
    insert_indicator_signal,
    insert_trade,
    update_trade_oco,
    insert_brief,
    insert_sentiment_log,
)

# Read operations (QueryService)
from data.query_service import (  # noqa: E402, F401
    get_trades,
    get_stats,
    get_stats_by_mode,
    get_recent_trades,
    get_equity_curve,
    get_briefs,
    get_brief_by_id,
    get_db_counts,
    get_latest_sentiment_log,
    get_recent_sentiments,
)




# ═══════════════════════════════════════════════════════════════
# AUTH HELPERS (synchronous — used by auth routes)
# ═══════════════════════════════════════════════════════════════


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


async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a setting value asynchronously."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else default
    except Exception as e:
        log.warning(f"Failed to get setting {key}: {e}")
        return default


async def set_setting(key: str, value: str) -> None:
    """Set a setting value asynchronously."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )
            await db.commit()
    except Exception as e:
        log.warning(f"Failed to set setting {key} to {value}: {e}")


async def get_rolling_drawdown(limit: int = 20) -> float:
    """
    Tính toán phần trăm sụt giảm tài khoản (Drawdown) dựa trên các giao dịch đóng gần nhất.
    """
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            # Lấy 20 giao dịch có PnL (chỉ tính các giao dịch đã đóng/có pnl)
            async with db.execute(
                "SELECT pnl FROM trades WHERE pnl IS NOT NULL ORDER BY id DESC LIMIT ?",
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                pnls = [float(r["pnl"]) for r in rows]
                
        if not pnls:
            return 0.0
            
        # Đảo ngược để tính theo trình tự thời gian
        pnls.reverse()
        
        # Giả lập đường cong vốn bắt đầu từ 1000
        equity = 1000.0
        peak = equity
        max_dd_pct = 0.0
        
        for pnl in pnls:
            equity += pnl
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak
                if dd > max_dd_pct:
                    max_dd_pct = dd
                    
        return max_dd_pct * 100.0
    except Exception as e:
        log.warning(f"Failed to calculate rolling drawdown: {e}")
        return 0.0


async def get_recent_profit_factor(limit: int = 5) -> float:
    """
    Tính Profit Factor của N lệnh gần nhất.
    """
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT pnl FROM trades WHERE pnl IS NOT NULL ORDER BY id DESC LIMIT ?",
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                pnls = [float(r["pnl"]) for r in rows]
                
        if not pnls:
            return 1.0
            
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = sum(abs(p) for p in pnls if p < 0)
        
        if gross_loss == 0:
            return 99.0 if gross_profit > 0 else 1.0
            
        return gross_profit / gross_loss
    except Exception as e:
        log.warning(f"Failed to calculate recent profit factor: {e}")
        return 1.0


async def get_daily_loss(exchange: str, window_hours: int = 24) -> float:
    """
    Tính toán tổng số lỗ (PnL âm) của một sàn giao dịch cụ thể trong vòng N giờ qua.
    """
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            query = (
                "SELECT pnl FROM trades "
                "WHERE LOWER(exchange) = ? AND pnl < 0 "
                "AND created_at >= datetime('now', ?)"
            )
            async with db.execute(query, (exchange.lower(), f"-{window_hours} hours")) as cursor:
                rows = await cursor.fetchall()
                return sum(abs(float(r["pnl"])) for r in rows)
    except Exception as e:
        log.warning(f"Failed to calculate daily loss for {exchange}: {e}")
        return 0.0


async def get_risk_settings(exchange: str, symbol: str = "*") -> Dict[str, Any]:
    """Get risk parameters and current circuit breaker state for an exchange."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM risk_settings WHERE exchange = ? AND symbol = ?",
                (exchange.lower(), symbol)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
    except Exception as e:
        log.warning(f"Failed to fetch risk settings for {exchange}: {e}")
    
    # Return defaults if not configured
    return {
        "exchange": exchange,
        "symbol": symbol,
        "daily_loss_cap": 10.0,
        "drawdown_cap": 5.0,
        "max_quote_qty": 100.0,
        "slippage_limit": 0.005,
        "safe_mode": 1,
        "state": "CLOSED"
    }


async def save_risk_settings(
    exchange: str, daily_loss_cap: float, drawdown_cap: float,
    max_quote_qty: float, slippage_limit: float, safe_mode: int,
    state: str = "CLOSED", symbol: str = "*"
) -> None:
    """Save or update risk settings for an exchange."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO risk_settings "
                "(exchange, symbol, daily_loss_cap, drawdown_cap, max_quote_qty, slippage_limit, safe_mode, state, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (exchange.lower(), symbol, daily_loss_cap, drawdown_cap, max_quote_qty, slippage_limit, safe_mode, state)
            )
            await db.commit()
    except Exception as e:
        log.warning(f"Failed to save risk settings for {exchange}: {e}")


async def update_circuit_breaker_state(exchange: str, new_state: str, symbol: str = "*") -> None:
    """Update only the state of the circuit breaker for an exchange."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            await db.execute(
                "UPDATE risk_settings SET state = ?, updated_at = datetime('now') "
                "WHERE exchange = ? AND symbol = ?",
                (new_state.upper(), exchange.lower(), symbol)
            )
            # If no rows were updated, we insert a default row with this state
            async with db.execute("SELECT changes()") as cursor:
                changes = await cursor.fetchone()
                if changes and changes[0] == 0:
                    await db.execute(
                        "INSERT INTO risk_settings "
                        "(exchange, symbol, daily_loss_cap, drawdown_cap, max_quote_qty, slippage_limit, safe_mode, state, updated_at) "
                        "VALUES (?, ?, 10.0, 5.0, 100.0, 0.005, 1, ?, datetime('now'))",
                        (exchange.lower(), symbol, new_state.upper())
                    )
            await db.commit()
    except Exception as e:
        log.warning(f"Failed to update circuit breaker state for {exchange}: {e}")


async def log_circuit_breaker(
    exchange: str, symbol: str, prev_state: str, new_state: str,
    trigger_reason: str, current_metrics: dict
) -> None:
    """Record a state transition event in the circuit breaker telemetry log."""
    try:
        import json
        metrics_json = json.dumps(current_metrics)
        async with aiosqlite.connect(config.DB_PATH) as db:
            await db.execute(
                "INSERT INTO circuit_breaker_logs "
                "(exchange, symbol, prev_state, new_state, trigger_reason, current_metrics) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (exchange.lower(), symbol, prev_state.upper(), new_state.upper(), trigger_reason, metrics_json)
            )
            await db.commit()
    except Exception as e:
        log.warning(f"Failed to write circuit breaker log: {e}")


async def get_all_risk_statuses() -> list:
    """Get status of all configured or default exchanges."""
    exchanges = ["weex", "bybit", "binance"]
    statuses = []
    for ex in exchanges:
        settings = await get_risk_settings(ex)
        daily_loss = await get_daily_loss(ex)
        drawdown = await get_rolling_drawdown()
        
        # Query actual latency from exchange_health table
        latency_ms = None
        try:
            async with aiosqlite.connect(config.DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT latency_ms FROM exchange_health WHERE exchange_id = ? ORDER BY id DESC LIMIT 1",
                    (ex.lower(),)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        latency_ms = float(row["latency_ms"])
        except Exception as e:
            log.warning(f"Failed to fetch actual latency for {ex}: {e}")
            
        if latency_ms is None:
            # Fallback to hardcoded defaults
            latency_ms = 120.0 if ex == "weex" else (85.0 if ex == "bybit" else 45.0)

        statuses.append({
            "exchange": ex,
            "state": settings["state"],
            "dailyLoss": daily_loss,
            "dailyLossCap": settings["daily_loss_cap"],
            "drawdown": drawdown,
            "drawdownCap": settings["drawdown_cap"],
            "latencyMs": int(latency_ms),
        })
    return statuses


async def get_recent_circuit_breaker_logs(limit: int = 10) -> list:
    """Fetch the recent circuit breaker state transition logs."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, timestamp, exchange, symbol, prev_state, new_state, trigger_reason, current_metrics "
                "FROM circuit_breaker_logs ORDER BY id DESC LIMIT ?",
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                logs = []
                for r in rows:
                    row_dict = dict(r)
                    if row_dict.get("current_metrics"):
                        try:
                            import json
                            row_dict["current_metrics"] = json.loads(row_dict["current_metrics"])
                        except Exception:
                            pass  # JSON parse of metrics is best-effort; keep raw string on failure
                    logs.append(row_dict)
                return logs
    except Exception as e:
        log.warning(f"Failed to fetch circuit breaker logs: {e}")
        return []


