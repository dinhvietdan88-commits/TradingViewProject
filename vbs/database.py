import json
import logging
from datetime import datetime, timedelta, timezone, UTC
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

import config

log = logging.getLogger(__name__)

# ── Display timezone: UTC+7 (ICT / Vietnam) ─────────────────────────────────
VN_TZ = timezone(timedelta(hours=7))


def format_vn_time(utc_str: str) -> str:
    """Convert a UTC datetime string to UTC+7 display format.

    Args:
        utc_str: datetime in '%Y-%m-%d %H:%M:%S' (UTC).
    Returns:
        Formatted string like '2026-06-04 01:45:11 (ICT)'
    """
    try:
        dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=UTC
        )
        vn_dt = dt.astimezone(VN_TZ)
        return vn_dt.strftime("%Y-%m-%d %H:%M:%S") + " (ICT)"
    except (ValueError, TypeError):
        return utc_str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at     TEXT    NOT NULL,
    dispatched_at   TEXT,
    acked_at        TEXT,
    expires_at      TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'PENDING',
    symbol          TEXT    NOT NULL,
    action          TEXT    NOT NULL,
    price           REAL,
    quote_qty       REAL,
    interval        TEXT,
    exchange        TEXT    NOT NULL DEFAULT 'binance',
    sl              TEXT,
    tp              TEXT,
    source          TEXT,
    payload_json    TEXT    NOT NULL,
    consumer_id     TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    ack_status      TEXT,
    error_msg       TEXT
);

CREATE INDEX IF NOT EXISTS idx_sq_status     ON signal_queue(status);
CREATE INDEX IF NOT EXISTS idx_sq_expires    ON signal_queue(expires_at);
CREATE INDEX IF NOT EXISTS idx_sq_symbol     ON signal_queue(symbol);
CREATE INDEX IF NOT EXISTS idx_sq_received   ON signal_queue(received_at);
CREATE INDEX IF NOT EXISTS idx_sq_status_exp ON signal_queue(status, expires_at);

CREATE TABLE IF NOT EXISTS signal_audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id        INTEGER NOT NULL,
    event           TEXT    NOT NULL,
    event_at        TEXT    NOT NULL,
    consumer_id     TEXT,
    detail          TEXT
);

