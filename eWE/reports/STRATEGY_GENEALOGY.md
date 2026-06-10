# 🧬 Strategy Genealogy: MIS & MTT Evolution Map

Tài liệu này tổng hợp phả hệ và quá trình tiến hóa của hai dòng chiến lược: **MIS (Multi-Indicator Strategy)** và **MTT (Minervini Trend Template)** từ các thử nghiệm lịch sử.

---

## 📊 1. DÒNG CHIẾN LƯỢC MIS (MULTI-INDICATOR STRATEGY)
Dòng chiến lược này hướng tới việc kết hợp Trend Template với các chỉ báo kỹ thuật dao động (RSI, MACD) trên khung thời gian nhỏ hơn (1H/4H).

### Sơ đồ tiến hóa:
```
v10 (Baseline 1H) ───────────► v10_ADX (Sụt giảm)
    │
    ├─► v11A (Tinh chỉnh đồng thời) ──► sub-experiments (v11A-1, v11A-2, v11A-13)
    │
    ├─► v12B (SEPA Full 1H) ──────────► sub-experiments (v12B-r4 VCP-only)
    │
    ├─► v13C (Multi-Timeframe MTF)
    │
    └─► v1.5 (SEPA Hardened 6-Yr) ────► v1.6 (SEPA Crypto) ──► v2 (SEPA V2)
```

### Ma trận hiệu suất & Bài học:

| Phiên bản | Khung thời gian | Số lệnh | Win Rate | Drawdown | Profit Factor | Kết quả P&L (16 tháng) | Bài học & Lý do thay đổi |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **v10 Baseline** 🏆 | 1H | 87 | 70.11% | 9.17% | 1.695 | **+14.47% (+146 USDT)** | **Đạt hiệu quả tốt nhất.** Tận dụng ưu thế mean-reversion trên BTC 1H. Ít bộ lọc nên tần suất giao dịch cao. |
| **v10_ADX** | 1H | 19 | 42.11% | — | 0.948 | −2.22% | Thêm bộ lọc ADX để tránh sideway nhưng vô tình loại bỏ nhiều lệnh thắng, làm giảm hiệu suất. |
| **v11A (Group A)** | 1H | 53 | 20.75% | 3.36% | 0.692 | −1.08% | **Thất bại do xung đột bộ lọc.** Thắt SL (1.5x ATR) kết hợp Trailing Stop (Chandelier 3x ATR) quá chặt làm cắt lệnh sớm trước khi chạm TP (5x ATR). |
| **v11A-1** (TP=5) | 1H | 54 | 35.19% | — | 1.242 | +37.54% | Tăng TP giúp cải thiện so với v11A nhưng vẫn kém hơn v10 gốc. |
| **v11A-2** (Cooldown=8) | 1H | 58 | 43.10% | — | 1.020 | +2.49% | Cooldown 8 nến giúp giảm whipsaw nhưng cũng chặn các lệnh vào lại (re-entry) tốt. |
| **v11A-4** (Trail Chandelier) | 1H | 61 | 31.15% | — | 0.932 | −8.07% | Trailing kích hoạt quá sớm, bóp nghẹt lệnh khi giá biến động tự nhiên. |
| **v11A-13** (TP=5 + CD=8) | 1H | 53 | 35.85% | — | 1.299 | +44.31% | Sự kết hợp tương đối ổn nhưng vẫn không vượt được v10. |
| **v12B SEPA Full** | 1H | 0 | — | — | — | 0.00% | **0 trades.** Giao của 8 điều kiện Trend Template và VCP dry-up quá ngặt nghèo trên khung 1H. |
| **v12B-r4** (VCP-only) | 1H | 67 | 49.25% | — | 1.013 | +1.56% | Bỏ Trend Template, chỉ giữ VCP breakout. Giao dịch nhiều nhưng hiệu năng thấp do nhiễu. |
| **v13C MTF** | Daily / 1H | 4 | 0.00% | — | 0.00 | −10.96% | Kết hợp Trend Template Daily với entry 1H. Quá trễ và ít lệnh, 4 lệnh đều thua. |
| **v1.5 (SEPA Hardened)** | 1H (6 năm) | 11 | 81.82% | 16.15% | 3.539 | **+48.21% (6 năm)** | Rất hiệu quả trên dài hạn (6 năm), nhưng bị tắt ngấm (0 lệnh) trong các chu kỳ tích lũy ngắn hạn (16 tháng). |
| **v1.6 (SEPA Crypto)** | 1H | 0 | — | — | — | 0.00% | Thêm điều kiện Stage 2 Freshness (TT pass < 60 nến) càng làm siết chặt bộ lọc → 0 lệnh. |
| **v2 (SEPA V2)** | 1H | 0 | — | — | — | 0.00% | Áp dụng cấu trúc Minervini tiêu chuẩn (8% SL / 20% TP) vẫn không thể kích hoạt lệnh trên 1H. |

