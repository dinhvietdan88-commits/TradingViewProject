# Hướng dẫn Kiểm thử (Backtest) Pine Script Minervini Trend Template

Tài liệu này hướng dẫn cách kiểm thử và sử dụng công cụ Pine Script `minervini_trend_template.pine` một cách khoa học và hiệu quả nhất trên nền tảng TradingView.

## 1. Kiểm thử trực quan bằng "Bar Replay" (Khuyên dùng)
Hệ thống SEPA của Mark Minervini phụ thuộc rất lớn vào phân tích hành vi giá và khối lượng (Price Action & Volume) bằng mắt thường, đặc biệt là mẫu hình Thu hẹp biến động (VCP). Máy móc khó có thể nhận diện đúng 100% ngữ cảnh thị trường.

*   **Bước 1:** Chọn một siêu cổ phiếu trong quá khứ có chu kỳ tăng giá mạnh (Ví dụ: `TSLA` năm 2020, `AAPL` năm 2019, hoặc ở thị trường VN là `DGC` năm 2021, `FPT` năm 2023).
*   **Bước 2:** Bật tính năng **Bar Replay** trên TradingView (biểu tượng Play trên thanh công cụ) và cắt biểu đồ lùi về thời điểm trước khi cổ phiếu bứt phá khoảng 1-2 tháng.
*   **Bước 3:** Cho nến chạy từng ngày.
*   **Bước 4 (Quan sát):** Chú ý khoảnh khắc thanh nến đổi sang **Màu Xanh Lá** (thỏa mãn 8 tiêu chí Trend Template) và xuất hiện mũi tên **VCP** màu tím. Đánh giá xem lúc đó cổ phiếu có đang tích lũy kiến tạo hay không.

## 2. Tránh "Bẫy Repaint" (Làm sai lệch tín hiệu)
*   **Khung thời gian:** Hệ thống của Minervini được thiết kế để giao dịch trên khung **Ngày (Daily)** hoặc **Tuần (Weekly)**. KHÔNG sử dụng Indicator này trên các khung thời gian ngắn như 15 phút, 1 giờ vì độ nhiễu rất cao.
*   **Chờ đóng nến:** Tín hiệu chuẩn xác nhất là khi **Nến Ngày đã đóng cửa**. Trong phiên giao dịch, giá có thể dao động làm nến đổi màu xanh, nhưng đến cuối phiên giá sập xuống làm mất đi tiêu chí Trend Template. Tuyệt đối không mua đuổi khi nến chưa đóng.

## 3. Nâng cấp lên Strategy (Automated Backtesting)
Hiện tại công cụ đang ở dạng `indicator()` nhằm mục đích hỗ trợ soi biểu đồ trực quan. Nếu muốn TradingView tự động tính toán Win Rate, Lợi nhuận và Max Drawdown:
*   Cần chuyển đổi hàm `indicator()` thành `strategy()`.
*   Cần định nghĩa **Điểm Mua (Entry)**: Mua khi nến xanh + có tín hiệu VCP.
*   Cần định nghĩa **Điểm Cắt Lỗ (Stoploss)**: Đây là yếu tố sống còn (Ví dụ: tự động cắt lỗ khi rớt -8% từ điểm mua, hoặc thủng đường SMA 50).

## 4. Forward Testing (Chạy thử nghiệm thực tế)
Trước khi giao dịch bằng tiền thật với hệ thống này:
*   **Tạo Alerts:** Đặt cảnh báo (Alert) trên TradingView cho công cụ này. Hệ thống sẽ gửi thông báo đến điện thoại mỗi khi có cổ phiếu thỏa mãn điều kiện.
*   **Trading Journal:** Ghi chép lại các tín hiệu báo mua vào file Excel trong 1-2 tháng. Theo dõi xem giá cổ phiếu đi như thế nào sau tín hiệu đó.
*   **Điều kiện thực chiến:** Chỉ bắt đầu dùng tiền thật khi bạn thấy tỷ lệ Win Rate > 50% và Tỷ lệ Lợi nhuận/Rủi ro (Reward/Risk ratio) lớn hơn 2:1 trên dữ liệu Forward Test của bạn.
