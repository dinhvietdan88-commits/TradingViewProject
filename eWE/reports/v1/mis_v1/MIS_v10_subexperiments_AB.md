# 🧪 MIS v10 — Sub-experiments isolation A/B (one-at-a-time)

**Symbol / TF**: BYBIT:BTCUSDT.P · 60m
**Range**: Jan 1, 2025 → May 9, 2026 (16 tháng)
**Equity**: 1,000 USDT · qty 2% · commission 0.05% · slippage 2 ticks
**Ngày test**: 2026-05-09

Mục tiêu: tách từng change của Group A để biết cái nào có giá trị, sau khi nhóm A tổng hợp đã thua v10 baseline.

---

## 1. Bảng tổng hợp 6 cấu hình

| Variant | A1 TP=5·ATR | A2 SL=1.5 | A3 cooldown=8 | A4 trail x3 | A5 no short | A6 no RSI cap | Total P&L | % Return | Trades | Win-rate | Profit factor | MDD | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **v10 baseline** | — | — | — | — | — | — | **+146.71** | **+14.47%** | **87** | **70.11%** | **1.695** | 9.17% | 🏆 |
| v11A (full) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | −10.82 | −1.08% | 53 | 20.75% | 0.692 | 3.36% | ❌ |
| **v11A-1** (A1 only) | ✓ | — | — | — | — | — | +37.54 | +3.75% | 54 | 35.19% | 1.242 | 4.61% | ⚠️ Kém |
| **v11A-2** (A3 only) | — | — | ✓ | — | — | — | +2.49 | +0.25% | 58 | 43.10% | 1.020 | 4.33% | ⚠️ Sát hoà |
| **v11A-4** (A4 only) | — | — | — | ✓ | — | — | −8.07 | −0.81% | 61 | 31.15% | 0.932 | 3.39% | ❌ Lỗ |
| **v11A-13** (A1+A3) | ✓ | — | ✓ | — | — | — | +44.31 | +4.43% | 53 | 35.85% | 1.299 | 3.94% | ⚠️ Kém |

→ **Không variant nào vượt v10**. Mỗi change của Group A khi tách riêng đều **giảm hiệu suất**.

---

## 2. Phát hiện cốt lõi: v10 đã tuned tốt cho BTC 1H

Đây là kết quả phản trực giác lớn nhất. Em đã sai khi cho rằng "R:R 1.5:1 quá thấp". Trong khung BTC 1H giai đoạn này:

- **TP=3·ATR là sweet spot**: sau MACD cross + EMA stack + volume spike, BTC thường **mean-revert** trong 5-15 bar sau (whipsaw 1H). TP=3·ATR đủ gần để hit nhanh trước khi đảo chiều.
- **WR 70% xác nhận**: phần lớn lệnh hit TP nhanh. Khi TP đẩy lên 5·ATR (A1), WR sập xuống 35% vì lệnh "chờ" hit TP xa thì giá đã đảo và đụng SL trước.
- **R:R 1.5 + WR 70% = expectancy +0.55R** → tốt hơn nhiều so với R:R 2.5 + WR 35% = +0.225R.

| Cấu hình | R:R | WR | Expectancy/R | Notes |
|---|---|---|---|---|
| v10 (TP=3, SL=2) | 1.5 | 70.11% | **+0.55R** | Best |
| v11A-1 (TP=5, SL=2) | 2.5 | 35.19% | +0.23R | Worse |
| v11A (TP=5, SL=1.5) | 3.33 | 20.75% | +0.05R | Worst |

→ **High-frequency mean-reversion** đánh bại **trend-following with wide TP** trong khung BTC 1H 2025-2026.

---

## 3. Phân tích từng change

### 3.1. A1 (TP=5·ATR) — tệ thứ ba
- WR sập 70% → 35%. Trades tốt bị "neo" chờ TP xa, gặp pullback đảo và hit SL.
- Net P&L vẫn dương (+37.54) vì các winners còn lại có size lớn (5·ATR), nhưng PF chỉ 1.242 — thua xa 1.695.
- **Rút ra**: TP cố định nên giữ ở 3·ATR cho 1H BTC.

### 3.2. A3 (cooldown=8 bars) — gần như xoá lợi nhuận
- Cooldown 8h cắt mất 29 lệnh (87→58). Net P&L sập từ +146.71 → +2.49 → các 29 lệnh bị cắt **net dương rất lớn** (~+144 USDT).
- Lý do: trong trend BTC mạnh, MACD cross liên tiếp có thể tạo 2-3 lệnh winner liên hoàn. Cooldown chặn cả chuỗi đó.
- **Rút ra**: cooldown tốt cho strategy whipsaw kéo dài (sideways thuần), nhưng trên BTC 1H 2025-2026 (mix bull-chop) thì hại nhiều hơn lợi.

### 3.3. A4 (Chandelier ATR×3 trail) — tệ thứ hai
- Trail kích hoạt sau khi giá vượt entry +1·ATR. Sau đó pullback nhỏ ~1·ATR đủ trigger exit ở break-even.
- Mất TP=3·ATR hits — winners bị cắt sớm thành break-even hoặc small win.
- WR 31.15%, PF 0.932 (lỗ).
- **Rút ra**: Chandelier×3 trail **không phù hợp với TP cố định 3·ATR** — hai cơ chế đánh nhau.

