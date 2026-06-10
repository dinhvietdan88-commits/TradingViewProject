# 📊 MIS v1 (v10) — Phân tích 90 lệnh backtest BTC 1H

**Phiên bản phân tích**: `pine/v1/strategy_multi_indicator_v10.pine` (shorttitle = "MIS v1", title = "Multi-Indicator Strategy (EMA + RSI + MACD + Volume + ATR)")
**Symbol / Timeframe**: BYBIT:BTCUSDT.P · 60m
**Giai đoạn**: ~2020-03-25 → 2026-05-09 (≈ 6 năm)
**Equity ban đầu**: 1,000 USDT · `default_qty_value = 2%` equity / lệnh · commission 0.05% · slippage 2 ticks
**Báo cáo lập ngày**: 2026-05-09

> ⚠️ **Ghi chú nguồn dữ liệu**
> Chart hiện đang load đúng strategy v10 (verify qua `chart_get_state` → study id `j4QHXF`). Tuy nhiên tại thời điểm chạy phân tích, MCP `data_get_strategy_results` / `data_get_trades` / `data_get_equity` đều trả 0 record (Strategy Tester panel chưa đồng bộ). Vì vậy:
> - **Số liệu tổng hợp** lấy từ ảnh equity curve anh gửi: cumulative P&L ≈ **+147.29 USDT**, drawdown chạm ≈ **−130.80 USDT**, ≈ **90 trade bars** trên trade-by-trade view.
> - **Phân tích entry/exit** lấy từ source Pine v10 — chính xác, không suy đoán.
> - Các phân loại theo năm / phía / exit reason ghi rõ "*(cần verify)*" — sẽ điền chính xác khi chạy lại với Strategy Tester mở.

---

## 1. Tóm tắt điều hành

| Chỉ số | Giá trị (từ ảnh) | Đánh giá |
|---|---|---|
| Tổng số lệnh | ~90 | Mật độ ~15 lệnh/năm — hợp lý cho strategy 4-filter AND |
| Net P&L cuối kỳ | **+147.29 USDT** (+14.7%) | Yếu so với B&H BTC cùng kỳ (~+1000%) và so với v1.5 (+482, +48%) |
| Max equity drawdown | **≈ −130.80 USDT** (−13.1%) | Chấp nhận được nhưng không tương xứng return |
| Giai đoạn equity âm/đi ngang | ~Q2/2022 → Q3/2025 (≈ 3.5 năm) | Khoảng "chết alpha" |
| Giai đoạn cứu cánh | Q4/2025 → Q1/2026 | Toàn bộ lợi nhuận đến từ ~3 tháng cuối |

**Kết luận chốt**: v10 là *baseline strategy* không có Stage-2 gate, không có cooldown, R:R chỉ 1.5:1. Trên BTC 1H giai đoạn 2022-Q3/2025 (sideways + nhiều mini-trend đảo chiều) thì cấu hình này tự rò rỉ alpha qua whipsaw, đặc biệt phía SHORT. Chỉ khi BTC vào pha bull mạnh nửa cuối 2025 các lệnh long mới đủ kéo equity về dương.

---

## 2. Phân tích lý do vào lệnh / thoát lệnh

### 2.1. Entry — 4 điều kiện AND mỗi nến

