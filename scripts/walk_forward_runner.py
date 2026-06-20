import os
import sys
import json
import sqlite3
import datetime
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
vbs_replay_db_path = PROJECT_ROOT / "scratch" / "vbs_replay.db"
signals_db_path = PROJECT_ROOT / "scratch" / "signal_queue_server_a.db"
REPORT_PATH = PROJECT_ROOT / "docs" / "reports" / "v2.1.0-7.6.3" / "walk_forward_report.md"

sys.path.insert(0, str(PROJECT_ROOT / "nerves" / "workers" / "trading"))
import config
from symbol_config import get_symbol_config

# Import các hàm mô phỏng từ run_vbs_backtest_campaign
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from run_vbs_backtest_campaign import (
    load_cached_candles,
    get_last_closed_candle,
    get_signal_start_index,
    simulate_trade_execution
)

def run_single_backtest(signals: list[dict], data_dfs: dict, atr_sl_mul: float, min_tt_score: int) -> list[dict]:
    """Chạy backtest trên danh sách signal với bộ tham số động."""
    trades = []
    for sig in signals:
        symbol = sig["symbol"]
        action = sig["action"]
        price = sig["price"]
        received_at = sig["received_at"]
        
        if action.lower() not in ("buy", "sell", "long", "short") or price <= 1000.0:
            continue
            
        df_1d = data_dfs.get(f"{symbol}_1d")
        df_1h = data_dfs.get(f"{symbol}_1h")
        if df_1d is None or df_1h is None or len(df_1d) == 0 or len(df_1h) == 0:
            continue
            
        # Parse time
        dt_signal = datetime.datetime.strptime(received_at.split(".")[0], "%Y-%m-%d %H:%M:%S")
        dt_signal = dt_signal.replace(tzinfo=datetime.timezone.utc)
        signal_time_ms = int(dt_signal.timestamp() * 1000)
        
        start_idx = get_signal_start_index(df_1h, signal_time_ms)
        if start_idx == -1:
            continue
            
        daily_row = get_last_closed_candle(df_1d, signal_time_ms, 86400000)
        daily_price = daily_row["close"]
        daily_atr = daily_row["atr14"]
        
        # Lọc theo Trend Template Score
        is_long = action.lower() in ("buy", "long")
        tt_score = daily_row["tt_score_long"] if is_long else daily_row["tt_score_short"]
        
        if tt_score < min_tt_score:
            continue  # Lọc bỏ
            
        # Tính toán SL & TP động
        if daily_atr and daily_atr > 0:
            sl = price - (atr_sl_mul * daily_atr) if is_long else price + (atr_sl_mul * daily_atr)
            tp = price + (3.0 * daily_atr) if is_long else price - (3.0 * daily_atr)
        else:
            sl = price * 0.92 if is_long else price * 1.08
            tp = price * 1.20 if is_long else price * 0.80
            
        sim = simulate_trade_execution(df_1h, start_idx, action, price, sl, tp)
        trades.append({
            "pnl_pct": sim["pnl_pct"],
            "pnl": 100.0 * sim["pnl_pct"] # Fixed $100 position size
        })
    return trades

