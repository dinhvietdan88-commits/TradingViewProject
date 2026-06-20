import os
import sys
import json
import sqlite3
import datetime
import random
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
vbs_replay_db_path = PROJECT_ROOT / "scratch" / "vbs_replay.db"
signals_db_path = PROJECT_ROOT / "scratch" / "signal_queue_server_a.db"
REPORT_PATH = PROJECT_ROOT / "docs" / "reports" / "v2.1.0-7.6.3" / "QUANTITATIVE_STRATEGY_REPORT.md"

sys.path.insert(0, str(PROJECT_ROOT / "nerves" / "workers" / "trading"))
import config
from symbol_config import get_symbol_config

# Import các hàm mô phỏng từ run_vbs_backtest_campaign
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from run_vbs_backtest_campaign import (
    load_cached_candles,
    get_last_closed_candle,
    get_signal_start_index,
    simulate_trade_execution,
    calculate_daily_indicators,
    calculate_hourly_indicators,
    process_single_signal
)

def run_monte_carlo_shuffling(trades_pnl: list[float], starting_equity: float = 10000.0, risk_pct: float = 0.02, num_simulations: int = 1000) -> dict:
    """Sequence Shuffling (Monte Carlo Type I)"""
    sim_final_equities = []
    sim_max_drawdowns = []
    
    for _ in range(num_simulations):
        shuffled_pnl = list(trades_pnl)
        random.shuffle(shuffled_pnl)
        
        equity = starting_equity
        peak = starting_equity
        max_dd = 0.0
        
        for pnl_pct in shuffled_pnl:
            pos_size = equity * risk_pct * 12.5 # Giả định SL = 8%
            pos_size = min(pos_size, equity)
            pnl = pos_size * pnl_pct
            equity += pnl
            
            if equity > peak:
                peak = equity
            dd = ((peak - equity) / peak * 100) if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
                
        sim_final_equities.append(equity)
        sim_max_drawdowns.append(max_dd)
        
    return {
        "final_equity_mean": float(np.mean(sim_final_equities)),
        "final_equity_median": float(np.median(sim_final_equities)),
        "final_equity_5th_percentile": float(np.percentile(sim_final_equities, 5)),
        "final_equity_95th_percentile": float(np.percentile(sim_final_equities, 95)),
        "max_dd_mean": float(np.mean(sim_max_drawdowns)),
        "max_dd_median": float(np.median(sim_max_drawdowns)),
        "max_dd_95th_percentile": float(np.percentile(sim_max_drawdowns, 95)),
        "probability_of_ruin": float(sum(1 for eq in sim_final_equities if eq < starting_equity * 0.5) / num_simulations * 100)
    }

def run_monte_carlo_outlier_removal(trades_pnl: list[float], drop_pct: float = 0.10) -> dict:
    """Outlier Removal (Monte Carlo Type II)"""
    sorted_pnl = sorted(trades_pnl, reverse=True)
    num_to_drop = int(len(trades_pnl) * drop_pct)
    degraded_pnl = sorted_pnl[num_to_drop:]
    
    original_expectancy = float(np.mean(trades_pnl)) if trades_pnl else 0.0
    degraded_expectancy = float(np.mean(degraded_pnl)) if degraded_pnl else 0.0
    
    return {
        "original_expectancy": original_expectancy,
        "degraded_expectancy": degraded_expectancy,
        "is_still_profitable": degraded_expectancy > 0
    }

