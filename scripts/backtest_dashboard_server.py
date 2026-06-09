import os
import sys
import json
import sqlite3
import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PROJECT_ROOT = Path(r"c:\Users\pesil\working\mj_trading\TradingViewProject")
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

# Cache for loaded candles & indicators to keep API fast
CANDLE_CACHE = {}


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


@app.get("/api/signals")
async def get_signals():
    """Retrieve list of all 627 signals in queue."""
    if not os.path.exists(signals_db_path):
        raise HTTPException(status_code=500, detail="Signals database not found.")

    conn = sqlite3.connect(str(signals_db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT id, symbol, action, price, received_at FROM signal_queue ORDER BY id ASC"
    )
    rows = cur.fetchall()
    conn.close()

    return [dict(r) for r in rows]


@app.post("/api/simulate/{signal_id}")
async def simulate_signal(signal_id: int, params: BacktestParams):
    """Run dynamic S1 ~ S6 backtest simulation for a specific signal ID and custom parameters."""
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
    sim1 = simulate_trade_execution(df_1h, start_idx, action, price, base_sl, base_tp)
    scenarios_results["S1"] = {
        "executed": True,
        "sl": base_sl,
        "tp": base_tp,
        "close_price": sim1["close_price"],
        "pnl_pct": sim1["pnl_pct"],
        "outcome": sim1["close_reason"],
        "bars": sim1["exit_idx"] - start_idx,
        "exit_idx": sim1["exit_idx"],
    }

    # S2: Minervini
    s2_ok = tt_score >= params.s2_min_tt_score and vcp_met
    if s2_ok:
        sim2 = simulate_trade_execution(
            df_1h, start_idx, action, price, base_sl, base_tp
        )
        scenarios_results["S2"] = {
            "executed": True,
            "sl": base_sl,
            "tp": base_tp,
            "close_price": sim2["close_price"],
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
            df_1h, start_idx, action, price, base_sl, base_tp
        )
        scenarios_results["S3"] = {
            "executed": True,
            "sl": base_sl,
            "tp": base_tp,
            "close_price": sim3["close_price"],
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
        )
        scenarios_results["S4"] = {
            "executed": True,
            "sl": tight_sl,
            "tp": tight_tp,
            "close_price": sim4["close_price"],
            "pnl_pct": sim4["pnl_pct"],
            "outcome": sim4["close_reason"],
            "bars": sim4["exit_idx"] - start_idx,
            "exit_idx": sim4["exit_idx"],
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
            df_1h, start_idx, action, price, base_sl, base_tp
        )
        scenarios_results["S5"] = {
            "executed": True,
            "sl": base_sl,
            "tp": base_tp,
            "close_price": sim5["close_price"],
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
            df_1h, start_idx, action, price, base_sl, base_tp
        )
        scenarios_results["S6"] = {
            "executed": True,
            "sl": base_sl,
            "tp": base_tp,
            "close_price": sim6["close_price"],
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

    # Fetch 120 candles around the trade for interactive charting (30 before, 90 after start_idx)
    start_slice = max(0, start_idx - 30)
    end_slice = min(start_idx + 90, len(df_1h))
    candles_slice = df_1h.iloc[start_slice:end_slice][
        ["timestamp", "open", "high", "low", "close", "volume"]
    ].to_dict(orient="records")

    return {
        "signal_info": {
            "vbs_id": signal_id,
            "symbol": symbol,
            "action": action.upper(),
            "price": price,
            "received_at": received_at,
            "start_idx": start_idx,
            "relative_entry_idx": start_idx - start_slice,
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
        },
        "scenarios": scenarios_results,
        "candles": candles_slice,
    }


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok"}


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

    # Pre-warm data cache
    print("Pre-warming candles data cache...")
    load_data_and_indicators()
    print("Data cache pre-warmed successfully.")

    port = int(os.getenv("PORT", 9109))
    print(f"Starting Backtest Playground on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
