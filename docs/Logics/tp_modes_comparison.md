# 📊 Phân Tích Chức Năng: Trailing Stop TP vs Default TP (Fixed RRR)

Bản nâng cấp **MIS(A7-01B.V3) Webhook** (phiên bản V3.2) hỗ trợ hai chế độ chốt lời (Take Profit - TP) cốt lõi: **Default TP (Fixed RRR)** và **Trailing Stop TP**. Dưới đây là phân tích chi tiết về logic hoạt động, cơ chế hiển thị visual trên chart và cấu trúc payload webhook của từng chế độ dựa trên mã nguồn và các ảnh chụp màn hình thực tế.

---

## 📸 Tổng Quan Trực Quan (Visual Analysis)

Dựa trên 3 ảnh chụp màn hình trong quá trình Replay lệnh **Long Entry** ở mức giá **77,617.3**:

### 1. Trạng thái ban đầu sau Entry (Screenshot 2)
* **Thông số**: `SL (ATR 2.0)` = **76,989.0** (Khoảng cách SL = `628.2`). `Trail ATR Multiplier` = **1.5**.
* **Trailing Stop ban đầu**: Được tính bằng `entryPrice - atrVal * trailMul` = **77,146.1**.
* **Visual**:
  * Đường **SL màu đỏ nét đứt** ở dưới cùng (76,989.0).
  * Đường **Trailing Stop màu cam (nét đứt kèm mũi tên)** nằm giữa Entry và SL (77,146.1).
  * **Vùng Risk (Hộp đỏ)** vẽ từ Entry xuống SL.
  * **Vùng Reward (Hộp xanh)** vẽ từ Entry xuống Trailing Stop. Vì Trailing Stop ban đầu nằm dưới Entry, hai hộp màu đỏ và xanh đè lên nhau tạo thành **vùng màu nâu/cam tối**.

### 2. Giá bắt đầu tăng nhẹ (Screenshot 1)
* **Trailing Stop cập nhật**: Khi giá tạo đỉnh cao hơn (`high`), đường Trailing Stop được đẩy lên mức **77,285.6** (cơ chế khóa lợi nhuận / giảm thiểu rủi ro).
* **Visual**: Đường màu cam dịch chuyển dần lên phía đường Entry. Vùng chồng lấn màu nâu/cam thu hẹp lại.

### 3. Giá tăng mạnh đột phá (Screenshot 3)
* **Trailing Stop vượt Entry**: Khi giá tăng mạnh lên vùng ~78,147, Trailing Stop được kéo lên **77,676.0** (vượt qua giá Entry **77,617.3**).
* **Visual**:
  * Lúc này, đường Trailing Stop nằm **phía trên** đường Entry.
  * Vùng Risk (màu đỏ) vẫn cố định ở dưới Entry (bảo vệ khoảng lỗ ban đầu).
  * Vùng Reward (màu xanh lá) lúc này kéo từ Entry lên đến Trailing Stop (ở phía trên). Không còn sự chồng lấn màu sắc, tạo ra giao diện **Forecasting Long** chuẩn mực (Xanh lá ở trên, Đỏ ở dưới). Lợi nhuận tối thiểu lúc này đã được khóa lại chắc chắn.

---

## 🔍 So Sánh Chi Tiết Hai Chế Độ TP

| Đặc tính | Default TP (Fixed RRR) | Trailing Stop TP |
| :--- | :--- | :--- |
| **Bản chất** | **Chốt lời tĩnh** (Tỉ lệ cố định) | **Chốt lời động** (Theo sát xu hướng) |
| **Mức TP ban đầu** | $TP = Entry \pm (SL\_Dist \times RRR)$ | Không có mức TP cố định. Khởi tạo mức Trail ban đầu cách Entry một khoảng ATR: $Trail = Entry \mp (ATR \times Trail\_Mul)$ |
| **Cơ chế cập nhật** | Cố định xuyên suốt thời gian giữ lệnh. | Tự động cập nhật theo mỗi nến đóng cửa (chỉ dịch chuyển theo chiều có lợi - Ratchet Mechanism). |
| **Đường hiển thị** | `tpLine` (Màu xanh lá nét đứt). | `trailLine` (Màu cam nét đứt có mũi tên chỉ hướng). |
| **Nhãn giá** | `tpLabel` hiển thị giá TP và RRR thực tế (Ví dụ: `TP: 79810.0 (+2197.0) R:R 3.5`). | `trailLabel` hiển thị giá trị dừng lỗ động hiện tại (Ví dụ: `TRAIL: 77285.6`). |
| **Vùng Forecast** | Hộp màu xanh lá cố định từ Entry đến TP. | Hộp màu xanh lá co giãn động từ Entry đến đường Trailing Stop hiện tại. |
| **Điều kiện Exit** | 1. Đạt mức TP tĩnh.<br>2. Vi phạm EMA crossover (Exit sớm).<br>3. Bị chạm SL cứng. | 1. Giá đóng cửa vi phạm đường Trailing Stop (`close <= trailStop` đối với Long).<br>2. Vi phạm EMA crossover (Exit sớm). |

---

## 💻 Logic Code Pine Script (V6)

