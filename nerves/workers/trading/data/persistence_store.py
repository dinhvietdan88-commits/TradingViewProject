import json
import logging
from typing import Any

import aiosqlite

import config

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# SIGNAL WRITE
# ═══════════════════════════════════════════════════════════════


async def insert_signal(
    symbol: str,
    action: str,
    price: float | None = None,
    quote_qty: float | None = None,
    source_ip: str | None = None,
    payload: dict | None = None,
    mode: str | None = None,
    vbs_queue_id: int | None = None,
    analysis_features: dict | None = None,
    raw_analysis_text: str | None = None,
) -> int:
    """Luu tin hieu moi tu TradingView, tra ve signal_id."""
    import time

    start_time = time.perf_counter()

    # Enforce privacy check: only store raw analysis on user's local machine, NEVER on server-a, server-b, server-c
    if getattr(config, "_is_restricted_server", lambda: False)() or not getattr(
        config, "STORE_RAW_ANALYSIS", False
    ):
        raw_analysis_text = None

    if analysis_features is None:
        try:
            from workers.ohlcv_sync import calculate_crystallized_features

            analysis_features = await calculate_crystallized_features(symbol)
        except Exception as e:
            log.warning(f"Failed to dynamically calculate crystallized features: {e}")
            analysis_features = None

    mode_upper = mode.upper() if mode else ""
    db_path = (
        config.FORWARD_DB_PATH
        if (
            mode_upper == "FORWARD"
            or (mode_upper not in ("LIVE", "BACKTEST") and config.FORWARD_TEST_ENABLED)
        )
        else config.DB_PATH
    )
    async with aiosqlite.connect(db_path, timeout=config.DB_TIMEOUT) as db:
        cursor = await db.execute(
            """INSERT INTO signals (symbol, action, price, quote_qty, source_ip, payload, mode, vbs_queue_id, analysis_features, raw_analysis_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                symbol,
                action,
                price,
                quote_qty,
                source_ip,
                json.dumps(payload) if payload else None,
                mode,
                vbs_queue_id,
                json.dumps(analysis_features) if analysis_features else None,
                raw_analysis_text,
            ),
        )
        await db.commit()
        signal_id = cursor.lastrowid
    latency_ms = (time.perf_counter() - start_time) * 1000
    log.info(f"DB_WRITE_LATENCY: {latency_ms:.2f}ms")
    log.info(
        f"Signal #{signal_id} saved: {action} {symbol}"  # codeql[py/log-injection]
        + (f" [{mode}]" if mode else "")
        + (f" (vbs_queue_id={vbs_queue_id})" if vbs_queue_id else "")
    )
    return signal_id


async def update_signal_status(signal_id: int, processed: int):
    """Cap nhat trang thai signal: 0=pending, 1=success, 2=failed."""
    from data.routing import get_db_path_by_signal_id

    db_path = await get_db_path_by_signal_id(signal_id)
    async with aiosqlite.connect(db_path, timeout=config.DB_TIMEOUT) as db:
        await db.execute(
            "UPDATE signals SET processed = ? WHERE id = ?",
            (processed, signal_id),
        )
        await db.commit()


async def update_signal_state(
    signal_id: int, state: str, rejection_reason: str | None = None
):
    """Cap nhat trang thai signal state (Ledger) kem theo ly do tu choi neu co."""
    from data.routing import get_db_path_by_signal_id

    db_path = await get_db_path_by_signal_id(signal_id)
    async with aiosqlite.connect(db_path, timeout=config.DB_TIMEOUT) as db:
        if rejection_reason:
            await db.execute(
                "UPDATE signals SET state = ?, rejection_reason = ? WHERE id = ?",
                (state, rejection_reason, signal_id),
            )
        else:
            await db.execute(
                "UPDATE signals SET state = ? WHERE id = ?",
                (state, signal_id),
            )
        await db.commit()
    log.info(
        f"Signal #{signal_id} state updated to: {state}"
        + (f" (reason: {rejection_reason})" if rejection_reason else "")
    )


async def insert_indicator_signal(
    signal_id: int,
    symbol: str,
    indicator_name: str,
    signal_type: str,
    confidence_score: int,
    conditions_met: str,
    metadata: str,
    interval: str = "",
    price: float | None = None,
    source_ip: str | None = None,
    exchange: str = "binance",
) -> int:
    """Luu tin hieu indicator vao bang indicator_signals (REQ 7.1 — full schema)."""
    from data.routing import get_db_path_by_signal_id

    db_path = await get_db_path_by_signal_id(signal_id)
    async with aiosqlite.connect(db_path, timeout=config.DB_TIMEOUT) as db:
        cursor = await db.execute(
            """INSERT INTO indicator_signals
               (signal_id, symbol, indicator_name, signal_type, interval, price,
                confidence_score, conditions_met, metadata, source_ip, exchange)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_id,
                symbol,
                indicator_name,
                signal_type,
                interval,
                price,
                confidence_score,
                conditions_met,
                metadata,
                source_ip,
                exchange,
            ),
        )
        await db.commit()
        indicator_signal_id = cursor.lastrowid
        log.info(
            f"Indicator Signal #{indicator_signal_id} saved for Webhook Signal #{signal_id}: "
            f"{indicator_name} {symbol} ({signal_type})"
        )
        return indicator_signal_id


