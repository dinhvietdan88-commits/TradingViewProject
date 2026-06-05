"""
P6 — Analysis Engine
Trend Template scorer (8 Minervini criteria) + VCP detector.
"""
import logging
import asyncio
import aiohttp
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class TrendTemplateResult:
    score: int                          # 0-8
    criteria: dict[str, bool]           # {criterion_name: passed}
    stage: str                          # "Stage 2", "Stage 1", "Stage 3/4", "Unknown"
    summary: str                        # Human-readable summary
    macro_regime: str = "Unknown"       # "Bull", "Bear", "Choppy", "Unknown"


@dataclass
class VCPResult:
    detected: bool
    volume_ratio: float  # current vol / 20-period avg (< 0.5 = contraction)
    range_ratio: float                  # (H-L) / ATR14 (< 0.5 = narrow)
    pivot_level: Optional[float]        # estimated breakout pivot
    vol_breakout: bool  # volume > 1.2x average (for breakout confirmation)
    note: str


@dataclass
class ScanResult:
    symbol: str
    price: float
    change_pct: float
    trend_template: TrendTemplateResult
    vcp: VCPResult
    volume: float
    volume_avg: Optional[float]
    exchange: str = ""
    error: Optional[str] = None


@dataclass
class MTFScanResult:
    symbol: str
    exchange: str
    price: float
    timeframes: Dict[str, ScanResult]
    aligned_long: bool
    aligned_short: bool
    verdict: str



def score_trend_template(
    price: float,
    sma50: Optional[float],
    sma150: Optional[float],
    sma200: Optional[float],
    high_52w: Optional[float],
    low_52w: Optional[float],
    sma200_slope: Optional[float] = None,   # positive = trending up
    rs_ratio: Optional[float] = None,       # > 1.0 = outperforming benchmark
) -> TrendTemplateResult:
    """
    Score 8 Minervini Trend Template criteria.

    Criteria:
    1. Price > SMA150 AND Price > SMA200
    2. SMA150 > SMA200
    3. SMA200 trending up (slope > 0, need at least 1 month = 20 bars)
    4. SMA50 > SMA150 AND SMA50 > SMA200
    5. Price > SMA50
    6. Price >= 52-week low × 1.30 (at least 30% above 52w low)
    7. Price >= 52-week high × 0.75 (within 25% of 52w high)
    8. Relative Strength vs benchmark > 1.0 (outperforming)
    """
    criteria = {}

    # 1. Price > SMA150 & SMA200
    if sma150 is not None and sma200 is not None:
        criteria["price_above_ma150_200"] = price > sma150 and price > sma200
    else:
        criteria["price_above_ma150_200"] = None

    # 2. SMA150 > SMA200
    if sma150 is not None and sma200 is not None:
        criteria["ma150_above_ma200"] = sma150 > sma200
    else:
        criteria["ma150_above_ma200"] = None

    # 3. SMA200 trending up
    if sma200_slope is not None:
        criteria["ma200_trending_up"] = sma200_slope > 0
    else:
        criteria["ma200_trending_up"] = None  # unknown

    # 4. SMA50 > SMA150 & SMA200
    if sma50 is not None and sma150 is not None and sma200 is not None:
        criteria["ma50_above_ma150_200"] = sma50 > sma150 and sma50 > sma200
    else:
        criteria["ma50_above_ma150_200"] = None

    # 5. Price > SMA50
    if sma50 is not None:
        criteria["price_above_ma50"] = price > sma50
    else:
        criteria["price_above_ma50"] = None

    # 6. Price >= 52w low × 1.30
    if low_52w is not None and low_52w > 0:
        criteria["above_52w_low_130pct"] = price >= low_52w * 1.30
    else:
        criteria["above_52w_low_130pct"] = None

    # 7. Price >= 52w high × 0.75 (within 25% of high)
    if high_52w is not None and high_52w > 0:
        criteria["within_25pct_of_52w_high"] = price >= high_52w * 0.75
    else:
        criteria["within_25pct_of_52w_high"] = None

    # 8. RS vs benchmark
    if rs_ratio is not None:
        criteria["rs_outperforming"] = rs_ratio > 1.0
    else:
        criteria["rs_outperforming"] = None

    # Score: count True (None = unknown, treated as 0)
    score = sum(1 for v in criteria.values() if v is True)

    # Macro regime classification
    macro_regime = "Unknown"
    if sma200_slope is not None and sma200 is not None:
        if sma200_slope > 0 and price > sma200:
            macro_regime = "Bull"
        elif sma200_slope < 0 and price < sma200:
            macro_regime = "Bear"
        else:
            macro_regime = "Choppy"

    # Stage classification
    if score >= 7:
        stage = "Stage 2 ⭐"
    elif score >= 5:
        stage = "Stage 1/2 Transition"
    elif score >= 3:
        stage = "Stage 1 (Base)"
    else:
        stage = "Stage 3/4 (Avoid)"

    # Macro Regime classification
    if sma200 is not None and sma50 is not None:
        if (
            price > sma50
            and sma50 > sma200
            and (sma200_slope is None or sma200_slope > 0)
        ):
            macro_regime = "Bull 🐂"
        elif (
            price < sma50
            and sma50 < sma200
            and (sma200_slope is None or sma200_slope < 0)
        ):
            macro_regime = "Bear 🐻"
        else:
            macro_regime = "Choppy 🌊"
    else:
        macro_regime = "Unknown"

    # Summary
    passed = [k for k, v in criteria.items() if v is True]
    failed = [k for k, v in criteria.items() if v is False]
    summary = f"Score {score}/8 — {stage}. Regime: {macro_regime}. ✅ {len(passed)} passed, ❌ {len(failed)} failed"

    return TrendTemplateResult(
        score=score,
        criteria=criteria,
        stage=stage,
        summary=summary,
        macro_regime=macro_regime
    )


