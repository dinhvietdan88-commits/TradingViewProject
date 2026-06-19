# Performance Report: Scenario 2: Standard Minervini Filter (MIS v12b)

## 1. Description
Strict Minervini SEPA rules: Daily Trend Template score >= 5, daily VCP filter met (vol_contracting < 50%, range_contracting < 50% ATR, near_boundary within 10% of 52w high/low). Representing the strict SEPA setup from MIS v12b.

- **Total Signals Scanned**: 1015
- **Executed Trades**: 150
- **Filtered Signals (Skipped)**: 865

---

## 2. Performance Comparison Table

| Sizing Mode | Executed Trades | Final Equity (USDT) | Net Profit (USDT) | Win Rate (%) | Profit Factor | Max Drawdown (%) | Expectancy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fixed Sizing ($100)** | 150 | 9381.08 | -618.92 | 0.0% | 0.00 | 6.19% | -4.1262 |
| **Dynamic Sizing (2% Risk)** | 150 | 2108.74 | -7891.26 | 0.0% | 0.00 | 78.91% | -52.6084 |

---

## 3. Equity Curve Comparison Chart
The chart below illustrates the cumulative equity curve performance for both Fixed Sizing (USDT P&L scale) and Dynamic Compounding Sizing (2% risk) over time:

![Equity Curve Chart](equity_curve.png)

---

## 4. Scenario Breakdown Analysis
- **Filter Restrictiveness**: This scenario filtered out 865 signals out of 1015 (Skip Rate: 85.2%).
- **Compounding Sizing Effect**: Dynamic compounding sizing led to an equity of **$2108.74** compared to **$9381.08** in Fixed Sizing.
- **Profitability Verdict**: UNPROFITABLE with a Profit Factor of **0.00** and expectancy **-52.6084** under Dynamic Sizing.
