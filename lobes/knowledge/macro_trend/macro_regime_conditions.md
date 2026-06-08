# Kiến thức Nền tảng: Phân loại Trạng thái và Lọc Xu hướng Vĩ mô
## (Macro Regime & Trend Filtering Knowledge Base)

Tài liệu này xác định các quy tắc lọc thô và đánh giá xu hướng vĩ mô (Multi-Timeframe Alignment) áp dụng cho hệ thống tự động xử lý tín hiệu giao dịch.

---

## 1. Định nghĩa Trạng thái Vĩ mô (Macro Regimes)

Thị trường được chia làm 3 trạng thái vĩ mô chính dựa trên độ biến động và hướng đi của giá:

1.  **TREND (Xu hướng rõ ràng)**:
    *   Giá liên tục tạo đỉnh cao hơn/đáy cao hơn (Bullish) hoặc đỉnh thấp hơn/đáy thấp hơn (Bearish).
    *   Các lệnh giao dịch thuận xu hướng được ưu tiên tối đa.
2.  **CHOP (Tích lũy / Biến động không xu hướng)**:
    *   Giá đi ngang trong một biên độ hẹp (Range-bound) hoặc dao động nhiễu.
    *   *Quy tắc:* Cấm mở vị thế BUY/SELL dài hạn (Daily MTT) trong vùng CHOP.
3.  **CRASH (Rơi tự do / Hoảng loạn)**:
    *   Thị trường giảm mạnh đột ngột với khối lượng lớn.
    *   *Quy tắc:* Circuit Breaker kích hoạt lập tức, ngắt toàn bộ lệnh BUY mới.

---

## 2. Tiêu chuẩn Đánh giá Xu hướng Lớn (MTA Criteria)

Hệ thống đánh giá xu hướng lớn thông qua việc đối chiếu Đường trung bình động đơn giản (Simple Moving Average - SMA) trên các khung thời gian lớn:

*   **Khung thời gian 1 Ngày (1D)**:
    *   *SMA 50 ngày (SMA_Daily)*: Xu hướng vĩ mô chủ đạo.
    *   *Điều kiện Bullish Daily:* Giá đóng cửa phiên gần nhất nằm **trên** SMA 50.
    *   *Điều kiện Bearish Daily:* Giá đóng cửa phiên gần nhất nằm **dưới** SMA 50.
*   **Khung thời gian 4 Giờ (4H)**:
    *   *SMA 50 chu kỳ (SMA_4H)*: Xu hướng trung hạn hỗ trợ.
    *   *Điều kiện Bullish 4H:* Giá đóng cửa gần nhất nằm **trên** SMA 50.
    *   *Điều kiện Bearish 4H:* Giá đóng cửa gần nhất nằm **dưới** SMA 50.

---

## 3. Quy tắc Phủ quyết Tín hiệu (Macro Veto Rules)

Để tránh mở vị thế ngược xu hướng vĩ mô cực đoan, `MacroTrendProcessor` áp dụng quy tắc lọc thô sau:

*   **Từ chối lệnh BUY (Mua)**:
    *   Khi cả khung 1D và khung 4H đồng thuận Bearish tuyệt đối:
        $$\text{Latest Close}_{1D} < \text{SMA}_{1D} \quad \text{AND} \quad \text{Latest Close}_{4H} < \text{SMA}_{4H}$$
    *   *Hành vi:* Báo lỗi `macro_trend_conflict` và hủy bỏ tín hiệu ngay lập tức.
*   **Từ chối lệnh SELL (Bán)**:
    *   Khi cả khung 1D và khung 4H đồng thuận Bullish tuyệt đối:
        $$\text{Latest Close}_{1D} > \text{SMA}_{1D} \quad \text{AND} \quad \text{Latest Close}_{4H} > \text{SMA}_{4H}$$
    *   *Hành vi:* Báo lỗi `macro_trend_conflict` và hủy bỏ tín hiệu ngay lập tức.
