# Báo cáo Macro TF Matrix — V1.003 vs A004 vs B004

**Symbol**: BYBIT:BTCUSDT.P (Bybit Perpetual)
**Chart type**: Candles
**Date range**: 2020-03-25 → 2026-05-09 (~6 năm cho TF D, ~16 tháng cho 1H/4H)
**Initial capital**: 100,000 USDT — **Commission**: 0.075% — **Slippage**: 2 ticks — **Pyramiding**: 0
**Run date**: 2026-05-09

3 strategy × 3 profile × 3 TF = **27 cells** (B004 không test Spot vì N/A)

---

## 1. V1.003 — LONG + SHORT (combined)

| Profile | TF | Net P&L | P&L % | Max DD % | Trades | Win % | PF | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|
| **Spot 25%** *(long-only do spot)* | 1H | +116.58 | +0.12% | 3.85% | 47 | 40.43% | 1.011 | 🟡 Hoà |
| Spot 25% | 4H | +10,145.40 | +10.15% | 10.84% | 40 | 30.00% | 1.223 | ✅ Mỏng |
| Spot 25% | **D** | **+59,273.08** | **+59.27%** | **9.91%** | 6 | 50.00% | **3.568** | 🏆 |
| **Margin 60%** | 1H | −14,706.27 | −14.71% | 23.09% | 94 | 39.36% | 0.742 | ❌ |
| Margin 60% | 4H | +6,296.81 | +6.30% | 36.00% | 86 | 33.72% | 1.01 | ⚠️ |
| Margin 60% | **D** | **+114,300.13** | **+114.30%** | 35.57% | 10 | 40.00% | 1.683 | ✅ |
| **Futures 30%** | 1H | −7,218.48 | −7.22% | 12.18% | 94 | 39.36% | 0.762 | ❌ |
| Futures 30% | 4H | +7,641.74 | +7.64% | 19.72% | 86 | 33.72% | 1.062 | 🟡 |
| Futures 30% | **D** | **+65,116.61** | **+65.12%** | 19.00% | 10 | 40.00% | 2.088 | ✅ |

## 2. A004 — LONG ONLY

| Profile | TF | Net P&L | P&L % | Max DD % | Trades | Win % | PF | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|
| **Spot 25%** | 1H | +116.58 | +0.12% | 3.85% | 47 | 40.43% | 1.011 | 🟡 Hoà |
| Spot 25% | 4H | +10,143.12 | +10.14% | 10.84% | 40 | 30.00% | 1.223 | ✅ |
| Spot 25% | **D** | **+59,273.08** | **+59.27%** | **9.91%** | 6 | 50.00% | **3.568** | 🏆 An toàn nhất |
| **Margin 60%** | 1H | −76.52 | −0.08% | 9.08% | 47 | 40.43% | 0.997 | 🟡 Hoà |
| Margin 60% | 4H | +17,447.84 | +17.45% | 24.74% | 40 | 30.00% | 1.14 | ✅ |
| Margin 60% | **D** | **+135,457.38** | **+135.46%** | 23.81% | 6 | 50.00% | 2.589 | 🏆 P&L cao nhất |
| **Futures 30%** | 1H | +124.92 | +0.12% | 4.61% | 47 | 40.43% | 1.01 | 🟡 |
| Futures 30% | 4H | +11,699.78 | +11.70% | 12.92% | 40 | 30.00% | 1.211 | ✅ |
| Futures 30% | **D** | **+70,895.24** | **+70.90%** | 11.90% | 6 | 50.00% | 3.376 | 🏆 Cân bằng |

## 3. B004 — SHORT ONLY

| Profile | TF | Net P&L | P&L % | Max DD % | Trades | Win % | PF | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---|
| Spot | — | (N/A) | — | — | — | — | — | Không áp dụng |
| **Margin 60%** | 1H | −14,640.09 | −14.64% | 21.89% | 47 | 38.30% | 0.586 | ❌ |
| Margin 60% | 4H | −9,510.46 | −9.51% | 36.04% | 46 | 36.96% | 0.882 | ❌ |
| Margin 60% | D | −8,986.52 | −8.99% | 30.18% | 4 | 25.00% | 0.644 | ❌ |
| **Futures 30%** | 1H | −7,348.68 | −7.35% | 11.52% | 47 | 38.30% | 0.607 | ❌ |
| Futures 30% | 4H | −3,615.11 | −3.62% | 19.71% | 46 | 36.96% | 0.91 | ❌ |
| Futures 30% | D | −3,382.46 | −3.38% | 15.90% | 4 | 25.00% | 0.69 | ❌ |

> **Tất cả profile của B004 đều lỗ** — bằng chứng rõ ràng: trên BTC bull market 6 năm, không có chỗ cho strategy short-only stack flip.

---

## 4. So sánh chéo: tác động của việc THÊM SHORT (V1.003 vs A004)

| Profile | TF | A004 (Long only) | V1.003 (Long+Short) | Δ P&L | Δ DD |
|---|---|---:|---:|---:|---:|
| Margin | D | **+135.46%** / DD 23.81% / PF 2.589 | +114.30% / DD 35.57% / PF 1.683 | **−21.16%** | **+11.76%** |
| Futures | D | **+70.90%** / DD 11.90% / PF 3.376 | +65.12% / DD 19.00% / PF 2.088 | −5.78% | **+7.10%** |
| Margin | 4H | +17.45% / DD 24.74% / PF 1.14 | +6.30% / DD 36.00% / PF 1.01 | **−11.15%** | **+11.26%** |
| Futures | 4H | +11.70% / DD 12.92% / PF 1.211 | +7.64% / DD 19.72% / PF 1.062 | −4.06% | +6.80% |
| Margin | 1H | −0.08% / DD 9.08% | −14.71% / DD 23.09% | −14.63% | **+14.01%** |
| Futures | 1H | +0.12% / DD 4.61% | −7.22% / DD 12.18% | −7.34% | **+7.57%** |