def detect_vcp(
    price: float,
    high: float,
    low: float,
    volume: float,
    volume_avg20: Optional[float],
    atr14: Optional[float],
    high_52w: Optional[float],
) -> VCPResult:
    """
    Detect VCP (Volatility Contraction Pattern).

    Signals:
    - Volume < 50% of 20-period average (drying up = smart money accumulating)
    - Price range (H-L) < 50% of ATR14 (contraction)
    - Price within 10% of 52w high (near breakout zone)
    """
    volume_ratio = (volume / volume_avg20) if volume_avg20 and volume_avg20 > 0 else 1.0
    current_range = high - low
    range_ratio = (current_range / atr14) if atr14 and atr14 > 0 else 1.0

    vol_contracting = volume_ratio < 0.5
    range_contracting = range_ratio < 0.5
    near_high = (price >= high_52w * 0.90) if high_52w and high_52w > 0 else False
    vol_breakout = volume_ratio > 1.2

    detected = vol_contracting and range_contracting

    # Pivot estimate: slight above recent high
    pivot_level = round(high * 1.005, 2) if detected else None

    if detected and near_high:
        note = f"VCP xác nhận: vol={volume_ratio:.0%} avg, range={range_ratio:.0%} ATR — gần 52w high ⭐ WATCH"
    elif detected:
        note = f"VCP contraction: vol={volume_ratio:.0%} avg, range={range_ratio:.0%} ATR"
    elif vol_contracting:
        note = f"Volume co lại ({volume_ratio:.0%} avg) nhưng range chưa hẹp"
    elif range_contracting:
        note = f"Range hẹp ({range_ratio:.0%} ATR) nhưng volume chưa co"
    else:
        note = f"Không có VCP: vol={volume_ratio:.0%} avg, range={range_ratio:.0%} ATR"

    return VCPResult(
        detected=detected,
        volume_ratio=volume_ratio,
        range_ratio=range_ratio,
        pivot_level=pivot_level,
        vol_breakout=vol_breakout,
        note=note,
    )


