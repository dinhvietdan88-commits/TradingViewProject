# Performance Report: Scenario 5: Multi-Timeframe Validation (MIS v13c)

## 1. Description
Multi-timeframe validation: Daily Trend Template score >= 5, AND hourly execution trend aligned (hourly EMA20 > EMA50 > EMA200 for long, opposite for short). Representing the MTF daily trend template check from MIS v13c.

- **Total Signals Scanned**: 1296
- **Executed Trades**: 347
- **Filtered Signals (Skipped)**: 949

---

## 2. Performance Comparison Table

| Sizing Mode | Executed Trades | Final Equity (USDT) | Net Profit (USDT) | Win Rate (%) | Profit Factor | Max Drawdown (%) | Expectancy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fixed Sizing ($100)** | 347 | 10460.75 | +460.75 | 61.4% | 1.56 | 7.16% | 1.3278 |
| **Dynamic Sizing (2% Risk)** | 347 | 307107.88 | +297107.88 | 61.4% | 1.09 | 92.63% | 856.2187 |

---

## 3. Equity Curve Comparison Chart
The chart below illustrates the cumulative equity curve performance for both Fixed Sizing (USDT P&L scale) and Dynamic Compounding Sizing (2% risk) over time:

![Equity Curve Chart](equity_curve.png)

---

## 4. Scenario Breakdown Analysis
- **Filter Restrictiveness**: This scenario filtered out 949 signals out of 1296 (Skip Rate: 73.2%).
- **Compounding Sizing Effect**: Dynamic compounding sizing led to an equity of **$307107.88** compared to **$10460.75** in Fixed Sizing.
- **Profitability Verdict**: PROFITABLE with a Profit Factor of **1.09** and expectancy **856.2187** under Dynamic Sizing.
