# 🥊 3-way comparison: v10 baseline vs v1.3C (MTF Daily TT) vs v10-ADX

**Symbol / TF**: BYBIT:BTCUSDT.P · 60m
**Range**: Jan 1, 2025 → May 9, 2026 (16 tháng)
**Equity**: 1,000 USDT · qty 2% · commission 0.05% · slippage 2 ticks
**Ngày test**: 2026-05-09

Hai biến thể test song song để xác minh hướng đi sau khi v12B (SEPA full direct) thất bại:
1. **v1.3C MTF** — Daily TT gate via `request.security` + 1H execution (đúng chuẩn Minervini)
2. **v10-ADX** — v10 nguyên + ADX(14)≥25 + EMA200 slope dương (regime filter pragmatic)

---

## 1. Kết quả

| Strategy | Filter | P&L | % | MDD | Trades | WR | PF | Verdict |
|---|---|---|---|---|---|---|---|---|
| **v10 baseline** 🏆 | none | **+146.71** | +14.47% | 96.82 (9.17%) | **87** | **70.11%** | **1.695** | Vẫn nhất |
| **v1.3C** | Daily TT-7 + 1H entry | **−10.96** | −1.10% | 10.96 (1.10%) | 4 | 0.00% (0/4) | 0.000 | ❌ Cắt 95% entries |
| **v10-ADX** | ADX≥25 + EMA200 slope>0 | −2.22 | −0.22% | 17.71 (1.75%) | 19 | 42.11% (8/19) | 0.948 | ❌ Cắt 78% entries |

→ **Cả 2 đều thua v10**. Mọi filter regime/macro thêm vào đều phá huỷ alpha.

---

## 2. Phân tích

### 2.1. v1.3C MTF — Daily TT chặn quá ngặt

**Trade count sập 87 → 4** (95% entries bị cắt).

Daily TT-7 trên BTCUSDT.P trong 16 tháng:
- Đầu 2025: BTC near cycle high ~$108K. Daily TT pass.
- Mar-Aug 2025: Pull-back và chop $80K-$95K. Daily TT fail (sma50_d slope down, close < sma50_d).
- Sep 2025 - đầu 2026: Recovery + breakout $100K. Daily TT pass.
- Q1 2026: Pullback. Daily TT borderline.

Đoạn Daily TT pass thực ra vẫn nhiều (~50% bars), NHƯNG khi giao với 1H entry trigger (MACD cross + EMA stack 1H + RSI 50-70 + vol×1.5) thì rất hiếm — chỉ 4 lần. Tất cả 4 lệnh đều thua.

**Lý do 0/4**: 4 entries có thể rơi vào pha "Daily TT vừa pass nhưng 1H đang exhaustion" (cú breakout late-stage). Số mẫu quá ít để có ý nghĩa thống kê — nhưng đủ thấy filter chặt + 4 lệnh đều thua = Daily TT lọc ra **các entry sai lệch về timing**.

**Kết luận**: Daily TT đúng cho việc xác định regime, nhưng overlap với 1H trigger không đem lại edge.

### 2.2. v10-ADX — ADX/slope cắt cả winners

**Trade count sập 87 → 19** (78% cắt). WR 70.11% → 42.11%.

ADX≥25 yêu cầu trend strength rõ ràng. Trên BTC 1H, ADX>25 thường chỉ kéo dài vài giờ trong các pha breakout. Phần lớn time ADX 15-22 (chop hoặc trend yếu).

Slope EMA200 > 0 (qua 20 bars) chặn các pha pull-back nông trong uptrend — nhưng đó chính là nơi v10's MACD cross + EMA stack lại hay bắt đáy nhỏ.

→ Filter này loại bỏ **mean-reversion sau pull-back** — chính là edge của v10.

### 2.3. v10's "edge" thực ra là mean-reversion sau breakout, không phải trend-following

Đây là phát hiện thứ 3 đảo ngược định kiến:

- v10 LOOKS LIKE trend-following (EMA stack + MACD cross + heavy vol).
- Nhưng entry trên 1H BTC với 4 điều kiện đó thường xảy ra **sau spike**, khi giá vừa break-out và sắp pull-back. SL=2·ATR / TP=3·ATR cố định giúp bắt **mean-reversion về vùng equilibrium**.
- Add filter "trend đủ mạnh" (ADX) hoặc "trend cấu trúc dài" (Daily TT) → loại các setup này → mất edge.

**Hệ luỵ thiết kế**: nếu muốn cải thiện v10, không phải thêm filter trend, mà phải:
1. **Tối ưu mean-reversion mechanics**: xác định vùng break-out cao bất thường (vol spike + ATR spike) và TP=mean rather than fixed ATR.
2. **Hoặc đổi hoàn toàn framework**: chuyển sang volatility-breakout strategy (Bollinger band + ATR), không cần TT.

---

## 3. Bảng tổng hợp toàn bộ tests đã chạy