# ═══════════════════════════════════════════════════════════════
# TRADE WRITE
# ═══════════════════════════════════════════════════════════════


async def insert_trade(
    signal_id: int,
    symbol: str,
    side: str,
    order_id: str | None = None,
    status: str | None = None,
    requested_qty: float | None = None,
    executed_qty: float | None = None,
    executed_price: float | None = None,
    commission: float | None = None,
    error_message: str | None = None,
    pnl: float | None = None,
    combined_score: str | None = None,
    exchange: str = "binance",
    vbs_queue_id: int | None = None,
) -> int:
    """Luu ket qua giao dich Binance/Bybit."""
    from data.routing import get_db_path_by_signal_id

    db_path = await get_db_path_by_signal_id(signal_id)
    async with aiosqlite.connect(db_path, timeout=config.DB_TIMEOUT) as db:
        # Auto-resolve vbs_queue_id from signals if not provided
        if vbs_queue_id is None:
            try:
                async with db.execute(
                    "SELECT vbs_queue_id FROM signals WHERE id = ?", (signal_id,)
                ) as cur:
                    row = await cur.fetchone()
                    if row:
                        vbs_queue_id = row[0]
            except Exception as e:
                log.warning(
                    f"Failed to auto-resolve vbs_queue_id for signal #{signal_id}: {e}"
                )

        cursor = await db.execute(
            """INSERT INTO trades
               (signal_id, symbol, side, order_id, status,
                requested_qty, executed_qty, executed_price,
                commission, error_message, pnl, combined_score, exchange, vbs_queue_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_id,
                symbol,
                side,
                order_id,
                status,
                requested_qty,
                executed_qty,
                executed_price,
                commission,
                error_message,
                pnl,
                combined_score,
                exchange,
                vbs_queue_id,
            ),
        )
        await db.commit()
        trade_id = cursor.lastrowid
        log.info(
            f"Trade #{trade_id} saved: {side} {symbol} on {exchange} (signal #{signal_id}, vbs_queue_id={vbs_queue_id})"
        )
        return trade_id


async def update_trade_oco(
    trade_id: int,
    stop_loss_price: float | None = None,
    take_profit_price: float | None = None,
    oco_order_id: str | None = None,
    order_type: str = "OCO",
) -> None:
    """Cập nhật OCO details cho một trade."""
    from data.routing import get_db_path_by_trade_id

    db_path = await get_db_path_by_trade_id(trade_id)
    async with aiosqlite.connect(db_path, timeout=config.DB_TIMEOUT) as db:
        await db.execute(
            """UPDATE trades SET
               stop_loss_price = ?, take_profit_price = ?,
               oco_order_id = ?, order_type = ?
               WHERE id = ?""",
            (stop_loss_price, take_profit_price, oco_order_id, order_type, trade_id),
        )
        await db.commit()
        log.info(
            f"Trade #{trade_id} updated: OCO SL=${stop_loss_price} TP=${take_profit_price}"
        )


# ═══════════════════════════════════════════════════════════════
# BRIEF WRITE
# ═══════════════════════════════════════════════════════════════


async def insert_brief(
    symbols_scanned: int,
    scan_data: str | None = None,
    ai_analysis: str | None = None,
    vision_data: str | None = None,
    screenshot: str | None = None,
    brief_text: str | None = None,
    success: int = 1,
) -> int:
    """Lưu morning brief vào database."""
    async with aiosqlite.connect(config.DB_PATH, timeout=config.DB_TIMEOUT) as db:
        cursor = await db.execute(
            """INSERT INTO briefs
               (symbols_scanned, scan_data, ai_analysis, vision_data,
                screenshot, brief_text, success)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                symbols_scanned,
                scan_data,
                ai_analysis,
                vision_data,
                screenshot,
                brief_text,
                success,
            ),
        )
        await db.commit()
        brief_id = cursor.lastrowid
        log.info(f"Brief #{brief_id} saved ({symbols_scanned} symbols scanned)")
        return brief_id


