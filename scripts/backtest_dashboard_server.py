import os
import sys
import json
import sqlite3
import datetime
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_vbs_backtest_campaign import (
    load_cached_candles,
    calculate_daily_indicators,
    calculate_hourly_indicators,
    get_signal_start_index,
    get_last_closed_candle,
    simulate_trade_execution,
)

app = FastAPI(
    title="V6 VBS Strategy - Dynamic Backtest Playground",
    description="Interactive backtesting dashboard that calculates trade outcomes dynamically based on signal ID and parameters.",
)

app.mount(
    "/static",
    StaticFiles(
        directory=str(PROJECT_ROOT / "nerves" / "workers" / "trading" / "static")
    ),
    name="static",
)

vbs_replay_db_path = PROJECT_ROOT / "scratch" / "vbs_replay.db"
signals_db_path = PROJECT_ROOT / "scratch" / "signal_queue_server_a.db"
v22_data_path = PROJECT_ROOT / "reports" / "v22_dashboard_data.js"

# Cache for loaded candles & indicators to keep API fast
CANDLE_CACHE = {}

# Cache for V2.2 pre-computed aggregate data
V22_DATA_CACHE = {}


def load_v22_data():
    """Load the pre-computed V2.2 dashboard data (with 0.05% slippage applied)."""
    if V22_DATA_CACHE:
        return V22_DATA_CACHE

    if not os.path.exists(v22_data_path):
        return {}

    with open(v22_data_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Parse: window.v22DashboardData = {...};
    json_str = content.replace("window.v22DashboardData = ", "").rstrip().rstrip(";")
    data = json.loads(json_str)
    V22_DATA_CACHE.update(data)
    return V22_DATA_CACHE


def load_data_and_indicators():
    if CANDLE_CACHE:
        return CANDLE_CACHE

    conn_v = sqlite3.connect(str(vbs_replay_db_path))
    cur_v = conn_v.cursor()
    cur_v.execute("SELECT DISTINCT symbol FROM replay_trades")
    active_symbols = [row[0] for row in cur_v.fetchall()]
    conn_v.close()

    if not active_symbols:
        active_symbols = ["BTCUSDT"]

    df_btc_daily = load_cached_candles("BTCUSDT", "1d")

    for sym in active_symbols:
        df_1d = load_cached_candles(sym, "1d")
        df_1h = load_cached_candles(sym, "1h")
        is_btc = sym in ("BTCUSDT", "BTC/USDT")

        df_1d_ind = calculate_daily_indicators(
            df_1d, is_btc=is_btc, df_btc_daily=df_btc_daily
        )
        df_1h_ind = calculate_hourly_indicators(df_1h)

        CANDLE_CACHE[f"{sym}_1d"] = df_1d_ind
        CANDLE_CACHE[f"{sym}_1h"] = df_1h_ind

    return CANDLE_CACHE


class BacktestParams(BaseModel):
    base_sl_pct: float = 8.0  # Baseline Stop Loss %
    base_tp_pct: float = 20.0  # Baseline Take Profit %
    s4_sl_atr_mult: float = 1.5
    s4_tp_atr_mult: float = 3.0
    s4_trail_atr_mult: float = 2.5
    s2_min_tt_score: int = 5
    s5_min_tt_score: int = 5
    s6_min_tt_score: int = 5
    s6_min_rsi: float = 50.0
    slippage_pct: float = 0.05  # Slippage penalty per side (%)


@app.get("/api/signals")
async def get_signals():
    """Retrieve list of all valid signals in queue (excluding mock/test signals)."""
    if not os.path.exists(signals_db_path):
        raise HTTPException(status_code=500, detail="Signals database not found.")

    conn = sqlite3.connect(str(signals_db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    # Synchronized filter with run_campaign: action must be buy/sell/long/short and price > 1000.0
    cur.execute(
        "SELECT id, symbol, action, price, received_at FROM signal_queue "
        "WHERE lower(action) IN ('buy', 'sell', 'long', 'short') "
        "AND price > 1000.0 "
        "ORDER BY id ASC"
    )
    rows = cur.fetchall()
    conn.close()

    return [dict(r) for r in rows]


def run_single_simulation(signal_id: int, params: BacktestParams) -> dict:
    if not os.path.exists(signals_db_path):
        raise HTTPException(status_code=500, detail="Signals database not found.")

    # Load data cache
    data_dfs = load_data_and_indicators()

    # Load signal
    conn = sqlite3.connect(str(signals_db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM signal_queue WHERE id = ?", (signal_id,))
    signal = cur.fetchone()
    conn.close()

    if not signal:
        raise HTTPException(status_code=404, detail=f"Signal #{signal_id} not found.")

    signal = dict(signal)
    symbol = signal["symbol"]
    action = signal["action"]
    price = signal["price"]
    received_at = signal["received_at"]
    payload_json = signal["payload_json"]

    # Check if we have candles for this symbol
    df_1d = data_dfs.get(f"{symbol}_1d")
    df_1h = data_dfs.get(f"{symbol}_1h")

    if df_1d is None or df_1h is None or len(df_1d) == 0 or len(df_1h) == 0:
        raise HTTPException(
            status_code=400, detail=f"No candle data available for symbol {symbol}."
        )

    # Parse signal time
    dt_signal = datetime.datetime.strptime(
        received_at.split(".")[0], "%Y-%m-%d %H:%M:%S"
    )
    dt_signal = dt_signal.replace(tzinfo=datetime.timezone.utc)
    signal_time_ms = int(dt_signal.timestamp() * 1000)

    # Find signal hourly start index
    start_idx = get_signal_start_index(df_1h, signal_time_ms)
    if start_idx == -1:
        raise HTTPException(
            status_code=400, detail="Signal timestamp is outside hourly candle range."
        )

    # Get daily indicators closed before signal
    daily_row = get_last_closed_candle(df_1d, signal_time_ms, 86400000)
    daily_price = daily_row["close"]
    daily_atr = daily_row["atr14"]
    daily_volume = daily_row["volume"]
    daily_volume_avg20 = daily_row["volume_avg20"]
    daily_high = daily_row["high"]
    daily_low = daily_row["low"]
    daily_high52w = daily_row["high52w"]
    daily_low52w = daily_row["low52w"]
    daily_rsi = daily_row["rsi14"]
    daily_macd = daily_row["macd_line"]
    daily_macd_sig = daily_row["macd_signal"]
    daily_ema20 = daily_row["ema20"]
    daily_ema50 = daily_row["ema50"]
    daily_ema100 = daily_row["ema100"]

    is_long = action.lower() in ("buy", "long")
    tt_score = daily_row["tt_score_long"] if is_long else daily_row["tt_score_short"]

    # VCP check
    volume_ratio = (
        (daily_volume / daily_volume_avg20)
        if daily_volume_avg20 and daily_volume_avg20 > 0
        else 1.0
    )
    range_ratio = (
        ((daily_high - daily_low) / daily_atr) if daily_atr and daily_atr > 0 else 1.0
    )
    vol_contracting = volume_ratio < 0.5
    range_contracting = range_ratio < 0.5
    if is_long:
        near_boundary = (
            (daily_price >= daily_high52w * 0.90) if daily_high52w else False
        )
    else:
        near_boundary = (daily_price <= daily_low52w * 1.10) if daily_low52w else False
    vcp_met = vol_contracting and range_contracting and near_boundary

    # Parse payload SL/TP
    payload = json.loads(payload_json) if payload_json else {}
    sl_val = payload.get("sl") or signal.get("sl")
    tp_val = payload.get("tp") or signal.get("tp")

    # 1. Custom Baseline SL/TP
    if not sl_val or not tp_val:
        if is_long:
            base_sl = price * (1.0 - params.base_sl_pct / 100.0)
            base_tp = price * (1.0 + params.base_tp_pct / 100.0)
        else:
            base_sl = price * (1.0 + params.base_sl_pct / 100.0)
            base_tp = price * (1.0 - params.base_tp_pct / 100.0)
    else:
        base_sl = float(sl_val)
        base_tp = float(tp_val)

    scenarios_results = {}

    # S1: Baseline
    sim1 = simulate_trade_execution(
        df_1h,
        start_idx,
        action,
        price,
        base_sl,
        base_tp,
        slippage_pct=params.slippage_pct,
    )
    scenarios_results["S1"] = {
        "executed": True,
        "sl": base_sl,
        "tp": base_tp,
        "close_price": sim1["close_price"],
        "close_time_ms": sim1["close_time_ms"],
        "pnl_pct": sim1["pnl_pct"],
        "outcome": sim1["close_reason"],
        "bars": sim1["exit_idx"] - start_idx,
        "exit_idx": sim1["exit_idx"],
    }

    # S2: Minervini
    s2_ok = tt_score >= params.s2_min_tt_score and vcp_met
    if s2_ok:
        sim2 = simulate_trade_execution(
            df_1h,
            start_idx,
            action,
            price,
            base_sl,
            base_tp,
            slippage_pct=params.slippage_pct,
        )
        scenarios_results["S2"] = {
            "executed": True,
            "sl": base_sl,
            "tp": base_tp,
            "close_price": sim2["close_price"],
            "close_time_ms": sim2["close_time_ms"],
            "pnl_pct": sim2["pnl_pct"],
            "outcome": sim2["close_reason"],
            "bars": sim2["exit_idx"] - start_idx,
            "exit_idx": sim2["exit_idx"],
        }
    else:
        scenarios_results["S2"] = {
            "executed": False,
            "reason": f"Trend Template score = {tt_score}/8 (need >= {params.s2_min_tt_score}) or VCP filter met = {vcp_met} (need True)",
        }

    # S3: Short-term EMA Filter
    ema_aligned = (
        (daily_price > daily_ema20 > daily_ema50 > daily_ema100)
        if is_long
        else (daily_price < daily_ema20 < daily_ema50 < daily_ema100)
    )
    if ema_aligned:
        sim3 = simulate_trade_execution(
            df_1h,
            start_idx,
            action,
            price,
            base_sl,
            base_tp,
            slippage_pct=params.slippage_pct,
        )
        scenarios_results["S3"] = {
            "executed": True,
            "sl": base_sl,
            "tp": base_tp,
            "close_price": sim3["close_price"],
            "close_time_ms": sim3["close_time_ms"],
            "pnl_pct": sim3["pnl_pct"],
            "outcome": sim3["close_reason"],
            "bars": sim3["exit_idx"] - start_idx,
            "exit_idx": sim3["exit_idx"],
        }
    else:
        scenarios_results["S3"] = {
            "executed": False,
            "reason": "Daily EMA trend stack is not aligned (Price > EMA20 > EMA50 > EMA100 for long, opposite for short)",
        }

    # S4: Tight SL / Trailing Stop (using custom ATR multipliers)
    if daily_atr and daily_atr > 0:
        if is_long:
            tight_sl = price - (params.s4_sl_atr_mult * daily_atr)
            tight_tp = price + (params.s4_tp_atr_mult * daily_atr)
        else:
            tight_sl = price + (params.s4_sl_atr_mult * daily_atr)
            tight_tp = price - (params.s4_tp_atr_mult * daily_atr)

        sim4 = simulate_trade_execution(
            df_1h,
            start_idx,
            action,
            price,
            tight_sl,
            tight_tp,
            is_trailing=True,
            trailing_dist_atr=params.s4_trail_atr_mult,
            daily_atr14=daily_atr,
            slippage_pct=params.slippage_pct,
        )
        scenarios_results["S4"] = {
            "executed": True,
            "sl": tight_sl,
            "tp": tight_tp,
            "close_price": sim4["close_price"],
            "close_time_ms": sim4["close_time_ms"],
            "pnl_pct": sim4["pnl_pct"],
            "outcome": sim4["close_reason"],
            "bars": sim4["exit_idx"] - start_idx,
            "exit_idx": sim4["exit_idx"],
            "trailing_sl_history": sim4.get("trailing_sl_history", []),
        }
    else:
        scenarios_results["S4"] = {
            "executed": False,
            "reason": "ATR14 is not available on daily candles",
        }

    # S5: Multi-Timeframe Validation
    s5_ok = False
    if tt_score >= params.s5_min_tt_score:
        hourly_row = get_last_closed_candle(df_1h, signal_time_ms, 3600000)
        h_ema20 = hourly_row["ema20"]
        h_ema50 = hourly_row["ema50"]
        h_ema200 = hourly_row["ema200"]
        if is_long:
            if h_ema20 > h_ema50 and h_ema50 > h_ema200:
                s5_ok = True
        else:
            if h_ema20 < h_ema50 and h_ema50 < h_ema200:
                s5_ok = True

    if s5_ok:
        sim5 = simulate_trade_execution(
            df_1h,
            start_idx,
            action,
            price,
            base_sl,
            base_tp,
            slippage_pct=params.slippage_pct,
        )
        scenarios_results["S5"] = {
            "executed": True,
            "sl": base_sl,
            "tp": base_tp,
            "close_price": sim5["close_price"],
            "close_time_ms": sim5["close_time_ms"],
            "pnl_pct": sim5["pnl_pct"],
            "outcome": sim5["close_reason"],
            "bars": sim5["exit_idx"] - start_idx,
            "exit_idx": sim5["exit_idx"],
        }
    else:
        scenarios_results["S5"] = {
            "executed": False,
            "reason": f"Trend Template score = {tt_score}/8 (need >= {params.s5_min_tt_score}) or hourly EMA trend not aligned",
        }

    # S6: Optimized Hybrid Mode
    s6_ok = False
    if tt_score >= params.s6_min_tt_score:
        if is_long:
            if daily_rsi >= params.s6_min_rsi and daily_macd > daily_macd_sig:
                s6_ok = True
        else:
            if daily_rsi <= (100.0 - params.s6_min_rsi) and daily_macd < daily_macd_sig:
                s6_ok = True

    if s6_ok:
        sim6 = simulate_trade_execution(
            df_1h,
            start_idx,
            action,
            price,
            base_sl,
            base_tp,
            slippage_pct=params.slippage_pct,
        )
        scenarios_results["S6"] = {
            "executed": True,
            "sl": base_sl,
            "tp": base_tp,
            "close_price": sim6["close_price"],
            "close_time_ms": sim6["close_time_ms"],
            "pnl_pct": sim6["pnl_pct"],
            "outcome": sim6["close_reason"],
            "bars": sim6["exit_idx"] - start_idx,
            "exit_idx": sim6["exit_idx"],
        }
    else:
        scenarios_results["S6"] = {
            "executed": False,
            "reason": f"Trend Template score = {tt_score}/8 (need >= {params.s6_min_tt_score}) or daily RSI/MACD not aligned",
        }

    # Calculate detailed Trend Template criteria at entry
    sma50 = daily_row.get("sma50")
    sma150 = daily_row.get("sma150")
    sma200 = daily_row.get("sma200")
    sma200_slope = daily_row.get("sma200_slope")
    high52w = daily_row.get("high52w")
    low52w = daily_row.get("low52w")
    rs_ratio = daily_row.get("rs_ratio")

    if is_long:
        tt_details = {
            "c1": bool(
                daily_price > sma150 and daily_price > sma200
                if sma150 and sma200
                else False
            ),
            "c2": bool(sma150 > sma200 if sma150 and sma200 else False),
            "c3": bool(sma200_slope > 0 if sma200_slope is not None else False),
            "c4": bool(
                sma50 > sma150 and sma50 > sma200
                if sma50 and sma150 and sma200
                else False
            ),
            "c5": bool(daily_price > sma50 if sma50 else False),
            "c6": bool(daily_price >= low52w * 1.30 if low52w else False),
            "c7": bool(daily_price >= high52w * 0.75 if high52w else False),
            "c8": bool(rs_ratio > 1.0 if rs_ratio is not None else False),
        }
    else:
        tt_details = {
            "c1": bool(
                daily_price < sma150 and daily_price < sma200
                if sma150 and sma200
                else False
            ),
            "c2": bool(sma150 < sma200 if sma150 < sma200 else False),
            "c3": bool(sma200_slope < 0 if sma200_slope is not None else False),
            "c4": bool(
                sma50 < sma150 and sma50 < sma200
                if sma50 and sma150 and sma200
                else False
            ),
            "c5": bool(daily_price < sma50 if sma50 else False),
            "c6": bool(daily_price <= high52w * 0.70 if high52w else False),
            "c7": bool(daily_price <= low52w * 1.25 if low52w else False),
            "c8": bool(rs_ratio < 1.0 if rs_ratio is not None else False),
        }

    return {
        "signal_info": {
            "vbs_id": signal_id,
            "symbol": symbol,
            "action": action.upper(),
            "price": price,
            "received_at": received_at,
            "start_idx": start_idx,
            "relative_entry_idx": 0,
        },
        "market_context": {
            "daily_close": float(daily_price),
            "daily_atr": float(daily_atr) if daily_atr else 0,
            "daily_rsi": float(daily_rsi),
            "daily_macd": float(daily_macd),
            "daily_macd_sig": float(daily_macd_sig),
            "tt_score": int(tt_score),
            "vcp_met": bool(vcp_met),
            "volume_ratio": float(volume_ratio),
            "range_ratio": float(range_ratio),
            "tt_details": tt_details,
        },
        "scenarios": scenarios_results,
        "df_1h": df_1h,
        "df_1d": df_1d,
        "daily_row_ts": int(daily_row["timestamp"]),
    }


@app.post("/api/simulate/{signal_id}")
async def simulate_signal(signal_id: int, params: BacktestParams):
    """Run dynamic S1 ~ S6 backtest simulation for a specific signal ID and custom parameters."""
    res = run_single_simulation(signal_id, params)

    # Format candles slice
    df_1h = res["df_1h"]
    df_1d = res.get("df_1d")
    daily_row_ts = res.get("daily_row_ts")
    start_idx = res["signal_info"]["start_idx"]

    # Dynamically find max exit index across all executed scenarios
    max_exit_idx = start_idx
    for sc in res["scenarios"].values():
        if sc.get("executed") and sc.get("exit_idx"):
            max_exit_idx = max(max_exit_idx, sc["exit_idx"])

    start_slice = max(0, start_idx - 30)
    end_slice = min(max(start_idx + 90, max_exit_idx + 15), len(df_1h))

    # Include indicator columns for scenario analysis charts
    candle_cols = ["timestamp", "open", "high", "low", "close", "volume"]
    indicator_cols = []
    for col in ["ema20", "ema50", "ema200"]:
        if col in df_1h.columns:
            indicator_cols.append(col)

    candles_slice = df_1h.iloc[start_slice:end_slice][
        candle_cols + indicator_cols
    ].to_dict(orient="records")

    # Convert NaN to None for JSON serialization
    for c in candles_slice:
        for k, v in c.items():
            if isinstance(v, float) and (v != v):  # NaN check
                c[k] = None

    # Format daily candles slice (30 days before entry, dynamically extended to cover max exit)
    daily_candles_slice = []
    if df_1d is not None and len(df_1d) > 0 and daily_row_ts is not None:
        # Find index of daily candle matching daily_row_ts
        daily_matches = df_1d[df_1d["timestamp"] == daily_row_ts]
        if len(daily_matches) > 0:
            daily_idx = daily_matches.index[0]
            daily_start_slice = max(0, daily_idx - 30)

            # Find the max close time across all executed scenarios
            max_close_time_ms = int(daily_row_ts)
            for sc in res["scenarios"].values():
                if sc.get("executed") and sc.get("close_time_ms"):
                    max_close_time_ms = max(max_close_time_ms, sc["close_time_ms"])

            # Find daily candle closed closest to or before max_close_time_ms
            daily_exit_matches = df_1d[df_1d["timestamp"] <= max_close_time_ms]
            if len(daily_exit_matches) > 0:
                daily_exit_idx = daily_exit_matches.index[-1]
                daily_end_slice = min(
                    max(daily_idx + 10, daily_exit_idx + 5), len(df_1d)
                )
            else:
                daily_end_slice = min(daily_idx + 10, len(df_1d))

            daily_cols = [
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "ema20",
                "ema50",
                "ema100",
                "rsi14",
                "macd_line",
                "macd_signal",
            ]
            valid_daily_cols = [col for col in daily_cols if col in df_1d.columns]
            daily_candles_slice = df_1d.iloc[daily_start_slice:daily_end_slice][
                valid_daily_cols
            ].to_dict(orient="records")

            # Convert NaN to None
            for c in daily_candles_slice:
                for k, v in c.items():
                    if isinstance(v, float) and (v != v):  # NaN check
                        c[k] = None

    res["signal_info"]["relative_entry_idx"] = start_idx - start_slice
    del res["df_1h"]
    if "df_1d" in res:
        del res["df_1d"]
    if "daily_row_ts" in res:
        del res["daily_row_ts"]

    return {
        "signal_info": res["signal_info"],
        "market_context": res["market_context"],
        "scenarios": res["scenarios"],
        "candles": candles_slice,
        "daily_candles": daily_candles_slice,
    }


@app.get("/api/v23/trade_replay/{signal_id}")
@app.get("/api/v22/trade_replay/{signal_id}")
async def get_v22_trade_replay(
    signal_id: int,
    scenario: str = "S4",
    base_sl_pct: float = 8.0,
    base_tp_pct: float = 20.0,
    s4_sl_atr_mult: float = 1.5,
    s4_tp_atr_mult: float = 3.0,
    s4_trail_atr_mult: float = 2.5,
    s2_min_tt_score: int = 5,
    s5_min_tt_score: int = 5,
    s6_min_tt_score: int = 5,
    s6_min_rsi: float = 50.0,
    slippage_pct: float = 0.05,
):
    """Simulate a specific trade in S1~S6 and return data structured for trade_replay.html."""
    params = BacktestParams(
        base_sl_pct=base_sl_pct,
        base_tp_pct=base_tp_pct,
        s4_sl_atr_mult=s4_sl_atr_mult,
        s4_tp_atr_mult=s4_tp_atr_mult,
        s4_trail_atr_mult=s4_trail_atr_mult,
        s2_min_tt_score=s2_min_tt_score,
        s5_min_tt_score=s5_min_tt_score,
        s6_min_tt_score=s6_min_tt_score,
        s6_min_rsi=s6_min_rsi,
        slippage_pct=slippage_pct,
    )

    res = run_single_simulation(signal_id, params)

    sc_code = scenario.upper()
    if sc_code not in res["scenarios"]:
        raise HTTPException(status_code=400, detail=f"Invalid scenario {scenario}")

    sc_res = res["scenarios"][sc_code]
    if not sc_res.get("executed", False):
        raise HTTPException(
            status_code=400,
            detail=f"Trade {signal_id} did not execute under scenario {scenario}: {sc_res.get('reason', 'Unknown reason')}",
        )

    # Get exit index and start index
    df_1h = res["df_1h"]
    start_idx = res["signal_info"]["start_idx"]
    exit_idx = sc_res["exit_idx"]

    # Slice of candles: 30 before entry to max(start_idx + 90, exit_idx + 15)
    start_slice = max(0, start_idx - 30)
    end_slice = min(max(start_idx + 90, exit_idx + 15), len(df_1h))

    candles_slice = df_1h.iloc[start_slice:end_slice][
        ["timestamp", "open", "high", "low", "close", "volume"]
    ].to_dict(orient="records")

    mapped_bars = []
    for c in candles_slice:
        mapped_bars.append(
            {
                "time": int(c["timestamp"]) // 1000,
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c["volume"]),
            }
        )

    action = res["signal_info"]["action"]
    entry_price = res["signal_info"]["price"]
    close_price = sc_res["close_price"]

    exit_type_map = {
        "TAKE_PROFIT": "TP",
        "STOP_LOSS": "SL",
        "TRAILING_STOP": "SL",
        "TIMEOUT": "TO",
    }
    raw_outcome = sc_res["outcome"]
    exit_type = exit_type_map.get(raw_outcome, "TO")

    entry_ts = int(df_1h.iloc[start_idx]["timestamp"]) // 1000
    exit_ts = int(sc_res["close_time_ms"]) // 1000

    dt_entry = datetime.datetime.fromtimestamp(entry_ts, tz=datetime.timezone.utc)
    dt_exit = datetime.datetime.fromtimestamp(exit_ts, tz=datetime.timezone.utc)

    pnl_val = sc_res["pnl_pct"] * entry_price

    trade_obj = {
        "id": f"{sc_code}_{signal_id}",
        "cfg": sc_code,
        "side": "long" if action.lower() in ("buy", "long") else "short",
        "outcome": "WIN" if sc_res["pnl_pct"] >= 0 else "LOSS",
        "exit_type": exit_type,
        "entry": entry_price,
        "exit": close_price,
        "sl": sc_res["sl"],
        "tp": sc_res["tp"],
        "pnl": pnl_val,
        "pnl_pct": sc_res["pnl_pct"],
        "bars_held": sc_res["bars"],
        "entry_time": dt_entry.strftime("%Y-%m-%dT%H:%M:%S"),
        "exit_time": dt_exit.strftime("%Y-%m-%dT%H:%M:%S"),
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "rsi": res["market_context"]["daily_rsi"],
        "adx": 30.0,
        "atr": res["market_context"]["daily_atr"],
        "ema200": None,
        "bars": mapped_bars,
    }

    return trade_obj


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════
# V2.2 AGGREGATE DATA APIs — Synced from Pattern Analysis
# ═══════════════════════════════════════════════════════════════


@app.get("/api/v23/aggregate")
@app.get("/api/v22/aggregate")
async def get_v22_aggregate():
    """Serve V2.2 pre-computed aggregate metrics (equity curves, KPIs per scenario).
    This data was generated with 0.05% slippage from 1,015 real signals."""
    data = load_v22_data()
    if not data:
        raise HTTPException(
            status_code=404,
            detail="V2.2 dashboard data not found. Run generate_v22_real_data.py first.",
        )

    # Build a lightweight summary (without the full equity curves to keep response fast)
    summary = {
        "generated_at": data.get("generated_at"),
        "total_signals": data.get("total_signals", 0),
        "slippage_penalty_pct": data.get("slippage_penalty_pct", 0.05),
        "scenarios": {},
    }

    for sc_code, sc_data in data.get("scenarios", {}).items():
        summary["scenarios"][sc_code] = {
            "executed_trades": sc_data.get("executed_trades", 0),
            "fixed": {
                k: v for k, v in sc_data.get("fixed", {}).items() if k != "equity_curve"
            },
            "dynamic": {
                k: v
                for k, v in sc_data.get("dynamic", {}).items()
                if k != "equity_curve"
            },
        }

    return summary


@app.get("/api/v23/equity")
@app.get("/api/v22/equity")
async def get_v22_equity(scenario: str = "S4", sizing: str = "fixed"):
    """Serve the real equity curve data for a specific scenario and sizing mode."""
    data = load_v22_data()
    if not data:
        raise HTTPException(status_code=404, detail="V2.2 data not found.")

    sc_data = data.get("scenarios", {}).get(scenario)
    if not sc_data:
        raise HTTPException(
            status_code=404, detail=f"Scenario {scenario} not found in V2.2 data."
        )

    sizing_data = sc_data.get(sizing, {})
    return {
        "scenario": scenario,
        "sizing": sizing,
        "equity_curve": sizing_data.get("equity_curve", []),
        "drawdown_curve": sizing_data.get("drawdowns", []),
        "trades_count": sc_data.get("executed_trades", 0),
    }


@app.get("/api/v23/trades")
@app.get("/api/v22/trades")
async def get_v22_trades(
    scenario: str = "S4",
    page: int = Query(0, ge=0),
    per_page: int = Query(50, ge=1, le=200),
    outcome: Optional[str] = None,
    side: Optional[str] = None,
):
    """Serve paginated scenario-specific trades from V2.2 data with optional filters."""
    data = load_v22_data()
    if not data:
        raise HTTPException(status_code=404, detail="V2.2 data not found.")

    trades_key = f"{scenario.lower()}_trades"
    trades = data.get(trades_key, [])
    if not trades and scenario.upper() == "S4":
        trades = data.get("s4_trades", [])

    # Apply filters
    if outcome:
        trades = [t for t in trades if t.get("outcome") == outcome]
    if side:
        trades = [t for t in trades if t.get("side", "").upper() == side.upper()]

    total = len(trades)
    start = page * per_page
    page_trades = trades[start : start + per_page]

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "trades": page_trades,
    }


@app.get("/reports/trade_replay", response_class=HTMLResponse)
def serve_trade_replay():
    return FileResponse(str(PROJECT_ROOT / "reports" / "trade_replay.html"))


@app.get("/reports/monthly_pattern_analysis", response_class=HTMLResponse)
def serve_monthly_pattern_analysis():
    return FileResponse(str(PROJECT_ROOT / "reports" / "monthly_pattern_analysis.html"))


@app.get("/", response_class=HTMLResponse)
def serve_index():
    return FileResponse(
        str(
            PROJECT_ROOT
            / "nerves"
            / "workers"
            / "trading"
            / "static"
            / "backtest_dashboard.html"
        )
    )


if __name__ == "__main__":
    import uvicorn

    # Pre-warm data caches
    print("Pre-warming candles data cache...")
    load_data_and_indicators()
    print("Data cache pre-warmed successfully.")

    print("Loading V2.2 aggregate data...")
    v22 = load_v22_data()
    if v22:
        print(
            f"V2.2 data loaded: {v22.get('total_signals', 0)} signals, "
            f"{len(v22.get('scenarios', {}))} scenarios, "
            f"{len(v22.get('s4_trades', []))} S4 trades"
        )
    else:
        print("WARNING: V2.2 data not found. Aggregate endpoints will return 404.")

    port = int(os.getenv("PORT", 9109))
    print(f"Starting Backtest Playground on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
