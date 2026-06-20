import pytest
import sqlite3
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[5]
vbs_replay_db_path = PROJECT_ROOT / "scratch" / "vbs_replay.db"
signals_db_path = PROJECT_ROOT / "scratch" / "signal_queue_server_a.db"

# Import các hàm mô phỏng
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from run_vbs_backtest_campaign import (  # noqa: E402
    load_cached_candles,
    get_last_closed_candle,
    get_signal_start_index,
    simulate_trade_execution,
    calculate_daily_indicators,
    calculate_hourly_indicators,
)


class TestSlippageDecay:
    def test_slippage_performance_decay(self):
        """
        Kiểm định độ suy giảm lợi nhuận khi tăng tỷ lệ trượt giá (Slippage Decay).
        Mục tiêu: Đảm bảo Profit Factor của trượt giá cao (0.5%) thấp hơn trượt giá thấp (0.0%).
        """
        # 1. Load active symbols
        if not os.path.exists(vbs_replay_db_path) or not os.path.exists(
            signals_db_path
        ):
            pytest.skip("Database files not found. Skipping integration slippage test.")

        conn_v = sqlite3.connect(str(vbs_replay_db_path))
        cur_v = conn_v.cursor()
        cur_v.execute("SELECT DISTINCT symbol FROM replay_trades")
        active_symbols = [row[0] for row in cur_v.fetchall()]
        conn_v.close()

        if not active_symbols:
            active_symbols = ["BTCUSDT"]

        # Load data
        data_dfs = {}
        df_btc_daily = (
            load_cached_candles("BTCUSDT", "1d")
            if "BTCUSDT" in active_symbols
            else None
        )

        for sym in active_symbols[:2]:  # Chỉ kiểm tra 2 symbols đầu để tối ưu tốc độ
            df_1d = load_cached_candles(sym, "1d")
            df_1h = load_cached_candles(sym, "1h")
            df_1d_ind = calculate_daily_indicators(
                df_1d, is_btc=(sym == "BTCUSDT"), df_btc_daily=df_btc_daily
            )
            df_1h_ind = calculate_hourly_indicators(df_1h)
            data_dfs[f"{sym}_1d"] = df_1d_ind
            data_dfs[f"{sym}_1h"] = df_1h_ind

        # Load subset of signals (50 signals đầu tiên)
        conn_sig = sqlite3.connect(str(signals_db_path))
        conn_sig.row_factory = sqlite3.Row
        cur_sig = conn_sig.cursor()
        cur_sig.execute("SELECT * FROM signal_queue ORDER BY id ASC LIMIT 50")
        signals = [dict(row) for row in cur_sig.fetchall()]
        conn_sig.close()

        # Thử nghiệm với các mức trượt giá khác nhau
        slippage_levels = [0.0, 0.05, 0.10, 0.20, 0.50]
        results = {}

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

                # Time conversion
                import datetime

                dt_signal = datetime.datetime.strptime(
                    received_at.split(".")[0], "%Y-%m-%d %H:%M:%S"
                )
                dt_signal = dt_signal.replace(tzinfo=datetime.timezone.utc)
                signal_time_ms = int(dt_signal.timestamp() * 1000)

                start_idx = get_signal_start_index(df_1h, signal_time_ms)
                if start_idx == -1:
                    continue

                get_last_closed_candle(df_1d, signal_time_ms, 86400000)

                is_long = action.lower() in ("buy", "long")

                # SL & TP mặc định của kịch bản S1
                sl = price * 0.92 if is_long else price * 1.08
                tp = price * 1.20 if is_long else price * 0.80

                # Chạy mô phỏng giao dịch với tham số slippage_pct tùy chỉnh
                sim = simulate_trade_execution(
                    df_1h, start_idx, action, price, sl, tp, slippage_pct=slip
                )

                trades.append(
                    {
                        "pnl": 100.0 * sim["pnl_pct"]  # Fixed $100 size
                    }
                )

            # Tính toán Profit Factor cho mức trượt giá hiện tại
            wins = [t["pnl"] for t in trades if t["pnl"] > 0]
            losses = [abs(t["pnl"]) for t in trades if t["pnl"] < 0]
            gross_profit = sum(wins)
            gross_loss = sum(losses)
            pf = (
                gross_profit / gross_loss
                if gross_loss > 0
                else float("inf")
                if gross_profit > 0
                else 1.0
            )

            results[slip] = {
                "trades": len(trades),
                "profit_factor": pf,
                "total_pnl": sum([t["pnl"] for t in trades]),
            }

        # In kết quả phân rã
        print("\n--- Slippage Decay Results ---")
        for slip, res in results.items():
            print(
                f"Slippage: {slip * 100:.2f}% | Trades: {res['trades']} | Net P&L: {res['total_pnl']:.2f} USDT | PF: {res['profit_factor']:.2f}"
            )

        # Kiểm chứng mối quan hệ phân rã toán học
        # Trượt giá 0.5% phải có Net P&L thấp hơn hoặc bằng trượt giá 0.0%
        assert results[0.50]["total_pnl"] <= results[0.0]["total_pnl"]
