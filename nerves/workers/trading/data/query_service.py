import json
import logging
from typing import Any

import aiosqlite

import config

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# QUERY — TRADE HISTORY
# ═══════════════════════════════════════════════════════════════


async def get_trades(
    symbol: str | None = None,
    limit: int = 50,
    offset: int = 0,
    from_date: str | None = None,
    to_date: str | None = None,
    demo: bool = False,
) -> dict[str, Any]:
    """Truy van lich su giao dich voi pagination va filter."""
    params = [
        symbol.upper() if symbol else None,
        symbol,
        from_date,
        from_date,
        to_date,
        to_date,
        1 if demo else 0,
    ]

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Count total
        sql_count = """
            SELECT COUNT(*) as cnt FROM trades t
            WHERE (t.symbol = ? OR ? IS NULL)
              AND (t.created_at >= ? OR ? IS NULL)
              AND (t.created_at <= ? OR ? IS NULL)
              AND (? = 1 OR (LOWER(t.exchange) = 'weex' OR (t.order_type != 'DRY_RUN' AND t.order_id IS NOT NULL AND t.order_id NOT LIKE 'DRY-%' AND t.order_id NOT LIKE 'ORD%')))
        """
        row = await db.execute_fetchall(sql_count, params)
        total = row[0][0] if row else 0

        # Fetch page
        limit = min(limit, 200)
        sql_fetch = """
            SELECT t.*, s.action as signal_action, s.payload as signal_payload
            FROM trades t LEFT JOIN signals s ON s.id = t.signal_id
            WHERE (t.symbol = ? OR ? IS NULL)
              AND (t.created_at >= ? OR ? IS NULL)
              AND (t.created_at <= ? OR ? IS NULL)
              AND (? = 1 OR (LOWER(t.exchange) = 'weex' OR (t.order_type != 'DRY_RUN' AND t.order_id IS NOT NULL AND t.order_id NOT LIKE 'DRY-%' AND t.order_id NOT LIKE 'ORD%')))
            ORDER BY t.created_at DESC LIMIT ? OFFSET ?
        """
        rows = await db.execute_fetchall(sql_fetch, params + [limit, offset])

        trades = [dict(r) for r in rows]

    return {"trades": trades, "total": total, "limit": limit, "offset": offset}


# ═══════════════════════════════════════════════════════════════
# QUERY — PERFORMANCE STATS
# ═══════════════════════════════════════════════════════════════


async def get_stats(symbol: str | None = None, demo: bool = False) -> dict[str, Any]:
    """Tinh metrics hieu suat: Win Rate, Profit Factor, Drawdown."""
    params = [symbol.upper() if symbol else None, symbol, 1 if demo else 0]

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        sql = """
            SELECT pnl FROM trades t
            WHERE t.status = 'FILLED' AND t.pnl IS NOT NULL
              AND (t.symbol = ? OR ? IS NULL)
              AND (? = 1 OR (LOWER(t.exchange) = 'weex' OR (t.order_type != 'DRY_RUN' AND t.order_id IS NOT NULL AND t.order_id NOT LIKE 'DRY-%' AND t.order_id NOT LIKE 'ORD%')))
        """
        rows = await db.execute_fetchall(sql, params)

        pnl_list = [r[0] for r in rows]

        if not pnl_list:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "profit_factor": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "max_drawdown": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
            }

        wins = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p <= 0]

        total_win = sum(wins) if wins else 0.0
        total_loss = abs(sum(losses)) if losses else 0.0

        # Max Drawdown (peak-to-trough)
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in pnl_list:
            cumulative += p
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        return {
            "total_trades": len(pnl_list),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / len(pnl_list) * 100, 1) if pnl_list else 0.0,
            "total_pnl": round(sum(pnl_list), 2),
            "profit_factor": round(total_win / total_loss, 2)
            if total_loss > 0
            else (99.0 if total_win > 0 else 0.0),
            "avg_win": round(total_win / len(wins), 2) if wins else 0.0,
            "avg_loss": round(-total_loss / len(losses), 2) if losses else 0.0,
            "max_drawdown": round(-max_dd, 2),
            "best_trade": round(max(pnl_list), 2),
            "worst_trade": round(min(pnl_list), 2),
        }


