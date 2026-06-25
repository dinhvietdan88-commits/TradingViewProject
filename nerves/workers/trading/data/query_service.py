import json
import logging
from typing import Optional, Dict, Any, List

import aiosqlite

import config

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# QUERY — TRADE HISTORY
# ═══════════════════════════════════════════════════════════════


async def get_trades(
    symbol: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    demo: bool = False,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Truy van lich su giao dich voi pagination va filter."""
    conditions = []
    params: list = []

    if symbol:
        conditions.append("t.symbol = ?")
        params.append(symbol.upper())
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

    join_clause = ""
    if mode:
        conditions.append("s.mode = ?")
        params.append(mode)
        join_clause = "JOIN signals s ON t.signal_id = s.id"
        if isinstance(mode, str) and mode.upper() == "FORWARD":
            conditions.append("s.id >= 1000000")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    mode_upper = mode.upper() if mode else ""
    db_path = (
        config.FORWARD_DB_PATH
        if (
            mode_upper == "FORWARD"
            or (mode_upper not in ("LIVE", "BACKTEST") and config.FORWARD_TEST_ENABLED)
        )
        else config.DB_PATH
    )
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Count total
        sql_query = f"SELECT COUNT(*) as cnt FROM trades t {join_clause} {where}"  # noqa: S608
        row = await db.execute_fetchall(sql_query, params)
        total = row[0][0] if row else 0

        # Fetch page
        limit = min(limit, 200)
        join_sql = (
            "JOIN signals s ON s.id = t.signal_id"
            if mode
            else "LEFT JOIN signals s ON s.id = t.signal_id"
        )
        sql_query = f"""SELECT t.*, s.action as signal_action, s.payload as signal_payload,
                       sl.twitter_score, sl.rss_score, sl.glassnode_score, sl.combined_score as sentiment_score, sl.raw_data as sentiment_raw
                FROM trades t
                {join_sql}
                LEFT JOIN sentiment_logs sl ON sl.id = (
                    SELECT id FROM sentiment_logs
                    WHERE symbol = t.symbol
                    AND created_at <= t.created_at
                    ORDER BY created_at DESC
                    LIMIT 1
                )
                {where}
                ORDER BY t.created_at DESC
                LIMIT ? OFFSET ?"""  # noqa: S608
        rows = await db.execute_fetchall(sql_query, params + [limit, offset])

        trades = []
        for r in rows:
            d = dict(r)
            if d.get("sentiment_raw"):
                try:
                    d["sentiment_raw"] = json.loads(d["sentiment_raw"])
                except Exception:  # noqa: S110
                    pass
            trades.append(d)

    return {"trades": trades, "total": total, "limit": limit, "offset": offset}


# ═══════════════════════════════════════════════════════════════
# QUERY — PERFORMANCE STATS
# ═══════════════════════════════════════════════════════════════


async def get_stats(
    symbol: Optional[str] = None, demo: bool = False, mode: Optional[str] = None
) -> Dict[str, Any]:
    """Tinh metrics hieu suat: Win Rate, Profit Factor, Drawdown."""
    conditions = ["t.status = 'FILLED'"]
    params: list = []

    if symbol:
        conditions.append("t.symbol = ?")
        params.append(symbol.upper())
    if not demo:
        conditions.append(
            "(LOWER(t.exchange) = 'weex' OR (t.order_type != 'DRY_RUN' AND t.order_id IS NOT NULL AND t.order_id NOT LIKE 'DRY-%' AND t.order_id NOT LIKE 'ORD%'))"
        )

    join_clause = ""
    if mode:
        conditions.append("s.mode = ?")
        params.append(mode)
        join_clause = "JOIN signals s ON t.signal_id = s.id"
        if isinstance(mode, str) and mode.upper() == "FORWARD":
            conditions.append("s.id >= 1000000")

    where = f"WHERE {' AND '.join(conditions)}"

    mode_upper = mode.upper() if mode else ""
    db_path = (
        config.FORWARD_DB_PATH
        if (
            mode_upper == "FORWARD"
            or (mode_upper not in ("LIVE", "BACKTEST") and config.FORWARD_TEST_ENABLED)
        )
        else config.DB_PATH
    )
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        sql_query = (
            f"SELECT t.pnl FROM trades t {join_clause} {where} AND t.pnl IS NOT NULL"  # noqa: S608
        )
        rows = await db.execute_fetchall(sql_query, params)

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


def _build_mode_stats(pnl_list: list) -> Dict[str, Any]:
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


async def get_stats_by_mode(
    demo: bool = False, mode: Optional[str] = None
) -> Dict[str, Any]:
    """Performance metrics grouped by strategy mode (MTT vs MIS)."""
    where_conds = ["t.status = 'FILLED'", "t.pnl IS NOT NULL"]
    if not demo:
        where_conds.append(
            "(LOWER(t.exchange) = 'weex' OR (t.order_type != 'DRY_RUN' AND t.order_id IS NOT NULL AND t.order_id NOT LIKE 'DRY-%' AND t.order_id NOT LIKE 'ORD%'))"
        )
    if isinstance(mode, str) and mode.upper() == "FORWARD":
        where_conds.append("s.id >= 1000000")
    where_clause = " AND ".join(where_conds)

    mode_upper = mode.upper() if mode else ""
    db_path = (
        config.FORWARD_DB_PATH
        if (
            mode_upper == "FORWARD"
            or (mode_upper not in ("LIVE", "BACKTEST") and config.FORWARD_TEST_ENABLED)
        )
        else config.DB_PATH
    )
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        sql_query = f"""
            SELECT t.pnl,
                   CASE
                     WHEN s.mode IS NULL OR TRIM(s.mode) = '' THEN 'OTHER'
                     ELSE UPPER(TRIM(s.mode))
                   END AS mode
            FROM trades t
            LEFT JOIN signals s ON s.id = t.signal_id
            WHERE {where_clause}
            """  # noqa: S608
        rows = await db.execute_fetchall(sql_query)

    all_rows = [(float(r["pnl"]), r["mode"]) for r in rows]

    # Overall bucket
    all_pnl = [pnl for pnl, _ in all_rows]
    overall = _build_mode_stats(all_pnl)

    # Per-mode buckets
    mode_map: Dict[str, list] = {}
    for pnl, mode in all_rows:
        mode_map.setdefault(mode, []).append(pnl)

    by_mode: Dict[str, Any] = {}
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
    symbol: Optional[str] = None,
    demo: bool = False,
    mode: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return the last N FILLED trades with signal mode for the /backtest history panel."""
    conditions = ["t.status = 'FILLED'", "t.pnl IS NOT NULL"]
    params: list = []
    if symbol:
        conditions.append("t.symbol = ?")
        params.append(symbol.upper())
    if not demo:
        conditions.append(
            "(LOWER(t.exchange) = 'weex' OR (t.order_type != 'DRY_RUN' AND t.order_id IS NOT NULL AND t.order_id NOT LIKE 'DRY-%' AND t.order_id NOT LIKE 'ORD%'))"
        )
    if mode:
        conditions.append("s.mode = ?")
        params.append(mode)
        if isinstance(mode, str) and mode.upper() == "FORWARD":
            conditions.append("s.id >= 1000000")

    where = f"WHERE {' AND '.join(conditions)}"
    params.append(limit)

    mode_upper = mode.upper() if mode else ""
    db_path = (
        config.FORWARD_DB_PATH
        if (
            mode_upper == "FORWARD"
            or (mode_upper not in ("LIVE", "BACKTEST") and config.FORWARD_TEST_ENABLED)
        )
        else config.DB_PATH
    )
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        join_sql = (
            "JOIN signals s ON s.id = t.signal_id"
            if mode
            else "LEFT JOIN signals s ON s.id = t.signal_id"
        )
        sql_query = f"""
            SELECT t.id,
                   t.created_at,
                   t.symbol,
                   t.side,
                   COALESCE(NULLIF(TRIM(s.mode), ''), 'OTHER') AS mode,
                   t.executed_price,
                   t.stop_loss_price,
                   t.take_profit_price,
                   t.pnl,
                   t.status,
                   t.exchange
            FROM trades t
            {join_sql}
            {where}
            ORDER BY t.created_at DESC
            LIMIT ?
            """  # noqa: S608
        rows = await db.execute_fetchall(sql_query, params)
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
# QUERY — EQUITY CURVE
# ═══════════════════════════════════════════════════════════════


async def get_equity_curve(
    symbol: Optional[str] = None, demo: bool = False, mode: Optional[str] = None
) -> Dict[str, Any]:
    """Tra ve equity curve data cho Chart.js."""
    conditions = ["t.status = 'FILLED'", "t.pnl IS NOT NULL"]
    params: list = []

    if symbol:
        conditions.append("t.symbol = ?")
        params.append(symbol.upper())
    if not demo:
        conditions.append(
            "(LOWER(t.exchange) = 'weex' OR (t.order_type != 'DRY_RUN' AND t.order_id IS NOT NULL AND t.order_id NOT LIKE 'DRY-%' AND t.order_id NOT LIKE 'ORD%'))"
        )

    join_clause = ""
    if mode:
        conditions.append("s.mode = ?")
        params.append(mode)
        join_clause = "JOIN signals s ON t.signal_id = s.id"
        if isinstance(mode, str) and mode.upper() == "FORWARD":
            conditions.append("s.id >= 1000000")

    where = f"WHERE {' AND '.join(conditions)}"

    mode_upper = mode.upper() if mode else ""
    db_path = (
        config.FORWARD_DB_PATH
        if (
            mode_upper == "FORWARD"
            or (mode_upper not in ("LIVE", "BACKTEST") and config.FORWARD_TEST_ENABLED)
        )
        else config.DB_PATH
    )
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        sql_query = f"""SELECT t.created_at, t.pnl, t.symbol, t.side, t.signal_id
                FROM trades t {join_clause} {where}
                ORDER BY t.created_at ASC"""  # noqa: S608
        rows = await db.execute_fetchall(sql_query, params)

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
                    "signal_id": r[4],
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
) -> Dict[str, Any]:
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
                except Exception:  # noqa: S110
                    pass
            if d.get("vision_data"):
                try:
                    d["vision_data"] = json.loads(d["vision_data"])
                except Exception:  # noqa: S110
                    pass
            briefs.append(d)

    return {"briefs": briefs, "total": total, "limit": limit, "offset": offset}


