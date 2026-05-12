# Replay Test Comparison — 2024-2026 (BINANCE:BTCUSDT 4H)

**Data captured:** 2026-05-10 via TradingView CDP/MCP
**Setup script:** `scripts/automated_replay_test.ps1` (orchestration log only)
**Method:** (1c) Hybrid — Strategy Tester native metrics for full data + replay setup snapshot

## Strategies tested

| Pane | Strategy | Pine source | Position sizing |
|---|---|---|---|
| 0 (left) | Minervini_TT_Indicator (Version1.1) → strategy_MTT_v1.A007 FWD (ADX25+Trail) | `pine/v1/strategy_MTT_v1.A007.pine` | 100k init, 200% notional (override_qty=200) |
| 1 (right) | SEPA_Multi-Indicator Strategy (Version1) → "MIS v1" | `pine/v2/strategy_multi_indicator_v16.pine` | 1M init, ~20k per trade (~2% of cap) |

## Setup screenshot
[tradingview-mcp/screenshots/replay_test_2024-01-01_setup_2026-05-10.png](../tradingview-mcp/screenshots/replay_test_2024-01-01_setup_2026-05-10.png)

## Strategy Tester metrics (full data Jan 2021 → May 2026)

### Pane 0 — Minervini A.007
[tradingview-mcp/screenshots/replay_pane0_minervini_metrics_2026-05-10.png](../tradingview-mcp/screenshots/replay_pane0_minervini_metrics_2026-05-10.png)

| Metric | Value |
|---|---:|
| Net P&L | **+76,832.94 USDT (+76.83%)** |
| Max equity DD | 29,713.31 USDT (23.28%) |
| Total trades | 30 (all Long) |
| Win rate | 53.33% (16/30) |
| Profit factor | 1.685 |
| Avg win / avg loss | 4.96% / 3.02% (R:R = 1.474) |
| Largest win / loss | +17.66% / −6.83% |
| Sharpe / Sortino | 0.132 / 0.327 |
| Avg bars (W/L) | 24 / 11 (winners ride 2.2× longer) |
| Buy & hold | +101.56% (strategy underperforms by −24.7k USDT) |

### Pane 1 — Multi-Indicator (MIS v1)
[tradingview-mcp/screenshots/replay_pane1_multi_metrics_2026-05-10.png](../tradingview-mcp/screenshots/replay_pane1_multi_metrics_2026-05-10.png)

| Metric | Value |
|---|---:|
| Net P&L | **+5,072.58 USDT (+0.51%)** |
| Max equity DD | 17,753.11 USDT (1.76%) |
| Total trades | 50 (24 Long + 26 Short) |
| Win rate | 74.00% (37/50) |
| Profit factor | 1.135 |
| Avg win / avg loss | 5.78% / **14.46%** (R:R = **0.399**) ⚠️ |
| Largest win / loss | +24.10% / **−53.23%** ⚠️ |
| Sharpe / Sortino | **−0.671 / −0.578** (negative!) |
| Avg bars (W/L) | 80 / 165 (losers held **2× longer** than winners — anti-pattern) |
| Buy & hold | +56.32% (strategy underperforms by **−558k USDT** on 1M cap) |

## Head-to-head — full period

| Metric | Minervini A.007 | Multi-Indicator | Winner |
|---|---:|---:|:---:|
| Net P&L % | **+76.83%** | +0.51% | Minervini |
| Max DD % | 23.28% | **1.76%** | Multi-Ind (smaller pos) |
| Win rate | 53.33% | **74.00%** | Multi-Ind |
| Profit factor | **1.685** | 1.135 | Minervini |
| R:R (avg W/L) | **1.474** | 0.399 | Minervini |
| Largest loss % | **−6.83%** | −53.23% | Minervini |
| Sharpe | **0.132** | −0.671 | Minervini |
| Trades | 30 | 50 | — |
| Direction | Long-only | Long+Short | — |
| Buy&hold gap | −24.7% under | −55.8% under | Both lose to HODL |