def run_slippage_decay_analysis(signals: list[dict], data_dfs: dict) -> dict:
    """Slippage Sensitivity Analysis"""
    slippage_levels = [0.0, 0.05, 0.10, 0.20, 0.50]
    decay_results = {}
    
    for slip in slippage_levels:
        trades = []
        for sig in signals:
            symbol = sig["symbol"]
            action = sig["action"]
            price = sig["price"]
            received_at = sig["received_at"]
            
            df_1d = data_dfs.get(f"{symbol}_1d")
            df_1h = data_dfs.get(f"{symbol}_1h")
            if df_1d is None or df_1h is None or len(df_1d) == 0 or len(df_1h) == 0:
                continue
                
            dt_signal = datetime.datetime.strptime(received_at.split(".")[0], "%Y-%m-%d %H:%M:%S")
            dt_signal = dt_signal.replace(tzinfo=datetime.timezone.utc)
            signal_time_ms = int(dt_signal.timestamp() * 1000)
            
            start_idx = get_signal_start_index(df_1h, signal_time_ms)
            if start_idx == -1:
                continue
                
            daily_row = get_last_closed_candle(df_1d, signal_time_ms, 86400000)
            is_long = action.lower() in ("buy", "long")
            
            # SL/TP mặc định
            sl = price * 0.92 if is_long else price * 1.08
            tp = price * 1.20 if is_long else price * 0.80
            
            sim = simulate_trade_execution(
                df_1h, start_idx, action, price, sl, tp, slippage_pct=slip
            )
            trades.append(sim["pnl_pct"])
            
        wins = [p for p in trades if p > 0]
        losses = [abs(p) for p in trades if p < 0]
        pf = sum(wins) / sum(losses) if sum(losses) > 0 else float("inf")
        
        decay_results[slip] = {
            "total_trades": len(trades),
            "net_pnl_pct": sum(trades) * 100.0,
            "profit_factor": pf
        }
    return decay_results

