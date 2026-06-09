# Báo cáo V1.005-b — 4H, Futures x20, qty 200% notional

**Strategy**: V1.005-b EMA 20/50/100, Long Only
**Symbol**: BYBIT:BTCUSDT.P
**Timeframe**: **4H**
**Initial capital (margin)**: 100,000 USDT
**Leverage**: **20x** → qty per entry = **10% margin × 20x = 200% notional** (≈ 200,000 USDT/lệnh)
**Commission**: 0.075% — **Slippage**: 2 ticks — **Pyramiding**: 0
**Run date**: 2026-05-10

---

## 1. So sánh 2 khoảng thời gian

| Range | Net P&L | P&L % | Max DD USDT | Max DD % | Trades | Win % | PF | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| **2025-01-01 → 2026-05-09** (~16 tháng) | −10,373.75 | **−10.37%** | 46,113.91 | **38.38%** | 21 | 33.33% | **0.871** | ❌ Lỗ |
| **2024-01-01 → 2026-05-09** (~28 tháng) | **+87,262.58** | **+87.26%** | 96,353.07 | 38.38% | 35 | 37.14% | **1.321** | ✅ Lãi |

> **Cùng strategy, cùng leverage, chỉ thêm 1 năm 2024 → đảo chiều từ lỗ sang lãi 87%**. Nguyên nhân: 2024 có 2 trade siêu lớn (#2 +93k, #13 +83k) bù toàn bộ losses.

## 2. Top 10 trades — 2024-2026 range (theo P&L USDT)

| Rank | # | Type | Entry | Exit | Entry $ | Exit $ | Hold | Notional ($K) | **P&L USDT** | P&L % notional |
|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| 🥇 | 2  | Long | 2024-01-31 12:00 | 2024-03-16 20:00 | 43,330.2  | 65,331.0  | 45d | 184.93  | **+93,551.59** | +50.55% |
| 🥈 | 13 | Long | 2024-11-06 00:00 | 2024-12-10 16:00 | 74,395.1  | 95,817.7  | 35d | 289.99  | **+83,007.68** | +28.60% |
| 🥉 | 19 | Long | 2025-04-14 20:00 | 2025-05-29 20:00 | 84,547.6  | 105,549.8 | 45d | 319.93  | **+78,932.83** | +24.65% |
| 4  | 34 | Long | 2026-04-08 08:00 | 2026-04-29 16:00 | 71,650.2  | 75,516.8  | 21d | 320.85  | +16,820.38 | +5.24% |
| 5  | 12 | Long | 2024-10-14 00:00 | 2024-11-03 12:00 | 64,288.2  | 68,073.1  | 20d | 260.11  | +14,912.06 | +5.73% |
| 6  | 35 | Long | 2026-05-01 12:00 | 2026-05-10 00:00 | 78,399.4  | 80,733.2  | 9d  | 354.44  | +10,011.53 | +2.82% |
| 7  | 10 | Long | 2024-09-15 04:00 | 2024-10-01 16:00 | 60,161.8  | 61,740.6  | 16d | 258.03  | +6,379.34  | +2.47% |
| 8  | 29 | Long | 2026-01-03 04:00 | 2026-01-11 16:00 | 89,525.2  | 90,642.6  | 8d  | 377.98  | +4,147.16  | +1.10% |
| 9  | 32 | Long | 2026-03-10 08:00 | 2026-03-20 04:00 | 70,560.5  | 70,815.0  | 10d | 328.11  | +690.38    | +0.21% |
| 10 | 30 | Long | 2026-01-11 20:00 | 2026-01-20 04:00 | 90,962.8  | 91,124.7  | 8d  | 386.23  | +107.57    | +0.03% |

**Top 3 trades = 255,492 USDT (255.49% trên capital)**, gấp 2.9× tổng P&L cuối → 22 losers ăn lại ~168k. Strategy thắng nhờ 3 cú trend BTC lớn.

## 3. Top 10 losers — 2024-2026 range (cảnh báo)

| Rank | # | Entry | Exit | Hold | **P&L USDT** | P&L % notional |
|---:|---:|---|---|---:|---:|---:|
| 1 (worst) | 31 | 2026-03-05 08:00 | 2026-03-08 08:00 | 3d  | **−29,194.44** | −7.55% ⚠️ |
| 2 | 3  | 2024-03-25 16:00 | 2024-04-02 08:00 | 7d  | −28,505.38 | −7.66% |
| 3 | 27 | 2025-10-01 20:00 | 2025-10-10 20:00 | 9d  | −22,487.87 | −5.05% |
| 4 | 14 | 2024-12-11 16:00 | 2024-12-20 00:00 | 8d  | −19,044.39 | −4.17% |
| 5 | 15 | 2025-01-06 08:00 | 2025-01-08 20:00 | 2d  | −18,371.31 | −4.39% |
| 6 | 18 | 2025-03-25 12:00 | 2025-03-29 04:00 | 4d  | −16,807.78 | −4.75% |
| 7 | 17 | 2025-01-30 04:00 | 2025-02-01 12:00 | 2d  | −11,584.72 | −3.07% |
| 8 | 28 | 2025-10-29 04:00 | 2025-10-29 16:00 | 12h | −10,855.20 | −2.71% |
| 9 | 4  | 2024-04-07 04:00 | 2024-04-13 04:00 | 6d  | −9,160.43  | −2.91% |
| 10 | 1 | 2024-01-01 20:00 | 2024-01-13 08:00 | 12d | −7,514.61  | −3.75% |

**13/22 losers hold ≤ 5 ngày** → fakeout pattern: stack flips lên rồi sập trong vài ngày. Đây là target số 1 cho V1.006 filters.

## 4. Phân tích

### 4.1. Tại sao 2025-2026 lỗ mà 2024-2026 lãi?
- 2025 BTC chạy sideway trong range 80k-110k → strategy ăn 1 cú lớn (#19 +78,932) nhưng bị 8 losers liên tiếp → DD 38.38%, P&L âm.
- 2024 thêm vào 2 cú trend macro (#2, #13) → bù toàn bộ và đẩy P&L lên +87%.
- **Strategy KHÔNG ổn định trên 4H** ở mức leverage 20x — phụ thuộc may mắn bắt được trend lớn.

### 4.2. So sánh với V1.005-b D (qty 10% no leverage)

| Metric | D 6 năm (qty 10%) | 4H 28 tháng (qty 200% = x20 lev) |
|---|---:|---:|
| P&L % | +53.45% | **+87.26%** (cao hơn) |
| Max DD % | 2.99% | **38.38%** (×12.8) |
| Trades | 13 | 35 |
| PF | 7.145 | 1.321 |
| Win % | 53.85% | 37.14% |
| **Risk-adjusted (PF)** | **🏆 D vượt trội** | Tệ hơn nhiều |

> **Kết luận**: x20 leverage trên 4H đem lại P&L tuyệt đối cao hơn nhưng **đánh đổi PF gấp 5.4× xấu hơn** và **DD gấp 12.8×**. Không khuyến nghị live trading ở leverage này.

### 4.3. Liquidation risk

Với 20x leverage và margin 100k:
- Notional 200k mỗi entry
- 5% adverse move → mất 10k = 10% margin
- **DD 38.38% = 38,380 USDT mất** trong giai đoạn xấu nhất → còn 61,620 margin
- Nếu thêm 10% adverse nữa khi đang ở trạng thái này → margin call

→ **Rủi ro thanh lý CAO** ở leverage này. Khuyến nghị giảm xuống x5–x10 nếu muốn dùng 4H.

## 5. Khuyến nghị

| Hướng | Cấu hình | Ghi chú |
|---|---|---|
| **An toàn** | V1.005-b D, qty 10%, no leverage (Spot/Futures 1x) | PF 7.145, DD 3% — đã chứng minh 6 năm |
| **Cân bằng** | V1.005-b 4H, qty 50% (5x lev) | Cần test thêm — dự kiến PF ~2, DD ~10% |
| **Aggressive** ⚠️ | V1.005-b 4H, qty 200% (20x lev) | **Báo cáo này** — DD 38%, dễ thanh lý |
| **Không khuyến nghị** | 4H, qty ≥ 300% | Liquidation gần như chắc chắn |

## 6. Roadmap V1.006 cho 4H

Để 4H ăn được mà không phụ thuộc vào trend lớn ngẫu nhiên, V1.006 cần:

1. **Slope filter** `mm[20] > mm[40]` → loại 13 fakeout losers ≤ 5 ngày
2. **Volume confirmation** → entry chỉ khi volume break-out xác nhận
3. **ATR trailing stop 2.5×** → bảo vệ winners trên 4H biến động lớn
4. **Position sizing scaling** → giảm qty khi DD rolling > 15%, tăng khi PF > 2

**Mục tiêu V1.006 4H x20**: PF ≥ 2, DD ≤ 20%, trade ≥ 30 / 28 tháng.

## 7. Files & screenshots

- Strategy V1.005-b: [pine/v1/strategy_MTT_v1.A005.pine](../../pine/v1/strategy_MTT_v1.A005.pine) (đặt qty 200 trong override)
- Screenshot 2024-2026: [tradingview-mcp/screenshots/V005b_4H_2024_2026_x20.png](../../tradingview-mcp/screenshots/V005b_4H_2024_2026_x20.png)
- Báo cáo trước: [strategy_MTT_v1.005_MA_tuning_report.md](strategy_MTT_v1.005_MA_tuning_report.md)
