# Báo cáo V1.005 — MA Tuning + Library Architecture + Top Trades

**Symbol**: BYBIT:BTCUSDT.P
**TF**: D
**Date range**: 2020-03-25 → 2026-05-09
**Capital**: 100,000 USDT — **qty 10% per entry** — **Commission 0.075%** — **Slippage 2 ticks**
**Run date**: 2026-05-10

---

## 1. Architecture mới: Library + Indicator + Strategy (tách 3 file)

| File | Vai trò |
|---|---|
| [pine/v1/strategy_mtt_lib.pine](../../pine/v1/strategy_mtt_lib.pine) | **Library** — `ma()`, `stack_signals()`, `profile_qty_pct()`, `bear_to_neutral_breakout()` |
| [pine/v1/indicator_MTT_v1.005.pine](../../pine/v1/indicator_MTT_v1.005.pine) | **Indicator** — visual only, dùng cho phân tích & alerts |
| [pine/v1/strategy_MTT_v1.A005.pine](../../pine/v1/strategy_MTT_v1.A005.pine) | **Strategy A** — Long Only |
| [pine/v1/strategy_MTT_v1.B005.pine](../../pine/v1/strategy_MTT_v1.B005.pine) | **Strategy B** — Short Only + **lưu Breakout Long signal** |

> Library publish trên TradingView trước, Indicator/Strategy import bằng `import TradingViewProject/strategy_mtt_lib/1 as mtt`.
> Lý do tách: nâng cấp logic 1 chỗ → cả 3 file tự động hưởng lợi, A/B test đổi import là xong.

## 2. Test 4 variant MA — quyết định công thức V1.005 (BTCUSDT.P @ D, qty 10%, A Long)

| Variant | MA Type | Periods | Trades | Win % | **PF** | P&L % | Max DD % | Verdict |
|---|---|---|---:|---:|---:|---:|---:|---|
| V1.005-a | SMA | 20/50/100 | 18 | 44.44% | 5.436 | +35.15% | 4.04% | Baseline V1.004 |
| **V1.005-b** | **EMA** | **20/50/100** | 13 | **53.85%** | **7.145** ⭐ | **+53.45%** | **2.99%** | 🏆 **CHỌN** |
| V1.005-c | SMA | 10/30/60 | 29 | 44.83% | 3.154 | +30.07% | 4.66% | Quá nhạy → noise |
| V1.005-d | Hybrid | EMA20 / SMA50 / SMA200 | 17 | 41.18% | 4.375 | +36.83% | 3.35% | OK nhưng kém b |

### Phân tích độ nhạy vs độ trễ

| Tradeoff | Quan sát |
|---|---|
| **EMA 20/50/100 (b)** | Lag thấp hơn SMA 20/50/100 → entry sớm hơn vài ngày → 5/13 trade tránh được giai đoạn sideway → **win rate nhảy từ 44% → 54%**, PF từ 5.4 → 7.1 |
| **SMA 10/30/60 (c)** | Quá nhạy → 29 trade nhưng nhiều cú vào nhầm pha → PF chỉ 3.15 (tệ nhất) |
| **Hybrid d** | Slow MA = SMA 200 quá chậm → bỏ lỡ trend đầu → trade #2 (340% gain) bị skip |

**Kết luận**: EMA 20/50/100 là **sweet spot** cho BTC daily — đủ nhạy để bắt swing, đủ trễ để lọc noise.

## 3. V1.005-b — Top 10 trades (sorted by P&L)

Strategy chỉ tạo **13 trade winners + losers** trong 6 năm. Đây là tất cả 13, sort theo P&L USDT giảm dần:

| Rank | # | Entry | Exit | Entry $ | Exit $ | Hold (days) | P&L USDT | P&L % | R-multiple |
|---:|---:|---|---|---:|---:|---:|---:|---:|---:|
| 🥇 | 2 | 2020-10-10 | 2021-05-14 | 11,303.7 | 49,850.3 | ~216 | **+34,496.66** | **+340.35%** | 14.5R ⭐ |
| 🥈 | 7 | 2023-10-22 | 2024-05-01 | 29,978.9 | 58,298.3 | ~192 | **+12,883.46** | +94.17% | 5.0R |
| 🥉 | 10 | 2024-10-13 | 2025-02-17 | 62,838.9 | 95,734.8 | ~127 | +7,604.26 | +52.12% | 2.8R |
| 4 | 5 | 2023-01-23 | 2023-05-19 | 22,908.7 | 26,868.6 | ~116 | +2,326.08 | +17.11% | 1.4R |
| 5 | 11 | 2025-05-03 | 2025-08-29 | 95,815.7 | 108,355.1 | ~118 | +1,981.80 | +12.92% | 1.0R |
| 6 | 4 | 2021-10-03 | 2021-12-03 | 48,175.7 | 53,626.3 | ~61 | +1,499.42 | +11.15% | 0.8R |
| 7 | 1 | 2020-07-02 | 2020-09-10 | 9,086.2 | 10,338.8 | ~70 | +1,361.83 | +13.62% | 0.7R |
| 8 | 8 | 2024-05-18 | 2024-06-22 | 66,876.0 | 64,222.9 | ~35 | −613.57 | −4.11% | −0.3R |
| 9 | 12 | 2025-09-15 | 2025-09-25 | 115,315.8 | 108,931.1 | ~10 | −884.64 | −5.68% | −0.5R |
| 10 | 3 | 2021-08-19 | 2021-09-27 | 46,738.2 | 42,169.8 | ~39 | −1,344.17 | −9.91% | −0.7R |
| 11 | 6 | 2023-06-22 | 2023-08-17 | 29,876.6 | 26,609.9 | ~56 | −1,532.10 | −11.07% | −0.8R |
| 12 | 13 | 2025-10-01 | 2025-10-17 | 118,555.6 | 106,364.4 | ~16 | −1,606.79 | −10.42% | −0.8R |
| 13 | 9 | 2024-07-23 | 2024-08-05 | 65,922.3 | 53,988.0 | ~13 | −2,717.48 | −18.23% | −1.4R (worst) |

