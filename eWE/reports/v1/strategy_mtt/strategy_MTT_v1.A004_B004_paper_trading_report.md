# Báo cáo Paper Trading — strategy_MTT v1.A004 (Long) & v1.B004 (Short)

**Symbol**: BYBIT:BTCUSDT.P
**Timeframe**: **D** (chỉ test TF Daily — TF duy nhất ăn được, đã chứng minh ở v1.003)
**Chart type**: Candles
**Date range**: 2020-03-25 → 2026-05-09 (~6 năm)
**Initial capital**: 100,000 USDT — **Commission**: 0.075% — **Slippage**: 2 ticks — **Pyramiding**: 0
**Run date**: 2026-05-09

---

## 1. Cấu trúc 2 strategy

| File | Mode | Tín hiệu vào | Tín hiệu ra |
|---|---|---|---|
| [strategy_MTT_v1.A004.pine](../../pine/v1/strategy_MTT_v1.A004.pine) | **LONG ONLY** | `SMA50>150>200` chuyển true (vùng xanh bắt đầu) | Vùng xanh kết thúc |
| [strategy_MTT_v1.B004.pine](../../pine/v1/strategy_MTT_v1.B004.pine) | **SHORT ONLY** | `SMA50<150<200` chuyển true (vùng đỏ bắt đầu) | Vùng đỏ kết thúc |

## 2. Profile presets (KHÔNG all-in)

| Profile | A004 (Long) | B004 (Short) | qty % equity | Lý do |
|---|---|---|---:|---|
| **Spot** | ✅ Áp dụng | ❌ N/A (không short được spot) | 25% | Tài khoản giao ngay, không đòn bẩy |
| **Margin** | ✅ Áp dụng | ✅ Áp dụng | 60% | 20% equity × 3x leverage |
| **Futures** | ✅ Áp dụng | ✅ Áp dụng | 30% | 10% equity × 10x leverage (thận trọng vì funding/liquidation) |

## 3. Kết quả

### A004 — LONG ONLY @ D

| Profile | qty% | Net P&L | P&L % | Max DD % | Trades | Win % | PF | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| **Spot**    | 25% | +59,273.08  | **+59.27%**  | 9.91%  | 6 | 50.00% | **3.568** | ✅ An toàn nhất |
| **Futures** | 30% | +70,895.24  | **+70.90%**  | 11.90% | 6 | 50.00% | 3.376     | ✅ Cân bằng |
| **Margin**  | 60% | +135,457.38 | **+135.46%** | 23.81% | 6 | 50.00% | 2.589     | ✅ Lợi nhuận cao nhất, DD x2 |

### B004 — SHORT ONLY @ D

| Profile | qty% | Net P&L | P&L % | Max DD % | Trades | Win % | PF | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Spot       | —     | (N/A) | — | — | — | — | — | Không áp dụng |
| **Futures** | 30% | −3,387.15  | **−3.39%** | 15.90% | 4 | 25.00% | 0.69  | ❌ Lỗ |
| **Margin**  | 60% | −8,997.31  | **−9.00%** | 30.18% | 4 | 25.00% | 0.644 | ❌ Lỗ nặng |

## 4. So sánh A004 vs B004

| Tiêu chí | A004 (Long) | B004 (Short) |
|---|---|---|
| Số lệnh trong 6 năm | 6 | 4 |
| Win rate | **50.00%** | 25.00% |
| Profit Factor (TB 3 profile) | **3.18** | 0.67 |
| Net P&L (TB) | **+88.5%** | −6.2% |
| Max DD | 9.9% – 23.8% | 15.9% – 30.2% |
| Đáng giao dịch live? | **Có** | **Không** |

## 5. Quan sát chính

1. **Long-only winning across all 3 profiles** — Bitcoin tự nhiên uptrend dài hạn, mỗi lần stack tăng → cú trend kéo dài, ăn lớn.
2. **Short-only thua đều ở mọi profile** — chỉ có 4 setup short trong 6 năm, win rate 25% và **mỗi cú thua hơn cú thắng** (PF < 1). Pha bear stack trên D rất ngắn → thường bị stopped out khi MA "ngoe nguẩy".
3. **Tăng qty% = tăng P&L gần như tuyến tính**, nhưng **DD nhân theo cùng tỉ lệ**:
   - A004: 25% → 30% → 60% qty: P&L = 59% / 71% / 135%, DD = 9.9% / 11.9% / 23.8%
   - PF của Margin (2.589) thấp hơn Spot (3.568) → leverage cao = khả năng bị shake out cao hơn ở pha sideway
4. **Win rate giữ nguyên 50%** giữa các profile A004 → đúng kỳ vọng (qty% chỉ scale size, không đổi tín hiệu).

## 6. Khuyến nghị

| Loại tài khoản | Strategy đề xuất | Profile | Ghi chú |
|---|---|---|---|
| **Spot wallet** | A004 only | Spot 25% | An toàn, R-multiple ổn định |
| **Margin account** | A004 only | Margin 60% | Bỏ B004 — short không cover được phí |
| **Futures perpetual** | A004 only | Futures 30% | Đừng all-in, đừng short. Tránh funding rate trừ vốn |

**KHÔNG NÊN** dùng B004 (Short Only) trên BTC trong điều kiện bull market dài hạn. Có thể giữ B004 như **hedge tactical** khi macro chuyển sang downturn xác nhận (SMA200 dốc xuống ≥ 60 phiên), nhưng cần thêm filter slope.

## 7. Files

- Strategy A004 (Long): [pine/v1/strategy_MTT_v1.A004.pine](../../pine/v1/strategy_MTT_v1.A004.pine)
- Strategy B004 (Short): [pine/v1/strategy_MTT_v1.B004.pine](../../pine/v1/strategy_MTT_v1.B004.pine)
- Báo cáo Combined v1.003 (Long+Short): [strategy_MTT_v1.003_BTCUSDT.P_paper_trading_report.md](strategy_MTT_v1.003_BTCUSDT.P_paper_trading_report.md)
