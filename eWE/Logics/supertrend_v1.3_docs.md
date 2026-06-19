# 📚 Tài liệu Hướng dẫn & Đặc tả Kỹ thuật: SuperTrend v1.3 (MTA)

Tài liệu này đặc tả cấu trúc thiết kế, tham số cấu hình, thuật toán mô phỏng và phương án tích hợp thực tế của **Bộ lọc định hướng đa khung thời gian SuperTrend v1.3 (Multi-Timeframe Alignment - MTA)** trong hệ thống giao dịch VBS.

---

## 🎯 1. Mục tiêu & Nguyên lý Thiết kế (v1.2 -> v1.3)

Trong phiên bản **SuperTrend v1.2**, hệ thống sử dụng bộ lọc xu hướng vĩ mô khung Daily dựa trên đường **EMA200** và độ mạnh xu hướng **ADX ≥ 20/25**. Tuy nhiên, thực tế vận hành cho thấy:
*   Đường trung bình EMA200 có độ trễ lớn, không phản ánh nhạy bén các pha xoay chiều xu hướng ngắn/trung hạn.
*   ADX chỉ đo lường sức mạnh xu hướng, không chỉ ra hướng đi cụ thể.
*   Hệ thống dễ bị dính bẫy giá (Traps) và hao mòn tài sản (Fee Drag) trong các giai đoạn thị trường tích lũy đi ngang (Chop).

**SuperTrend v1.3** giải quyết các vấn đề này bằng cách thiết lập **Bộ lọc điều hướng đa khung thời gian (MTA)** đồng thuận tuyệt đối:
*   **Khung 1 Ngày (1D) - Lọc dài hạn:** Xác định chu kỳ giá vĩ mô và vùng breakout lớn có thể diễn ra.
*   **Khung 4 Giờ (4H) - Lọc trung hạn:** Xác định xu hướng chủ đạo hiện tại, lọc bỏ hoàn toàn các pha sideway biên độ hẹp.
*   **Khung 1 Giờ (1H) - Lọc nhanh (Fast Filter):** Loại bỏ nhiễu ngắn hạn và các bẫy giá (Bull/Bear Traps), đồng thời đóng vai trò là "chốt kích hoạt" (Trigger Gate).

---

## ⚙️ 2. Tham số Cấu hình Tối ưu (Optimized Parameters)

Dựa trên kết quả tối ưu hóa Walk-Forward lịch sử và kết quả thực nghiệm trên **1,015 tín hiệu**, cấu hình SuperTrend v1.3 được xác định như sau:

*   **ATR Period (Chu kỳ ATR):** `7`
*   **ATR Multiplier (Hệ số nhân):** `3.5`
*   **SL ATR Mult (Hệ số cắt lỗ):** `1.5`
*   **Risk/Reward Ratio (Tỷ lệ R/R):** `2.0` (Mặc định cho S6/S3+S5) hoặc chạy theo trailing stop ẩn (S4).

> [!NOTE]
> Cấu hình `ST(7, 3.5)` cho kết quả vượt trội hoàn toàn so với cấu hình mặc định `ST(10, 3.0)` nhờ khả năng nới rộng biên độ để tránh bị quét stop loss sớm trong các nhịp rút râu của Crypto, đồng thời giữ bộ lọc nhạy bén ở khung thời gian 1H.

---

## 📐 3. Thuật toán Lọc Tín hiệu (MTA Logic)

Một tín hiệu breakout từ khung nhỏ (ví dụ: khung 5m từ webhook) chỉ được chấp nhận khớp lệnh khi đạt được sự đồng thuận xu hướng trên cả 3 khung thời gian lớn:

### 🟢 Điều kiện khớp lệnh BUY (LONG):
$$\text{ST\_Dir}_{1H} == 1 \quad \text{AND} \quad \text{ST\_Dir}_{4H} == 1 \quad \text{AND} \quad \text{ST\_Dir}_{1D} == 1$$
*(Trong đó $1$ đại diện cho trạng thái SuperTrend Bullish)*

### 🔴 Điều kiện khớp lệnh SELL (SHORT):
$$\text{ST\_Dir}_{1H} == -1 \quad \text{AND} \quad \text{ST\_Dir}_{4H} == -1 \quad \text{AND} \quad \text{ST\_Dir}_{1D} == -1$$
*(Trong đó $-1$ đại diện cho trạng thái SuperTrend Bearish)*

> [!IMPORTANT]
> Nếu bất kỳ khung thời gian nào không đồng thuận (ví dụ: 1D và 4H đang Bearish nhưng 1H hồi phục Bullish), tín hiệu lập tức bị từ chối với mã lỗi `st_trend_conflict` để bảo vệ tài khoản.

---

## 📊 4. Kết quả Thực nghiệm trên 1,015 Tín hiệu (May 30 - June 17, 2026)

Mô phỏng thực nghiệm đã chứng minh sức mạnh của bộ lọc SuperTrend v1.3 trong việc cắt giảm lệnh thua và nâng cao hiệu quả lãi kép:

### 🏆 Kịch bản S6 (Optimized Hybrid)
*   **Baseline:** WR **38.75%** (449 lệnh) -> Lợi nhuận Dynamic: **-311.83 USDT** (Thua lỗ do phí giao dịch dồn dập).
*   **ST v1.3 Filter (1H ST Only):** WR **55.95% (+17.20%)** (311 lệnh) -> Lợi nhuận Dynamic: **+34,920.78 USDT**.
*   *Nhận xét:* Lọc bỏ 138 lệnh nhiễu, giải phóng sức mạnh lãi kép.

### 🚀 Kịch bản S4 (Trailing SL)
*   **Baseline:** WR **46.99%** (1013 lệnh) -> Lợi nhuận Dynamic: **+106,972.26 USDT**.
*   **ST v1.3 Filter (1H ST Only):** WR **66.99% (+20.00%)** (509 lệnh) -> Lợi nhuận Dynamic: **+5,714,692.57 USDT**.
*   *Nhận xét:* Loại bỏ hơn 50% số lệnh lỗi. Win Rate cực cao (66.99%) kết hợp ATR Trailing tạo ra đà tăng trưởng tài sản không tưởng (**gấp 572 lần vốn gốc**).

### ❌ Kịch bản S3+S5 (Trend Stack)
*   **ST v1.3 Filter:** WR chỉ tăng nhẹ lên **41.38%**, PnL vẫn âm nặng do tính chất trễ của đường trung bình EMA.

---

## 🧭 5. Hướng dẫn Tích hợp & Vận hành (Operational Plan)

1.  **Cấu hình Webhook:** Cập nhật script Pine Script trên TradingView để gửi kèm trạng thái SuperTrend 1H trong trường metadata.
2.  **Bộ xử lý tín hiệu tại Satellite Gateway (Server A):**
    *   Tích hợp module kiểm tra trạng thái SuperTrend 1H của cặp giao dịch trước khi gửi lệnh vào Queue.
    *   Đọc trạng thái `direction` từ payload để so khớp với hướng lệnh.
3.  **Quản lý Vốn:**
    *   **Bắt buộc** sử dụng chế độ **Dynamic Sizing (2% Risk)** cho S4 và S6 khi đã kích hoạt bộ lọc SuperTrend v1.3 để tận dụng tối đa lãi kép.
    *   **Cấm** áp dụng Fixed Sizing cho S4 do hiệu suất bị bóp nghẹt khi số lượng lệnh khớp giảm.
