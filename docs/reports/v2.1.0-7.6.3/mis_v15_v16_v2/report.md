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
| **Fixed Sizing ($100)** | 370 | 8908.46 | -1091.54 | 25.9% | 0.28 | 14.54% | -2.9501 |
| **Dynamic Sizing (2% Risk)** | 370 | 627.48 | -9372.52 | 25.9% | 0.66 | 97.81% | -25.3311 |

---

## 3. Equity Curve Comparison Chart
The chart below illustrates the cumulative equity curve performance for both Fixed Sizing (USDT P&L scale) and Dynamic Compounding Sizing (2% risk) over time:

![Equity Curve Chart](equity_curve.png)

---

## 4. Scenario Breakdown Analysis
- **Filter Restrictiveness**: This scenario filtered out 645 signals out of 1015 (Skip Rate: 63.5%).
- **Compounding Sizing Effect**: Dynamic compounding sizing led to an equity of **$627.48** compared to **$8908.46** in Fixed Sizing.
- **Profitability Verdict**: UNPROFITABLE with a Profit Factor of **0.66** and expectancy **-25.3311** under Dynamic Sizing.