async def get_brief_by_id(brief_id: int) -> Optional[Dict[str, Any]]:
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
            except Exception:  # noqa: S110
                pass
        if d.get("vision_data"):
            try:
                d["vision_data"] = json.loads(d["vision_data"])
            except Exception:  # noqa: S110
                pass
        return d


async def get_db_counts() -> Dict[str, int]:
    """Đếm tổng records trong mỗi bảng cho system status."""
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


async def get_latest_sentiment_log(symbol: str) -> Optional[Dict[str, Any]]:
    """Retrieve the latest sentiment log for a given symbol."""
    clean_symbol = symbol.split(":")[-1].split(".")[0]
    if "_" in clean_symbol:
        clean_symbol = clean_symbol.split("_")[0]

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """SELECT * FROM sentiment_logs
               WHERE symbol = ?
               ORDER BY created_at DESC
               LIMIT 1""",
            [clean_symbol],
        )
        if not rows:
            return None
        d = dict(rows[0])
        if d.get("raw_data"):
            try:
                d["raw_data"] = json.loads(d["raw_data"])
            except Exception:  # noqa: S110
                pass
        return d


async def get_recent_sentiments(limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieve the recent sentiment logs across all symbols."""
    limit = min(limit, 100)
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            """SELECT * FROM sentiment_logs
               ORDER BY created_at DESC
               LIMIT ?""",
            [limit],
        )
        logs = []
        for r in rows:
            d = dict(r)
            if d.get("raw_data"):
                try:
                    d["raw_data"] = json.loads(d["raw_data"])
                except Exception:  # noqa: S110
                    pass
            logs.append(d)
        return logs


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
    mode: Optional[str] = None,
) -> dict[str, Any]:
    """Truy van danh sach signals de phuc vu Ledger Dashboard UI."""
    query_parts = []
    params = []

    if symbol:
        query_parts.append("symbol = ?")
        params.append(symbol.upper())

    if state:
        states = [s.strip().upper() for s in state.split(",")]
        if len(states) == 1:
            query_parts.append("state = ?")
            params.append(states[0])
        else:
            placeholders = ",".join("?" for _ in states)
            query_parts.append(f"state IN ({placeholders})")
            params.extend(states)

    if mode:
        query_parts.append("mode = ?")
        params.append(mode)
        if isinstance(mode, str) and mode.upper() == "FORWARD":
            query_parts.append("id >= 1000000")

    where_clause = " WHERE " + " AND ".join(query_parts) if query_parts else ""

    limit = min(limit, 1000)

    mode_upper = mode.upper() if mode else ""
    db_path = (
        config.FORWARD_DB_PATH
        if (
            mode_upper == "FORWARD"
            or (mode_upper not in ("LIVE", "BACKTEST") and config.FORWARD_TEST_ENABLED)
        )
        else config.DB_PATH
    )
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        # Lay tong so record
        count_sql = f"SELECT COUNT(*) as cnt FROM signals{where_clause}"  # noqa: S608
        row = await db.execute_fetchall(count_sql, params)
        total = row[0][0] if row else 0

        # Lay danh sach record theo trang
        fetch_sql = f"""
            SELECT id, created_at, symbol, action, price, quote_qty, source_ip, payload, mode, processed, vbs_queue_id, state, rejection_reason, analysis_features, raw_analysis_text
            FROM signals
            {where_clause}
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
            if d.get("analysis_features"):
                try:
                    d["analysis_features"] = json.loads(d["analysis_features"])
                except Exception:  # noqa: S110
                    pass
            signals.append(d)

    return {"signals": signals, "total": total, "limit": limit, "offset": offset}