def calculate_profit_factor(trades: list[dict]) -> float:
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [abs(t["pnl"]) for t in trades if t["pnl"] < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    return gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 1.0

def main():
    print("=== STARTING WALK-FORWARD ANALYSIS ===")
    
    # 1. Load active symbols
    conn_v = sqlite3.connect(str(vbs_replay_db_path))
    cur_v = conn_v.cursor()
    cur_v.execute("SELECT DISTINCT symbol FROM replay_trades")
    active_symbols = [row[0] for row in cur_v.fetchall()]
    conn_v.close()
    
    if not active_symbols:
        active_symbols = ["BTCUSDT"]
        
    # 2. Load candles
    data_dfs = {}
    df_btc_daily = None
    if "BTCUSDT" in active_symbols:
        df_btc_daily = load_cached_candles("BTCUSDT", "1d")
        
    # Import functions for calculations
    from run_vbs_backtest_campaign import calculate_daily_indicators, calculate_hourly_indicators
    for sym in active_symbols:
        df_1d = load_cached_candles(sym, "1d")
        df_1h = load_cached_candles(sym, "1h")
        df_1d_ind = calculate_daily_indicators(df_1d, is_btc=(sym == "BTCUSDT"), df_btc_daily=df_btc_daily)
        df_1h_ind = calculate_hourly_indicators(df_1h)
        data_dfs[f"{sym}_1d"] = df_1d_ind
        data_dfs[f"{sym}_1h"] = df_1h_ind
        
    # 3. Load signals
    conn_sig = sqlite3.connect(str(signals_db_path))
    conn_sig.row_factory = sqlite3.Row
    cur_sig = conn_sig.cursor()
    cur_sig.execute("SELECT * FROM signal_queue ORDER BY id ASC")
    signals = [dict(row) for row in cur_sig.fetchall()]
    conn_sig.close()
    
    print(f"Loaded {len(signals)} signals.")
    
    # Định nghĩa không gian tham số tối ưu hóa (Parameter Space)
    param_grid = [
        {"atr_sl_mul": 1.5, "min_tt_score": 5},
        {"atr_sl_mul": 2.0, "min_tt_score": 5},
        {"atr_sl_mul": 2.5, "min_tt_score": 5},
        {"atr_sl_mul": 1.5, "min_tt_score": 6},
        {"atr_sl_mul": 2.0, "min_tt_score": 6},
        {"atr_sl_mul": 2.5, "min_tt_score": 6},
    ]
    
    # Phân chia 4 rolling windows cuốn chiếu
    # Tổng số signals ~600, mỗi OOS khoảng 100 nốt
    window_splits = [
        {"is_start": 0, "is_end": 250, "oos_start": 250, "oos_end": 350},
        {"is_start": 100, "is_end": 350, "oos_start": 350, "oos_end": 450},
        {"is_start": 200, "is_end": 450, "oos_start": 450, "oos_end": 550},
        {"is_start": 300, "is_end": 550, "oos_start": 550, "oos_end": 650},
    ]
    
    windows_results = []
    
    for idx, w in enumerate(window_splits):
        print(f"\nRunning Walk-Forward Window {idx + 1}/4...")
        is_signals = signals[w["is_start"]:min(w["is_end"], len(signals))]
        oos_signals = signals[w["oos_start"]:min(w["oos_end"], len(signals))]
        
        if not is_signals or not oos_signals:
            print("Skipping window due to insufficient signals.")
            continue
            
        # 1. Optimize on In-Sample
        best_pf = -1.0
        best_param = None
        
        for p in param_grid:
            trades = run_single_backtest(is_signals, data_dfs, p["atr_sl_mul"], p["min_tt_score"])
            pf = calculate_profit_factor(trades)
            if pf > best_pf:
                best_pf = pf
                best_param = p
                
        # 2. Test on Out-of-Sample using best parameter set
        oos_trades = run_single_backtest(oos_signals, data_dfs, best_param["atr_sl_mul"], best_param["min_tt_score"])
        oos_pf = calculate_profit_factor(oos_trades)
        
        # Tính Walk-Forward Efficiency (WFE)
        if best_pf == float('inf'):
            if oos_pf == float('inf'):
                wfe = 100.0
            else:
                wfe = 0.0
        elif oos_pf == float('inf'):
            wfe = 100.0
        else:
            wfe = (oos_pf / best_pf * 100) if best_pf > 0 else 0.0
            
        if np.isnan(wfe):
            wfe = 0.0
        
        windows_results.append({
            "window": idx + 1,
            "best_param": best_param,
            "is_pf": best_pf,
            "oos_pf": oos_pf,
            "wfe": wfe,
            "num_is_trades": len(is_signals),
            "num_oos_trades": len(oos_trades)
        })
        print(f"Window {idx + 1}: Optimal Param={best_param}, IS PF={best_pf:.2f}, OOS PF={oos_pf:.2f}, WFE={wfe:.1f}%")
        
    # Tính WFE trung bình toàn cục
    avg_wfe = np.mean([r["wfe"] for r in windows_results]) if windows_results else 0.0
    
    # 4. Ghi báo cáo Walk-Forward
    report_content = f"""# Walk-Forward Analysis (WFA) Report

Tài liệu kiểm định Walk-Forward cuốn chiếu đánh giá khả năng thích ứng của các tham số tối ưu hóa trên dữ liệu thực tế (Out-of-Sample).

## 1. Kết Quả Từng Cửa Sổ (Rolling Windows Breakdown)

| Window | In-Sample Range | Out-of-Sample Range | Optimal Parameters | IS Profit Factor | OOS Profit Factor | WFE (%) |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: |
"""
    for idx, r in enumerate(windows_results):
        w_split = window_splits[idx]
        is_range = f"Signal {w_split['is_start']} - {w_split['is_end']}"
        oos_range = f"Signal {w_split['oos_start']} - {w_split['oos_end']}"
        param_str = f"SL: {r['best_param']['atr_sl_mul']}x ATR, Min TT: {r['best_param']['min_tt_score']}"
        report_content += f"| {r['window']} | {is_range} | {oos_range} | {param_str} | {r['is_pf']:.2f} | {r['oos_pf']:.2f} | {r['wfe']:.1f}% |\n"
        
    report_content += f"""
---

## 2. Kết Luận Đánh Giá (Final Verdict)
- **Walk-Forward Efficiency (WFE) Trung bình**: **{avg_wfe:.2f}%**
- **Đánh giá độ tin cậy**: {"✅ ĐẠT TIÊU CHUẨN (WFE >= 60%) - Hệ thống thích ứng tốt với nến thị trường thay đổi." if avg_wfe >= 60.0 else "⚠️ CẦN TỐI ƯU HÓA LẠI (WFE < 60%) - Có dấu hiệu Overfitting khi đổi chế độ nến."}

*Báo cáo được tạo tự động bởi walk_forward_runner.py vào {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
"""
    
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"\nWalk-Forward Analysis Complete. Average WFE: {avg_wfe:.2f}%. Report generated at {REPORT_PATH}")

if __name__ == "__main__":
    main()