Dưới đây là cách mà hai chế độ này được phân nhánh trong mã nguồn:

### 1. Khởi tạo khi vào lệnh (Entry)
```pine
if longCondition
    signalDir  := 1
    entryPrice := close
    slDist      = calcSlDist()
    slPrice    := close - slDist
    tpPrice    := close + slDist * activeRRR
    trailStop  := close - atrVal * trailMul // Khởi tạo trail stop dưới entry

    // Phân nhánh hiển thị đường nét đứt
    if showSlTp and tpMode == "Fixed RRR"
        tpLine := line.new(..., tpPrice, ...)
    if showSlTp and tpMode == "Trailing Stop"
        trailLine := line.new(..., trailStop, ..., style=line.style_arrow_right)
```

### 2. Cập nhật động theo từng nến (Chỉ áp dụng cho Trailing Stop)
```pine
if tpMode == "Trailing Stop" and signalDir == 1 and not longCondition
    newTrail = high - atrVal * trailMul
    if newTrail > nz(trailStop, 0.0)
        trailStop := newTrail // Chỉ dịch chuyển lên, không bao giờ dịch chuyển xuống

    // Cập nhật lại vị trí đường và nhãn cam trên chart
    line.set_y1(trailLine, trailStop)
    line.set_y2(trailLine, trailStop)

    // Điều chỉnh vùng hộp dự báo (Reward Box) co giãn theo trailStop
    box.set_top(rewardBox, trailStop)
```

---

## 📡 Khác Biệt Trong Payload Webhook

Khi tín hiệu được trigger để gửi về FastAPI server, payload của cả hai chế độ sẽ mang các thông số cấu hình khác nhau trong phần `metadata` để Server-side Executer (ví dụ: `trade_engine.py`) xử lý lệnh chính xác trên sàn giao dịch:

### 1. Webhook Payload - Default TP (Fixed RRR)
* Server sẽ đặt lệnh **Limit Order** tại mức giá `tp` tĩnh ngay khi vào lệnh.
```json
{
  "secret": "REPLACE_WITH_WEBHOOK_SECRET",
  "source": "indicator",
  "indicator_name": "MIS(A7-01B.V3)",
  "version": "V3.2",
  "symbol": "BTCUSDT",
  "signal_type": "entry",
  "action": "buy",
  "price": "77617.3",
  "interval": "60",
  "exchange": "BINANCE",
  "confidence_score": 85,
  "metadata": {
    "direction": "long",
    "atr_value": "314.15",
    "sl": "76989.0",
    "tp": "79817.5", // Mức chốt lời tĩnh (RRR 3.5)
    "rrr_ratio": "3.5",
    "rrr_preset": "Aggressive (3.5:1)",
    "sl_mode": "ATR",
    "tp_mode": "Fixed RRR",
    "trail_stop": "0.0" // Không sử dụng trailing
  }
}
```

### 2. Webhook Payload - Trailing Stop TP
* Server sẽ sử dụng mức `sl` ban đầu làm Stop Loss cứng, và liên tục lắng nghe cập nhật hoặc tự động tính toán dịch chuyển Stop Loss (Trailing) theo thời gian thực dựa trên ATR.
```json
{
  "secret": "REPLACE_WITH_WEBHOOK_SECRET",
  "source": "indicator",
  "indicator_name": "MIS(A7-01B.V3)",
  "version": "V3.2",
  "symbol": "BTCUSDT",
  "signal_type": "entry",
  "action": "buy",
  "price": "77617.3",
  "interval": "60",
  "exchange": "BINANCE",
  "confidence_score": 85,
  "metadata": {
    "direction": "long",
    "atr_value": "314.15",
    "sl": "76989.0",
    "tp": "0.0", // Không có TP tĩnh
    "rrr_ratio": "3.5",
    "rrr_preset": "Aggressive (3.5:1)",
    "sl_mode": "ATR",
    "tp_mode": "Trailing Stop",
    "trail_stop": "77146.1" // Giá trị kích hoạt dừng lỗ động ban đầu
  }
}
```

---

## 💡 Đánh Giá Hướng Sử Dụng (Recommendations)

1. **Khi nào dùng Default TP (Fixed RRR)**:
   * Phù hợp với thị trường **Sideway (Range-bound)**, dao động trong biên độ tích lũy nơi giá thường đảo chiều sau khi đạt các kháng cự/hỗ trợ kỹ thuật.
   * Giúp hiện thực hóa lợi nhuận nhanh chóng tại các mốc RRR toán học tối ưu mà không lo sợ giá quay đầu mất lãi.

2. **Khi nào dùng Trailing Stop TP**:
   * Phù hợp tối đa khi giao dịch trong thị trường **Có Xu Hướng Mạnh (Strong Trend / Rally)**.
   * Giúp "gồng lãi" tối đa, tối ưu hóa lợi nhuận khi có những sóng tăng/giảm dài hạn vượt trội hơn nhiều so với mốc RRR 3.5 định sẵn.
   * Bảo vệ vốn cực tốt vì khi giá đi đúng hướng, rủi ro ban đầu (`SL`) được kéo dần về hòa vốn (`Entry`) và chuyển thành khóa lãi.
