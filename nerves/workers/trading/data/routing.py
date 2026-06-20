import logging
import aiosqlite
import config

log = logging.getLogger(__name__)


async def get_db_path_by_signal_id(signal_id: int) -> str:
    """
    Check if the signal_id exists in forward_trades.db.
    Return FORWARD_DB_PATH if found, otherwise default to DB_PATH.
    """
    if not signal_id:
        return config.DB_PATH
    try:
        async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM signals WHERE id = ?", (signal_id,)
            ) as cur:
                row = await cur.fetchone()
                if row:
                    return config.FORWARD_DB_PATH
    except Exception as e:
        log.warning(f"Error checking signal_id {signal_id} in forward DB: {e}")
    return config.DB_PATH


async def get_db_path_by_trade_id(trade_id: int) -> str:
    """
    Check if the trade_id exists in forward_trades.db.
    Return FORWARD_DB_PATH if found, otherwise default to DB_PATH.
    """
    if not trade_id:
        return config.DB_PATH
    try:
        async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM trades WHERE id = ?", (trade_id,)
            ) as cur:
                row = await cur.fetchone()
                if row:
                    return config.FORWARD_DB_PATH
    except Exception as e:
        log.warning(f"Error checking trade_id {trade_id} in forward DB: {e}")
    return config.DB_PATH