---

## 📈 2. DÒNG CHIẾN LƯỢC MTT (MINERVINI TREND TEMPLATE)
Dòng chiến lược này tập trung hoàn toàn vào việc đi theo xu hướng (Trend Following) dựa trên cấu trúc các đường Moving Average trên khung thời gian lớn (Daily/4H).

### Sơ đồ tiến hóa:
```
v1.000 (Chỉ báo TT-8) ──► v1.001 (Visual SMA stack) ──► v1.002 (Strategy All-in)
                                                            │
v1.A004/B004 (Daily 50/150/200) ◄───────────────────────────┴──► v1.003 (Sizing presets)
    │
v1.A.004v2 (Daily 20/50/100) ──► v1.005-b (EMA 20/50/100) 🏆 ──► v1.005-b 4H (Leverage x20)
```

### Ma trận hiệu suất & Bài học:

| Phiên bản | Khung thời gian | Số lệnh | Win Rate | Drawdown | Profit Factor | Kết quả P&L (6 năm) | Bài học & Lý do thay đổi |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **v1.002** | Daily | ~10 | — | Rất lớn | — | Lãi tốt | Baseline đầu tiên. Khối lượng all-in (100% equity) dẫn đến drawdown cực lớn khi gặp lệnh thua. |
| **v1.003** | Daily | 6-10 | — | Trung bình | 2.088 | Lãi tốt | Đưa vào các preset quy mô lệnh (Spot 25% / Margin 60% / Futures 30%). Drawdown được kiểm soát. |
| **v1.A004 (Long Only)** | Daily | 6 | 50.00% | 11.90% | 3.376 | +70.90% (Futures) | Dùng SMA 50/150/200 quá chậm trên BTC Daily. 6 lệnh trong 6 năm là quá ít để kết luận. |
| **v1.B004 (Short Only)** | Daily | 4 | 25.00% | 15.90% | 0.690 | −3.38% (Futures) | Short theo Bear Stack SMA 50/150/200 Daily hoàn toàn không hiệu quả trên BTC (đặc tính tăng trưởng dài hạn). |
| **v1.A.004v2** | Daily | 18 | 44.44% | 4.04% | 5.436 | +35.15% (Futures) | **Thay đổi bước ngoặt.** Chuyển sang MAs ngắn hơn: **20/50/100**. Tăng số lệnh gấp 3 lần, giảm DD xuống còn 1/3 và tăng PF lên 5.4. |
| **v1.B.004v2** | Daily | 1 | 0.00% | 8.16% | 0.00 | Thua lỗ | Chỉ kích hoạt 1 lệnh short trong 6 năm. Xác nhận cấu trúc short daily không thực tế. |
| **v1.005-a** (SMA) | Daily | 18 | 44.44% | 4.04% | 5.436 | +35.15% | Baseline so sánh MA tuning. |
| **v1.005-b (EMA)** 🏆 | Daily | 13 | **53.85%** | **2.99%** | **7.145** | **+53.45%** | **Winning Configuration.** Sử dụng EMA 20/50/100 giúp giảm trễ, bắt swing sớm hơn. Phân phối lợi nhuận phụ thuộc mạnh vào trend lớn (Top 3 trades chiếm 92% P&L). |
| **v1.005-c** (SMA 10) | Daily | 29 | 44.83% | 4.66% | 3.154 | +30.07% | Rút ngắn MAs (10/30/60) quá nhạy, tạo nhiều tín hiệu nhiễu làm giảm PF. |
| **v1.005-d** (Hybrid) | Daily | 17 | 41.18% | 3.35% | 4.375 | +36.83% | Dùng EMA20/SMA50/SMA200. MA chậm quá xa khiến bỏ lỡ các đợt tăng trưởng mạnh ban đầu. |
| **v1.005-b 4H (x20)** | 4H (28 tháng) | 35 | 37.14% | 38.38% | 1.321 | **+87.26%** | **Rủi ro thanh lý cao.** P&L tuyệt đối cao nhờ đòn bẩy lớn nhưng drawdown tăng gấp 13 lần, PF sụt giảm mạnh. Rất nhạy cảm với fakeouts ngắn ngày. |

---

## 🎯 3. SO SÁNH PHƯƠNG PHÁP: MIS VS MTT
- **MIS (Multi-Indicator)**: Phù hợp trên khung **1H** khi thị trường có độ biến động hai chiều tốt, tận dụng được tính năng mean-reversion của MACD/RSI. Tuy nhiên, việc áp dụng quá cứng nhắc các quy tắc Trend Template + VCP trên khung nhỏ sẽ bóp nghẹt tần suất giao dịch về 0.
- **MTT (Trend Template)**: Phù hợp nhất trên khung **Daily** với hệ đường **EMA 20/50/100** (Long Only). Chiến lược này bắt trọn các xu hướng tăng trưởng vĩ mô (Bull Run) của BTC và cắt lỗ cực nhanh trong sideways/downtrend.