def _build_mode_stats(pnl_list: list) -> dict[str, Any]:
    """Compute performance metrics for a given list of PnL values."""
    if not pnl_list:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
        }

    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]
    total_win = sum(wins) if wins else 0.0
    total_loss = abs(sum(losses)) if losses else 0.0

    return {
        "total_trades": len(pnl_list),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(len(wins) / len(pnl_list) * 100, 1),
        "total_pnl": round(sum(pnl_list), 2),
        "profit_factor": round(total_win / total_loss, 2)
        if total_loss > 0
        else (99.0 if total_win > 0 else 0.0),
        "avg_win": round(total_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-total_loss / len(losses), 2) if losses else 0.0,
        "best_trade": round(max(pnl_list), 2),
        "worst_trade": round(min(pnl_list), 2),
    }


async def get_stats_by_mode(demo: bool = False) -> dict[str, Any]:
    """Performance metrics grouped by strategy mode (MTT vs MIS).

    JOINs trades → signals to access the signals.mode column (added Phase 2).
    Returns:
        {
            "overall":  { ...metrics... },     # All FILLED trades regardless of mode
            "by_mode": {
                "MTT":   { ...metrics... },    # Daily Trend Follower signals
                "MIS":   { ...metrics... },    # 1H Momentum/Mean Reversion signals
                "OTHER": { ...metrics... },    # Empty or unknown mode
            }
        }
    """
    params = [1 if demo else 0]

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sql = """
            SELECT t.pnl,
            CASE
              WHEN s.mode IS NULL OR TRIM(s.mode) = '' THEN 'OTHER'
              ELSE UPPER(TRIM(s.mode))
            END AS mode
            FROM trades t
            LEFT JOIN signals s ON s.id = t.signal_id
            WHERE t.status = 'FILLED' AND t.pnl IS NOT NULL
              AND (? = 1 OR (LOWER(t.exchange) = 'weex' OR (t.order_type != 'DRY_RUN' AND t.order_id IS NOT NULL AND t.order_id NOT LIKE 'DRY-%' AND t.order_id NOT LIKE 'ORD%')))
        """
        rows = await db.execute_fetchall(sql, params)

    all_rows = [(float(r["pnl"]), r["mode"]) for r in rows]

    # Overall bucket
    all_pnl = [pnl for pnl, _ in all_rows]
    overall = _build_mode_stats(all_pnl)

    # Per-mode buckets
    mode_map: dict[str, list] = {}
    for pnl, mode in all_rows:
        mode_map.setdefault(mode, []).append(pnl)

    by_mode: dict[str, Any] = {}
    for mode_key in sorted(mode_map.keys()):
        by_mode[mode_key] = _build_mode_stats(mode_map[mode_key])

    # Ensure MTT, MIS, OTHER keys always exist (even with zero data)
    for sentinel in ("MTT", "MIS", "OTHER"):
        if sentinel not in by_mode:
            by_mode[sentinel] = _build_mode_stats([])

    return {"overall": overall, "by_mode": by_mode}


# ═══════════════════════════════════════════════════════════════
# QUERY — RECENT TRADE HISTORY (for /backtest history panel)
# ═══════════════════════════════════════════════════════════════


