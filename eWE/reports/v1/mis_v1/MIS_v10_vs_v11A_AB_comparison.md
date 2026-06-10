# 📊 A/B Backtest: MIS v10 (baseline) vs MIS v1.1A (Group A tuned)

**Symbol / Timeframe**: BYBIT:BTCUSDT.P · 60m
**Backtest range hiển thị trong Strategy Tester**: **Jan 1, 2025 → May 9, 2026** (≈16 tháng)
**Equity ban đầu**: 1,000 USDT · qty 2% equity · commission 0.05% · slippage 2 ticks
**Ngày test**: 2026-05-09

> ⚠️ Range backtest **chỉ là 16 tháng** chứ không phải 6 năm như em ước lượng ban đầu (TradingView mặc định cap data theo plan/symbol). Mọi nhận định Q4/2025 cứu cánh trong báo cáo trước cần đọc lại trong khung thời gian này.

---

## 1. Kết quả tổng hợp

| Metric | **v10 baseline** | **v1.1A (Group A)** | Δ |
|---|---|---|---|
| Total P&L | **+146.71 USDT (+14.47%)** | **−10.82 USDT (−1.08%)** | −157.53 USDT |
| Max equity drawdown | 96.82 USDT (9.17%) | 33.58 USDT (3.36%) | −63.24 USDT (drawdown nhẹ hơn) |
| Total trades | 87 | 53 | −34 |
| Profitable trades | 70.11% (61/87) | **20.75% (11/53)** | −49.36 pp |
| Profit factor | **1.695** | 0.692 | −1.003 |

**Kết luận chốt**: Bộ tinh chỉnh nhóm A áp dụng đồng thời **đảo ngược lợi thế của v10**. Trade frequency giảm đúng kỳ vọng (87→53), drawdown giảm như mong đợi (9.17%→3.36%), nhưng **win-rate sập từ 70% xuống 20.75% và profit factor xuống dưới 1**. Kết quả: chiến lược lỗ ròng trong cùng khung 16 tháng.

---

## 2. So sánh tham số (recap)

| Tham số | v10 | v1.1A | Mục đích nhóm A |
|---|---|---|---|
| `atr_tp_mul` | 3.0 | **5.0** | A1 — nâng R:R |
| `atr_sl_mul` | 2.0 | **1.5** | A2 — thắt loss |
| `cooldown_bars` | 0 | **8** | A3 — chặn whipsaw |
| `use_trail` | false | **true** + Chandelier ATR×3 | A4 — giữ profit |
| `allow_short` | true | **false** | A5 — bỏ short |
| RSI long | 50-70 | **>50, no ceiling** | A6 — bắt momentum |

File: [pine/v1/strategy_multi_indicator_v11A.pine](../../pine/v1/strategy_multi_indicator_v11A.pine)

---

## 3. Phân tích vì sao nhóm A phản tác dụng

### 3.1. Win-rate sụp do tương tác A2 + A4 + A1

- **A2 (SL=1.5·ATR)** thắt loss xuống 25% so với v10 → noise BTC 1H (thường xuyên ~1·ATR pullback) **chạm SL trước cả khi setup phát huy**.
- **A4 (Chandelier ATR×3 trailing)** kích hoạt từ bar entry. Sau khi giá tiến lên một chút, `sl_trail = trail_high - 3·ATR` có thể lên trên `sl_hard = entry - 1.5·ATR`. Lúc đó `sl = max(sl_hard, sl_trail)` chuyển sang trail tight → 1 pullback bình thường là **đóng lệnh lỗ nhẹ hoặc hoà**. Lệnh cần kiên nhẫn để chạm TP=5·ATR thì lại không đủ thời gian.
- **A1 (TP=5·ATR)** bản thân đẩy TP xa hơn — phải kiên nhẫn hơn — nhưng A2+A4 lại cắt sớm. Hai lực ngược nhau làm phần lớn lệnh đóng ở vùng SL thay vì TP.

→ Trên chart screenshot có thể thấy nhãn **"Long Exit"** xuất hiện sát ngay sau **"Long"** — confirm exit sớm.

### 3.2. A5 (bỏ short) làm mất đỉnh win-rate gốc

- v10 win-rate 70% có một phần đến từ short (BTC giai đoạn Jan-2025 → Apr-2025 chop xuống → các short MACD-cross hit TP=3·ATR). Trong khung 2025-2026 này ngắn nên short không bị "drift up" đè như giai đoạn 2022.
- Bỏ short = mất đi pool lệnh đó → win-rate trung bình tụt.

→ A5 chỉ hợp lý khi backtest dài hạn có downtrend dày (2022). Trong khung ngắn 2025-2026 với chop hai chiều, short thực sự đóng góp dương.

### 3.3. A3 (cooldown 8 bars) cắt nhằm cả lệnh tốt

- Cooldown 8h sau exit chặn được whipsaw trong sideways, **nhưng cũng chặn re-entry sau pullback ngắn trong trend mạnh**.
- Trade frequency giảm 39% (87→53). Một phần tốt mất theo.

### 3.4. A6 (bỏ RSI ceiling) trên thực tế ít tác động

- Trong giai đoạn 2025-2026 BTC range nhiều, RSI hiếm khi vượt 70 với MACD cross up đồng thời và EMA stack đồng thời → A6 chỉ thêm ~1-2 entry → không đủ tạo khác biệt.