def main():
    print("=== STARTING QUANTITATIVE STRATEGY ANALYSIS ===")
    
    # 1. Load active symbols
    conn_v = sqlite3.connect(str(vbs_replay_db_path))
    cur_v = conn_v.cursor()
    cur_v.execute("SELECT DISTINCT symbol FROM replay_trades")
    active_symbols = [row[0] for row in cur_v.fetchall()]
    conn_v.close()
    
    if not active_symbols:
        active_symbols = ["BTCUSDT"]
        
    # 2. Load and calculate candles
    data_dfs = {}
    df_btc_daily = load_cached_candles("BTCUSDT", "1d") if "BTCUSDT" in active_symbols else None
    
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
    
    # Filter out mock signals
    valid_signals = [sig for sig in signals if sig["action"].lower() in ("buy", "sell", "long", "short") and sig["price"] > 1000.0]
    print(f"Loaded {len(valid_signals)} valid signals.")
    
    # 4. Generate S6 Trades list for Monte Carlo
    print("Simulating Scenario S6 (Optimized Hybrid Mode) to gather trade distribution...")
    s6_trades_pnl = []
    for sig in valid_signals:
        res = process_single_signal(sig, data_dfs)
        if res and "S6" in res:
            s6_trades_pnl.append(res["S6"]["pnl_pct"])
            
    if not s6_trades_pnl:
        # Fallback to S1 if S6 is too restrictive or empty
        print("S6 generated 0 trades. Falling back to S1 for distribution.")
        for sig in valid_signals:
            res = process_single_signal(sig, data_dfs)
            if res and "S1" in res:
                s6_trades_pnl.append(res["S1"]["pnl_pct"])
                
    print(f"Generated {len(s6_trades_pnl)} trades for Monte Carlo.")
    
    # 5. Run Monte Carlo Type I & II
    print("Running Monte Carlo Simulations...")
    mc_shuffling = run_monte_carlo_shuffling(s6_trades_pnl, num_simulations=1000)
    mc_outlier = run_monte_carlo_outlier_removal(s6_trades_pnl, drop_pct=0.10)
    
    # 6. Run Slippage Sensitivity
    print("Running Slippage Sensitivity Analysis...")
    slippage_decay = run_slippage_decay_analysis(valid_signals[:100], data_dfs) # Giới hạn 100 signals để chạy nhanh
    
    # 7. Load WFA results from walk_forward_report.md if it exists
    wfa_content = ""
    wfa_report_path = PROJECT_ROOT / "docs" / "reports" / "v2.1.0-7.6.3" / "walk_forward_report.md"
    if wfa_report_path.exists():
        with open(wfa_report_path, "r", encoding="utf-8") as f:
            wfa_content = f.read()
            
    # 8. Compile the report
    report_content = f"""# Báo Cáo Phân Tích Định Lượng Chiến Lược (Phần A)

Báo cáo này chứa các kết quả tính toán và mô phỏng thực tế của các kỹ thuật định lượng nâng cao: **Mô phỏng Monte Carlo**, **Kiểm thử độ nhạy Trượt giá**, và **Walk-Forward Analysis**.

---

## 1. Mô Phỏng Monte Carlo (Monte Carlo Simulations)

Phân tích trên **{len(s6_trades_pnl)} lệnh giao dịch** được tạo ra từ kịch bản S6/S1:

### A. Sequence Shuffling (Type I) - 1,000 Chu kỳ mô phỏng
Đánh giá mức độ ảnh hưởng của thứ tự lệnh đến Drawdown tài khoản (vốn ban đầu 10,000 USDT, rủi ro 2%):

- **Equity Trung bình cuối kỳ**: **{mc_shuffling['final_equity_mean']:.2f} USDT**
- **Equity Trung vị**: **{mc_shuffling['final_equity_median']:.2f} USDT**
- **Mức sụt giảm vốn lớn nhất (Max Drawdown) Trung bình**: **{mc_shuffling['max_dd_mean']:.2f}%**
- **Max Drawdown tệ nhất (95th Percentile)**: **{mc_shuffling['max_dd_95th_percentile']:.2f}%**
- **Xác suất cháy tài khoản (Ruin Probability - giảm 50% vốn)**: **{mc_shuffling['probability_of_ruin']:.2f}%**

### B. Outlier Removal (Type II) - Loại bỏ 10% lệnh thắng tốt nhất
Đánh giá mức độ phụ thuộc của chiến lược vào các lệnh thắng lớn (Outliers):

- **Kỳ vọng lợi nhuận ban đầu**: **{mc_outlier['original_expectancy']*100:.2f}%** per trade
- **Kỳ vọng lợi nhuận sau khi bỏ 10% lệnh thắng tốt nhất**: **{mc_outlier['degraded_expectancy']*100:.2f}%** per trade
- **Kết luận khả năng sinh lời**: {"✅ CHIẾN LƯỢC BỀN BỈ - Vẫn giữ được kỳ vọng dương sau khi loại outliers." if mc_outlier['is_still_profitable'] else "⚠️ CẢNH BÁO - Chiến lược phụ thuộc quá mức vào một vài lệnh thắng lớn để sinh lời."}

---

## 2. Kiểm Thử Độ Nhạy Trượt Giá (Slippage Sensitivity Analysis)

Phân tích hiệu suất giao dịch dưới các mức trượt giá (Slippage) từ 0% đến 0.5%:

| Slippage (%) | Tổng số lệnh | Net P&L (%) | Profit Factor | Trạng thái |
| :---: | :---: | :---: | :---: | :--- |
"""
    for slip, res in slippage_decay.items():
        status = "🟢 TỐT" if res["profit_factor"] >= 1.2 else "⚠️ BIÊN AN TOÀN THẤP" if res["profit_factor"] >= 1.0 else "🔴 LỖ"
        report_content += f"| {slip*100:.2f}% | {res['total_trades']} | {res['net_pnl_pct']:+.2f}% | {res['profit_factor']:.2f} | {status} |\n"
        
    report_content += f"""
*Nhận xét*: Khi trượt giá tăng lên mức 0.50%, Profit Factor giảm về **{slippage_decay[0.50]['profit_factor']:.2f}**. Hệ thống cần kiểm soát độ trễ giao dịch < 500ms để giữ trượt giá thực tế dưới 0.10%.

---

## 3. Walk-Forward Analysis (WFA) Summary

{wfa_content if wfa_content else "Không tìm thấy báo cáo walk_forward_report.md. Vui lòng chạy scripts/walk_forward_runner.py trước."}
"""

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    print(f"Quantitative Strategy Report generated successfully at {REPORT_PATH}")

if __name__ == "__main__":
    main()