async def get_recent_trades(
    limit: int = 10,
    symbol: str | None = None,
    demo: bool = False,
) -> list[dict[str, Any]]:
    """Return the last N FILLED trades with signal mode for the /backtest history panel.

    Columns returned per trade:
        id, created_at, symbol, side, mode, executed_price,
        stop_loss_price, take_profit_price, pnl, status, exchange
    """
    params = [symbol.upper() if symbol else None, symbol, 1 if demo else 0, limit]

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sql = """
            SELECT t.id, t.created_at, t.symbol, t.side,
            COALESCE(NULLIF(TRIM(s.mode), ''), 'OTHER') AS mode,
            t.executed_price, t.stop_loss_price, t.take_profit_price,
            t.pnl, t.status, t.exchange
            FROM trades t LEFT JOIN signals s ON s.id = t.signal_id
            WHERE t.status = 'FILLED' AND t.pnl IS NOT NULL
              AND (t.symbol = ? OR ? IS NULL)
              AND (? = 1 OR (LOWER(t.exchange) = 'weex' OR (t.order_type != 'DRY_RUN' AND t.order_id IS NOT NULL AND t.order_id NOT LIKE 'DRY-%' AND t.order_id NOT LIKE 'ORD%')))
            ORDER BY t.created_at DESC LIMIT ?
        """
        rows = await db.execute_fetchall(sql, params)
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
# QUERY — EQUITY CURVE
# ═══════════════════════════════════════════════════════════════


async def get_equity_curve(
    symbol: str | None = None, demo: bool = False
) -> dict[str, Any]:
    """Tra ve equity curve data cho Chart.js."""
    params = [symbol.upper() if symbol else None, symbol, 1 if demo else 0]

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        sql = """
            SELECT t.created_at, t.pnl, t.symbol, t.side
            FROM trades t
            WHERE t.status = 'FILLED' AND t.pnl IS NOT NULL
              AND (t.symbol = ? OR ? IS NULL)
              AND (? = 1 OR (LOWER(t.exchange) = 'weex' OR (t.order_type != 'DRY_RUN' AND t.order_id IS NOT NULL AND t.order_id NOT LIKE 'DRY-%' AND t.order_id NOT LIKE 'ORD%')))
            ORDER BY t.created_at ASC
        """
        rows = await db.execute_fetchall(sql, params)

        labels = []
        cumulative_pnl = []
        drawdown_pct = []
        trades_detail = []
        running = 0.0
        peak = 0.0

        for r in rows:
            running += r[1]  # pnl
            if running > peak:
                peak = running
            dd_pct = round(((peak - running) / peak * 100), 2) if peak > 0 else 0.0
            labels.append(r[0])  # created_at
            cumulative_pnl.append(round(running, 2))
            drawdown_pct.append(dd_pct)
            trades_detail.append(
                {
                    "date": r[0],
                    "pnl": r[1],
                    "symbol": r[2],
                    "side": r[3],
                    "cumulative": round(running, 2),
                    "drawdown_pct": dd_pct,
                }
            )

        return {
            "labels": labels,
            "cumulative_pnl": cumulative_pnl,
            "drawdown_pct": drawdown_pct,
            "trades": trades_detail,
        }


# ═══════════════════════════════════════════════════════════════
# QUERY — BRIEFS
# ═══════════════════════════════════════════════════════════════


async def get_briefs(
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Truy vấn lịch sử morning briefs với pagination."""
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        row = await db.execute_fetchall("SELECT COUNT(*) as cnt FROM briefs")
        total = row[0][0] if row else 0

        limit = min(limit, 100)
        rows = await db.execute_fetchall(
            """SELECT * FROM briefs
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            [limit, offset],
        )

        briefs = []
        for r in rows:
            d = dict(r)
            # Parse JSON fields
            if d.get("scan_data"):
                try:
                    d["scan_data"] = json.loads(d["scan_data"])
                except ValueError as e:
                    log.warning("Ignored: %s", e)
            if d.get("vision_data"):
                try:
                    d["vision_data"] = json.loads(d["vision_data"])
                except ValueError as e:
                    log.warning("Ignored: %s", e)
            briefs.append(d)

    return {"briefs": briefs, "total": total, "limit": limit, "offset": offset}