| Test | Direction | P&L | Trades | WR | PF | Vs v10 |
|---|---|---|---|---|---|---|
| **v10 baseline** | both | **+146.71** | 87 | 70.11% | 1.695 | — |
| v11A full (Group A) | long-only | −10.82 | 53 | 20.75% | 0.692 | thua |
| v11A-1 (TP=5 only) | both | +37.54 | 54 | 35.19% | 1.242 | thua |
| v11A-2 (cooldown=8 only) | both | +2.49 | 58 | 43.10% | 1.020 | thua |
| v11A-4 (trail x3 only) | both | −8.07 | 61 | 31.15% | 0.932 | thua |
| v11A-13 (A1+A3) | both | +44.31 | 53 | 35.85% | 1.299 | thua |
| v12B SEPA full | long | 0 | 0 | — | — | N/A |
| v12B-r3 (TT-lite + MACD) | long | −4.95 | 14 | 35.71% | 0.806 | thua |
| v12B-r4 (VCP only) | long | +1.56 | 67 | 49.25% | 1.013 | thua |
| v12B-r5 (VCP + TT-lite) | long | −6.08 | 37 | 48.65% | 0.912 | thua |
| **v13C MTF (Daily TT)** | long | **−10.96** | 4 | 0% | 0 | thua |
| **v10-ADX (ADX+slope)** | both | **−2.22** | 19 | 42.11% | 0.948 | thua |

Kỷ lục: **0/12 cải tiến vượt được v10**.

---

## 4. Kết luận lớn

Sau 12 thử nghiệm, không phương án nào (tinh chỉnh tham số, regime filter, port Minervini) vượt qua v10 baseline trên BTC 1H 16 tháng. 3 khả năng:

### 4.1. v10 đã near-optimal cho khung này
- v10's mean-reversion edge tự nhiên trên BTC 1H. Mọi filter trend cấu trúc đều loại bỏ entries có giá trị.
- Walk-forward (3/4 quý lỗ/hoà) cho thấy edge này **không robust** — phụ thuộc nặng Q4 bull. Có thể chỉ phù hợp regime cụ thể.

### 4.2. v10 overfit với khung 16 tháng cụ thể
- Full-period +146.71 chủ yếu từ Q4. Walk-forward isolated chỉ −1.74 USDT.
- Forward performance ngoài 2026-05 nhiều khả năng kém hơn.

### 4.3. BTC 1H thiếu edge cho strategy đa filter "all-must-agree"
- Số mẫu thưa (87 lệnh / 16 tháng), phương sai cao.
- Cần test trên timeframe khác (4H, Daily) hoặc symbol khác (altcoins) để xác định framework có giá trị không.

---

## 5. Đề xuất quyết định cuối

### 5.1. Dừng tinh chỉnh v10 trên 1H
Quá nhiều thử nghiệm cho thấy không có "tinh chỉnh nhỏ" nào cứu được. Cần thay đổi căn bản hoặc đổi sân chơi.

### 5.2. 3 hướng có thực chất

| # | Hướng | Effort | Lý do |
|---|---|---|---|
| **A** | Test v10 trên **4H** và **Daily** (cùng tham số) | Thấp — chỉ đổi resolution | Xem cấu trúc strategy có robust trên timeframe phù hợp với Minervini gốc không |
| **B** | Forward paper-trade v10 từ 2026-05-10 | Trung — cần monitor | Xác minh v10 có hold ngoài training window không |
| **C** | Xây dựng strategy mới framework volatility-breakout (Bollinger + ATR + vol spike) | Cao — viết lại từ đầu | Nếu v10 không có edge thật, cần thay paradigm |

### 5.3. Recommend cá nhân
Em đề xuất **A + B song song**:
- **A** (4H + Daily test) cho insight nhanh, chi phí thấp.
- **B** (paper-trade) chạy ngầm để biết v10 có hold không — không tốn capital.

Sau 4-8 tuần paper-trade nếu v10 vẫn dương → có thể trade nhỏ với risk 0.5%/lệnh. Nếu âm → confirm overfitting và chuyển C.

---

## 6. Quyết định cần từ anh

1. **Triển khai 5.3 (A + B song song)?**
2. **Hay nhảy thẳng C (volatility-breakout framework mới)?**
3. **Hay dừng test, chấp nhận v10 as-is** và focus vào risk management / portfolio sizing thay vì sửa strategy?

---

**Files**:
- [pine/v1/strategy_multi_indicator_v10.pine](../../pine/v1/strategy_multi_indicator_v10.pine) — baseline
- [pine/v1/strategy_multi_indicator_v13C.pine](../../pine/v1/strategy_multi_indicator_v13C.pine) — MTF Daily TT (mới)
- [pine/v1/strategy_multi_indicator_v10_ADX.pine](../../pine/v1/strategy_multi_indicator_v10_ADX.pine) — ADX/slope filter (mới)
- [docs/reports/MIS_v12B_SEPA_full_test.md](MIS_v12B_SEPA_full_test.md) — SEPA direct fail
- [docs/reports/MIS_v10_walkforward.md](MIS_v10_walkforward.md) — WF v10 (3/4 quý lỗ)
- [docs/reports/MIS_v10_subexperiments_AB.md](MIS_v10_subexperiments_AB.md) — Group A isolation
- [docs/reports/MIS_v10_vs_v11A_AB_comparison.md](MIS_v10_vs_v11A_AB_comparison.md) — v10 vs v11A
- [docs/reports/MIS_v1_v10_90trades_analysis.md](MIS_v1_v10_90trades_analysis.md) — phân tích 90 lệnh ban đầu