async def _run_rest_scan_for_symbols(symbols: list[str]) -> list[ScanResult]:
    """Helper to run REST scanning for a list of symbols concurrently."""
    if not symbols:
        return []
    logger.info(f"Performing REST scan for symbols: {symbols}...")
    semaphore = asyncio.Semaphore(15)
    
    async with aiohttp.ClientSession() as session:
        btc_benchmarks = {}
        
        # Sequentially pre-fetch BTC benchmarks to avoid Thundering Herd
        unique_eids = set("weex" if sym.endswith("_UMCBL") else "binance" for sym in symbols)
        for eid in unique_eids:
            btc_symbol = "BTCUSDT_UMCBL" if eid == "weex" else "BTCUSDT"
            try:
                btc_candles = await fetch_candles_with_retry(session, eid, btc_symbol, limit=365, semaphore=semaphore)
                btc_closes = {c[0]: c[4] for c in btc_candles} if btc_candles else {}
                btc_benchmarks[eid] = (btc_candles, btc_closes)
            except Exception as ex:
                logger.warning(f"Could not fetch BTC benchmark for exchange {eid}: {ex}")
                btc_benchmarks[eid] = ([], {})

        tasks = []
        for sym in symbols:
            eid = "weex" if sym.endswith("_UMCBL") else "binance"
            btc_candles, btc_closes = btc_benchmarks[eid]
            tasks.append(scan_single_symbol_rest(session, eid, sym, btc_closes, btc_candles, semaphore))
        
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]


async def scan_symbols(symbols: list[str], mcp_client) -> list[ScanResult]:
    """
    Batch scan symbols: fetch data from MCP, score TT + VCP.
    Falls back to REST scanning if MCP is unavailable, fails, or returns incomplete data.
    Returns sorted by VCP detected first, then by TT score descending.
    """
    raw_data = None
    mcp_healthy = False
    
    if mcp_client is not None:
        try:
            health = await mcp_client.health_check()
            mcp_healthy = bool(health.get("connected"))
        except Exception as e:
            logger.warning(f"MCP health check failed: {e}")
            mcp_healthy = False

    if mcp_healthy:
        try:
            raw_data = await mcp_client.batch_run(symbols)
        except Exception as e:
            logger.warning(f"MCP batch_run failed: {e}. Falling back to REST scan.")

    if raw_data is None:
        logger.info("MCP is not healthy or batch_run failed. Globally falling back to REST scan.")
        results = await _run_rest_scan_for_symbols(symbols)
        results.sort(key=lambda r: (r.vcp.detected, r.trend_template.score), reverse=True)
        return results

    results = []
    symbols_for_rest_fallback = []

    for item in raw_data:
        sym = item["symbol"]

        if item.get("error"):
            logger.warning(f"MCP error for {sym}: {item.get('error')}. Adding to REST fallback scan.")
            symbols_for_rest_fallback.append(sym)
            continue

        quote = item.get("quote")
        studies = item.get("studies")

        # Check if we have the critical indicators needed for Trend Template
        has_essential_indicators = False
        if quote and studies:
            has_essential_indicators = (
                quote.close > 0 and
                studies.sma50 is not None and
                studies.sma150 is not None and
                studies.sma200 is not None
            )

        if not has_essential_indicators:
            logger.warning(f"MCP returned incomplete indicator/quote data for {sym}. Adding to REST fallback scan.")
            symbols_for_rest_fallback.append(sym)
            continue

        tt = score_trend_template(
            price=quote.close,
            sma50=studies.sma50,
            sma150=studies.sma150,
            sma200=studies.sma200,
            high_52w=studies.high_52w,
            low_52w=studies.low_52w,
            rs_ratio=studies.rs_line,
        )

        vcp = detect_vcp(
            price=quote.close,
            high=quote.high,
            low=quote.low,
            volume=quote.volume,
            volume_avg20=studies.volume_avg20,
            atr14=studies.atr14,
            high_52w=studies.high_52w,
        )

        results.append(ScanResult(
            symbol=sym,
            price=quote.close,
            change_pct=quote.change_pct,
            trend_template=tt,
            vcp=vcp,
            volume=quote.volume,
            volume_avg=studies.volume_avg20,
            exchange="weex" if sym.endswith("_UMCBL") else "binance",
            error=None,
        ))

    if symbols_for_rest_fallback:
        fallback_results = await _run_rest_scan_for_symbols(symbols_for_rest_fallback)
        results.extend(fallback_results)

    # Sort: VCP detected first, then by TT score desc
    results.sort(key=lambda r: (r.vcp.detected, r.trend_template.score), reverse=True)
    return results

    # Sort: VCP detected first, then by TT score desc
    results.sort(key=lambda r: (r.vcp.detected, r.trend_template.score), reverse=True)
    return results


# ── REST-based Concurrent Scanner ─────────────────────────────────────────