async def get_brief_by_id(brief_id: int) -> dict[str, Any] | None:
    """Lấy chi tiết một brief theo ID."""
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            "SELECT * FROM briefs WHERE id = ?", [brief_id]
        )
        if not rows:
            return None
        d = dict(rows[0])
        if d.get("scan_data"):
            try:
                d["scan_data"] = json.loads(d["scan_data"])
            except ValueError as e:
                log.warning("Ignored: %s", e)
        if d.get("vision_data"):
            try:
                d["vision_data"] = json.loads(d["vision_data"])
            except ValueError as e:
                log.warning("Ignored: %s", e)
        return d


async def get_db_counts() -> dict[str, int]:
    """Đếm tổng records trong mỗi bảng cho system status.

    SEC-003 fix: Explicit allowlist guard before table name interpolation.
    SQLite does not support parameterized table names, so we validate against
    a hardcoded frozenset to prevent injection if this list ever becomes dynamic.
    """
    _ALLOWED_TABLES = frozenset({"signals", "trades", "briefs"})
    async with aiosqlite.connect(config.DB_PATH) as db:
        counts = {}
        for table in _ALLOWED_TABLES:
            if table == "signals":
                rows = await db.execute_fetchall("SELECT COUNT(*) FROM signals")
            elif table == "trades":
                rows = await db.execute_fetchall("SELECT COUNT(*) FROM trades")
            elif table == "briefs":
                rows = await db.execute_fetchall("SELECT COUNT(*) FROM briefs")
            else:
                raise ValueError(f"Disallowed table name: {table!r}")
            counts[f"{table}_count"] = rows[0][0] if rows else 0
        return counts


async def get_sentiment_history(symbol: str, limit: int = 30) -> list[dict[str, Any]]:
    """Get historical sentiment records for a symbol."""
    clean_symbol = symbol.split(":")[-1].split(".")[0].split("_")[0].upper()
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT created_at, combined_score, twitter_score, rss_score, glassnode_score, raw_data
               FROM sentiment_logs
               WHERE symbol = ? OR symbol = ?
               ORDER BY created_at DESC LIMIT ?""",
            (clean_symbol, symbol, limit),
        )
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("raw_data"):
                try:
                    d["raw_data"] = json.loads(d["raw_data"])
                except Exception:  # noqa: S110
                    pass
            result.append(d)
        result.reverse()
        return result


# ═══════════════════════════════════════════════════════════════
# CONSENSUS QUERY
# ═══════════════════════════════════════════════════════════════


async def get_consensus_audit_logs(
    limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        sql = """
            SELECT * FROM consensus_audit_logs
            ORDER BY timestamp DESC LIMIT ? OFFSET ?
        """
        rows = await db.execute_fetchall(sql, [limit, offset])
        return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
# STATE LEDGER QUERY
# ═══════════════════════════════════════════════════════════════


async def get_signals(
    symbol: str | None = None,
    state: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Truy van danh sach signals de phuc vu Ledger Dashboard UI."""
    query_parts = []
    params = []

    if symbol:
        query_parts.append("symbol = ?")
        params.append(symbol.upper())

    if state:
        query_parts.append("state = ?")
        params.append(state.upper())

    where_clause = " WHERE " + " AND ".join(query_parts) if query_parts else ""

    limit = min(limit, 200)

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Lay tong so record
        count_sql = f"SELECT COUNT(*) as cnt FROM signals{where_clause}"  # noqa: S608
        row = await db.execute_fetchall(count_sql, params)
        total = row[0][0] if row else 0

        # Lay danh sach record theo trang
        fetch_sql = f"""  # noqa: S608
            SELECT id, created_at, symbol, action, price, quote_qty, source_ip, payload, mode, processed, vbs_queue_id, state, rejection_reason
            FROM signals
            {where_clause}  # noqa: S608
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
        """  # noqa: S608
        rows = await db.execute_fetchall(fetch_sql, params + [limit, offset])

        signals = []
        for r in rows:
            d = dict(r)
            if d.get("payload"):
                try:
                    d["payload"] = json.loads(d["payload"])
                except Exception:  # noqa: S110
                    pass
            signals.append(d)

    return {"signals": signals, "total": total, "limit": limit, "offset": offset}