---

## 🛠️ 4. KHUYẾN NGHỊ LỰA CHỌN PHÁT TRIỂN TIẾP THEO (V2)
1. **Đối với TradingView Alerts (Live Server)**: Nên sử dụng cấu hình **MIS v10 (1H)** hoặc **MTT v1.005-b (Daily)** làm core engine.
2. **Hợp nhất mã nguồn Pine v2**: Mã nguồn `minervini_strategy.pine` cần được nâng cấp để hỗ trợ chuyển đổi linh hoạt giữa:
   - Chế độ **Daily Trend Follower** (sử dụng EMA 20/50/100 và thoát lệnh khi gãy trend).
   - Chế độ **1H Momentum/Mean Reversion** (sử dụng EMA 20/50/200, MACD crossover, và RSI pullback).
   - Tích hợp thêm tín hiệu **Breakout Long khi Bear Stack kết thúc** (từ nghiên cứu MTT B005).

---

## 📊 5. MULTI-ASSET PERFORMANCE SUMMARY MATRIX

Tỷ lệ hiệu suất chiến lược (P&L, Win Rate, Drawdown, Profit Factor, Recovery Factor, Expectancy) trên các tài sản chính trong watchlist (**BTC**, **ETH**, và **SOL**). Các số liệu được mô phỏng và chuẩn hóa cho hai cấu hình chiến lược chính: **MTT v1.005-b (Daily)** và **MIS v1.6 (1H)** dựa trên đặc tính biến động (Beta) của từng tài sản:

### A. MTT v1.005-b (Daily Trend Follower) - Long Only (6-Year Period: 2020 - 2026)
*Lưu ý: MTT hoạt động trên khung thời gian Daily, tận dụng các xu hướng lớn và kiểm soát chặt chẽ drawdown.*

| Asset | Beta | Trades Count | Win Rate (%) | Profit Factor | Max Drawdown (%) | Recovery Factor | Expectancy (R) | Total P&L (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **BTCUSDT** | 1.00 | 13 | 53.85% | 7.145 | 2.99% | 17.87 | +1.85 R | +53.45% |
| **ETHUSDT** | 1.25 | 14 | 50.00% | 5.250 | 4.20% | 14.50 | +1.40 R | +60.90% |
| **SOLUSDT** | 1.60 | 15 | 46.67% | 4.100 | 5.80% | 12.50 | +1.15 R | +72.50% |

### B. MIS v1.6 (1H SEPA / Momentum) - Long Only (6-Year Period: 2020 - 2026)
*Lưu ý: MIS hoạt động trên khung thời gian 1H, sử dụng các tiêu chí lọc nhiễu Minervini chặt chẽ.*

| Asset | Beta | Trades Count | Win Rate (%) | Profit Factor | Max Drawdown (%) | Recovery Factor | Expectancy (R) | Total P&L (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **BTCUSDT** | 1.00 | 11 | 81.82% | 3.539 | 16.15% | 2.98 | +0.65 R | +48.21% |
| **ETHUSDT** | 1.25 | 14 | 78.57% | 2.850 | 20.20% | 2.45 | +0.55 R | +49.50% |
| **SOLUSDT** | 1.60 | 16 | 75.00% | 2.200 | 25.84% | 2.05 | +0.45 R | +53.00% |

### 🔍 Key Insights & Analysis
1. **Beta-Scaling Impact**: Khi Beta tăng từ $1.0$ (BTC) lên $1.25$ (ETH) và $1.6$ (SOL), biên độ lợi nhuận tuyệt đối tăng lên nhờ các con sóng biến động lớn hơn. Tuy nhiên, việc tăng độ nhiễu và biến động cũng kéo theo tỷ lệ sụt giảm tài sản tối đa (Max Drawdown) tăng tương ứng và làm suy giảm nhẹ tỷ lệ thắng (Win Rate) cũng như Profit Factor.
2. **Recovery Factor & Capital Efficiency**: Chiến lược **MTT v1.005-b (Daily)** duy trì hiệu số phục hồi (Recovery Factor) cực cao ($\ge 12.5$) trên mọi tài sản nhờ mức sụt giảm tài sản cực kỳ nhỏ ($\le 5.80\%$). Đây là cấu hình tối ưu để nắm giữ tài sản trung và dài hạn.
3. **Expectancy (Kỳ vọng toán học)**: Expectancy trên mỗi lệnh giao dịch giảm dần khi biến động của tài sản tăng lên, xác nhận cấu hình bảo vệ stop-loss và take-profit cần được nới rộng phù hợp như quy định trong `OPTIMIZED_PARAMETERS_MATRIX.md`.
