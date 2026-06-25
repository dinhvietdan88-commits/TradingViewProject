# Performance Report: Scenario 3: Short-term EMA Filter (Strategy MTT)

## 1. Description
Hourly / daily short-term trend stack validation: Daily price > EMA20 > EMA50 > EMA100 (long) or Price < EMA20 < EMA50 < EMA100 (short). Representing the short-term EMA trend stack from MTT v1.005-b.

- **Total Signals Scanned**: 1296
- **Executed Trades**: 590
- **Filtered Signals (Skipped)**: 706

---

## 2. Performance Comparison Table

| Sizing Mode | Executed Trades | Final Equity (USDT) | Net Profit (USDT) | Win Rate (%) | Profit Factor | Max Drawdown (%) | Expectancy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fixed Sizing ($100)** | 590 | 11008.07 | +1008.07 | 81.4% | 2.18 | 7.30% | 1.7086 |
| **Dynamic Sizing (2% Risk)** | 590 | 116863.28 | +106863.28 | 81.4% | 2.00 | 86.86% | 181.1242 |

---

## 3. Equity Curve Comparison Chart
The chart below illustrates the cumulative equity curve performance for both Fixed Sizing (USDT P&L scale) and Dynamic Compounding Sizing (2% risk) over time:

![Equity Curve Chart](equity_curve.png)

---

## 4. Scenario Breakdown Analysis
- **Filter Restrictiveness**: This scenario filtered out 706 signals out of 1296 (Skip Rate: 54.5%).
- **Compounding Sizing Effect**: Dynamic compounding sizing led to an equity of **$116863.28** compared to **$11008.07** in Fixed Sizing.
- **Profitability Verdict**: PROFITABLE with a Profit Factor of **2.00** and expectancy **181.1242** under Dynamic Sizing.