Tham chiếu: [pine/v1/strategy_multi_indicator_v10.pine:51-58](../../pine/v1/strategy_multi_indicator_v10.pine#L51-L58)

```
LONG  = trend_up   AND rsi_long  AND macd_cross_up   AND high_vol
SHORT = trend_down AND rsi_short AND macd_cross_down AND high_vol
```

| Filter | Tham số | Bản chất | Vai trò |
|---|---|---|---|
| `trend_up` / `trend_down` | EMA 20-50-200 xếp tầng | **Trạng thái** trend | Loại bỏ sideways có cấu trúc EMA đan |
| `rsi_long` / `rsi_short` | LONG: 50-70 · SHORT: 30-50 | Bộ lọc dải động lượng | Tránh entry quá mua/quá bán *nhưng cũng cắt mất các trend mạnh* |
| `macd_cross_up/down` | MACD(12,26,9) cắt signal | **Trigger sự kiện** rời rạc | Yếu tố chính kiểm soát số lệnh |
| `high_vol` | volume > 1.5 × SMA20(vol) | Xác nhận khối lượng | Gần đỉnh/đáy local hay cho heavy volume |

**Nhận xét quan trọng**:
- RSI dải hẹp **chống lại Minervini** — Minervini mua sức mạnh (RSI có thể > 70). v1.6 đã bỏ ceiling. Trên BTC, đoạn trend mạnh nhất thường nằm ngoài dải 50-70 → entry trượt mất pha tốt nhất.
- High-volume gần đỉnh local thường là **distribution candle** chứ không phải accumulation → bull trap.
- Không có TT gate (8 SMA criteria) → vào lệnh ở Stage 1 (tích lũy lỏng) và Stage 3 (phân phối) — hai stage rủi ro cao nhất.

### 2.2. Exit — chỉ 2 cơ chế

Tham chiếu: [pine/v1/strategy_multi_indicator_v10.pine:64-91](../../pine/v1/strategy_multi_indicator_v10.pine#L64-L91)

```
SL = entry ∓ ATR(14) × 2.0     (cố định tại bar entry)
TP = entry ± ATR(14) × 3.0     (cố định tại bar entry)
```

- `use_trail = false` mặc định → **không trailing**. Một khi đã đặt SL/TP, lệnh chạy đến khi chạm 1 trong 2.
- **R:R = 1.5 : 1** → break-even tại win-rate 40%. Với crypto whipsaw, win-rate thực tế dao động 45-55% → margin lợi nhuận quá mỏng, chi phí phí + slippage ăn mòn nhanh.
- ATR đóng băng tại bar entry: nếu volatility giãn nở sau entry, SL không nới theo → SL hit vô nghĩa khi chỉ là noise.
- **Không có cooldown**: bar kế tiếp ngay sau khi exit có thể vào lại lệnh mới (cùng phía hoặc đảo phía). Đây là cơ chế tử thần trong sideways.

### 2.3. Position sizing — 2% equity flat

`default_qty_value = 2%` của equity → lệnh nào cũng cùng % vốn, **không scale theo SL distance**. Lệnh có ATR lớn (volatile) chiếm cùng % equity nhưng risk USDT lớn hơn nhiều → 1 SL hit trong giai đoạn vol cao có thể xoá sạch lợi nhuận của 3-4 lệnh trước.

---

## 3. Vì sao chỉ ~90 lệnh trong ~6 năm

Tổng số nến BTC 1H trong giai đoạn ≈ 6 × 365 × 24 ≈ **52,560 bars**. Số lệnh ~90 = signal rate ≈ **0.17%**.

Phân rã thông qua các filter (ước lượng dựa trên BTC 1H regime 2020-2026):

| Bộ lọc | Tỷ lệ pass | Bottleneck? |
|---|---|---|
| `trend_up` ∨ `trend_down` (EMA stack) | ~35-45% bars | Vừa |
| `rsi_long` ∨ `rsi_short` (dải 50-70 hoặc 30-50) | ~40-55% bars | Vừa |
| `macd_cross_up` ∨ `macd_cross_down` | **~1-3% bars** | **Chính** — chỉ true ngay tại bar cross |
| `high_vol` (vol > 1.5×MA20) | ~15-25% bars | Vừa |

→ Filter dominant là **MACD crossover** (event-based). Mỗi cycle trend BTC thường chỉ cho 3-8 cross hợp lệ, qua 6 năm có ~30-50 cycle → ~90 entries là đúng kỳ vọng.

**Hệ luỵ**: lệnh quá thưa → mỗi lệnh phải "đắt giá". Khi R:R chỉ 1.5:1 và win-rate trung bình thì 90 mẫu là quá ít để luật số lớn cứu — phương sai cao, equity curve sẽ phụ thuộc nặng vào 5-10 lệnh tốt nhất (như đoạn cứu cánh Q4/2025).

---

## 4. Vì sao hiệu suất thấp đến ~tháng 11/2025

### 4.1. R:R 1.5:1 không đủ bù whipsaw (nguyên nhân chính #1)

- TP = 3·ATR, SL = 2·ATR. Để hoà vốn cần win-rate ≥ 40%.
- Sau commission 0.05% × 2 chiều + slippage 2 ticks, threshold thực tế **≈ 43-45% win-rate**.
- Trong sideways 2022 + Q1-Q3/2025, MACD cross liên tục cả hai phía. Mỗi pha chop cho ra 4-6 lệnh đảo chiều, win-rate có thể tụt xuống 30-40% → equity âm dần.

### 4.2. Short-side là gánh nặng lớn nhất (nguyên nhân chính #2)

- BTC có **upward drift dài hạn**. Pha downtrend cấu trúc EMA stack down ngắn (vài tuần), MACD cross down thường xảy ra **gần đáy local** → SL hit > TP hit.
- Trong giai đoạn 2022 (BTC từ 47K → 16K) các short MACD-cross trên 1H bị tích luỹ đè bởi bounce 5-10% → SL liên tục.
- Đối chiếu báo cáo MIS v1.5 (11 lệnh) — short chỉ +214 USDT trong 4 lệnh là nhờ **TT gate + freshness filter** chứ không phải logic short cốt lõi tốt. v10 không có hai filter này.

**Action item (cần verify)**: tách Long P&L vs Short P&L. Giả thuyết: Long ≈ +400-600 USDT, Short ≈ −250 đến −400 USDT, ròng +147.

### 4.3. Không có Stage 2 / Trend Template gate

- v10 entry trong Stage 1 (chop tích luỹ) và Stage 3 (phân phối đỉnh) — chính 2 stage Minervini cấm vào lệnh.
- Pha 2022 + đầu 2023: BTC dưới SMA200, EMA20>50>200 thi thoảng xảy ra trên 1H trong các bounce ngắn → fake long entries.

### 4.4. Cooldown = 0 → re-entry whipsaw

- Sideways 2022/2025: 1 vùng giá có thể tạo 4-5 cross MACD trong 1-2 ngày. v10 vào lại ngay bar kế.
- v1.5 thêm `cooldown_bars = 3` (~3h sau exit không vào lệnh) đã đủ chặn phần lớn whipsaw chuỗi này.

### 4.5. SL/TP đông cứng theo ATR tại bar entry

- ATR co (vol thấp) → TP=3·ATR rất gần → "skim TP" rồi bỏ lỡ trend kéo dài.
- ATR phình (vol cao) → SL=2·ATR rộng → 1 SL hit ăn 2-3 lần lợi nhuận trung bình.
- Không có hard cap % (v1.5 thêm `hard_sl_pct=8%`).

### 4.6. Volume filter không đủ tinh

- `high_vol = volume > 1.5 × MA20` true ở cả breakout thật lẫn capitulation/blow-off.
- Thiếu **VCP dry-up gate**: không yêu cầu một bar volume thấp gần đó (institutional accumulation signal) — v1.5/v1.6 đã thêm.

### 4.7. Pha cứu cánh Q4/2025 — Q1/2026

- BTC sau halving + breakout > 90K (theo trade #11 trong v1.5: long từ 85,469 → 70,115 nhưng đó là short v1.5; còn v10 với cooldown=0 và allow_short có thể đã long-short hỗn hợp).
- Trên image, đường cumulative P&L gập đầu tăng từ ~ giữa-cuối 2025, kết thúc +147 USDT. Ước tính ~50-70% lợi nhuận cuối kỳ đến từ 3-5 lệnh long trong giai đoạn này.

---

## 5. Phân loại 90 lệnh (cần verify khi MCP đọc được trade list)

> Bảng dưới là **template** sẽ điền sau khi `data_get_trades` trả data. Hiện tại em điền ước lượng dựa trên hành vi strategy + image equity curve.

### 5.1. Theo năm

| Năm | Số lệnh (ước) | P&L USDT (ước) | Regime BTC | Ghi chú |
|---|---|---|---|---|
| 2020 (từ Mar) | ~10-15 | ~0 đến −20 | Bull → Mar crash → recover | Mới khởi tạo, ít data EMA200 |
| 2021 | ~15-20 | +30 đến +60 | Bull mạnh | Nhiều long thắng |
| 2022 | ~20-25 | **−80 đến −130** | Bear + chop | Chính nguồn drawdown |
| 2023 | ~10-15 | +20 đến +50 | Range → mid-bull | Trung tính |
| 2024 | ~10-12 | +50 đến +100 | Bull (post-halving) | Long thắng tốt |
| 2025 | ~8-10 | **+100 đến +180** | Chop → Q4 bull | Cứu cánh |
| 2026 (đến May) | ~3-5 | +20 đến +50 | Pull-back | Open trades có thể MTM |

### 5.2. Theo phía (giả thuyết kiểm chứng)

| Phía | Số lệnh | P&L | Win-rate | Ghi chú |
|---|---|---|---|---|
| LONG | ~50-55 | **+400 đến +550** | ~55-60% | Driver chính |
| SHORT | ~35-40 | **−250 đến −400** | ~35-45% | Rò rỉ alpha |

### 5.3. Theo lý do exit

| Lý do | % lệnh | P&L trung bình |
|---|---|---|
| Hit TP (3·ATR) | ~40-50% | +18 đến +25 USDT |
| Hit SL (2·ATR) | ~50-55% | −12 đến −18 USDT |
| Open / pending (cuối kỳ) | 0-2 | — |

→ **Nếu win-rate ~45% × R:R 1.5 = expectancy ≈ −0.2 R/lệnh** — phù hợp với cumulative P&L èo uột cho đến khi vài lệnh fat-tail cuối 2025 cứu lại.

---

## 6. So sánh v10 vs v1.5 vs v1.6

| Chiều | v10 (đang phân tích) | v1.5 | v1.6 |
|---|---|---|---|
| Entry trigger | MACD cross | MACD cross | **VCP pivot breakout** |
| TT gate (8 SMA) | ❌ | ✅ | ✅ |
| Stage 2 freshness | ❌ | ❌ | ✅ (`fresh_bars=60`) |
| RSI ceiling | 70 (long) | 70 | **bỏ ceiling** |
| VCP dry-up | ❌ | ✅ (lookback 10) | ✅ (lookback 20) |
| ATR SL mul | 2.0 | 2.0 | 2.0 |
| ATR TP mul | **3.0** | 5.0 | **8.0** |
| R:R | 1.5:1 | 2.5:1 | **4:1** |
| Hard SL cap | ❌ | 8% | 8% |
| Cooldown | 0 bar | 3 bars | 3 bars |
| ATR trailing | ❌ | ❌ | ✅ Chandelier×3 |
| Position sizing | 2% equity flat | **risk-based 1%** | risk-based 1% |
| Số lệnh (cùng symbol/TF, ~6 năm) | **~90** | 11 | (chưa có report) |
| Net P&L | **+147 USDT (+14.7%)** | +482 (+48.2%) | — |
| Win-rate | ước ~45-50% | **81.8%** | — |
| Max DD | ~13% | 16.2% | — |

→ v1.5 đánh đổi tần suất (90→11) lấy chất lượng (win-rate gấp đôi, P&L gấp 3+). Đây là **trade-off cốt lõi của Minervini SEPA**: ít entry hơn, nhưng mỗi entry là Stage 2 fresh.

---

## 7. Đề xuất tinh chỉnh tham số

Chia 2 nhóm. Mỗi đề xuất ghi rõ trade-off.

### Nhóm A — Tinh chỉnh nhẹ (giữ kiến trúc v10)

Mục tiêu: cải thiện expectancy mà không thay đổi triết lý "MACD cross + EMA stack".

| # | Input | Hiện tại | Đề xuất | Trade-off |
|---|---|---|---|---|
| A1 | `atr_tp_mul` | 3.0 | **5.0** | R:R lên 2.5:1 → break-even win-rate giảm xuống 28%. Cái giá: bỏ lỡ TP nhanh trong volatile pump → 1 phần trade chuyển từ TP sang SL khi giá đảo trước khi chạm 5·ATR. Net expectancy thường tăng. |
| A2 | `atr_sl_mul` | 2.0 | **1.5** | Thắt SL → loss size nhỏ hơn 25%. Cái giá: noise dễ trigger hơn → win-rate có thể giảm 3-5pp. Phối hợp với A1 → R:R lên 3.3:1. |
| A3 | thêm `cooldown_bars` | 0 | **6-8** | Chặn re-entry whipsaw trong sideways. Cái giá: bỏ lỡ vài entry ngay sau swing (hiếm). |
| A4 | `use_trail` | false | **true** + thêm Chandelier ATR×3 ([port từ v1.6](../../pine/v1/strategy_multi_indicator_v16.pine#L196-L199)) | Giữ profit khi trend mở rộng quá TP. Cái giá: code phức tạp hơn, exit có thể trước TP final khi pull-back nhẹ. |
| A5 | `allow_short` | true | **false** ban đầu | Loại bỏ nguồn rò rỉ alpha lớn nhất. Cái giá: mất ~35% lệnh, chỉ có long. |
| A6 | RSI long ceiling | 70 | **bỏ ceiling** (chỉ giữ floor 50) | Bắt được trend mạnh. Cái giá: 1 phần entry sát đỉnh local. |

**Backtest A (tổng hợp A1+A2+A3+A4+A5+A6) trên cùng symbol/TF**: ưu tiên kiểm chứng. Giả thuyết: net P&L tăng từ +147 → +300-400 USDT, số lệnh giảm từ 90 → ~55-65 (do bỏ short).

### Nhóm B — Upgrade lên kiến trúc v1.5/v1.6

Nếu nhóm A không đạt mục tiêu, đề xuất chuyển hẳn sang v1.5 hoặc v1.6:

| # | Phần upgrade | Mục đích | Reference |
|---|---|---|---|
| B1 | Trend Template gate (8 SMA criteria) | Chỉ vào Stage 2 confirmed | [v15:106-115](../../pine/v1/strategy_multi_indicator_v15.pine#L106-L115) |
| B2 | Stage 2 freshness (TT FAIL→PASS trong N bars) | Bắt đoạn "first leg" của trend | [v16:118-126](../../pine/v1/strategy_multi_indicator_v16.pine#L118-L126) |
| B3 | VCP pivot breakout entry | Thay MACD cross | [v16:128-142](../../pine/v1/strategy_multi_indicator_v16.pine#L128-L142) |
| B4 | Hard SL cap 8% | Safety khi ATR phình | [v15](../../pine/v1/strategy_multi_indicator_v15.pine) |
| B5 | Risk-based position sizing | Chuẩn Minervini, scale theo SL | [v15](../../pine/v1/strategy_multi_indicator_v15.pine) |

**Ưu tiên thực tế**: nhóm A trước (chi phí thấp, kiểm chứng nhanh). Nếu kết quả expectancy vẫn âm trong sideways → B.

---

## 8. Quy trình verify số liệu (khi muốn làm chặt)

1. Mở Strategy Tester panel (TradingView Desktop) cho chart hiện tại.
2. Chạy lại các MCP:
   - `mcp__tradingview__data_get_strategy_results` → fill các metric chính (sharpe, sortino, profit factor, gross P/L, MDD, expected payoff).
   - `mcp__tradingview__data_get_trades` (max_trades=100) → trade list raw.
   - `mcp__tradingview__data_get_equity` → equity series để xác nhận điểm gãy 2022 và rally Q4/2025.
3. Replace bảng Phần 5 bằng số liệu thật.
4. Capture 2-3 screenshot lệnh điển hình bằng `mcp__tradingview__capture_screenshot` (region "strategy_tester") đính kèm Phần 4.

---

## 9. Quyết định cần từ anh

1. **Có muốn em implement nhóm A** (fork file mới `pine/v1/strategy_multi_indicator_v10_tuned.pine`, KHÔNG đè v10) và backtest đối chứng không?
2. **Có cần em tự mở Strategy Tester** rồi pull số liệu thật để điền chính xác Phần 5 không? (Cần anh duyệt MCP write actions cho `ui_open_panel` / `pine_smart_compile`.)
3. **Phạm vi short**: tắt hoàn toàn (A5) hay thêm filter `close < SMA200` rồi giữ?

---

**Files liên quan**:
- [pine/v1/strategy_multi_indicator_v10.pine](../../pine/v1/strategy_multi_indicator_v10.pine) — source v10 (read-only)
- [pine/v1/strategy_multi_indicator_v15.pine](../../pine/v1/strategy_multi_indicator_v15.pine) — reference v1.5
- [pine/v1/strategy_multi_indicator_v16.pine](../../pine/v1/strategy_multi_indicator_v16.pine) — reference v1.6
- [docs/reports/backtest_report_MIS_v1_2025_2026.md](backtest_report_MIS_v1_2025_2026.md) — báo cáo cũ (thực ra là v1.5)
- [docs/reports/MIS_v1_COMPLETE_BACKTEST_REPORT.md](MIS_v1_COMPLETE_BACKTEST_REPORT.md) — báo cáo cũ 1h vs 4h (cũng v1.5)
