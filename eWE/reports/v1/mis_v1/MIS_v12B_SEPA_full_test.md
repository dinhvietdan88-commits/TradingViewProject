# 🧬 MIS v1.2B — Minervini SEPA full port test (TT gate + VCP + risk-based sizing)

**Symbol / TF**: BYBIT:BTCUSDT.P · 60m
**Range**: Jan 1, 2025 → May 9, 2026 (16 tháng — Strategy Tester default)
**Equity**: 1,000 USDT
**Ngày test**: 2026-05-09

Mục tiêu: port toàn bộ logic Minervini SEPA (Trend Template 8-criteria + Stage 2 freshness + VCP pivot breakout + Risk-based sizing + Hard SL cap + Chandelier trail + cooldown) sang BTC 1H, kỳ vọng vượt v10 baseline về win-rate và robustness.

**File source**: [pine/v1/strategy_multi_indicator_v12B.pine](../../pine/v1/strategy_multi_indicator_v12B.pine)

---

## 1. Kết quả: hoàn toàn ngoài kỳ vọng — không variant nào vượt v10

| Variant | TT gate | VCP entry | Stage 2 fresh | Total P&L | Trades | WR | PF | Verdict |
|---|---|---|---|---|---|---|---|---|
| **v10 baseline** (long+short, no gates) | ❌ | ❌ MACD | ❌ | **+146.71** | **87** | **70.11%** | **1.695** | 🏆 |
| v10-long-only test | ❌ | ❌ MACD | ❌ | +6.49 | 22 | 45.45% | 1.176 | Base mới |
| **v1.2B full** (TT-8 + VCP + fresh + sizing + trail) | TT-8 | VCP | ✓ | **0** | **0** | — | — | ❌ Quá ngặt |
| v1.2B-r1 (no freshness) | TT-8 | VCP | ❌ | 0 | 0 | — | — | ❌ |
| v1.2B-r2 (TT-7, MACD entry, no VCP) | TT-7 | ❌ MACD | ❌ | 0 | 0 | — | — | ❌ |
| v1.2B-r3 (TT-lite tt1-5, MACD entry) | TT-5 | ❌ MACD | ❌ | −4.95 | 14 | 35.71% | 0.806 | ❌ Lỗ |
| v1.2B-r4 (VCP only, no TT) | ❌ | VCP | ❌ | +1.56 | 67 | 49.25% | 1.013 | ⚠️ Hoà |
| v1.2B-r5 (VCP + TT-lite) | TT-5 | VCP | ❌ | −6.08 | 37 | 48.65% | 0.912 | ❌ Lỗ |

→ **Không variant SEPA nào sinh lãi đáng kể**. Tất cả đều thua v10-long-only (+6.49 USDT) và xa cách v10 full (+146.71).

---

## 2. Phát hiện cốt lõi: SEPA timeframe-mismatch với BTC 1H

### 2.1. TT gate (Trend Template 8 criteria) trên 1H = filter chết

- TT thiết kế cho **DAILY stocks** với SMA 50/150/200 tính bằng ngày, low52/high52 tính bằng 52 tuần.
- Khi bê nguyên sang 1H BTC:
  - SMA200 = 200 giờ ≈ 8 ngày (không phải 200 ngày)
  - low52/high52 = 250 bars ≈ 10 ngày (không phải 52 tuần)
  - tt6 (close ≥ 10-day-low × 1.30) và tt7 (close ≥ 10-day-high × 0.75) trở thành điều kiện **micro-scope** không liên quan đến trend cấu trúc dài.
  - tt3 (sma200 sloping up over 20 bars = 20 giờ) thường flat/đảo trong 2025 sideways → fail liên tục.
- Kết quả: **0 entries** với TT-8 hoặc TT-7. Chỉ TT-lite (5 criteria, bỏ tt6/tt7) cho ra ~14 trades — nhưng vẫn lỗ vì các bar còn lại đều fail tt3.

### 2.2. VCP detection trên 1H trigger quá thường xuyên

- VCP gốc thiết kế cho daily charts: vol dry-up + tight range trong 4-6 tuần là institutional accumulation.
- Trên 1H: vol_dry (vol < 60% × MA50) + tight (H-L < 70% × ATR) xảy ra ~5-10% bars (~80-160 bars/tuần).
- Pivot price reset liên tục → "breakout" thực ra chỉ là noise.
- Result: VCP entry tạo nhiều trade hơn MACD (67 vs 22) nhưng PF 1.013 = không edge.

### 2.3. Stage 2 freshness lại càng siết cứng

- Khi TT pass thường xuyên (BTC bull 2025 H2/2026 Q1), `bars_since_tt_pass` reset mỗi lần TT fail/pass.
- Trên 1H, TT trôi PASS-FAIL liên tục → freshness window 60 bars có khi không bao giờ trùng với entry trigger.
- Combined với TT gate đã 0 trade → freshness vô tác dụng.

### 2.4. Risk-based sizing đúng đắn nhưng không cứu được

- `qty = (equity × 1%) / (ATR × 2)` — Minervini standard.
- Đẹp về lý thuyết, nhưng nếu strategy không có alpha thì sizing chuẩn cũng không đảo ngược lỗ.

---

## 3. So sánh trực tiếp với v10

| Kích thước | v10 (no SEPA) | v1.2B variants tốt nhất | Δ |
|---|---|---|---|
| P&L | **+146.71** | +6.49 (long-only, no TT) → +1.56 (VCP only) | ~−145 |
| Trades | 87 (long+short) | 14-67 | ít hơn nhiều |
| WR | 70.11% | 35-49% | thấp hơn ~25 pp |
| PF | 1.695 | 0.81-1.18 | thấp hơn |

