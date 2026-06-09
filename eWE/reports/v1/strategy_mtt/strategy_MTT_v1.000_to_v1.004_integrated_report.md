# Báo cáo tích hợp V1.000 → V1.004

**Symbol**: BYBIT:BTCUSDT.P (Bybit Perpetual)
**Chart type**: Candles
**Initial capital**: 100,000 USDT — **Commission**: 0.075% — **Slippage**: 2 ticks
**Run date**: 2026-05-09

---

## 1. Lịch sử các phiên bản

| Version | Loại | MA periods | Qty% | Long | Short | Trades D | Ghi chú |
|---|---|---|---:|:-:|:-:|---:|---|
| **V1.000** | Indicator | 50/150/200 | — | — | — | — | Trend Template + bảng 8 tiêu chí |
| **V1.001** | Indicator | 50/150/200 | — | — | — | — | Thêm tô nền vùng SMA stack |
| **V1.002** | Strategy | 50/150/200 | 100% (all-in) | ✓ | ✓ | ~10 | Baseline, qty all-in → DD lớn |
| **V1.003** | Strategy | 50/150/200 | Spot 25 / Margin 60 / Futures 30 | ✓ | ✓ | 6–10 | Profile presets, không all-in |
| **V1.A004** | Strategy | 50/150/200 | Spot 25 / Margin 60 / Futures 30 | ✓ | ✗ | 6 | LONG ONLY |
| **V1.B004** | Strategy | 50/150/200 | Margin 60 / Futures 30 | ✗ | ✓ | 4 | SHORT ONLY |
| **V1.A.004v2** | Strategy | **20/50/100** | **Spot/Futures 10 / Margin 20** | ✓ | ✗ | **18** | MA ngắn → 3× trade, qty nhỏ |
| **V1.B.004v2** | Strategy | **20/50/100** | **Margin 20 / Futures 10** | ✗ | ✓ | 1 | Bear stack 20/50/100 cực hiếm trên BTC D |

> **V1.000 / V1.001** là indicator (không backtest được). Strategy backtest từ V1.002.

## 2. Tại sao V1.004 thay đổi MA periods?

**Vấn đề V1.003 / A004 / B004**: SMA 50/150/200 trên Daily quá chậm → chỉ **6–10 trade** trong 6 năm, không đủ thống kê để đánh giá robust.

**V1.004**: chuyển sang **20/50/100** (vẫn theo nguyên tắc Minervini stacked MAs) → **18 trade** trên D với A004v2 (3× nhiều hơn), giữ được hiệu năng cao.

## 3. Profile qty% — bảng so sánh

| Profile | V1.003 / A004 / B004 (qty per entry) | **V1.004 (mới)** | Lý do giảm |
|---|---:|---:|---|
| Spot     | 25% | **10%** | Position trading dài hạn, an toàn vốn |
| Margin   | 60% | **20%** | 20% × 3x lev = 60% notional (giữ) |
| Futures  | 30% | **10%** | 10% × 10x lev = 100% notional (cao hơn cũ; thực ra v1.003 quá thận trọng) |

> V1.004 qty/entry nhỏ hơn → mỗi tín hiệu rủi ro thấp hơn, đủ chỗ bù lỗ khi 1 cú thua, và scale thẳng theo PF nếu cần phóng đại sau.

## 4. Bảng tổng hợp kết quả — Macro TFs (BTCUSDT.P)

### V1.A004 v1 (MA 50/150/200, Long Only)

| Profile | TF | P&L % | DD % | Trades | Win % | PF |
|---|---|---:|---:|---:|---:|---:|
| Spot 25%    | 1H | +0.12  | 3.85  | 47 | 40.43 | 1.011 |
| Spot 25%    | 4H | +10.14 | 10.84 | 40 | 30.00 | 1.223 |
| Spot 25%    | D  | **+59.27** | 9.91  | 6  | 50.00 | **3.568** |
| Margin 60%  | 1H | −0.08  | 9.08  | 47 | 40.43 | 0.997 |
| Margin 60%  | 4H | +17.45 | 24.74 | 40 | 30.00 | 1.140 |
| Margin 60%  | D  | **+135.46** | 23.81 | 6 | 50.00 | 2.589 |
| Futures 30% | 1H | +0.12  | 4.61  | 47 | 40.43 | 1.010 |
| Futures 30% | 4H | +11.70 | 12.92 | 40 | 30.00 | 1.211 |
| Futures 30% | D  | **+70.90** | 11.90 | 6  | 50.00 | 3.376 |