CREATE INDEX IF NOT EXISTS idx_sal_queue_id ON signal_audit_log(queue_id);
CREATE INDEX IF NOT EXISTS idx_sal_event_at ON signal_audit_log(event_at);
"""


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_str() -> str:
    return utc_now().strftime("%Y-%m-%d %H:%M:%S")


async def init_db():
    """Initialize SQLite database for VPS Buffer Service."""
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    log.info(f"VPS database initialized at: {config.DB_PATH}")


async def write_audit_log(
    db: aiosqlite.Connection,
    queue_id: int,
    event: str,
    consumer_id: str | None = None,
    detail: str | None = None,
):
    """Write an entry to the audit log (expects an open database connection)."""
    await db.execute(
        """INSERT INTO signal_audit_log (queue_id, event, event_at, consumer_id, detail)
           VALUES (?, ?, ?, ?, ?)""",
        (queue_id, event, utc_now_str(), consumer_id, detail),
    )


async def check_duplicate(
    symbol: str, action: str, price: float, window_seconds: int = 10
) -> int | None:
    """Check if a signal with same symbol+action+price exists within the dedup window.

    Uses a fingerprint of (symbol_upper, action_lower, rounded_price) within
    a configurable time window.

    Returns:
        The existing queue_id if duplicate found, None otherwise.
    """
    cutoff = (utc_now() - timedelta(seconds=window_seconds)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    sym = symbol.upper()
    act = action.lower()

    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            """SELECT id FROM signal_queue
               WHERE UPPER(symbol) = ? AND LOWER(action) = ?
                 AND received_at >= ?
               ORDER BY id DESC LIMIT 1""",
            (sym, act, cutoff),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def insert_signal(payload: dict[str, Any]) -> tuple[int, str]:
    """Insert a new signal into the queue.

    Returns:
        (queue_id, expires_display) — expires_display is UTC+7 formatted for Telegram.
    """
    now = utc_now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    expires = now + timedelta(hours=config.SIGNAL_TTL_HOURS)
    expires_str = expires.strftime("%Y-%m-%d %H:%M:%S")  # DB storage (UTC)

    # Parse basic attributes with fallback
    symbol = payload.get("symbol", "")
    if ":" in symbol:
        symbol = symbol.split(":")[-1]

    action = payload.get("action") or payload.get("side") or ""
    action = str(action).lower()

    price = payload.get("price")
    try:
        price_float = float(str(price).replace(",", "")) if price else None
    except (ValueError, TypeError):
        price_float = None

    quote_qty = payload.get("quoteQty") or payload.get("size")
    try:
        quote_qty_float = float(quote_qty) if quote_qty else 10.0
    except (ValueError, TypeError):
        quote_qty_float = 10.0

    interval = payload.get("interval", "")
    exchange = (payload.get("exchange") or "binance").upper()
    sl = payload.get("sl", "")
    tp = payload.get("tp", "")
    source = payload.get("source", "")

    # Save full clean payload as JSON (strip secret)
    clean_payload = payload.copy()
    clean_payload.pop("secret", None)
    payload_json = json.dumps(clean_payload)

    async with aiosqlite.connect(config.DB_PATH) as db:
        # Check current queue size limit
        if config.MAX_QUEUE_SIZE > 0:
            async with db.execute(
                "SELECT COUNT(*) FROM signal_queue WHERE status = 'PENDING'"
            ) as cur:
                count_row = await cur.fetchone()
                if count_row and count_row[0] >= config.MAX_QUEUE_SIZE:
                    # Queue overflow: Delete the oldest pending signal or reject new signal
                    # Triết lý: Xóa cũ nhất để hứng mới nhất (hoặc reject). Let's log warning and delete oldest.
                    log.warning(
                        f"Queue size limit reached ({config.MAX_QUEUE_SIZE}). Deleting oldest pending signal."
                    )
                    await db.execute(
                        "UPDATE signal_queue SET status = 'STALE', error_msg = 'Queue overflow cleanup' "
                        "WHERE id = (SELECT id FROM signal_queue WHERE status = 'PENDING' ORDER BY received_at ASC LIMIT 1)"
                    )

        cursor = await db.execute(
            """INSERT INTO signal_queue
               (received_at, expires_at, status, symbol, action, price, quote_qty, interval, exchange, sl, tp, source, payload_json)
               VALUES (?, ?, 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now_str,
                expires_str,
                symbol,
                action,
                price_float,
                quote_qty_float,
                interval,
                exchange,
                sl,
                tp,
                source,
                payload_json,
            ),
        )
        queue_id = cursor.lastrowid

        await write_audit_log(
            db, queue_id, "QUEUED", detail=f"Signal queued for {symbol} {action}"
        )
        await db.commit()

        log.info(
            f"VBS Queue Signal #{queue_id} stored: {action} {symbol} (expires at {expires_str} UTC)"
        )
        return queue_id, format_vn_time(expires_str)


async def update_signal_status(queue_id: int, status: str, detail: str = "") -> bool:
    """Updates the status of a specific signal (e.g. APPROVED, CANCELLED)."""
    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            "UPDATE signal_queue SET status = ? WHERE id = ? AND status = 'PENDING'",
            (status, queue_id),
        ) as cursor:
            if cursor.rowcount > 0:
                await write_audit_log(db, queue_id, status, detail=detail)
                await db.commit()
                return True
            return False