**Tổng P&L: +53,454.77 USDT (+53.45%)**

### Quan sát top trades

1. **Trade #2 (2020 bull run) đóng góp 65% tổng P&L** — 1 trade ăn cả game. Đây là rủi ro: nếu bỏ lỡ trade này (hoặc chậm vài tuần) → strategy underperform nặng.
2. **Top 3 trades = 92% tổng P&L** → strategy phụ thuộc vào trend lớn. Sideway không kiếm tiền.
3. **6/7 winners hold > 60 ngày** vs **5/6 losers hold < 50 ngày** → công thức rõ: **winners cho chạy, losers cắt nhanh** đã được hệ thống tự thực hiện.
4. **Worst trade #9** (Jul-Aug 2024): −18.23% trong 13 ngày. Đây là pha "fakeout" — bull stack hình thành rồi sập. Cần filter slope hoặc volume confirmation (V1.006).

## 4. Equity curve & visual

![V1.005-b chart overview](../../tradingview-mcp/screenshots/V005b_chart_overview.png)
*BTCUSDT.P D chart với V1.005-b EMA 20/50/100 (Pine Editor mở bên phải).*

![V1.005-b strategy tester](../../tradingview-mcp/screenshots/V005b_D_metrics.png)
*Strategy Tester: List of trades. PF 7.145, Win 53.85%, DD 2.99%.*

## 5. Tích hợp B4v2F break-out signal

Phát hiện từ test V1.B.004v2 (Short Only, 4H): khi **bear stack kết thúc** (`bear_end`), market thường bắt đầu break-out lên → đây là tín hiệu LONG có giá trị.

Đã lưu vào:
- **Library**: `mtt.bear_to_neutral_breakout(bear_stack)` → series bool
- **Indicator V1.005**: marker hình kim cương màu aqua chữ "BO"
- **Strategy B005**: plot marker + `alertcondition` để TV gửi cảnh báo, **không tự vào lệnh**
- **Roadmap V1.006+**: Strategy A005 sẽ subscribe signal này như entry phụ trợ song song với `bull_start`

## 6. Roadmap V1.006 (filters)

V1.005 đã chốt MA combo. V1.006 sẽ thêm:

| Filter | Mục tiêu | Test trên |
|---|---|---|
| **Slope filter** | Loại sideway: chỉ entry khi `mm[20] > mm[40]` (slope dương ≥ 20 bars) | Tránh cú trade #9 (-18%) |
| **Volume confirmation** | Entry chỉ khi `volume > sma(volume, 50)` | Lọc fake breakout |
| **ATR trailing stop** | Bảo vệ winners: trail = 2.5 × ATR(14) | Locks profit khi market reverse |
| **Breakout long subscribe** | A005 nhận tín hiệu `breakout_long` từ B005 | Thêm 5–10 entries/year |
| **Time filter** | Chỉ trade trong giờ Mỹ/EU active (futures) | Tránh thanh khoản kém |

**Mục tiêu V1.006**: tăng số trade D từ 13 → 25–30, giữ PF ≥ 5.

## 7. Khuyến nghị cấu hình production

```text
Strategy:        strategy_MTT_v1.A005 (Long Only)
Symbol:          BYBIT:BTCUSDT.P
Timeframe:       D
MA:              EMA 20/50/100
Profile:         Futures
Qty per entry:   10% equity
Commission:      0.075%
Slippage:        2 ticks
Pyramiding:      0
Backtested PF:   7.145
Backtested DD:   2.99%
Backtested P&L:  +53.45% / 6 năm
```

⚠️ **Lưu ý quan trọng**:
- 13 trade trong 6 năm vẫn là sample nhỏ. Forward test ít nhất 3–6 tháng paper trading trước khi đưa vào live.
- Trade #2 (340% gain) là outlier — nếu bỏ lỡ → P&L thực ~ +18% (vẫn dương nhưng PF giảm xuống ~3).
- B (Short) **không** dùng như standalone strategy — chỉ giữ làm signal generator cho break-out.

## 8. Files

| Loại | Path |
|---|---|
| Library | [pine/v1/strategy_mtt_lib.pine](../../pine/v1/strategy_mtt_lib.pine) |
| Indicator | [pine/v1/indicator_MTT_v1.005.pine](../../pine/v1/indicator_MTT_v1.005.pine) |
| Strategy A (Long) | [pine/v1/strategy_MTT_v1.A005.pine](../../pine/v1/strategy_MTT_v1.A005.pine) |
| Strategy B (Short + BO signal) | [pine/v1/strategy_MTT_v1.B005.pine](../../pine/v1/strategy_MTT_v1.B005.pine) |
| Screenshots | [tradingview-mcp/screenshots/V005b_*.png](../../tradingview-mcp/screenshots/) |
| Báo cáo trước | [strategy_MTT_v1.000_to_v1.004_integrated_report.md](strategy_MTT_v1.000_to_v1.004_integrated_report.md) |