### 3.5. Drawdown giảm là **artifact của lệnh nhỏ / ít**, không phải robustness thật

- MDD 3.36% nhỏ hơn 9.17% nhìn có vẻ tốt, nhưng đi kèm với:
  - Số lệnh ít hơn → ít cơ hội tích luỹ loss chuỗi.
  - Mỗi loss bị cắt sớm bởi A2/A4 → loss size nhỏ.
- Không phải dấu hiệu strategy ổn định hơn — chỉ là "thua nhỏ giọt nhiều lần".

---

## 4. Bài học và đề xuất tiếp theo

### 4.1. Áp dụng đồng thời 6 thay đổi là sai lầm

Nhóm A trên giấy hợp lý từng cái, nhưng **tác dụng phụ tương tác** không lường trước. Cần test **lần lượt từng change** (one-at-a-time) để biết cái nào có giá trị.

### 4.2. Đề xuất sub-experiments (giữ template v11A, chỉ bật 1 input/lần)

| Variant | Chỉ bật change | Giả thuyết |
|---|---|---|
| **v11A-1** (chỉ A1) | TP=5·ATR, giữ SL=2, cooldown=0, no trail, allow_short=true, RSI ceiling 70 | R:R lên 2.5 → expectancy tăng nếu trend kéo dài |
| **v11A-2** (chỉ A3) | cooldown=8, mọi cái khác giữ v10 | Test riêng tác dụng cooldown trên 2025-chop |
| **v11A-4** (chỉ A4) | trailing Chandelier×3, mọi cái khác giữ v10 | Test trail có giữ profit hay cắt sớm |
| **v11A-A1+A3** | TP=5, cooldown=8, không bỏ short, không trail, SL=2 | Hai change "an toàn" nhất |

### 4.3. Việc bỏ short cần điều kiện kèm theo

A5 chỉ nên áp dụng khi **có TT gate / regime filter** xác nhận BTC đang downtrend cấu trúc dài. Không nên tắt cứng bằng `allow_short=false` mặc định trong khung 1H BTC.

### 4.4. Trailing stop cần sl_trail "lazy"

Nếu vẫn muốn trailing, đổi từ Chandelier ATR×3 sang **chỉ kích hoạt sau khi giá chạm 1·ATR profit** (break-even shift), tránh đè SL ngay từ entry bar.

### 4.5. Cân nhắc nhóm B luôn

Nhóm A test xong đã rõ: tinh chỉnh tham số trên cấu trúc v10 chưa đủ. Nguyên nhân gốc của v10 yếu (báo cáo trước, Phần 4) là **thiếu TT/Stage-2 gate** — đây là nhóm B. Em đề xuất triển khai v1.5/v1.6 logic full thay vì tiếp tục patch v10.

---

## 5. Dữ liệu raw (verify từ screenshot)

### v10 — `pine/v1/strategy_multi_indicator_v10.pine`
- Screenshot: [tradingview-mcp/screenshots/v10_strategy_tester.png](../../tradingview-mcp/screenshots/v10_strategy_tester.png)
- Total P&L: **+146.71 USDT (+14.47%)**
- Max equity drawdown: 96.82 USDT (9.17%)
- Total trades: 87
- Profitable: 70.11% (61/87)
- Profit factor: 1.695

### v1.1A — `pine/v1/strategy_multi_indicator_v11A.pine`
- Screenshot: [tradingview-mcp/screenshots/after_v11A_save.png](../../tradingview-mcp/screenshots/after_v11A_save.png)
- Total P&L: **−10.82 USDT (−1.08%)**
- Max equity drawdown: 33.58 USDT (3.36%)
- Total trades: 53
- Profitable: 20.75% (11/53)
- Profit factor: 0.692

### Lưu ý dữ liệu
- `mcp__tradingview__data_get_strategy_results` và `data_get_trades` trả 0 record cho cả hai run (lỗi CDP detect strategy artifact). Tất cả số liệu đọc trực tiếp từ Strategy Report tab trong screenshot.
- Range backtest = **16 tháng** (Jan 2025 → May 2026), không phải 6 năm. Nếu cần validate trên 6 năm, cần symbol có đủ data history (BYBIT:BTCUSDT.P chỉ có ~16 tháng visible, có thể do gói data hoặc giới hạn TradingView).

---

## 6. Quyết định cần từ anh

1. **Có muốn em chạy 4 sub-experiments** (v11A-1, v11A-2, v11A-4, v11A-A1+A3) để xác định change nào cứu được không?
2. **Hay chuyển hẳn nhóm B** — fork sang `pine/v1/strategy_multi_indicator_v12B.pine` với TT gate + VCP + risk-based sizing (port toàn bộ logic v1.5/v1.6)?
3. **Range backtest 16 tháng có đủ với anh không**, hay cần tìm symbol khác (BINANCE:BTCUSDT spot có history dài hơn) để validate trên 2020-2026?

---

**Files**:
- [pine/v1/strategy_multi_indicator_v10.pine](../../pine/v1/strategy_multi_indicator_v10.pine) — baseline
- [pine/v1/strategy_multi_indicator_v11A.pine](../../pine/v1/strategy_multi_indicator_v11A.pine) — Group A tuned
- [docs/reports/MIS_v1_v10_90trades_analysis.md](MIS_v1_v10_90trades_analysis.md) — báo cáo phân tích v10 trước đó
