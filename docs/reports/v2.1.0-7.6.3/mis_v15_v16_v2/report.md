# Performance Report: Scenario 6: Optimized Hybrid Mode (MIS v15/v16/v2)

## 1. Description
Hybrid momentum pullback: Daily Trend Template score >= 5, daily RSI 14 >= 50 (long) or <= 50 (short), daily MACD line > MACD signal line (long) or opposite (short). Representing the optimized hybrid V2 configuration.

- **Total Signals Scanned**: 1015
- **Executed Trades**: 370
- **Filtered Signals (Skipped)**: 645

---

## 2. Performance Comparison Table

| Sizing Mode | Executed Trades | Final Equity (USDT) | Net Profit (USDT) | Win Rate (%) | Profit Factor | Max Drawdown (%) | Expectancy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fixed Sizing ($100)** | 370 | 9479.25 | -520.75 | 28.1% | 0.62 | 12.55% | -1.4074 |
| **Dynamic Sizing (2% Risk)** | 370 | 6392.48 | -3607.52 | 28.1% | 0.99 | 98.70% | -9.7501 |

---

## 3. Equity Curve Comparison Chart
The chart below illustrates the cumulative equity curve performance for both Fixed Sizing (USDT P&L scale) and Dynamic Compounding Sizing (2% risk) over time:

![Equity Curve Chart](equity_curve.png)

---

## 4. Scenario Breakdown Analysis
- **Filter Restrictiveness**: This scenario filtered out 645 signals out of 1015 (Skip Rate: 63.5%).
- **Compounding Sizing Effect**: Dynamic compounding sizing led to an equity of **$6392.48** compared to **$9479.25** in Fixed Sizing.
- **Profitability Verdict**: UNPROFITABLE with a Profit Factor of **0.99** and expectancy **-9.7501** under Dynamic Sizing.
