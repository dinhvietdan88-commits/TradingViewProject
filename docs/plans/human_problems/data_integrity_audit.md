# 🔍 VBS Reports Data Integrity Audit

> [!CAUTION]
> **Nghi vấn của bạn là CHÍNH XÁC.** Dữ liệu trong báo cáo cần được hiểu đúng ngữ cảnh. Dưới đây là phân tích toàn diện.

---

## Phát hiện #1: Tất cả 710 trades đều là DRY-RUN

```
replay_trades — tag distribution:
  tag='dry-run': 710 trades  (100%)
  tag='live':      0 trades  (  0%)
```

> [!WARNING]
> **100% dữ liệu trade trong `vbs_replay.db` được gắn tag `dry-run`**. Điều này có nghĩa:
> - Đây là **backtesting trên dữ liệu lịch sử** (historical replay), KHÔNG phải giao dịch thật trên sàn
> - Mã nguồn gốc tại [run_full_vbs_backtest.py:616](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/scratch/run_full_vbs_backtest.py#L616) ghi nhận rõ: `tag = "dry-run"`
> - Giá Entry/Exit là giá **lý thuyết** dựa trên OHLC candle, KHÔNG phải giá khớp lệnh thực tế từ sàn giao dịch

**Kết luận**: Các báo cáo KHÔNG dính "lệnh thử nghiệm" theo nghĩa test data giả. Chúng là kết quả replay thực sự nhưng trên dữ liệu lịch sử — chưa có lệnh thực nào được thực hiện.

---

## Phát hiện #2: Dashboard KPI là HARDCODED, không truy vấn DB

```
⚠ HARDCODED campaignsData found at char 34676 in strategy_summary.html
```

| Thành phần | Nguồn dữ liệu | Cách load |
|------------|----------------|-----------|
| KPI Strip (925 trades, 52.5% WR, +$27,776) | `const campaignsData = {...}` | **Hardcoded JS object** |
| Comparison Matrix (S2/S4/S5/S6) | Same `campaignsData` | **Hardcoded JS object** |
| Trade Execution Log (710 trades) | `trades_data.js` → `vbs_replay.db` | ✅ Truy vấn từ DB |
| Popup Candlestick Chart | `trades_data.js` → `replay_candles` | ✅ Truy vấn từ DB |

> [!IMPORTANT]
> Các con số KPI trên Dashboard **KHÔNG được tính trực tiếp từ DB**. Chúng được copy thủ công từ file `v2_stress_test_results.json` vào HTML. Nếu backtest được chạy lại với dữ liệu mới, Dashboard sẽ KHÔNG tự cập nhật.

---

## Phát hiện #3: S6 "99% Win Rate" — Survivorship Bias nghiêm trọng

Đây là phát hiện quan trọng nhất:

### S6 Optimized Hybrid — Cơ chế đạt 99% WR

| Metric | Giá trị | Giải thích |
|--------|---------|------------|
| Tổng signals | 1,015 | Toàn bộ tín hiệu VBS trong 19 ngày |
| Signals S6 thực thi | **103** | Chỉ 10.1% được chấp nhận |
| Signals S6 bỏ qua | **912** | 89.9% bị lọc bỏ bởi RSI + MACD + TrendTemplate |
| Wins | 102 | |
| Losses | **1** | Chỉ thua 1 lệnh duy nhất |

### Vì sao 99% WR không đáng tin?

1. **Survivorship Bias cực độ**: Bộ lọc RSI(35-50) + MACD + TT ≥ 4/8 loại bỏ 90% tín hiệu. Những tín hiệu còn lại **tự nhiên** có xác suất thắng cao hơn vì chúng chỉ trigger trong điều kiện thị trường cực kỳ thuận lợi.

2. **Sample Size quá nhỏ**: 103 trades trong 19 ngày ≠ statistical significance. Theo quy tắc thống kê, cần ≥ 385 trades ở 95% confidence level (margin of error 5%).

3. **12 configs DIFFERENT đều cho ra CÙNG kết quả 99.03%**: Điều này cho thấy bộ lọc RSI short (35-50) là yếu tố quyết định — thay đổi `rsi_long_max` hoặc `tt_score_threshold` không ảnh hưởng gì. Bộ lọc đang **overfit** lên pattern cụ thể trong 19 ngày.

4. **Configs nghiêm ngặt hơn đạt 100% WR / 0 losses**:
   ```
   tt_score ≥ 5 + ST(7,3.0):  36 trades, 100% WR, 0 losses
   tt_score ≥ 6 + ST(7,3.0):  36 trades, 100% WR, 0 losses
   ```
   → Càng lọc mạnh → càng ít trades → WR càng cao → **ảo tưởng hoàn hảo**

---

## Phát hiện #4: S4 "$26,414 PnL" — Context Misleading

Dashboard hiển thị S4 ATR Trailing: **+$26,414.68** với 514 trades.

| Sizing Mode | PnL | Giải thích |
|-------------|-----|------------|
| **Fixed ($100)** | **$1,108.16** | Con số thực khi đặt cố định $100/lệnh |
| Dynamic (2%) | $26,414.68 | Con số khi compounding — **không realistic** |

> [!WARNING]
> Con số $26,414 chỉ đúng khi:
> - Bắt đầu với $10,000
> - Đặt 2% vốn mỗi lệnh
> - **KHÔNG có slippage** (giá khớp lý tưởng)
> - **KHÔNG có spread** (bid/ask gap)
> - **KHÔNG có liquidity issue** (BTC luôn có thanh khoản đủ)
> - **Hoàn toàn sequential** (không có 2 lệnh chạy song song)
>
> Trong thực tế, Dynamic PnL sẽ thấp hơn đáng kể do các yếu tố trên.

---

## Phát hiện #5: PnL Distribution bất thường

```
Top repeated PnL values:
  PnL = -$8.00  → chiếm ~30% tất cả trades (220+ lần)
  PnL = +$20.00 → chiếm ~5% trades (37 lần)
```

Điều này xác nhận:
- **SL distance cố định**: Hầu hết lệnh thua đều mất đúng $8.00 (= 8% của $100)
- **TP distance cố định**: Nhiều lệnh thắng đều lãi đúng $20.00 (= 20% của $100)
- Đây là hệ thống `R:R = 1:2.5` (risk $8 để target $20)
- **Không realistic** vì thực tế slippage sẽ khiến SL hit ở $8.05-$8.20

---

## Tóm tắt: Đánh giá Tổng thể

| Câu hỏi | Trả lời |
|---------|---------|
| Các báo cáo có phải file tĩnh? | **CÓ** — 100% HTML tĩnh, KPI hardcoded |
| Có dính dry-run/test? | **CÓ** — 100% trades tagged `dry-run` (backtest replay, KHÔNG phải live) |
| Kết quả có quá tốt? | **CÓ** — S6 99% WR là survivorship bias, S4 $26k là dynamic compounding lý tưởng |
| Dữ liệu có giả? | **KHÔNG** — Prices từ Binance OHLCV thực, nhưng execution là lý thuyết |

### Khuyến nghị

1. **Thêm cảnh báo rõ ràng** trên Dashboard: "⚠ Backtesting Results — Not Live Trading"
2. **Phân biệt Fixed vs Dynamic PnL** rõ hơn — default hiển thị Fixed
3. **Chạy Walk-Forward validation** trên data ngoài sample (out-of-sample) trước khi tin bất kỳ con số nào
4. **S6 cần ≥ 500 trades** trên dữ liệu khác giai đoạn trước khi coi là viable
5. **Thêm slippage simulation** (0.05-0.1%) vào backtest engine