_latest_scan_results: List[ScanResult] = []
_scan_status: str = "idle"
_scan_start_time: Optional[str] = None
_scan_end_time: Optional[str] = None
_scan_error: Optional[str] = None
_scan_lock = asyncio.Lock()



async def fetch_candles_with_retry(
    session: aiohttp.ClientSession,
    exchange_name: str,
    symbol: str,
    interval: str = "1d",
    limit: int = 365,
    max_retries: int = 5,
    backoff_factor: float = 1.5,
    semaphore: Optional[asyncio.Semaphore] = None
) -> List[List[Any]]:
    """Fetch candles directly from public REST endpoints with retry-on-429 rate limit protection."""
    exchange_name = exchange_name.lower()
    if ":" in symbol:
        symbol = symbol.split(":")[-1]
    
    # Map standard timeframes to exchange standard
    bybit_tf_map = {"1d": "D", "4h": "240", "1h": "60"}
    
    # 1. Determine URL and params based on exchange
    if exchange_name == "weex":
        clean_symbol = symbol.upper().replace("/", "").replace("-", "").replace("_UMCBL", "").lower()
        weex_symbol = f"cmt_{clean_symbol}"
        url = "https://api-contract.weex.com/capi/v2/market/candles"
        params = {"symbol": weex_symbol, "granularity": interval, "limit": str(limit)}
    elif exchange_name == "bybit":
        bybit_interval = bybit_tf_map.get(interval, interval)
        url = "https://api.bybit.com/v5/market/kline"
        params = {"category": "linear", "symbol": symbol.upper(), "interval": bybit_interval, "limit": str(limit)}
    else:
        # Default to binance
        url = "https://api.binance.com/api/v3/klines"
        params = {"symbol": symbol.upper(), "interval": interval, "limit": str(limit)}

    retries = 0
    while retries < max_retries:
        try:
            if semaphore:
                await semaphore.acquire()
            try:
                async with session.get(url, params=params, timeout=10) as resp:
                    status = resp.status
                    headers = resp.headers
                    if hasattr(headers, "get") and not asyncio.iscoroutinefunction(headers.get):
                        retry_after_header = headers.get("Retry-After", None)
                    else:
                        retry_after_header = None
                    if status == 200:
                        res = await resp.json()
                    else:
                        res = None
            finally:
                if semaphore:
                    semaphore.release()

            if status == 429:
                retry_after = 1.0
                if retry_after_header is not None:
                    try:
                        retry_after = float(retry_after_header)
                    except ValueError:
                        try:
                            from email.utils import parsedate_to_datetime
                            from datetime import datetime, timezone
                            dt_hdr = parsedate_to_datetime(str(retry_after_header))
                            delta = (dt_hdr - datetime.now(timezone.utc)).total_seconds()
                            retry_after = max(delta, 1.0)
                        except Exception:
                            retry_after = 1.0
                wait_time = max(retry_after, backoff_factor ** retries)
                logger.warning(f"Rate limited (429) for {symbol} on {exchange_name}. Waiting {wait_time}s...")
                await asyncio.sleep(wait_time)
                retries += 1
                continue
            elif status != 200:
                # If Bybit category linear failed, try spot
                if exchange_name == "bybit" and params.get("category") == "linear":
                    logger.info(f"Bybit linear failed for {symbol}, trying category spot...")
                    params["category"] = "spot"
                    continue
                logger.warning(f"HTTP error {status} for {symbol} on {exchange_name}")
                await asyncio.sleep(backoff_factor ** retries)
                retries += 1
                continue

            # Process response
            if exchange_name == "weex":
                if isinstance(res, list):
                    ohlcv = []
                    for c in res:
                        ohlcv.append([
                            int(c[0]),
                            float(c[1]),
                            float(c[2]),
                            float(c[3]),
                            float(c[4]),
                            float(c[5])
                         ])
                    ohlcv.sort(key=lambda x: x[0])  # ascending order
                    return ohlcv
                else:
                    raise ValueError(f"Weex response is not a list: {res}")
            elif exchange_name == "bybit":
                if isinstance(res, dict) and res.get("retCode") == 0:
                    list_data = res.get("result", {}).get("list", [])
                    ohlcv = []
                    for c in list_data:
                        ohlcv.append([
                            int(c[0]),
                            float(c[1]),
                            float(c[2]),
                            float(c[3]),
                            float(c[4]),
                            float(c[5])
                        ])
                    ohlcv.reverse()  # ascending chronological order
                    return ohlcv
                else:
                    # try category spot if not tried
                    if params.get("category") == "linear":
                        logger.info("Bybit linear retCode non-zero, trying category spot...")
                        params["category"] = "spot"
                        continue
                    raise ValueError(f"Bybit response error: {res}")
            else:
                # Binance
                if isinstance(res, list):
                    ohlcv = []
                    for c in res:
                        ohlcv.append([
                            int(c[0]),
                            float(c[1]),
                            float(c[2]),
                            float(c[3]),
                            float(c[4]),
                            float(c[5])
                        ])
                    return ohlcv
                else:
                    raise ValueError(f"Binance response is not a list: {res}")

        except Exception as e:
            logger.warning(f"Attempt {retries+1} failed for {symbol} on {exchange_name}: {e}")
            await asyncio.sleep(backoff_factor ** retries)
            retries += 1

    logger.error(f"Failed to fetch candles for {symbol} on {exchange_name} after {max_retries} attempts.")
    raise RuntimeError(f"Failed to fetch candles for {symbol} on {exchange_name} after {max_retries} attempts.")