**Verdict (full period):** Minervini wins clearly on P&L, PF, R:R, Sharpe, tail risk. Multi-Indicator's high 74% win rate is misleading — losers held 2× longer than winners (anti-pattern), and a single trade (Aug 23, 2021 short, −53.23%) wipes out half the profit base.

## 2024-2026 isolated (filtered from cumulative P&L column)

### Minervini A.007 — 11 trades from 2024-01-01 onward

| # | Entry | Type | P&L % | Cum % |
|---:|---|---|---:|---:|
| 20 | Feb 01, 2024 | L | −3.25% | 50.08% |
| 21 | May 20, 2024 | L | +5.67% | 67.12% |
| 22 | Jul 23, 2024 | L | +2.65% | 76.00% |
| 23 | Oct 07, 2024 | L | −1.97% | 69.04% |
| 24 | Jan 06, 2025 | L | +2.69% | 78.16% |
| 25 | Mar 28, 2025 | L | −3.06% | 67.24% |
| 26 | Apr 21, 2025 | L | +2.94% | 77.06% |
| 27 | Aug 11, 2025 | L | +0.49% | 78.80% |
| 28 | Oct 07, 2025 | L | +2.59% | 88.06% |
| 29 | Oct 29, 2025 | L | −2.73% | 77.77% |
| 30 | Apr 12, 2026 | L | −0.26% | 76.83% |

