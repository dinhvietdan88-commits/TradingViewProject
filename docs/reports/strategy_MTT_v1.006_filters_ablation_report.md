# Báo cáo V1.006 — Filters Ablation Study

**Branch**: `feat/v1.006-filters`
**Strategy**: V1.005-b EMA 20/50/100 Long Only (baseline) + 3 filters
**Symbol**: BYBIT:BTCUSDT.P — **Capital**: 100,000 USDT — **qty 10%** — **Comm 0.075%** — **Slippage 2 ticks**
**Run date**: 2026-05-10

---

## 1. 3 Filters thêm vào V1.006

| Filter | Logic | Mục tiêu |
|---|---|---|
| **Slope filter** | `mm > mm[20]` (medium MA cao hơn 20 bars trước) | Loại entry ở vùng sideway / dốc xuống |
| **Volume filter** | `volume > sma(volume, 50) × 1.0` | Lọc fake breakout (cần lực) |
| **ATR trailing stop** | `trail = max(trail, close − 2.5 × ATR(14))`, exit nếu `low ≤ trail` | Bảo vệ winners trong pha reverse |

## 2. Ablation matrix — Daily timeframe

| # | Variant | Trades | Win % | **PF** | DD % | P&L % | Δ vs Baseline |
|--:|---|---:|---:|---:|---:|---:|---|
| 0 | **Baseline V1.005-b** | 13 | 53.85% | 7.145 | 2.99% | **+53.45%** | reference |
| 1 | + Slope only | 7 | **71.43%** ⭐ | **8.939** ⭐ | 2.45% | +17.76% | PF +25%, P&L −67% |
| 2 | + Trail only | 13 | 53.85% | 6.096 | **1.66%** | +13.00% | DD −44%, P&L −76% |
| 3 | + Slope + Trail | 7 | 71.43% | 7.286 | **1.48%** ⭐ | +6.58% | DD lowest, P&L kém |
| 4 | + All 3 (Full) | 3 | 33.33% | 2.089 | 1.96% | +1.11% | Quá strict |

## 3. Ablation matrix — 4H timeframe

| # | Variant | Trades | Win % | **PF** | DD % | P&L % |
|--:|---|---:|---:|---:|---:|---:|
| 0 | Baseline V1.005-b 4H | 95 | 36.84% | 1.183 | 8.26% | +4.81% |
| 1 | + Slope only | 47 | 34.04% | **1.924** | 3.51% | **+12.65%** |
| 2 | + Trail only | 79 | **49.37%** ⭐ | 1.971 | **1.54%** | +10.52% |
| 3 | + Slope + Trail | 47 | 46.81% | 1.5 | 1.67% | +3.60% |
| 4 | + All 3 (Full) | 19 | 42.11% | 2.141 ⭐ | **1.07%** ⭐ | +2.53% |

## 4. Quan sát chính

### 4.1 Slope filter
- **D**: PF 8.939 (cao nhất), Win 71.43% — lọc 6 fakeout trades, giữ winners trend dài
- **4H**: PF gấp 1.6× (1.183 → 1.924), giảm trade nửa (95 → 47)
- **Cost**: bỏ lỡ trade #2 (340% gain) trên D vì slope chưa kích hoạt khi entry → P&L tụt 67%
- **Verdict**: ✅ Winner cho **statistical robustness** nhưng cắt 1 outlier khổng lồ

### 4.2 ATR Trailing stop
- **D**: DD giảm 44% (2.99 → 1.66%) nhưng P&L giảm 76% — trail cắt sớm trade #2 khi BTC pullback Mar 2021
- **4H**: Cải thiện TOÀN DIỆN — Win 36.84% → 49.37%, DD 8.26% → 1.54%, P&L gấp đôi
- **Verdict**: ✅ Winner trên **4H** vì 4H có nhiều noise → trail bảo vệ profit; ❌ Trên D thì cắt sớm trend dài

### 4.3 Volume filter
- Quá strict — `volume > SMA50` tại moment bull_start hiếm khi đạt
- Kết hợp với 2 filter khác → giảm trade từ 13 → 3 trên D
- **Verdict**: ❌ Quá strict ở mức multiplier 1.0; nên hạ xuống 0.7 hoặc dùng làm "boost" thay vì "gate"

### 4.4 Tradeoff PF vs P&L

```
Baseline:      PF 7.145, P&L +53% (1 outlier carry)
Slope only:    PF 8.939, P&L +18% (no outlier)
Trail only:    PF 6.096, P&L +13% (early exit)
Slope+Trail:   PF 7.286, P&L +7%  (both effects)
Full:          PF 2.089, P&L +1%  (over-filtered)
```

> Filter cải thiện CHẤT LƯỢNG (PF, win rate, DD) nhưng GIẢM TỔNG P&L vì cắt outliers.
> Nếu mục tiêu là "đáng tin cậy + ít DD" → bật slope (D) hoặc trail (4H).
> Nếu mục tiêu là "P&L tuyệt đối + chấp nhận sample mỏng" → giữ baseline.

## 5. Khuyến nghị config production V1.006

| TF | Bật filter | qty% | PF kỳ vọng | DD kỳ vọng | Ghi chú |
|---|---|---:|---:|---:|---|
| **D** | **Slope ON**, Volume OFF, Trail OFF | 10% | **8.9** | 2.5% | Best PF / Win combo |
| **D conservative** | Slope + Trail | 10% | 7.3 | 1.5% | Lowest DD |
| **4H** | **Trail ON**, Slope ON, Volume OFF | 10% | 1.5–2.0 | 1.5% | Trail là quan trọng nhất 4H |
| **4H aggressive** | Slope ON only | 10% | 1.9 | 3.5% | P&L cao hơn |

**Default V1.A006**: D với Slope ON. Trên 4H tự động bật thêm Trail (TF-aware).

## 6. So sánh V1.005-b → V1.A006 (slope) trên D

| Metric | V1.005-b (no filter) | V1.A006 (slope) | Δ |
|---|---:|---:|---|
| Trades | 13 | 7 | -46% |
| Win rate | 53.85% | 71.43% | **+17.6 pts** |
| PF | 7.145 | **8.939** | **+25%** |
| Max DD % | 2.99% | 2.45% | -18% |
| P&L % | +53.45% | +17.76% | -67% (1 outlier loss) |
| Trades/year | 2.2 | 1.2 | quá thưa |

→ **V1.006 chỉ nên dùng nếu chấp nhận P&L thấp hơn để có hệ thống ổn định hơn**.
   Nếu giữ leverage cao như x10–x20 thì V1.006 slope là phải có để tránh blow-up.

## 7. Files

- Library mới: [pine/v1/strategy_mtt_lib.pine](../../pine/v1/strategy_mtt_lib.pine) (thêm `slope_up`, `slope_down`, `volume_ok`, `atr_trail_long/short`)
- Strategy A.006: [pine/v1/strategy_MTT_v1.A006.pine](../../pine/v1/strategy_MTT_v1.A006.pine)
- Strategy B.006: [pine/v1/strategy_MTT_v1.B006.pine](../../pine/v1/strategy_MTT_v1.B006.pine)
- Báo cáo trước: [strategy_MTT_v1.005_MA_tuning_report.md](strategy_MTT_v1.005_MA_tuning_report.md)
