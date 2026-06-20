import random
import pytest
import numpy as np

# Định nghĩa các thuật toán Monte Carlo


def run_monte_carlo_shuffling(
    trades_pnl: list[float],
    starting_equity: float = 10000.0,
    risk_pct: float = 0.02,
    num_simulations: int = 1000,
) -> dict:
    """
    Monte Carlo Type I: Tráo đổi ngẫu nhiên thứ tự thực hiện các lệnh (Sequence Shuffling).
    Tính toán phân phối của Drawdown và Equity cuối cùng.
    """
    sim_final_equities = []
    sim_max_drawdowns = []

    for _ in range(num_simulations):
        # Tráo đổi thứ tự ngẫu nhiên
        shuffled_pnl = list(trades_pnl)
        random.shuffle(shuffled_pnl)

        equity = starting_equity
        peak = starting_equity
        max_dd = 0.0

        for pnl_pct in shuffled_pnl:
            # Sizing dựa trên 2% tài khoản (Dynamic Sizing)
            pos_size = equity * risk_pct
            # Giả định khoảng dừng lỗ trung bình là 8% để tính Position Size
            # (risk_amount = pos_size * sl_pct) -> pos_size = risk_amount / sl_pct
            # Ở đây đơn giản hóa: pos_size = equity * risk_pct * 12.5 (tương đương sl = 8%)
            pos_size = min(pos_size * 12.5, equity)
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
        "probability_of_ruin": float(
            sum(1 for eq in sim_final_equities if eq < starting_equity * 0.5)
            / num_simulations
            * 100
        ),
    }


def run_monte_carlo_outlier_removal(
    trades_pnl: list[float], drop_pct: float = 0.10
) -> dict:
    """
    Monte Carlo Type II: Loại bỏ ngẫu nhiên các lệnh thắng lớn (Outlier Removal) để đo lường độ nhạy.
    """
    sorted_pnl = sorted(trades_pnl, reverse=True)
    num_to_drop = int(len(trades_pnl) * drop_pct)

    # Loại bỏ N lệnh thắng lớn nhất
    degraded_pnl = sorted_pnl[num_to_drop:]

    original_expectancy = float(np.mean(trades_pnl)) if trades_pnl else 0.0
    degraded_expectancy = float(np.mean(degraded_pnl)) if degraded_pnl else 0.0

    return {
        "original_len": len(trades_pnl),
        "degraded_len": len(degraded_pnl),
        "original_expectancy": original_expectancy,
        "degraded_expectancy": degraded_expectancy,
        "is_still_profitable": degraded_expectancy > 0,
    }


# Lớp kiểm thử Pytest


class TestMonteCarloSimulation:
    @pytest.fixture
    def sample_trades_pnl(self):
        # Tạo ra 100 lệnh mẫu: 45 lệnh thắng (+2R đến +3R), 55 lệnh thua (-1R)
        # Giả sử 1R = 8% -> thắng = +16% đến +24%, thua = -8%
        random.seed(42)
        trades = []
        for _ in range(45):
            trades.append(random.uniform(0.12, 0.25))  # noqa: S311 # Thắng lớn
        for _ in range(55):
            trades.append(-0.08)  # Thua cố định
        return trades

    def test_shuffling_statistics(self, sample_trades_pnl):
        results = run_monte_carlo_shuffling(sample_trades_pnl, num_simulations=500)

        assert "final_equity_mean" in results
        assert "max_dd_95th_percentile" in results
        assert results["max_dd_mean"] > 0
        assert results["probability_of_ruin"] < 100.0

        print("\n--- Monte Carlo Type I (Shuffling) Results ---")
        print(f"Mean Final Equity: {results['final_equity_mean']:.2f} USDT")
        print(f"95th Percentile Max Drawdown: {results['max_dd_95th_percentile']:.2f}%")
        print(f"Probability of Ruin (<50%): {results['probability_of_ruin']:.2f}%")

    def test_outlier_removal_degradation(self, sample_trades_pnl):
        results = run_monte_carlo_outlier_removal(sample_trades_pnl, drop_pct=0.10)

        assert results["degraded_len"] == 90
        assert results["degraded_expectancy"] < results["original_expectancy"]

        print("\n--- Monte Carlo Type II (Outlier Removal) Results ---")
        print(f"Original Expectancy: {results['original_expectancy'] * 100:.2f}%")
        print(
            f"Degraded Expectancy (Drop 10% best trades): {results['degraded_expectancy'] * 100:.2f}%"
        )
        print(f"Is Still Profitable: {results['is_still_profitable']}")
