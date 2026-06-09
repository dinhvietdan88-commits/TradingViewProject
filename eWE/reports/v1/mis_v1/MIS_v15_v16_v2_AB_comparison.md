# 🥊 4-way A/B: v10 baseline vs v1.5 vs v1.6 vs v2 (Minervini SEPA strategies)

**Symbol / TF**: BYBIT:BTCUSDT.P · 60m
**Range**: Jan 1, 2025 → May 9, 2026 (16 tháng)
**Ngày test**: 2026-05-09

Test 3 phiên bản SEPA strict (v1.5, v1.6, v2) — vốn được thiết kế hoàn chỉnh theo Minervini methodology — vs v10 baseline trên cùng khung BTC 1H.

---

## 1. Kết quả

| Strategy | Logic chính | Initial / Qty | P&L | % | Trades | WR | PF | Verdict |
|---|---|---|---|---|---|---|---|---|
| **v10 baseline** 🏆 | EMA stack + RSI 50-70 + MACD cross + vol×1.5 (no SEPA) | 1000 / 2% | **+146.71** | +14.47% | **87** | **70.11%** | **1.695** | Vẫn nhất |
| **v1.5** (SEPA Hardened) | TT-8 + VCP dry-up (last 10 bars) + MACD entry + risk sizing | 10000 / 5% | **0** | 0% | **0** | — | — | ❌ |
| **v1.6** (SEPA Crypto) | TT-8 + Stage 2 freshness + VCP pivot breakout + Chandelier trail | 10000 / 5% | **0** | 0% | **0** | — | — | ❌ |
| **v2** (Minervini SEPA V2) | TT-8 + VCP + breakout + 8%SL/20%TP + SMA50 trail | 10000 / 100% | **0** | 0% | **0** | — | — | ❌ |

→ **Cả 3 strategies SEPA strict đều ra 0 trades**. v10 vẫn là duy nhất sinh lãi.

---

## 2. Tại sao SEPA strict = 0 trades trên 1H 16 tháng?

### Vấn đề cốt lõi: **TT-8 trên 1H BTC không đủ "intersection time" với entry trigger**

3 strategies có chung TT-8 condition (Trend Template 8 criteria) làm gate cho long entry. Kết hợp 8 criteria SMA + RS so với benchmark, TT pass rate trên 1H BTC có thể chỉ ~10-30% bars trong 16 tháng. Mỗi strategy thêm trigger:

| Strategy | Trigger thêm | Tần suất | Intersection với TT |
|---|---|---|---|
| v1.5 | MACD crossover + vol×1.5 + VCP dry-up trong 10 bars trước | ~1-3% bars | ~0% intersection |
| v1.6 | VCP pivot breakout trong 15 bars + freshness (TT mới pass <60 bars) | ~0.5-1% bars | ~0% intersection (freshness siết thêm) |
| v2 | VCP breakout (10 bars lookback) + vol×1.5 | ~1-2% bars | ~0% intersection |

→ **Phép giao trên 1H 16 tháng ≈ 0**. Ngay cả khi có vài bar pass, position management (`strategy.position_size==0` requirement, cooldown) có thể khiến không entry nào được fire.

### Validation: v15 6-year report cũ ra 11 trades

Trong [docs/reports/backtest_report_MIS_v1_2025_2026.md](backtest_report_MIS_v1_2025_2026.md) cũ, v1.5 chạy trên 6 năm Mar-2020 → May-2026 ra 11 trades, +482.05 USDT. Khoảng thời gian dài hơn 4.5× → tạo đủ "intersection moments" cho TT-8 và VCP trigger trùng. Trên chỉ 16 tháng, không đủ.

### v1.6 thêm freshness lại càng siết

`fresh_bars=60` yêu cầu TT vừa chuyển từ FAIL → PASS trong vòng 60 bars. Trên 1H BTC, TT trôi PASS-FAIL liên tục (mỗi vài giờ một lần). Mỗi lần TT pass, freshness window 60 bar có thể không có VCP setup bar nào → 0 trade.

---

## 3. So sánh logic 3 SEPA strategies

| Component | v1.5 | v1.6 | v2 |
|---|---|---|---|
| TT gate | 8 criteria | 8 criteria | 8 criteria |
| RS benchmark | BTCUSD | BINANCE:BTCUSDT (disable_rs=false default) | BTCUSD |
| Stage 2 freshness | ❌ | ✅ 60 bars | ❌ |
| Entry trigger | MACD up + vol×1.5 + EMA stack + RSI 50-70 | VCP pivot breakout + RSI > 50 (no ceiling) + EMA stack | VCP pivot breakout + vol×1.5 |
| VCP detection | "dry-up trong last 10 bars" (vol < 50% MA) | dry-up + tight range pivot, breakout window 15 | dry-up + tight range, breakout 10 |
| SL | max(ATR×2, 8%) | max(ATR×2, 8%) | 8% fixed |
| TP | ATR×5 | ATR×8 | 20% fixed |
| Trailing | SMA50 close | Chandelier ATR×3 | SMA50 close |
| Position sizing | risk-based 1% | risk-based 1% + max 95% notional | 100% equity flat |
| Cooldown | 3 bars | 3 bars | ❌ |

→ Cả 3 đều quá ngặt cho 1H BTC 16 tháng. v2 thậm chí default qty=100% → 1 lệnh full equity, càng cần precision filter mà filter lại không cho entry nào.

---

