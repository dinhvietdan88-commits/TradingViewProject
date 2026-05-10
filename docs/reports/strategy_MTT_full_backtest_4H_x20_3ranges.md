# Backtest tổng — V1.A004 → V1.A006, 4H, Futures x20, 3 ranges

**Symbol**: BYBIT:BTCUSDT.P
**Timeframe**: **4H**
**Profile**: **Futures**, qty per entry = **200% notional** (= 10% margin × 20x leverage)
**Initial margin**: 100,000 USDT
**Commission**: 0.075% — **Slippage**: 2 ticks — **Pyramiding**: 0
**Run date**: 2026-05-10
**Branch**: `feat/v1.006-filters`

---

## 1. Variants tested

| Code | Strategy | MA | Filters |
|---|---|---|---|
| **V1.A004** | strategy_MTT_v1.A004 | SMA 50/150/200 | none |
| **V1.005-b** | strategy_MTT_v1.A.004v2 / A005 | EMA 20/50/100 | none |
| **V1.A006-S** | A006 | EMA 20/50/100 | Slope only |
| **V1.A006-T** | A006 | EMA 20/50/100 | Trail only |
| **V1.A006-ST** | A006 | EMA 20/50/100 | Slope + Trail |

## 2. Bảng kết quả 5 × 3 = 15 cells

### 2025-01-01 → 2026-05-09 (~16 tháng)

| Variant | P&L % | Max DD % | Trades | Win % | PF | Verdict |
|---|---:|---:|---:|---:|---:|---|
| V1.A004 (SMA 50/150/200) | **−14.21%** | 41.16% | 10 | 30.00% | 0.698 | ❌ |
| V1.005-b (EMA 20/50/100) | −10.37% | 38.38% | 21 | 33.33% | 0.871 | ❌ |
| V1.A006-S (slope) | +0.52% | 35.66% | 14 | 28.57% | 1.007 | 🟡 Hoà |
| V1.A006-T (trail) | −6.73% | **21.81%** | 21 | 47.62% | 0.861 | ❌ DD thấp nhất |
| V1.A006-ST (slope+trail) | −5.06% | **17.56%** ⭐ | 14 | 50.00% | 0.858 | ❌ DD lowest |

> 2025 là **năm xấu** cho mọi variant. Không config nào ăn được. BTC sideway 80k–120k, MA stack flip liên tục bị fakeout.

### 2024-01-01 → 2026-05-09 (~28 tháng)

| Variant | P&L % | Max DD % | Trades | Win % | PF | Verdict |
|---|---:|---:|---:|---:|---:|---|
| V1.A004 | −8.82% | 62.08% | 20 | 30.00% | 0.94 | ❌ |
| V1.005-b | +87.26% | 38.38% | 35 | 37.14% | 1.321 | ✅ |
| V1.A006-S | **+119.46%** ⭐ | 35.67% | 20 | 45.00% | 1.629 | ✅ |
| V1.A006-T | +81.06% | **21.81%** | 35 | 51.43% | 1.645 | ✅ |
| V1.A006-ST | +44.32% | **17.57%** ⭐ | 20 | 55.00% | **1.655** | ✅ Best risk-adjusted |

### 2021-01-01 → 2026-05-09 (~64 tháng) — backtest dài

| Variant | P&L % | Max DD % | Trades | Win % | PF | Verdict |
|---|---:|---:|---:|---:|---:|---|
| V1.A004 | −19.75% | 65.91% | 41 | 31.71% | 0.919 | ❌ Dead |
| V1.005-b | +218.59% | 66.63% | 79 | 30.38% | 1.289 | ✅ |
| V1.A006-S | +251.77% | 54.77% | 47 | 34.04% | 1.452 | ✅ |
| **V1.A006-T** | **+381.24%** 🏆 | **28.79%** | 79 | **49.37%** | **1.726** | 🏆 Champion |
| V1.A006-ST | +64.56% | 29.87% | 47 | 46.81% | 1.36 | ✅ |

## 3. So sánh evolution V1.A004 → V1.005-b → V1.A006-T (5 năm 2021-2026)

| Metric | V1.A004 | V1.005-b | V1.A006-T | Δ A004→A006-T |
|---|---:|---:|---:|---|
| P&L | **−19.75%** | +218.59% | **+381.24%** | **+401 pp** ⭐ |
| Max DD | 65.91% | 66.63% | **28.79%** | **−37 pp** ⭐ |
| Win rate | 31.71% | 30.38% | **49.37%** | **+17.66 pp** ⭐ |
| PF | 0.919 | 1.289 | **1.726** | **+88%** ⭐ |
| Trades | 41 | 79 | 79 | gấp 1.9× |

> **3 nâng cấp** (MA, leverage-aware sizing, ATR trail) → strategy đảo từ thua thành ăn 5x vốn ban đầu, DD giảm 1/2.

## 4. So sánh điều kiện thị trường qua 3 ranges (best variant V1.A006-T)

