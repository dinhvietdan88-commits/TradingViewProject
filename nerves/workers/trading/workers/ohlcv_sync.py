"""
ohlcv_sync.py — OHLCV Candlestick Sync Daemon & Feature Crystallization Helpers.
Milestone 2 & Milestone 4.
"""

import asyncio
import logging
from typing import Any

from watchlist import get_watchlist
from security.sanitizers import sanitize_symbol, sanitize_log
from capture_client import get_capture_client

logger = logging.getLogger(__name__)


async def sync_ohlcv_all_symbols() -> None:
    """
    Fetch active symbols list using watchlist.get_watchlist().
    For each symbol, fetch last 200 candles of '5m' and 250 candles of '1d' via capture_client.
    Write batches to database.insert_ohlcv_batch().
    """
    import database

    logger.info("Starting sync_ohlcv_all_symbols daemon job")
    try:
        symbols = get_watchlist()
    except Exception as e:
        logger.error(f"Failed to fetch watchlist: {e}")
        return

    client = get_capture_client()

    for symbol in symbols:
        # Sync 5m
        try:
            logger.info(f"Syncing 5m OHLCV for {symbol}")
            candles_5m = await client.fetch_ohlcv(
                symbol, "5m", limit=200, force_exchange=True
            )
            if candles_5m:
                formatted = [
                    [symbol, c[0], c[1], c[2], c[3], c[4], c[5]] for c in candles_5m
                ]
                await database.insert_ohlcv_batch("5m", formatted)
            else:
                logger.warning(f"No 5m candles returned for {symbol}")
        except Exception as e:
            logger.error(f"Failed to sync 5m OHLCV for {symbol}: {e}", exc_info=True)

        await asyncio.sleep(0.5)

        # Sync 1d
        try:
            logger.info(f"Syncing 1d OHLCV for {symbol}")
            candles_1d = await client.fetch_ohlcv(
                symbol, "1d", limit=250, force_exchange=True
            )
            if candles_1d:
                formatted = [
                    [symbol, c[0], c[1], c[2], c[3], c[4], c[5]] for c in candles_1d
                ]
                await database.insert_ohlcv_batch("1d", formatted)
            else:
                logger.warning(f"No 1d candles returned for {symbol}")
        except Exception as e:
            logger.error(f"Failed to sync 1d OHLCV for {symbol}: {e}", exc_info=True)

        await asyncio.sleep(0.5)

    logger.info("Finished sync_ohlcv_all_symbols daemon job")


# ── Indicator Helpers ─────────────────────────────────────────────────────────


def get_sma(closes: list[float], period: int) -> float | None:
    """Calculate Simple Moving Average (SMA) of closes for the specified period."""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def get_rsi(closes: list[float], period: int) -> float | None:
    """Calculate Relative Strength Index (RSI) using Wilder's smoothing."""
    if len(closes) < period + 1:
        return None

    # Calculate differences
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [d if d > 0 else 0.0 for d in diffs]
    losses = [-d if d < 0 else 0.0 for d in diffs]

    # Initial average gain/loss (simple average)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder's smoothing
    for i in range(period, len(diffs)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0.0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def get_atr(
    highs: list[float], lows: list[float], closes: list[float], period: int
) -> float | None:
    """Calculate Average True Range (ATR) using Wilder's smoothing."""
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None

    tr_list = []
    for i in range(1, len(highs)):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i - 1])
        tr3 = abs(lows[i] - closes[i - 1])
        tr_list.append(max(tr1, tr2, tr3))

    if len(tr_list) < period:
        return None

    # Initial ATR (simple average)
    atr = sum(tr_list[:period]) / period

    # Wilder's smoothing
    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period

    return atr


# ── Feature Crystallization ───────────────────────────────────────────────────


async def calculate_crystallized_features(symbol: str) -> dict[str, Any]:
    """
    Fetch last 250 candles of 5m and 1d timeframes.
    Calculate SMA(50), SMA(150), SMA(200), RSI(14), and ATR(14) for both timeframes.
    Return a nested dict of features.
    """
    client = get_capture_client()
    features = {
        "5m": {
            "sma50": None,
            "sma150": None,
            "sma200": None,
            "rsi14": None,
            "atr14": None,
        },
        "1d": {
            "sma50": None,
            "sma150": None,
            "sma200": None,
            "rsi14": None,
            "atr14": None,
        },
    }

    # 5m timeframe
    try:
        candles_5m = await client.fetch_ohlcv(symbol, "5m", limit=250)
        if candles_5m and len(candles_5m) >= 200:
            closes = [float(c[4]) for c in candles_5m]
            highs = [float(c[2]) for c in candles_5m]
            lows = [float(c[3]) for c in candles_5m]

            features["5m"]["sma50"] = get_sma(closes, 50)
            features["5m"]["sma150"] = get_sma(closes, 150)
            features["5m"]["sma200"] = get_sma(closes, 200)
            features["5m"]["rsi14"] = get_rsi(closes, 14)
            features["5m"]["atr14"] = get_atr(highs, lows, closes, 14)
    except Exception as e:
        logger.warning(
            f"Failed to calculate 5m features for {sanitize_symbol(symbol)}: {sanitize_log(str(e))}"
        )

    # 1d timeframe
    try:
        candles_1d = await client.fetch_ohlcv(symbol, "1d", limit=250)
        if candles_1d and len(candles_1d) >= 200:
            closes = [float(c[4]) for c in candles_1d]
            highs = [float(c[2]) for c in candles_1d]
            lows = [float(c[3]) for c in candles_1d]

            features["1d"]["sma50"] = get_sma(closes, 50)
            features["1d"]["sma150"] = get_sma(closes, 150)
            features["1d"]["sma200"] = get_sma(closes, 200)
            features["1d"]["rsi14"] = get_rsi(closes, 14)
            features["1d"]["atr14"] = get_atr(highs, lows, closes, 14)
    except Exception as e:
        logger.warning(
            f"Failed to calculate 1d features for {sanitize_symbol(symbol)}: {sanitize_log(str(e))}"
        )

    return features