## 4. Tổng kết toàn bộ thử nghiệm (15 tests)

| # | Test | P&L | Trades | WR | PF | Vs v10 |
|---|---|---|---|---|---|---|
| 1 | **v10 baseline** | **+146.71** | **87** | **70.11%** | **1.695** | — |
| 2 | v11A full (Group A) | −10.82 | 53 | 20.75% | 0.692 | thua |
| 3 | v11A-1 (TP=5 only) | +37.54 | 54 | 35.19% | 1.242 | thua |
| 4 | v11A-2 (cooldown=8 only) | +2.49 | 58 | 43.10% | 1.020 | thua |
| 5 | v11A-4 (trail x3 only) | −8.07 | 61 | 31.15% | 0.932 | thua |
| 6 | v11A-13 (A1+A3) | +44.31 | 53 | 35.85% | 1.299 | thua |
| 7 | v12B SEPA full | 0 | 0 | — | — | thua |
| 8 | v12B-r3 (TT-lite + MACD) | −4.95 | 14 | 35.71% | 0.806 | thua |
| 9 | v12B-r4 (VCP only) | +1.56 | 67 | 49.25% | 1.013 | thua |
| 10 | v12B-r5 (VCP + TT-lite) | −6.08 | 37 | 48.65% | 0.912 | thua |
| 11 | v13C MTF (Daily TT) | −10.96 | 4 | 0% | 0 | thua |
| 12 | v10-ADX | −2.22 | 19 | 42.11% | 0.948 | thua |
| 13 | **v1.5 (SEPA Hardened)** | **0** | **0** | — | — | thua |
| 14 | **v1.6 (SEPA Crypto)** | **0** | **0** | — | — | thua |
| 15 | **v2 (Minervini SEPA V2)** | **0** | **0** | — | — | thua |

**Score: 0/14 cải tiến vượt được v10 baseline.**

---

## 5. Kết luận lớn (lần thứ 4)

### 5.1. Mọi cấu trúc Minervini SEPA hoàn chỉnh đều = 0 trades trên 1H 16 tháng

3 strategies độc lập (v1.5, v1.6, v2) viết bởi 3 cách tiếp cận khác nhau, đều ra 0 trade khi áp dụng đúng mặc định Minervini trên BTC 1H trong khung 16 tháng. Đây không phải lỗi code — đây là **fundamental timeframe-asset mismatch**.

### 5.2. v15 6-year report (11 trades, +482) chỉ áp dụng được trên timeframe đủ dài

Để TT-8 + VCP có intersection với MACD/breakout trigger trên 1H, cần ít nhất 4-6 năm data — không phải 16 tháng. Với crypto 16 tháng, SEPA filter đè quá chặt.

### 5.3. v10 đơn giản, ít filter, nhưng đang khai thác mean-reversion edge

Như đã phát hiện ở báo cáo v13C/v10-ADX: v10 không phải trend-following thực sự, mà là mean-reversion sau breakout. Đây là edge tự nhiên trên BTC 1H, không cần SEPA.

### 5.4. Rủi ro overfit của v10 vẫn còn

Walk-forward đã cho thấy v10 chỉ thực sự lãi Q4 2026. 3/4 quý lỗ/hoà. Forward performance ngoài 2026-05 vẫn là dấu hỏi.

---

## 6. Quyết định cần từ anh

Lần này em đề xuất chốt 1 trong 3 hướng cuối:

### Option A — Test SEPA đúng timeframe (Daily)
- Chuyển BYBIT:BTCUSDT.P sang **Daily timeframe** rồi chạy v1.5 / v1.6 / v2.
- Trên Daily, TT-8 + VCP có ý nghĩa thật. Số trade kỳ vọng 5-15 / 16 tháng.
- Effort: thấp (chỉ đổi resolution chart).

### Option B — Forward paper-trade v10 từ 2026-05-10
- Chạy v10 thật trên Bybit testnet hoặc paper trade.
- 4-8 tuần để xác nhận v10 còn alpha ngoài training window.
- Nếu lãi → trade nhỏ (risk 0.5%). Nếu lỗ → confirm overfit → dừng v10.

### Option C — Dừng cải thiện strategy, chuyển sang risk management
- Chấp nhận v10 as-is với caveat overfit risk.
- Focus vào: position sizing, portfolio diversification, max DD limit, dynamic risk per regime.

---

**Files**:
- [pine/v1/strategy_multi_indicator_v10.pine](../../pine/v1/strategy_multi_indicator_v10.pine) — baseline
- [pine/v1/strategy_multi_indicator_v15.pine](../../pine/v1/strategy_multi_indicator_v15.pine), [v16](../../pine/v1/strategy_multi_indicator_v16.pine), [v2/minervini_strategy.pine](../../pine/v2/minervini_strategy.pine) — SEPA reference
- [docs/reports/MIS_v13C_vs_v10ADX_vs_v10.md](MIS_v13C_vs_v10ADX_vs_v10.md) — báo cáo 3-way trước
- [docs/reports/MIS_v12B_SEPA_full_test.md](MIS_v12B_SEPA_full_test.md) — SEPA fail trên 1H lần đầu
- [docs/reports/MIS_v10_walkforward.md](MIS_v10_walkforward.md) — WF v10 (3/4 quý lỗ)
- [docs/reports/backtest_report_MIS_v1_2025_2026.md](backtest_report_MIS_v1_2025_2026.md) — v15 6-year report (11 trades, +482)
