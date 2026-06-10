# Kế Hoạch Triển Khai: Tích Hợp Đồ Thị Đa Phương Án Lên Telegram

Kế hoạch này mô tả chi tiết phương án thiết kế và tích hợp bộ vẽ đồ thị đa dạng (Matplotlib offline, Playwright CDP screenshot, mô hình toán học SEPA) vào luồng cảnh báo của Telegram Bot.

---

## 🔒 Yêu Cầu Thiết Kế

1. **Phương án 1 (Local Matplotlib):** Render nến offline từ dữ liệu OHLCV tải qua exchange REST API/CCXT, vẽ đè các mốc giá Entry/SL/TP.
2. **Phương án 2 (TradingView CDP Screenshot):** Kết nối qua cổng CDP `9222` tới phiên TradingView thực tế, đổi mã cảnh báo, tự động crop tỉ lệ `1200x700`. Có cơ chế tự động fallback về Matplotlib khi mất kết nối CDP.
3. **Phương án 3 (VCP/SEPA Pattern Visualizer):** Render mô hình toán học lý thuyết (VCP, Cup & Handle, Double Bottom) tối màu chuẩn TradingView và tích hợp semantic matching từ AI Core.
4. **HTML Safe Caption & Chunking:** Giải quyết triệt để lỗi parse HTML của Telegram khi cắt ngắn caption ảnh (giới hạn 1024 ký tự) và chia nhỏ tin nhắn dài hơn 4096 ký tự mà không làm vỡ các thẻ HTML.

---

## 🛠️ Các Cấu Phần Thay Đổi

### 1. Client Chụp Ảnh Đồ Thị
* **File**: `server/capture_client.py`
* **Nhiệm vụ**:
  - Tích hợp phương thức capture `"tv-cdp-real"` kết nối qua Playwright CDP.
  - Xây dựng cơ chế đổi symbol/resolution thông qua việc đánh giá biểu đồ của TradingView API.
  - Tải dữ liệu nến đồng thời (asyncio.gather) và cache nến để tối ưu hóa hiệu suất vẽ biểu đồ cục bộ.
  - Thực hiện crop và resize ảnh về tỉ lệ chuẩn bằng Pillow LANCZOS.

### 2. Bộ Vẽ Đồ Thị Cục Bộ
* **File**: `server/utils/chart_generator_mpl.py`
* **Nhiệm vụ**:
  - Thiết lập theme tối chuẩn TradingView cho Matplotlib (`#131722`).
  - Xây dựng mô hình vẽ sóng co hẹp biến động (T1, T2, T3) cho mẫu hình VCP.
  - Xây dựng mô hình vẽ đáy tròn cốc và kênh giá dốc xuống của Handle cho mẫu hình Cup & Handle.
  - Xây dựng mô hình vẽ chữ W với đáy 2 thấp hơn đáy 1 cho mẫu hình Double Bottom.

### 3. Cổng Bot Telegram & Phân Mảnh Tin Nhắn
* **File**: `server/telegram_bot.py`
* **Nhiệm vụ**:
  - Nâng cấp `send_interactive_trade_approval` và `send_interactive_indicator_alert` nhận tham số `photo_path`.
  - Triển khai hàm `truncate_caption_html_safe` để dọn sạch tag HTML trước khi cắt caption của ảnh gửi đi.
  - Triển khai hàm `chunk_html_message` sử dụng tag stack để phân chia tin nhắn lớn thành các phần dưới 4096 ký tự và cân bằng các thẻ HTML qua các biên phân khúc.

---

## 🧪 Kế Hoạch Xác Minh (Verification Plan)

### Kiểm Thử Đơn Vị (Unit Tests)
- Kiểm tra cache nến, fallback và định tuyến capture trong `test_capture_client_routing.py`.
- Kiểm tra tính đúng đắn của việc sinh đồ thị nến cơ bản trong `test_chart_generators.py`.
- Kiểm tra việc render các đường mô hình toán học VCP/Cup/Double Bottom trong `test_pattern_detector.py` và `test_pattern_challenger.py`.
- Kiểm tra tính ổn định của luồng gửi Telegram, chunking và dọn dẹp caption trong `test_telegram_bot_p8.py`, `test_telegram_chart_rendering.py`, `test_pattern_overlay_integration.py`.

### Kiểm Thử Hệ Thống (Integration Tests)
- Chạy tích hợp E2E Server A -> Server C thông qua `test_server_a_c_integration.py`.
- Sử dụng bộ script `verify_server_c_gaps.py` để kiểm tra cổng kết nối, seeding ChromaDB và cơ chế shutdown an toàn của AI Core.