### V1.A.004v2 (MA 20/50/100, Long Only, qty Futures 10%)

| TF | P&L % | DD % | Trades | Win % | PF | So với A004v1 |
|---|---:|---:|---:|---:|---:|---|
| 1H | −4.16 | 4.61 | **103** | 30.10 | 0.62  | Trade ×2.2, PF tệ hơn (nhiễu) |
| 4H | +4.81 | 8.26 | **95**  | 36.84 | 1.183 | Trade ×2.4, P&L scale theo qty 10/30 |
| **D** | **+35.15** | **4.04** | **18** | **44.44** | **5.436** ⭐ | Trade ×3, **PF gấp đôi**, DD 1/3 |

> **D là điểm sáng** của V1.004: PF 5.436 vs 3.376 cũ, DD chỉ 4.04%, 18 trade thay vì 6.

### V1.B004 v1 (MA 50/150/200, Short Only)

| Profile | TF | P&L % | DD % | Trades | Win % | PF |
|---|---|---:|---:|---:|---:|---:|
| Margin 60%  | 1H | −14.64 | 21.89 | 47 | 38.30 | 0.586 |
| Margin 60%  | 4H | −9.51  | 36.04 | 46 | 36.96 | 0.882 |
| Margin 60%  | D  | −8.99  | 30.18 | 4  | 25.00 | 0.644 |
| Futures 30% | 1H | −7.35  | 11.52 | 47 | 38.30 | 0.607 |
| Futures 30% | 4H | −3.62  | 19.71 | 46 | 36.96 | 0.910 |
| Futures 30% | D  | −3.38  | 15.90 | 4  | 25.00 | 0.690 |

### V1.B.004v2 (MA 20/50/100, Short Only, qty 10%)

| TF | P&L abs (USDT) | DD % | Trades | Win % | PF | Ghi chú |
|---|---:|---:|---:|---:|---:|---|
| 1H | 0 | 0 | **0** | — | — | Không bear stack hình thành trong window 1H |
| 4H | −1,243 | 17.81 | **11** | 27.27 | 0.42 | Trade ×0 (hiếm hơn trên 4H 20/50/100 vs 50/150/200) |
| D  | −816   | 8.16  | **1**  | 0.00  | 0    | 6 năm BTC, chỉ 1 cú bear stack 20/50/100 trên D |

## 5. So sánh V1.A004 v1 vs V1.A.004v2 trên Daily (cùng qty 10% sau scale)

Để fair, scale V1.A004 Futures D xuống 1/3 (30% → 10%) ≈ +23.6% / DD 3.97% / PF 3.376 (PF không đổi).

| Metric | V1.A004 D Futures (10% scaled) | V1.A.004v2 D (10%, MA 20/50/100) | Δ |
|---|---:|---:|---|
| P&L | ~+23.6% | **+35.15%** | **+11.55pp** |
| DD | ~3.97% | 4.04% | ~bằng |
| Trades | 6 | **18** | **×3** |
| Win % | 50% | 44.44% | −5.56pp |
| **PF** | 3.376 | **5.436** | **+2.06** |

> V1.004 thắng **chắc** trên D: P&L cao hơn, PF gấp 1.6×, trade gấp 3, DD ngang.

## 6. Top 5 cấu hình tốt nhất theo PF (toàn bộ V1.000 → V1.004)

