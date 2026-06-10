# Incident Response SOP: Quy trình Xử lý Sự cố Vận hành

Tài liệu này hướng dẫn các bước hành động tiêu chuẩn (SOP) dành cho quản trị viên/trader khi nhận được thông báo sự cố từ hệ thống giám sát **GlitchTip** và **Telegram Alerts**.

---

## SOP-01: Xử lý Cảnh báo Lỗi OCO (Orphan Position Risk - Mức FATAL)

### 1. Hiện tượng kích hoạt:
Telegram nhận tin nhắn cảnh báo màu đỏ: `[FATAL] OCO Exit Order placement FAILED for symbol <SYMBOL>`. Có nguy cơ vị thế bị mồ côi (không có stop-loss/take-profit bảo vệ).

### 2. Các bước xử lý khẩn cấp:
1. **Kiểm tra trạng thái vị thế (mục tiêu trong 60 giây):**
   * Mở ứng dụng Telegram và gõ lệnh `/positions` gửi tới bot giao dịch để xem vị thế hiện tại của mã `<SYMBOL>`.
   * Hoặc đăng nhập trực tiếp vào giao diện web/mobile của sàn giao dịch (Weex/Bybit/Binance).
2. **Quyết định Hành động:**
   * **Phương án A (Khuyên dùng): Đóng vị thế thủ công ngay lập tức.**
     * Nhấp vào nút tương tác **[ĐÓNG VỊ THẾ KHẨN CẤP]** trên tin nhắn Telegram của bot, hoặc đặt lệnh Market CLOSE trực tiếp trên giao diện sàn giao dịch.
   * **Phương án B: Đặt lại SL/TP thủ công trên sàn.**
     * Nếu anh muốn giữ vị thế: Đăng nhập sàn, tạo thủ công một lệnh điều kiện (Trigger Order/OCO) cho mã đó với mức giá SL/TP được chỉ rõ trong cảnh báo Telegram.
3. **Kiểm tra khóa an toàn:**
   * Sau sự cố lỗi đặt OCO, Circuit Breaker tự động chuyển sang trạng thái `OPEN` để ngắt kết nối.
   * Sau khi đã đóng vị thế hoặc đặt xong SL/TP thủ công, gõ lệnh `/cb_close <EXCHANGE>` trên Telegram bot để khôi phục trạng thái vận hành của bot.

---

## SOP-02: Xử lý Sự cố Sập nguồn VPS Giao dịch (VPS OFFLINE - Mức FATAL)

### 1. Hiện tượng kích hoạt:
Telegram nhận tin nhắn từ Monitor VPS: `[CRITICAL] Trading VPS is UNREACHABLE! Uptime probe failed for 3 consecutive cycles.`

### 2. Các bước xử lý khẩn cấp:
1. **Kiểm tra vật lý VPS (mục tiêu trong 3 phút):**
   * Thử ping trực tiếp tới địa chỉ IP của VPS giao dịch.
   * Đăng nhập vào bảng điều khiển VPS (Hetzner Console / DigitalOcean Dashboard) xem trạng thái máy ảo (Active hay Power Off).
2. **Khởi động lại dịch vụ:**
   * Nếu VPS vẫn chạy bình thường nhưng API treo: SSH vào VPS giao dịch và khởi động lại FastAPI Server:
     ```bash
     sudo systemctl restart trading-bot
     ```
   * Kiểm tra log hoạt động để tìm nguyên nhân:
     ```bash
     tail -n 100 /opt/trading-bot/logs/trading.log
     ```
3. **Xác nhận trạng thái khôi phục:**
   * Kiểm tra tin nhắn Telegram xác nhận: `🟢 SERVER ONLINE - Health monitoring resumed.`
   * Gõ lệnh `/health` trên Telegram bot để đảm bảo bot phản hồi bình thường.

---

## SOP-03: Mở khóa Circuit Breaker sau khi đã Trip (Mức ERROR/FATAL)

### 1. Hiện tượng kích hoạt:
Circuit Breaker bị kích hoạt nhảy sang `OPEN` do tài khoản vượt ngưỡng lỗ ngày (`daily_loss_cap`) hoặc sụt giảm tài sản (`drawdown_cap`). Bot bỏ qua toàn bộ tín hiệu giao dịch mới.

### 2. Các bước xử lý khẩn cấp:
1. **Đánh giá rủi ro tài chính:**
   * Xem báo cáo thống kê qua lệnh `/report_today` hoặc xem Grafana Dashboard để biết nguyên nhân thua lỗ hàng loạt (do thị trường thay đổi regime, trượt giá quá sâu, hay bot bị lỗi loop đặt lệnh).
2. **Xác định thời điểm mở khóa:**
   * **Nếu do vượt ngưỡng lỗ ngày:** Đợi qua thời điểm 00:00 (Reset ngày mới) hệ thống sẽ tự động chuyển trạng thái Circuit Breaker về `CLOSED` (mở khóa).
   * **Nếu cần giao dịch lại ngay lập tức (Bypass khẩn cấp):**
     * Gõ lệnh `/cb_bypass <EXCHANGE> <HOURS>` trên Telegram (ví dụ: `/cb_bypass weex 4` để bỏ qua khóa CB trong 4 giờ tiếp theo).
3. **Kiểm tra trạng thái:**
   * Gõ lệnh `/status` trên Telegram bot để đảm bảo trường `Circuit Breaker` đã chuyển về `CLOSED` hoặc `BYPASS_ACTIVE`.