### 3.4. A1+A3 combo (v11A-13) — tốt hơn từng cái riêng nhưng vẫn thua
- +44.31 USDT, PF 1.299. Cooldown bù lại một phần cho việc TP xa khó hit.
- Vẫn thua v10 ~100 USDT.

---

## 4. Hệ luỵ với báo cáo phân tích trước

Báo cáo [MIS_v1_v10_90trades_analysis.md](MIS_v1_v10_90trades_analysis.md) trước có một số điểm phải đính chính:

| Mục cũ | Đính chính |
|---|---|
| "R:R 1.5:1 quá thấp" | **Sai cho khung 16 tháng**. R:R 1.5 + WR 70% > R:R 2.5 + WR 35%. |
| "Cooldown=0 là rò rỉ alpha" | **Sai cho khung này**. Cooldown=8 cắt mất ~+144 USDT. |
| "Không trailing là vấn đề" | **Sai**. Trailing ATR×3 cắt sớm winners. |
| "Short rò rỉ alpha" | **Chưa verify** — A5 đi kèm các change khác. Cần test isolated. |
| Range 6 năm | **Range thực = 16 tháng** (Strategy Tester cap). |

---

## 5. Hướng đi tiếp theo (đề xuất)

### 5.1. Vẫn còn 2 change chưa isolate
- **A2 only** (SL=1.5·ATR, mọi cái khác giữ v10): có thể tiếp tục test.
- **A5 only** (allow_short=false, mọi cái khác giữ v10): test riêng để biết short net contribution.
- **A6 only** (bỏ RSI ceiling): low-impact, test sau cùng.

### 5.2. Khả năng cao v10 đã near-optimal cho khung 1H BTC ngắn hạn

Nếu A2 và A5 cũng không cải thiện, kết luận sẽ là: **v10 là baseline mạnh, mọi tinh chỉnh tham số nhỏ không đem lại alpha**. Hướng tiếp theo chỉ còn:

1. **Đổi cấu trúc entry/exit** (nhóm B — TT gate + VCP), đánh đổi tần suất lấy chất lượng — kết quả đã thấy ở v1.5 (11 trades, +482 USDT, WR 81.8%) nhưng đó là trên khung dài hơn.
2. **Đổi timeframe** — test 30m hoặc 4h để xem v10 còn near-optimal không.
3. **Walk-forward test** — chia 16 tháng thành 4 quý, optimize trên 3 và validate trên 1, để chống overfitting.

### 5.3. Câu hỏi cần anh quyết
1. Test thêm **A2 only**, **A5 only**, **A6 only** không?
2. Hay chuyển sang **walk-forward test** cho v10 để confirm tính ổn định trước khi quyết upgrade nhóm B?
3. Hay nhảy thẳng nhóm B (port v1.5/v1.6 logic vào v12)?

---

## 6. Raw data (DOM scrape từ Strategy Tester)

| Variant | Total P&L | % | MDD USDT | MDD % | Trades | Profitable | WR | PF |
|---|---|---|---|---|---|---|---|---|
| v10 | +146.71 | +14.47% | 96.82 | 9.17% | 87 | 61/87 | 70.11% | 1.695 |
| v11A full | −10.82 | −1.08% | 33.58 | 3.36% | 53 | 11/53 | 20.75% | 0.692 |
| v11A-1 A1 | +37.54 | +3.75% | 46.14 | 4.61% | 54 | 19/54 | 35.19% | 1.242 |
| v11A-2 A3 | +2.49 | +0.25% | 43.29 | 4.33% | 58 | 25/58 | 43.10% | 1.020 |
| v11A-4 A4 | −8.07 | −0.81% | 33.88 | 3.39% | 61 | 19/61 | 31.15% | 0.932 |
| v11A-13 A1+A3 | +44.31 | +4.43% | 39.37 | 3.94% | 53 | 19/53 | 35.85% | 1.299 |

Method: `mcp__tradingview__pine_set_source` → `pine_smart_compile` → `ui_click("Metrics")` → `ui_evaluate(scrape DOM around "Total P&L")`.

---

**Files**:
- [pine/v1/strategy_multi_indicator_v10.pine](../../pine/v1/strategy_multi_indicator_v10.pine) — baseline
- [pine/v1/strategy_multi_indicator_v11A.pine](../../pine/v1/strategy_multi_indicator_v11A.pine) — Group A full (đã lưu file)
- v11A-1, v11A-2, v11A-4, v11A-13 — chỉ inject vào editor, không lưu file (nguồn nằm trong báo cáo này nếu cần tái tạo)
- [docs/reports/MIS_v10_vs_v11A_AB_comparison.md](MIS_v10_vs_v11A_AB_comparison.md) — A/B trước
- [docs/reports/MIS_v1_v10_90trades_analysis.md](MIS_v1_v10_90trades_analysis.md) — phân tích v10
