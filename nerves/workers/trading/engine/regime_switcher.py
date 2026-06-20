import logging
import math

import aiohttp

import config
from analysis import fetch_candles_with_retry

log = logging.getLogger(__name__)


def _calculate_ema(prices: list[float], span: int) -> list[float]:
    """Calculate Exponential Moving Average (EMA) for a list of prices."""
    if not prices:
        return []
    alpha = 2.0 / (span + 1)
    ema = [prices[0]]
    for price in prices[1:]:
        ema.append(alpha * price + (1.0 - alpha) * ema[-1])
    return ema


def _calculate_std_dev(values: list[float]) -> float:
    """Calculate standard deviation of a list of values."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


async def get_market_regime(symbol: str, exchange: str = "binance") -> str:
    """
    Xác định trạng thái thị trường ("TRENDING" hoặc "CHOP") cho symbol.
    Dựa trên:
    1. Sắp xếp thứ tự các đường EMA 20/50/100.
    2. Độ lệch chuẩn thu hẹp (Rolling Volatility) của 20 phiên gần nhất.
    3. Khoảng cách (spread) giữa các EMA.
    """
    try:
        # Tải 100 nến 1D gần nhất
        async with aiohttp.ClientSession() as session:
            candles = await fetch_candles_with_retry(
                session, exchange, symbol, interval="1d", limit=100
            )

        if not candles or len(candles) < 50:
            log.warning(
                f"RegimeSwitcher: Không đủ nến cho {symbol} ({len(candles) if candles else 0}). Mặc định TRENDING."
            )
            return "TRENDING"

        closes = [float(c[4]) for c in candles]

        # Tính toán EMA 20, 50, 100
        ema20 = _calculate_ema(closes, 20)
        ema50 = _calculate_ema(closes, 50)
        ema100 = _calculate_ema(closes, 100)

        latest_close = closes[-1]
        latest_ema20 = ema20[-1]
        latest_ema50 = ema50[-1]
        latest_ema100 = ema100[-1]

        # 1. Kiểm tra sự sắp xếp xu hướng (Trend alignment)
        # Up-trend: EMA20 > EMA50 > EMA100
        # Down-trend: EMA20 < EMA50 < EMA100
        is_trending_up = latest_ema20 > latest_ema50 > latest_ema100
        is_trending_down = latest_ema20 < latest_ema50 < latest_ema100
        is_aligned = is_trending_up or is_trending_down

        # 2. Tính toán Rolling Volatility (config.REGIME_VOLATILITY_WINDOW phiên gần nhất)
        recent_closes = closes[-config.REGIME_VOLATILITY_WINDOW :]
        std_dev = _calculate_std_dev(recent_closes)
        mean_price = sum(recent_closes) / len(recent_closes) if recent_closes else 1.0
        coef_of_variation = std_dev / mean_price if mean_price > 0 else 0.0

        # 3. Khoảng cách (Spread) giữa các EMA dưới dạng phần trăm giá
        spread = (
            abs(latest_ema20 - latest_ema100) / latest_close
            if latest_close > 0
            else 0.0
        )

        log.info(
            f"RegimeSwitcher: {symbol} - Aligned: {is_aligned}, Volatility: {coef_of_variation:.4f}, Spread: {spread:.4f}"
        )

        # Ngưỡng (Thresholds) để xác định Chop/Consolidation:
        # Nếu biến động giá quá nhỏ (< 1.5%) HOẶC các EMA xoắn vào nhau (spread < 1.5% và EMA không xếp hàng)
        if coef_of_variation < 0.015:
            # Giá biến động siêu hẹp -> CHOP
            log.info(
                f"RegimeSwitcher: {symbol} classified as CHOP due to low volatility ({coef_of_variation:.4f} < 0.015)"
            )
            return "CHOP"

        if not is_aligned and spread < 0.02:
            # Các đường EMA xoắn chéo nhau và spread hẹp -> CHOP
            log.info(
                f"RegimeSwitcher: {symbol} classified as CHOP due to EMA convergence (spread {spread:.4f} < 0.02)"
            )
            return "CHOP"

        # Ngược lại, xem là Trending
        log.info(f"RegimeSwitcher: {symbol} classified as TRENDING")
        return "TRENDING"

    except Exception as e:
        log.error(
            f"RegimeSwitcher: Lỗi xác định regime cho {symbol}: {e}. Mặc định TRENDING."
        )
        return "TRENDING"
