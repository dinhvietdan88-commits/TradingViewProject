# Performance Report: Scenario 6: Optimized Hybrid Mode (MIS v15/v16/v2)

## 1. Description
Hybrid momentum pullback: Daily Trend Template score >= 5, daily RSI 14 >= 50 (long) or <= 50 (short), daily MACD line > MACD signal line (long) or opposite (short). Representing the optimized hybrid V2 configuration.

- **Total Signals Scanned**: 1015
- **Executed Trades**: 448
- **Filtered Signals (Skipped)**: 567

---

## 2. Performance Comparison Table

| Sizing Mode | Executed Trades | Final Equity (USDT) | Net Profit (USDT) | Win Rate (%) | Profit Factor | Max Drawdown (%) | Expectancy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fixed Sizing ($100)** | 448 | 10033.11 | +33.11 | 38.8% | 1.02 | 13.12% | 0.0739 |
| **Dynamic Sizing (2% Risk)** | 448 | 9887.87 | -112.13 | 38.8% | 1.00 | 97.81% | -0.2503 |

---

## 3. Equity Curve Comparison Chart
The chart below illustrates the cumulative equity curve performance for both Fixed Sizing (USDT P&L scale) and Dynamic Compounding Sizing (2% risk) over time:

![Equity Curve Chart](equity_curve.png)

---

## 4. Scenario Breakdown Analysis
- **Filter Restrictiveness**: This scenario filtered out 567 signals out of 1015 (Skip Rate: 55.9%).
- **Compounding Sizing Effect**: Dynamic compounding sizing led to an equity of **$9887.87** compared to **$10033.11** in Fixed Sizing.
- **Profitability Verdict**: UNPROFITABLE with a Profit Factor of **1.00** and expectancy **-0.2503** under Dynamic Sizing.
