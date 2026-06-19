# Performance Report: Scenario 1: Baseline Bypass AI (MIS v1)

## 1. Description
Execute trades using the entry, SL, and TP prices directly from the signal records (8% SL / 20% TP fallback). Representing the baseline breakout execution from MIS v1.

- **Total Signals Scanned**: 1015
- **Executed Trades**: 1008
- **Filtered Signals (Skipped)**: 7

---

## 2. Performance Comparison Table

| Sizing Mode | Executed Trades | Final Equity (USDT) | Net Profit (USDT) | Win Rate (%) | Profit Factor | Max Drawdown (%) | Expectancy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fixed Sizing ($100)** | 1008 | 9815.10 | -184.90 | 47.5% | 0.94 | 6.43% | -0.1834 |
| **Dynamic Sizing (2% Risk)** | 1008 | 5387.85 | -4612.15 | 47.5% | 0.96 | 82.84% | -4.5755 |

---

## 3. Equity Curve Comparison Chart
The chart below illustrates the cumulative equity curve performance for both Fixed Sizing (USDT P&L scale) and Dynamic Compounding Sizing (2% risk) over time:

![Equity Curve Chart](equity_curve.png)

---

## 4. Scenario Breakdown Analysis
- **Filter Restrictiveness**: This scenario filtered out 7 signals out of 1015 (Skip Rate: 0.7%).
- **Compounding Sizing Effect**: Dynamic compounding sizing led to an equity of **$5387.85** compared to **$9815.10** in Fixed Sizing.
- **Profitability Verdict**: UNPROFITABLE with a Profit Factor of **0.96** and expectancy **-4.5755** under Dynamic Sizing.