# ═══════════════════════════════════════════════════════════════
# SENTIMENT WRITE
# ═══════════════════════════════════════════════════════════════


async def insert_sentiment_log(
    symbol: str,
    twitter_score: float | None = None,
    rss_score: float | None = None,
    glassnode_score: float | None = None,
    combined_score: float | None = None,
    raw_data: dict[str, Any] | None = None,
) -> int:
    """Luu ket qua phan tich sentiment vao database."""
    async with aiosqlite.connect(config.DB_PATH, timeout=config.DB_TIMEOUT) as db:
        cursor = await db.execute(
            """INSERT INTO sentiment_logs
               (symbol, twitter_score, rss_score, glassnode_score, combined_score, raw_data)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                symbol,
                twitter_score,
                rss_score,
                glassnode_score,
                combined_score,
                json.dumps(raw_data) if raw_data else None,
            ),
        )
        await db.commit()
        log_id = cursor.lastrowid
        log.info(
            f"Sentiment log #{log_id} saved for {symbol}: combined={combined_score}"
        )
        return log_id


# ═══════════════════════════════════════════════════════════════
# CONSENSUS WRITE
# ═══════════════════════════════════════════════════════════════


async def insert_consensus_audit_log(
    operation: str,
    sa_verdict: str,
    sre_verdict: str,
    meta_verdict: str,
    ac_verdict: str,
    final_verdict: str,
    override_token: str | None,
    rationale: str,
    details: Any,
) -> int:
    import json

    details_str = json.dumps(details) if isinstance(details, dict) else (details or "")
    async with aiosqlite.connect(config.DB_PATH, timeout=config.DB_TIMEOUT) as db:
        cursor = await db.execute(
            """INSERT INTO consensus_audit_logs
               (operation, sa_verdict, sre_verdict, meta_verdict, ac_verdict, final_verdict, override_token, rationale, details)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                operation,
                sa_verdict,
                sre_verdict,
                meta_verdict,
                ac_verdict,
                final_verdict,
                override_token,
                rationale,
                details_str,
            ),
        )
        await db.commit()
        log_id = cursor.lastrowid
        log.info(f"Consensus audit log #{log_id} saved for {operation}")
        return log_id


# ═══════════════════════════════════════════════════════════════
# OHLCV WRITE
# ═══════════════════════════════════════════════════════════════


async def insert_ohlcv_batch(timeframe: str, candles: list) -> None:
    """Lưu batch OHLCV vào table tương ứng (ohlcv_5m hoặc ohlcv_1d) bằng INSERT OR REPLACE."""
    if timeframe not in ("5m", "1d"):
        raise ValueError(f"Invalid timeframe: {timeframe}. Must be '5m' or '1d'.")

    table_name = f"ohlcv_{timeframe}"
    query = f"INSERT OR REPLACE INTO {table_name} (symbol, timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)"  # noqa: S608

    data_to_insert = []
    for candle in candles:
        if isinstance(candle, dict):
            symbol = candle.get("symbol")
            timestamp = candle.get("timestamp")
            if timestamp is None:
                timestamp = candle.get("time")
            open_val = candle.get("open")
            high_val = candle.get("high")
            low_val = candle.get("low")
            close_val = candle.get("close")
            volume_val = candle.get("volume")

            if symbol is not None and timestamp is not None:
                data_to_insert.append(
                    (
                        symbol,
                        int(timestamp),
                        float(open_val) if open_val is not None else None,
                        float(high_val) if high_val is not None else None,
                        float(low_val) if low_val is not None else None,
                        float(close_val) if close_val is not None else None,
                        float(volume_val) if volume_val is not None else None,
                    )
                )
        elif isinstance(candle, (list, tuple)):
            if len(candle) == 7:
                data_to_insert.append(
                    (
                        candle[0],
                        int(candle[1]) if candle[1] is not None else None,
                        float(candle[2]) if candle[2] is not None else None,
                        float(candle[3]) if candle[3] is not None else None,
                        float(candle[4]) if candle[4] is not None else None,
                        float(candle[5]) if candle[5] is not None else None,
                        float(candle[6]) if candle[6] is not None else None,
                    )
                )
            else:
                log.warning(f"Skipping candle with invalid length: {candle}")
        else:
            log.warning(f"Skipping candle with unsupported type: {type(candle)}")

    if not data_to_insert:
        return

    async with aiosqlite.connect(config.DB_PATH, timeout=config.DB_TIMEOUT) as db:
        await db.executemany(query, data_to_insert)
        await db.commit()
    log.info(f"Inserted/Replaced {len(data_to_insert)} candles into {table_name}")