| Range | P&L % | Max DD % | Win % | Đặc điểm BTC |
|---|---:|---:|---:|---|
| 2025-2026 | **−6.73%** | 21.81% | 47.62% | Sideway 80k–120k, fakeout liên tục |
| 2024-2026 | +81.06% | 21.81% | 51.43% | Có 2 trend lớn (#2, #13) carry |
| 2021-2026 | **+381.24%** 🏆 | 28.79% | 49.37% | Bao gồm bull run 2021 (10k→69k) + 2024 |

> Strategy **chỉ tỏa sáng khi có trend lớn**. Năm sideway như 2025 → kể cả config tốt nhất vẫn lỗ.

## 5. Risk-adjusted ranking (Sortino-like proxy = P&L / DD)

| # | Variant | Range | P&L % | DD % | **P&L / DD** |
|--:|---|---|---:|---:|---:|
| 1 | V1.A006-T | 2021-2026 | 381.24 | 28.79 | **13.24** 🏆 |
| 2 | V1.A006-S | 2021-2026 | 251.77 | 54.77 | 4.60 |
| 3 | V1.A006-T | 2024-2026 | 81.06 | 21.81 | 3.72 |
| 4 | V1.005-b | 2021-2026 | 218.59 | 66.63 | 3.28 |
| 5 | V1.A006-S | 2024-2026 | 119.46 | 35.67 | 3.35 |
| 6 | V1.A006-ST | 2024-2026 | 44.32 | 17.57 | 2.52 |
| 7 | V1.005-b | 2024-2026 | 87.26 | 38.38 | 2.27 |
| 8 | V1.A006-ST | 2021-2026 | 64.56 | 29.87 | 2.16 |
| 9 | V1.A006-S | 2025-2026 | 0.52 | 35.66 | 0.01 |
| 10–15 | (all negative) | — | <0 | — | <0 |

## 6. Phát hiện chính

### 6.1 ATR Trail là filter giá trị nhất trên 4H
- Đóng góp lớn nhất vào P&L: trail-only 5 năm = **+381%** vs no-filter +218% → trail sinh thêm **163 pp**
- Giảm DD từ 66.63% → 28.79% (cắt một nửa)
- Tăng Win rate từ 30.38% → 49.37% (gần gấp đôi 1/3 baseline)
- Lý do: 4H có nhiều noise → trail bảo vệ winners khi market quay đầu nhanh

### 6.2 Slope filter cho ổn định nhưng không đột phá
- 2021-2026: +251.77% (kém trail-only)
- DD 54.77% (kém trail-only 28.79%)
- Win rate không đổi nhiều (30 → 34%)
- → Slope đơn lẻ chỉ giúp "lọc nhiễu" chứ không bảo vệ vốn như trail

### 6.3 Slope + Trail combo = "safe mode"
- DD lowest mọi range (17.57% / 17.56% / 29.87%)
- P&L thấp hơn nhiều: 64.56% trên 5 năm vs 381% với trail-only
- → Chấp nhận trade-off: nếu cần leverage cao nhưng phải sleep well, dùng combo này

### 6.4 V1.A004 (SMA 50/150/200) hoàn toàn dead trên 4H x20
- Lỗ ở mọi range
- Chứng minh: SMA chậm + leverage cao = sự kết hợp tệ nhất
- DD 65.91% trên 5 năm = gần liquidation (margin call ở DD ~40-50%)

### 6.5 2025 sideway giết mọi config
- Mọi variant lỗ hoặc hoà
- Không ai ăn được trong sideway market
- → Cần regime detection (V1.007?): dừng trade khi market detected sideway

## 7. Khuyến nghị cấu hình

| Mục tiêu | Cấu hình | P&L 5 năm | DD | PF |
|---|---|---:|---:|---:|
| **Tối đa lợi nhuận** | V1.A006 Trail-only, 4H, x20 | **+381%** | 28.8% | 1.73 |
| **Cân bằng** | V1.A006-S, 4H, x20 | +251% | 54.8% | 1.45 |
| **Bảo toàn vốn (low DD)** | V1.A006-ST, 4H, x20 | +64% | 29.9% | 1.36 |
| **An toàn nhất (no leverage)** | V1.005-b, D, qty 10% | +53% (6 năm) | 2.99% | 7.15 |
| ❌ KHÔNG dùng | V1.A004 4H x20 | −20% | 66% | 0.92 |

## 8. Roadmap V1.007

Để giải quyết **vấn đề 2025 sideway**, V1.007 đề xuất:

| Filter | Cơ chế | Mục đích |
|---|---|---|
| **Regime detection** | ADX < 20 → block entry | Stop trade trong sideway |
| **Bollinger squeeze** | BB width < 1% → block | Tương tự ADX |
| **Volatility expansion** | Entry chỉ khi ATR đang mở rộng | Bắt được trend mới hình thành |
| **Dynamic ATR mult** | Tăng mult khi DD rolling cao | Auto risk-down khi đang lỗ |
| **Time-based stop** | Close lệnh nếu hold > N bars không profit | Tránh nắm lỗ kéo dài |

**Mục tiêu V1.007**: turn 2025 từ −5% thành ≥ 0% mà vẫn giữ +200% trên 2024 / +350% trên 2021.

## 9. Files

- Báo cáo trước:
  - [strategy_MTT_v1.005_MA_tuning_report.md](strategy_MTT_v1.005_MA_tuning_report.md)
  - [strategy_MTT_v1.005_4H_x20_futures_report.md](strategy_MTT_v1.005_4H_x20_futures_report.md)
  - [strategy_MTT_v1.006_filters_ablation_report.md](strategy_MTT_v1.006_filters_ablation_report.md)
- Strategies: [pine/v1/strategy_MTT_v1.A006.pine](../../pine/v1/strategy_MTT_v1.A006.pine), [pine/v1/strategy_MTT_v1.B006.pine](../../pine/v1/strategy_MTT_v1.B006.pine)
- Library: [pine/v1/strategy_mtt_lib.pine](../../pine/v1/strategy_mtt_lib.pine)