> **Thêm short = trừ P&L + cộng DD + giảm PF ở MỌI cấu hình**. Nhánh short không bù được nhánh long mạnh, mà còn ăn phí + slippage và ép DD lên cao hơn nhiều.

## 5. Cải thiện chỉ số dựa trên A004 / B004

### Phát hiện
1. **Tắt nhánh short hoàn toàn** → V1.003 không nên có lựa chọn `allow_short=true` mặc định cho BTC trong giai đoạn 2020–2026.
2. **A004 Spot D** là cấu hình **risk-adjusted tốt nhất**: PF 3.568, DD chỉ 9.91% — phù hợp giáo dục/holder bảo toàn vốn.
3. **A004 Margin D** là cấu hình **return-maximizing**: +135% nhưng DD chấp nhận được 23.81% với 3x leverage.
4. **A004 Futures D** là điểm cân bằng tốt nhất: PF 3.376 + lợi suất tuyệt đối +70.90%, DD chỉ 11.90%.
5. **TF nhỏ hơn D vẫn không nên dùng** kể cả với A004:
   - 1H: hoà vốn (0.12%) — không xứng công sức theo dõi.
   - 4H: positive (+10–17%) nhưng PF chỉ 1.14–1.22 → mỏng, dễ bị regime change.
6. **B004 không cứu được** kể cả khi giảm size xuống 30% (Futures) — tất cả 6 ô vẫn lỗ.

### Khuyến nghị V1.005 (improvement)

Chốt thiết kế cho v1.005:
- **Bỏ B004** ra khỏi suite mặc định (chỉ để file demo).
- **Mặc định = A004 Daily**, profile Futures (risk-adjusted optimum).
- **Cho phép B004 BẬT MỀM** (input toggle) chỉ khi market cycle xác định bear (ví dụ: SMA200 dốc xuống ≥ 60 phiên).
- Thêm **filter slope**: chỉ vào Long khi `SMA200[20] > SMA200[40]` (slope dương đáng kể) → loại bỏ trade ở vùng sideway 4H/1H.
- Thêm **trailing stop** để bảo vệ DD.

## 6. Bảng xếp hạng 27 cells theo Profit Factor

| # | Cell | PF | P&L % | DD % |
|--:|---|---:|---:|---:|
| 1 | A004 Spot D = V1.003 Spot D | **3.568** | +59.27% | 9.91% |
| 2 | A004 Futures D | **3.376** | +70.90% | 11.90% |
| 3 | A004 Margin D | **2.589** | +135.46% | 23.81% |
| 4 | V1.003 Futures D | 2.088 | +65.12% | 19.00% |
| 5 | V1.003 Margin D | 1.683 | +114.30% | 35.57% |
| 6 | A004 Spot 4H = V1.003 Spot 4H | 1.223 | +10.14–15% | 10.84% |
| 7 | A004 Futures 4H | 1.211 | +11.70% | 12.92% |
| 8 | A004 Margin 4H | 1.14 | +17.45% | 24.74% |
| 9 | V1.003 Futures 4H | 1.062 | +7.64% | 19.72% |
| 10 | V1.003 Spot 1H = A004 Spot 1H | 1.011 | +0.12% | 3.85% |
| 11 | A004 Futures 1H | 1.01 | +0.12% | 4.61% |
| 12 | V1.003 Margin 4H | 1.01 | +6.30% | 36.00% |
| 13 | A004 Margin 1H | 0.997 | −0.08% | 9.08% |
| 14 | B004 Futures 4H | 0.91 | −3.62% | 19.71% |
| 15 | B004 Margin 4H | 0.882 | −9.51% | 36.04% |
| 16 | V1.003 Futures 1H | 0.762 | −7.22% | 12.18% |
| 17 | V1.003 Margin 1H | 0.742 | −14.71% | 23.09% |
| 18 | B004 Futures D | 0.69 | −3.38% | 15.90% |
| 19 | B004 Margin D | 0.644 | −8.99% | 30.18% |
| 20 | B004 Futures 1H | 0.607 | −7.35% | 11.52% |
| 21 | B004 Margin 1H | 0.586 | −14.64% | 21.89% |

## 7. Top 3 cấu hình theo mục tiêu

| Mục tiêu | Cấu hình tối ưu | P&L | DD | PF |
|---|---|---:|---:|---:|
| **Bảo toàn vốn (PF cao, DD thấp)** | A004 / V1.003 Spot @ D | +59.27% | 9.91% | 3.568 |
| **Cân bằng** (return tốt, DD vừa) | **A004 Futures @ D** | +70.90% | 11.90% | 3.376 |
| **Tối đa lợi nhuận** (chấp nhận DD cao) | A004 Margin @ D | +135.46% | 23.81% | 2.589 |

## 8. Files

- v1.003: [pine/v1/strategy_MTT_v1.003.pine](../../pine/v1/strategy_MTT_v1.003.pine)
- A004 (Long): [pine/v1/strategy_MTT_v1.A004.pine](../../pine/v1/strategy_MTT_v1.A004.pine)
- B004 (Short): [pine/v1/strategy_MTT_v1.B004.pine](../../pine/v1/strategy_MTT_v1.B004.pine)
- Báo cáo trước: [strategy_MTT_v1.003_BTCUSDT.P_paper_trading_report.md](strategy_MTT_v1.003_BTCUSDT.P_paper_trading_report.md), [strategy_MTT_v1.A004_B004_paper_trading_report.md](strategy_MTT_v1.A004_B004_paper_trading_report.md)
