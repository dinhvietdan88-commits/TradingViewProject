# Performance Report: Scenario 4: Tight SL / Trailing Stop (MIS v10/v11a)

## 1. Description
Volatility-adjusted execution: Entry SL tightened to 1.5 * daily ATR14, TP set to 3.0 * ATR14. Chandelier trailing stop trails the extreme high/low since entry by 2.5 * ATR14. Representing the tight SL and trailing stops from MIS v10/v11a.

- **Total Signals Scanned**: 1015
- **Executed Trades**: 1008
- **Filtered Signals (Skipped)**: 7

---

## 2. Performance Comparison Table

| Sizing Mode | Executed Trades | Final Equity (USDT) | Net Profit (USDT) | Win Rate (%) | Profit Factor | Max Drawdown (%) | Expectancy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Fixed Sizing ($100)** | 1008 | 10423.14 | +423.14 | 46.8% | 1.19 | 3.13% | 0.4198 |
| **Dynamic Sizing (2% Risk)** | 1008 | 102410.17 | +92410.17 | 46.8% | 1.08 | 70.69% | 91.6768 |

---

## 3. Equity Curve Comparison Chart
The chart below illustrates the cumulative equity curve performance for both Fixed Sizing (USDT P&L scale) and Dynamic Compounding Sizing (2% risk) over time:

![Equity Curve Chart](equity_curve.png)

---

## 4. Scenario Breakdown Analysis
- **Filter Restrictiveness**: This scenario filtered out 7 signals out of 1015 (Skip Rate: 0.7%).
- **Compounding Sizing Effect**: Dynamic compounding sizing led to an equity of **$102410.17** compared to **$10423.14** in Fixed Sizing.
- **Profitability Verdict**: PROFITABLE with a Profit Factor of **1.08** and expectancy **91.6768** under Dynamic Sizing.