def _calculate_scan_result(
    ohlcv: List[List[Any]],
    exchange_name: str,
    symbol: str,
    btc_closes: Dict[int, float],
    btc_candles: List[List[Any]]
) -> ScanResult:
    """Analyze ohlcv to construct a ScanResult containing Trend Template & VCP scorecards."""
    if not ohlcv or len(ohlcv) < 50:
        return ScanResult(
            symbol=symbol, price=0.0, change_pct=0.0,
            trend_template=TrendTemplateResult(0, {}, "Unknown", "Unknown", f"Insufficient candles ({len(ohlcv) if ohlcv else 0})"),
            vcp=VCPResult(False, 1.0, 1.0, None, False, "Insufficient candles"),
            volume=0.0, volume_avg=None, exchange=exchange_name,
            error="Insufficient data"
        )

    prices = [c[4] for c in ohlcv]
    latest_close = prices[-1]
    latest_high = ohlcv[-1][2]
    latest_low = ohlcv[-1][3]
    latest_volume = ohlcv[-1][5]

    # Calculate change_pct
    prev_close = prices[-2] if len(prices) >= 2 else latest_close
    change_pct = ((latest_close - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

    # Calculate SMA indicators
    sma50 = sum(prices[-50:]) / 50 if len(prices) >= 50 else None
    sma150 = sum(prices[-150:]) / 150 if len(prices) >= 150 else None
    sma200 = sum(prices[-200:]) / 200 if len(prices) >= 200 else None

    # SMA200 slope (trend) over past 20 days
    sma200_20_ago = sum(prices[-220:-20]) / 200 if len(prices) >= 220 else None
    sma200_slope = (sma200 - sma200_20_ago) if (sma200 is not None and sma200_20_ago is not None) else None

    high_52w = max(c[2] for c in ohlcv[-365:])
    low_52w = min(c[3] for c in ohlcv[-365:])

    # ATR14 calculation
    tr_values = []
    for i in range(len(ohlcv)):
        h = ohlcv[i][2]
        low_val = ohlcv[i][3]
        if i == 0:
            tr = h - low_val
        else:
            prev_c = ohlcv[i-1][4]
            tr = max(h - low_val, abs(h - prev_c), abs(low_val - prev_c))
        tr_values.append(tr)
    atr14 = sum(tr_values[-14:]) / 14 if len(tr_values) >= 14 else None

    # Volume average 20
    volumes = [c[5] for c in ohlcv]
    volume_avg20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else None

    # Relative Strength ratio calculation vs BTC benchmark
    close_now = latest_close
    close_50_ago = ohlcv[-50][4] if len(ohlcv) >= 50 else ohlcv[0][4]
    ts_now = ohlcv[-1][0]
    ts_50_ago = ohlcv[-50][0] if len(ohlcv) >= 50 else ohlcv[0][0]

    btc_close_now = btc_closes.get(ts_now)
    btc_close_50_ago = btc_closes.get(ts_50_ago)

    if not btc_close_now and btc_candles:
        btc_close_now = btc_candles[-1][4]
    if not btc_close_50_ago and btc_candles:
        btc_close_50_ago = btc_candles[-50][4] if len(btc_candles) >= 50 else btc_candles[0][4]

    if close_50_ago > 0 and btc_close_50_ago and btc_close_50_ago > 0:
        perf_symbol = close_now / close_50_ago
        perf_btc = btc_close_now / btc_close_50_ago
        rs_ratio = perf_symbol / perf_btc
    else:
        rs_ratio = 1.0

    tt = score_trend_template(
        price=latest_close,
        sma50=sma50,
        sma150=sma150,
        sma200=sma200,
        high_52w=high_52w,
        low_52w=low_52w,
        sma200_slope=sma200_slope,
        rs_ratio=rs_ratio,
    )

    vcp = detect_vcp(
        price=latest_close,
        high=latest_high,
        low=latest_low,
        volume=latest_volume,
        volume_avg20=volume_avg20,
        atr14=atr14,
        high_52w=high_52w,
    )

    return ScanResult(
        symbol=symbol,
        price=latest_close,
        change_pct=change_pct,
        trend_template=tt,
        vcp=vcp,
        volume=latest_volume,
        volume_avg=volume_avg20,
        exchange=exchange_name,
        error=None
    )


async def scan_single_symbol_rest(
    session: aiohttp.ClientSession,
    exchange_name: str,
    symbol: str,
    btc_closes: Dict[int, float],
    btc_candles: List[List[Any]],
    semaphore: asyncio.Semaphore
) -> ScanResult:
    """Scan a single symbol using REST endpoints, scoring Trend Template & VCP."""
    try:
        ohlcv = await fetch_candles_with_retry(session, exchange_name, symbol, limit=365, semaphore=semaphore)
        return _calculate_scan_result(ohlcv, exchange_name, symbol, btc_closes, btc_candles)
    except Exception as e:
        logger.exception(f"Exception during REST scan for {symbol}")
        return ScanResult(
            symbol=symbol, price=0.0, change_pct=0.0,
            trend_template=TrendTemplateResult(0, {}, "Unknown", "Unknown", f"Scan error: {str(e)}"),
            vcp=VCPResult(False, 1.0, 1.0, None, False, "Scan error"),
            volume=0.0, volume_avg=None, exchange=exchange_name,
            error=str(e)
        )


async def scan_symbol_multi_timeframe(
    session: aiohttp.ClientSession,
    exchange_name: str,
    symbol: str,
    semaphore: asyncio.Semaphore
) -> MTFScanResult:
    """Scan 1D, 4H, and 1H timeframes for a symbol, verifying trend alignment."""
    timeframes = ["1d", "4h", "1h"]
    scans = {}
    
    btc_symbol = "BTCUSDT_UMCBL" if exchange_name == "weex" else "BTCUSDT"

    async def fetch_tf(tf):
        try:
            # Fetch symbol candles
            ohlcv = await fetch_candles_with_retry(session, exchange_name, symbol, interval=tf, limit=365, semaphore=semaphore)
            # Fetch BTC benchmark candles
            try:
                btc_candles = await fetch_candles_with_retry(session, exchange_name, btc_symbol, interval=tf, limit=365, semaphore=semaphore)
                btc_closes = {c[0]: c[4] for c in btc_candles} if btc_candles else {}
            except Exception:
                btc_candles = []
                btc_closes = {}
            
            # Analyze ohlcv
            result = _calculate_scan_result(ohlcv, exchange_name, symbol, btc_closes, btc_candles)
            return tf, result
        except Exception as e:
            logger.warning(f"Failed to scan timeframe {tf} for {symbol}: {e}")
            err_result = ScanResult(
                symbol=symbol, price=0.0, change_pct=0.0,
                trend_template=TrendTemplateResult(0, {}, "Unknown", "Unknown", f"Fetch error: {e}"),
                vcp=VCPResult(False, 1.0, 1.0, None, False, "Fetch error"),
                volume=0.0, volume_avg=None, exchange=exchange_name,
                error=str(e)
            )
            return tf, err_result

    tf_results = await asyncio.gather(*(fetch_tf(tf) for tf in timeframes))
    scans = dict(tf_results)

    price = 0.0
    for tf in ["1h", "4h", "1d"]:
        if tf in scans and scans[tf].price > 0:
            price = scans[tf].price
            break

    aligned_long = False
    aligned_short = False
    
    scan_1d = scans.get("1d")
    scan_4h = scans.get("4h")
    scan_1h = scans.get("1h")
    
    if scan_1d and scan_4h and scan_1h and not scan_1d.error and not scan_4h.error and not scan_1h.error:
        aligned_long = (
            scan_1d.trend_template.score >= 6 and
            scan_4h.trend_template.score >= 4 and
            (scan_1h.trend_template.score >= 4 or scan_1h.vcp.detected)
        )
        aligned_short = (
            scan_1d.trend_template.score <= 2 and
            scan_4h.trend_template.score <= 3 and
            scan_1h.trend_template.score <= 3
        )

    if aligned_long:
        verdict = "LONG SIGNAL (MTF Aligned) 📈"
    elif aligned_short:
        verdict = "SHORT SIGNAL (MTF Aligned) 📉"
    else:
        verdict = "NEUTRAL (No Alignment) 🟡"

    return MTFScanResult(
        symbol=symbol,
        exchange=exchange_name,
        price=price,
        timeframes=scans,
        aligned_long=aligned_long,
        aligned_short=aligned_short,
        verdict=verdict
    )



async def scan_all_configured_exchanges() -> List[ScanResult]:
    """Perform background scan of active symbols on all registered exchanges."""
    global _scan_status, _scan_start_time, _scan_end_time, _scan_error, _latest_scan_results

    async with _scan_lock:
        if _scan_status == "running":
            logger.info("Background scan already in progress. Skipping trigger.")
            return _latest_scan_results

        _scan_status = "running"
        _scan_start_time = datetime.now(timezone.utc).isoformat()
        _scan_end_time = None
        _scan_error = None

    try:
        from exchanges.registry import get_registry
        registry = get_registry()
        exchange_ids = registry.list_exchange_ids()
        
        results = []
        semaphore = asyncio.Semaphore(15)

        async with aiohttp.ClientSession() as session:
            async def fetch_exchange_metadata(eid):
                try:
                    adapter = registry.get_adapter(eid)
                    active_symbols = await adapter.get_active_symbols()
                except Exception as ex:
                    logger.warning(f"Could not retrieve active symbols for exchange {eid}: {ex}")
                    active_symbols = []

                btc_symbol = "BTCUSDT_UMCBL" if eid == "weex" else "BTCUSDT"
                try:
                    btc_candles = await fetch_candles_with_retry(session, eid, btc_symbol, limit=365, semaphore=semaphore)
                    btc_closes = {c[0]: c[4] for c in btc_candles} if btc_candles else {}
                except Exception as ex:
                    logger.warning(f"Could not fetch BTC benchmark for exchange {eid}: {ex}")
                    btc_candles = []
                    btc_closes = {}

                return eid, active_symbols, btc_candles, btc_closes

            metadata_results = await asyncio.gather(*(fetch_exchange_metadata(eid) for eid in exchange_ids))

            tasks = []
            for eid, active_symbols, btc_candles, btc_closes in metadata_results:
                for symbol in active_symbols:
                    tasks.append(scan_single_symbol_rest(
                        session=session,
                        exchange_name=eid,
                        symbol=symbol,
                        btc_closes=btc_closes,
                        btc_candles=btc_candles,
                        semaphore=semaphore
                    ))

            if tasks:
                results = list(await asyncio.gather(*tasks))


        # Sort: VCP setups first, then by trend template score desc, then by change_pct desc
        results.sort(key=lambda r: (
            1 if r.vcp and r.vcp.detected else 0,
            r.trend_template.score if r.trend_template else 0,
            r.change_pct
        ), reverse=True)

        async with _scan_lock:
            _latest_scan_results = results
            _scan_status = "completed"

    except Exception as e:
        logger.exception("Error executing background scan of configured exchanges")
        async with _scan_lock:
            _scan_error = str(e)
            _scan_status = "failed"
    finally:
        async with _scan_lock:
            _scan_end_time = datetime.now(timezone.utc).isoformat()

    return _latest_scan_results