→ **Mọi cải thiện cấu trúc Minervini đều phá huỷ alpha gốc của v10.**

---

## 4. Nguyên nhân sâu xa: SEPA không phải framework cho intraday crypto

Minervini SEPA designed for:
- **Tài sản**: cổ phiếu Mỹ với fundamental momentum (earnings, RS vs SPY, IBD ratings).
- **Timeframe**: daily charts, hold weeks-to-months.
- **Filter**: trend template trên weekly/daily, VCP nhận diện 4-8 tuần consolidation.
- **Edge**: bắt đầu Stage 2 trước institutional rotation in.

BTC 1H thiếu cả 4:
- Không có RS benchmark có ý nghĩa (BTC vs BTC = self).
- Không có "earnings catalyst".
- Trend template trên 1H = nhiễu cấu trúc, không phản ánh regime dài hạn.
- VCP nhận diện trên 1H = noise pattern, không phải institutional accumulation.

→ Bê nguyên SEPA logic sang 1H crypto = **anti-alpha**. Strategy tự loại bỏ những setup mà v10 đơn giản đang khai thác (MACD cross trong EMA stack uptrend + volume spike — đây là **mean-reversion sau breakout** trên 1H, một edge crypto-specific).

---

## 5. 3 hướng đi khả thi

### 5.1. Áp Minervini ĐÚNG cách: dùng Daily chart cho regime, 1H cho execution
- Compute TT trên D/W bằng `request.security(syminfo.tickerid, "D", ...)` từ chart 1H.
- Chỉ enter khi TT-D pass + 1H entry trigger (MACD/breakout) khớp.
- Trade ít hơn nhiều, nhưng edge giữ được ở mức macro.

### 5.2. Dropp Minervini, giữ v10 + thêm regime filter crypto-specific
- ADX > 25 trên 1H để chặn chop (đề xuất 6.2 từ báo cáo walk-forward trước).
- Hoặc EMA200 slope > 0 trong N bars liên tiếp.
- Hoặc daily ATR percentile để chặn high-volatility chop.

### 5.3. Đổi timeframe lên 4H hoặc Daily
- 4H: 6× ít bars → ít whipsaw, các filter Minervini có ý nghĩa hơn.
- Daily: chuẩn Minervini, nhưng số mẫu BTC 16 tháng = ~485 bars → quá ít cho crypto trade.

---

## 6. Quyết định cần từ anh

1. **Triển khai 5.1 (Daily TT gate qua `request.security`, 1H execution)** — port Minervini đúng cách qua MTF? Em fork `v13C.pine` với MTF logic.
2. **Hay 5.2 (giữ v10 + ADX/slope filter)** — pragmatic, test xem có cứu Q1/Q2 không?
3. **Hay 5.3 (test ngay trên 4H)** — đơn giản, chỉ đổi timeframe?
4. **Hay dừng cải thiện strategy v10** vì WF cho thấy nó đã near-optimal cho 1H BTC (mean-reversion edge tự nhiên), tập trung vào risk management / position sizing tốt hơn?

---

## 7. Raw data

| Variant | Logic | P&L | Trades | WR | PF | MDD |
|---|---|---|---|---|---|---|
| v10 full (long+short, MACD) | EMA stack + RSI 50-70 + MACD cross + vol×1.5 | +146.71 | 87 | 70.11% | 1.695 | 9.17% |
| v10-long-only TEST | Same, allow_short=false | +6.49 | 22 | 45.45% | 1.176 | 1.67% |
| v1.2B full | + TT-8 + VCP + fresh + risk sizing + trail + cooldown | 0 | 0 | — | — | 0 |
| v1.2B-r1 | -fresh | 0 | 0 | — | — | 0 |
| v1.2B-r2 | TT-7 + MACD entry | 0 | 0 | — | — | 0 |
| v1.2B-r3 | TT-lite (tt1-5) + MACD | −4.95 | 14 | 35.71% | 0.806 | 1.59% |
| v1.2B-r4 | VCP entry only, no TT | +1.56 | 67 | 49.25% | 1.013 | 2.52% |
| v1.2B-r5 | VCP + TT-lite | −6.08 | 37 | 48.65% | 0.912 | 1.79% |

Source variants r1-r5 được inject qua MCP, KHÔNG lưu file (chỉ dùng debug). File chính `v12B.pine` đã lưu vẫn giữ logic full SEPA — anh có thể quyết giữ làm reference hoặc xoá.

---

**Files**:
- [pine/v1/strategy_multi_indicator_v12B.pine](../../pine/v1/strategy_multi_indicator_v12B.pine) — full SEPA port (ĐÃ LƯU, kết quả 0 trades)
- [pine/v1/strategy_multi_indicator_v10.pine](../../pine/v1/strategy_multi_indicator_v10.pine) — baseline
- [pine/v1/strategy_multi_indicator_v15.pine](../../pine/v1/strategy_multi_indicator_v15.pine), [v16](../../pine/v1/strategy_multi_indicator_v16.pine) — reference SEPA logic
- [docs/reports/MIS_v10_walkforward.md](MIS_v10_walkforward.md) — WF v10
- [docs/reports/MIS_v10_subexperiments_AB.md](MIS_v10_subexperiments_AB.md) — sub-experiments Group A
- [docs/reports/MIS_v10_vs_v11A_AB_comparison.md](MIS_v10_vs_v11A_AB_comparison.md) — A/B v10 vs v11A
- [docs/reports/MIS_v1_v10_90trades_analysis.md](MIS_v1_v10_90trades_analysis.md) — phân tích v10 ban đầu