| # | Strategy | TF | qty% | P&L | DD | Trades | PF |
|--:|---|---|---:|---:|---:|---:|---:|
| 1 | **V1.A.004v2** Long | **D** | 10% | **+35.15%** | 4.04% | **18** | **5.436** ⭐ |
| 2 | V1.A004 Long Spot | D | 25% | +59.27% | 9.91% | 6 | 3.568 |
| 3 | V1.A004 Long Futures | D | 30% | +70.90% | 11.90% | 6 | 3.376 |
| 4 | V1.A004 Long Margin | D | 60% | +135.46% | 23.81% | 6 | 2.589 |
| 5 | V1.003 Futures (L+S) | D | 30% | +65.12% | 19.00% | 10 | 2.088 |

## 7. Khuyến nghị V1.005 (next iteration)

Dựa trên kết quả tích hợp V1.000 → V1.004:

1. **Adopt V1.004** (MA 20/50/100) làm baseline mới. SMA 50/150/200 quá chậm cho BTC.
2. **Bỏ B (Short)** khỏi suite mặc định — 6 năm BTC chỉ có 1 bear stack trên D với MA 20/50/100. Chỉ giữ làm tactical hedge khi macro xác nhận bear cycle.
3. **Profile mặc định**: Futures 10% (single entry) — PF 5.436, DD 4.04%, 18 trade trên D = sweet spot.
4. **Áp dụng Profile sizing**:
   - Spot: 10% per entry (max 1 entry)
   - Margin: 20% per entry (max 1 entry, 3x leverage thực)
   - Futures: 10% per entry (max 1 entry, 10x leverage thực = 100% notional)
5. **Chỉ dùng TF Daily** — TF nhỏ hơn vẫn không vượt được phí + slippage trên BTC.
6. **Cải tiến tiếp theo**:
   - Thêm filter slope SMA100 (≥ 30 bars) → loại trade ở vùng sideway
   - Trailing stop ATR-based để bảo vệ DD khi pha bear bắt đầu
   - Filter volume: chỉ enter khi volume > SMA50(volume) (xác nhận xu hướng)

## 8. Số lệnh & độ tin cậy thống kê

| Strategy | TF | Trades | Đánh giá thống kê |
|---|---|---:|---|
| V1.A004 D | D | 6 | ❌ Quá ít, có thể là may mắn |
| **V1.A.004v2 D** | D | **18** | 🟢 Đủ để đánh giá sơ bộ |
| V1.A004 4H | 4H | 40 | 🟢 Tốt |
| V1.A.004v2 4H | 4H | 95 | 🟢 Rất tốt |
| V1.A004 1H | 1H | 47 | 🟢 Tốt nhưng PF 1.0 = noise |
| V1.A.004v2 1H | 1H | 103 | 🟢 Nhiều nhưng PF 0.62 = thua phí |

> Nguyên tắc: **PF cao + ≥ 30 trades** là combo cần để tin được. **V1.A.004v2 4H** là trade-off cân bằng (95 trades, PF 1.183, DD 8.26%).

## 9. Files

- V1.000: [pine/v1/indicator_minervini_trend_template_v1.000.pine](../../pine/v1/indicator_minervini_trend_template_v1.000.pine)
- V1.001: [pine/v1/indicator_MTT_v1.001.pine](../../pine/v1/indicator_MTT_v1.001.pine)
- V1.002: [pine/v1/strategy_MTT_v1.002.pine](../../pine/v1/strategy_MTT_v1.002.pine)
- V1.003: [pine/v1/strategy_MTT_v1.003.pine](../../pine/v1/strategy_MTT_v1.003.pine)
- V1.A004 (Long): [pine/v1/strategy_MTT_v1.A004.pine](../../pine/v1/strategy_MTT_v1.A004.pine)
- V1.B004 (Short): [pine/v1/strategy_MTT_v1.B004.pine](../../pine/v1/strategy_MTT_v1.B004.pine)
- Báo cáo trước:
  - [strategy_MTT_v1.003_BTCUSDT.P_paper_trading_report.md](strategy_MTT_v1.003_BTCUSDT.P_paper_trading_report.md)
  - [strategy_MTT_v1.A004_B004_paper_trading_report.md](strategy_MTT_v1.A004_B004_paper_trading_report.md)
  - [strategy_MTT_macro_TF_full_matrix_report.md](strategy_MTT_macro_TF_full_matrix_report.md)