async def get_pending_count() -> int:
    """Return the number of pending signals."""
    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM signal_queue WHERE status = 'PENDING'"
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def consume_signals(
    consumer_id: str,
    limit: int,
    source: str | None = None,
    exclude_source: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve and dispatch pending signals, marking them as DISPATCHED."""
    now_str = utc_now_str()
    signals = []

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Build dynamic query based on source filters
        query = "SELECT * FROM signal_queue WHERE status = 'PENDING' AND expires_at > ?"
        params = [now_str]

        if source:
            query += " AND source = ?"
            params.append(source)

        if exclude_source:
            query += " AND (source IS NULL OR source != ?)"
            params.append(exclude_source)

        query += " ORDER BY id ASC LIMIT ?"
        params.append(limit)

        # Retrieve pending signals that are not expired yet
        async with db.execute(query, tuple(params)) as cur:
            rows = await cur.fetchall()

        if not rows:
            return []

        queue_ids = [row["id"] for row in rows]

        # Mark as DISPATCHED
        await db.executemany(
            "UPDATE signal_queue SET status = 'DISPATCHED', dispatched_at = ?, consumer_id = ? WHERE id = ?",
            [(now_str, consumer_id, q_id) for q_id in queue_ids],
        )

        for q_id in queue_ids:
            await write_audit_log(db, q_id, "DISPATCHED", consumer_id=consumer_id)

        await db.commit()

        # Format the return structure
        for row in rows:
            payload = json.loads(row["payload_json"])

            # calculate age
            rec_time = datetime.strptime(
                row["received_at"], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=UTC)
            now = utc_now()
            age_min = (now - rec_time).total_seconds() / 60.0

            signals.append(
                {
                    "queue_id": row["id"],
                    "symbol": row["symbol"],
                    "action": row["action"],
                    "price": row["price"],
                    "quote_qty": row["quote_qty"],
                    "interval": row["interval"],
                    "exchange": row["exchange"],
                    "sl": row["sl"],
                    "tp": row["tp"],
                    "received_at": row["received_at"],
                    "expires_at": row["expires_at"],
                    "age_minutes": round(age_min, 1),
                    "payload": payload,
                }
            )

    return signals


async def ack_signals(acks: list[Any]) -> tuple[int, list[dict[str, Any]]]:
    """Process confirmations for consumed signals."""
    acked_count = 0
    results = []
    now_str = utc_now_str()

    async with aiosqlite.connect(config.DB_PATH) as db:
        for ack in acks:
            q_id = ack.queue_id
            ack_status = ack.status  # "executed", "skipped_stale", "failed"
            error_msg = ack.error_msg

            # Mapped DB status: ACKED for executed, SKIPPED for skipped_stale, FAILED for failed (or PENDING if retryable)
            db_status = "ACKED"
            if ack_status == "skipped_stale":
                db_status = "SKIPPED"
            elif ack_status == "failed":
                db_status = "FAILED"

            # Perform update
            cursor = await db.execute(
                """UPDATE signal_queue
                   SET status = ?, acked_at = ?, ack_status = ?, error_msg = ?
                   WHERE id = ? AND status = 'DISPATCHED'""",
                (db_status, now_str, ack_status, error_msg, q_id),
            )

            if cursor.rowcount > 0:
                acked_count += 1
                results.append({"queue_id": q_id, "status": db_status})
                await write_audit_log(
                    db,
                    q_id,
                    db_status,
                    detail=f"ACK status: {ack_status}. Msg: {error_msg}",
                )
            else:
                # If not DISPATCHED (e.g. already acked or expired), check what it is
                async with db.execute(
                    "SELECT status FROM signal_queue WHERE id = ?", (q_id,)
                ) as cur:
                    row = await cur.fetchone()
                    current_status = row[0] if row else "UNKNOWN"
                results.append({"queue_id": q_id, "status": current_status})

        await db.commit()

    return acked_count, results


async def stale_cleanup() -> int:
    """Clean up expired signals in the queue."""
    now_str = utc_now_str()
    async with aiosqlite.connect(config.DB_PATH) as db:
        # Get count
        async with db.execute(
            "SELECT id, source FROM signal_queue WHERE status IN ('PENDING', 'DISPATCHED') AND expires_at < ?",
            (now_str,),
        ) as cur:
            rows = await cur.fetchall()

        if not rows:
            return 0

        ids = [row[0] for row in rows]
        # Count non-indicator signals for alerting
        alert_count = sum(1 for row in rows if row[1] != "indicator")

        await db.executemany(
            "UPDATE signal_queue SET status = 'STALE', error_msg = 'Expired via TTL scheduler' WHERE id = ?",
            [(q_id,) for q_id in ids],
        )

        for q_id in ids:
            await write_audit_log(db, q_id, "STALE", detail="Expired via TTL scheduler")

        await db.commit()
        log.info(
            f"VBS Cleanup: marked {len(ids)} expired signals as STALE ({alert_count} alertable)"
        )
        return alert_count


async def requeue_timeouts(timeout_minutes: float) -> tuple[int, list[dict[str, Any]]]:
    """Requeue signals that were dispatched but never ACKed within the timeout period."""
    cutoff_time = (utc_now() - timedelta(minutes=timeout_minutes)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    requeued_count = 0
    stale_alerts = []

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM signal_queue WHERE status = 'DISPATCHED' AND dispatched_at < ?",
            (cutoff_time,),
        ) as cur:
            rows = await cur.fetchall()

        if not rows:
            return 0, []

        for row in rows:
            q_id = row["id"]
            retries = row["retry_count"]
            symbol = row["symbol"]
            action = row["action"]

            if retries < 3:
                # Requeue
                await db.execute(
                    "UPDATE signal_queue SET status = 'PENDING', dispatched_at = NULL, consumer_id = NULL, retry_count = retry_count + 1 WHERE id = ?",
                    (q_id,),
                )
                await write_audit_log(
                    db,
                    q_id,
                    "REQUEUED",
                    detail=f"Requeued due to lack of ACK. Retry count now: {retries + 1}",
                )
                requeued_count += 1
                log.info(f"VBS Re-queue: Signal #{q_id} requeued (retry={retries + 1})")
            else:
                # Mark as STALE
                await db.execute(
                    "UPDATE signal_queue SET status = 'STALE', error_msg = 'Max ACK retries exceeded' WHERE id = ?",
                    (q_id,),
                )
                await write_audit_log(
                    db,
                    q_id,
                    "STALE",
                    detail="Max ACK retries exceeded. Marked as stale.",
                )
                stale_alerts.append({"id": q_id, "symbol": symbol, "action": action})
                log.warning(
                    f"VBS Re-queue Timeout: Signal #{q_id} exceeded max retries, marked as STALE."
                )

        await db.commit()

    return requeued_count, stale_alerts


async def audit_cleanup(days: int) -> int:
    """Delete audit logs older than N days."""
    cutoff_str = (utc_now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(config.DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM signal_audit_log WHERE event_at < ?", (cutoff_str,)
        )
        await db.commit()
        return cursor.rowcount


async def get_queue_status() -> dict[str, Any]:
    """Retrieve queue statistics and pending items."""
    today_start = (
        utc_now()
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .strftime("%Y-%m-%d %H:%M:%S")
    )

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Pending count
        async with db.execute(
            "SELECT COUNT(*) FROM signal_queue WHERE status = 'PENDING'"
        ) as cur:
            row = await cur.fetchone()
            pending = row[0] if row else 0

        # Dispatched count
        async with db.execute(
            "SELECT COUNT(*) FROM signal_queue WHERE status = 'DISPATCHED'"
        ) as cur:
            row = await cur.fetchone()
            dispatched = row[0] if row else 0

        # ACKed today
        async with db.execute(
            "SELECT COUNT(*) FROM signal_queue WHERE status = 'ACKED' AND acked_at >= ?",
            (today_start,),
        ) as cur:
            row = await cur.fetchone()
            acked_today = row[0] if row else 0

        # Stale today
        async with db.execute(
            "SELECT COUNT(*) FROM signal_queue WHERE status = 'STALE' AND acked_at >= ?",
            (today_start,),
        ) as cur:
            row = await cur.fetchone()
            stale_today = row[0] if row else 0

        # Oldest pending age in minutes
        oldest_pending_age = None
        async with db.execute(
            "SELECT received_at FROM signal_queue WHERE status = 'PENDING' ORDER BY received_at ASC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            if row:
                rec_time = datetime.strptime(
                    row["received_at"], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=UTC)
                oldest_pending_age = (utc_now() - rec_time).total_seconds() / 60.0

        # Retrieve detailed pending list
        async with db.execute(
            "SELECT id, symbol, action, received_at, expires_at FROM signal_queue WHERE status = 'PENDING' ORDER BY id ASC"
        ) as cur:
            pending_rows = await cur.fetchall()

        pending_signals = []
        for r in pending_rows:
            exp_time = datetime.strptime(r["expires_at"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=UTC
            )
            remaining = (exp_time - utc_now()).total_seconds() / 60.0

            pending_signals.append(
                {
                    "queue_id": r["id"],
                    "symbol": r["symbol"],
                    "action": r["action"],
                    "received_at": r["received_at"],
                    "ttl_remaining_minutes": max(0.0, round(remaining, 1)),
                }
            )

    return {
        "summary": {
            "pending": pending,
            "dispatched": dispatched,
            "acked_today": acked_today,
            "stale_today": stale_today,
            "oldest_pending_age_minutes": round(oldest_pending_age, 1)
            if oldest_pending_age is not None
            else None,
        },
        "pending_signals": pending_signals,
    }


async def update_signal_payload(queue_id: int, extra_data: dict[str, Any]) -> bool:
    """Updates payload_json in the queue by merging in new keys."""
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT payload_json FROM signal_queue WHERE id = ?", (queue_id,)
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return False
            payload = json.loads(row["payload_json"])

        payload.update(extra_data)
        new_payload_json = json.dumps(payload)

        async with db.execute(
            "UPDATE signal_queue SET payload_json = ? WHERE id = ?",
            (new_payload_json, queue_id),
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0