- 2024-2026 contribution: 76.83% − 60.52% (end of 2023, after #19) = **+16.31%** (~$16.3k profit on 100k cap)
- Wins/Losses: 6/5 → 54.5% win rate
- Largest win: +5.67% (May 2024) | Largest loss: −3.25% (Feb 2024)
- Recent: 2 losers liên tiếp (#29, #30) — sát thời điểm forward test bắt đầu

### Multi-Indicator — 22 trades from 2024-01-22 onward

| # | Entry | Type | P&L % | Cum % |
|---:|---|---|---:|---:|
| 29 | Jan 22, 2024 | S | −6.05% | −0.30% |
| 30 | Feb 06, 2024 | L | +12.36% | −0.05% |
| 31 | Feb 26, 2024 | L | +5.49% | 0.06% |
| 32 | Mar 08, 2024 | L | +0.51% | 0.07% |
| 33 | Apr 17, 2024 | S | +1.73% | 0.10% |
| 34 | May 10, 2024 | S | −15.60% | −0.21% |
| 35 | May 27, 2024 | L | −16.62% | −0.54% |
| 36 | Aug 19, 2024 | S | +1.19% | −0.52% |
| 37 | Sep 26, 2024 | L | +1.63% | −0.48% |
| 38 | Nov 19, 2024 | L | +2.76% | −0.43% |
| 39 | Dec 04, 2024 | L | +2.12% | −0.39% |
| 40 | Jan 06, 2025 | L | +3.93% | −0.31% |
| 41 | Feb 11, 2025 | S | +6.92% | −0.17% |
| 42 | May 07, 2025 | L | +7.45% | −0.02% |
| 43 | Jul 02, 2025 | L | +9.93% | 0.18% |
| 44 | Aug 10, 2025 | L | −0.05% | 0.17% |
| 45 | Aug 24, 2025 | S | +2.92% | 0.23% |
| 46 | Sep 16, 2025 | L | −4.56% | 0.14% |
| 47 | Sep 25, 2025 | S | +5.45% | 0.25% |
| 48 | Oct 16, 2025 | S | +21.71% | 0.69% |
| 49 | Feb 12, 2026 | S | −13.22% | 0.42% |
| 50 | Apr 14, 2026 | L | +4.34% | 0.51% |

- 2024-2026 contribution: 0.51% − (−0.18%) = **+0.69%** (~$6.9k profit on 1M cap)
- Wins/Losses: 16/6 → 72.7% win rate
- Largest win: +21.71% (Oct 16, 2025 short) | Largest loss: **−16.62%** (May 27, 2024 long counter-trend)
- 2 long entries in May 2024 (#34/#35) tổng −32% — strategy bị whipsaw mạnh ở vùng giá đi ngang sau ATH

## 2024-2026 head-to-head

| Metric | Minervini A.007 | Multi-Indicator | Winner |
|---|---:|---:|:---:|
| Trades | 11 | 22 | — |
| Win rate | 54.5% | **72.7%** | Multi-Ind |
| Cum P&L % (capital) | **+16.31%** | +0.69% | Minervini |
| Profit ($) | ~$16,300 (100k cap) | ~$6,900 (1M cap) | Minervini |
| Capital efficiency | **16.3% / year≈ 7.7% CAGR** | <1% | Minervini |
| Worst single trade | −3.25% | **−16.62%** | Minervini |
| Activity | Quarterly | Monthly | depends |
| Direction balance | Long-only | Both directions | Multi |

## Insights

**Minervini A.007 (Long-only, ADX-gated):**
- Less active (1 trade ~2.5 months) but high quality — every trade ≤−3.25% in 2024-2026.
- 2024 carry trade dip (Aug-Sep) bị skip vì ADX gate — không vào lệnh ⇒ tránh loss lớn.
- Compounding effect rõ: cum % di chuyển smoothly từ 50% → 88% → drawdown about 11% peak-to-trough trong 2024-2026.

**Multi-Indicator:**
- High win rate misleading — 4/22 losing trades trong 2024-2026 nuốt hết winners; cum P&L gần như flat.
- Bị whipsaw nghiêm trọng tại vùng May 2024 (2 trade thua liên tiếp = −32%).
- Largest 2024-2026 win (#48 Short Oct 16, 2025 +21.71%) là đóng góp duy nhất kéo cum P&L lên dương.
- Strategy giữ lệnh quá lâu khi thua (avg 165 bars losing vs 80 bars winning) — cần stop loss kỷ luật hơn.

## Caveats / Disclaimers

1. **Position sizing không match:** Minervini dùng 200% notional (leverage), Multi-Indicator chỉ ~2% of cap → so sánh tuyệt đối (USDT) không công bằng. So sánh nên dùng % of cap hoặc đẩy 2 strategy về cùng risk-per-trade.
2. **BINANCE feed ≠ BYBIT feed:** V1.A007 trên BYBIT (forward live) cho +183.68% / 29 trades / 24.15% DD, trên BINANCE cho +76.83% / 30 trades / 23.28% DD trong cùng period. Chênh lệch do funding/liquidation/spread khác nhau giữa 2 sàn.
3. **Slippage & funding chưa modeled:** Multi-Indicator giữ lệnh trung bình 102 bars (~17 ngày @ 4H) — funding cost trên BYBIT/BINANCE cộng dồn có thể ~1-2% per trade chưa tính.
4. **Buy & hold beats both:** +56% trong 2024-2026 — cả 2 strategy đều không bằng HODL trên BTC. Chỉ có ý nghĩa nếu mục tiêu là risk-managed return (smaller DD) hoặc multi-asset rotation.

## Files

- Setup screenshot: [replay_test_2024-01-01_setup_2026-05-10.png](../tradingview-mcp/screenshots/replay_test_2024-01-01_setup_2026-05-10.png)
- Pane 0 metrics: [replay_pane0_minervini_metrics_2026-05-10.png](../tradingview-mcp/screenshots/replay_pane0_minervini_metrics_2026-05-10.png)
- Pane 1 metrics: [replay_pane1_multi_metrics_2026-05-10.png](../tradingview-mcp/screenshots/replay_pane1_multi_metrics_2026-05-10.png)
- Full chart compare: [replay_compare_full_2026-05-10.png](../tradingview-mcp/screenshots/replay_compare_full_2026-05-10.png)
- Full chart reset: [replay_compare_full_reset_2026-05-10.png](../tradingview-mcp/screenshots/replay_compare_full_reset_2026-05-10.png)
- Orchestration log: [reports/replay_test_20260510_181856.log](../reports/replay_test_20260510_181856.log)
- Orchestration JSON: [reports/replay_test_20260510_181856.json](../reports/replay_test_20260510_181856.json)
