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
) -> int:
    """Luu tin hieu moi tu TradingView, tra ve signal_id."""
    async with aiosqlite.connect(config.DB_PATH, timeout=config.DB_TIMEOUT) as db:
        cursor = await db.execute(
            """INSERT INTO signals (symbol, action, price, quote_qty, source_ip, payload, mode, vbs_queue_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                symbol,
                action,
                price,
                quote_qty,
                source_ip,
                json.dumps(payload) if payload else None,
                mode,
                vbs_queue_id,
            ),
        )
        await db.commit()
        signal_id = cursor.lastrowid
        log.info(
            f"Signal #{signal_id} saved: {action} {symbol}"  # codeql[py/log-injection]
            + (f" [{mode}]" if mode else "")
            + (f" (vbs_queue_id={vbs_queue_id})" if vbs_queue_id else "")
        )
        return signal_id


async def update_signal_status(signal_id: int, processed: int):
    """Cap nhat trang thai signal: 0=pending, 1=success, 2=failed."""
    async with aiosqlite.connect(config.DB_PATH, timeout=config.DB_TIMEOUT) as db:
        await db.execute(
            "UPDATE signals SET processed = ? WHERE id = ?",
            (processed, signal_id),
        )
        await db.commit()


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
    async with aiosqlite.connect(config.DB_PATH, timeout=config.DB_TIMEOUT) as db:
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
    async with aiosqlite.connect(config.DB_PATH, timeout=config.DB_TIMEOUT) as db:
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
    async with aiosqlite.connect(config.DB_PATH, timeout=config.DB_TIMEOUT) as db:
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
