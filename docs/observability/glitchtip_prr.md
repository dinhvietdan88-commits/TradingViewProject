# Production Readiness Review (PRR): GlitchTip Checklist

Tài liệu này xác lập quy trình Đánh giá sẵn sàng vận hành (Production Readiness Review - PRR) nhằm kiểm tra và xác nhận hệ thống giám sát **GlitchTip** đã đủ điều kiện an toàn để nâng cấp lên giao dịch tiền thật (Real Money).

---

## 1. Bảng kiểm tra Sẵn sàng (Readiness Checklist)

Trước khi kích hoạt chế độ giao dịch tiền thật (`FORCE_LIVE_TRADING=true`), quản trị viên bắt buộc phải kiểm tra và đánh dấu hoàn thành các hạng mục sau:

- [ ] **1. Xác thực Kết nối GlitchTip thành công:**
  * Sentry DSN đã cấu hình đúng trong `.env.production`.
  * Bot gọi thử endpoint test `/api/debug-sentry` và ghi nhận lỗi xuất hiện trên giao diện GlitchTip thành công.
- [ ] **2. Kiểm tra bộ lọc dữ liệu nhạy cảm (PII & Credentials Scrubbing):**
  * Chạy thử lệnh đặt lỗi với API Key giả lập và xác nhận trong log sự kiện gửi lên GlitchTip, trường `api_key` hoặc `secret` hiển thị là `[SCRUBBED]`.
- [ ] **3. Cấu hình Kênh Cảnh báo Telegram:**
  * Webhook gửi tin nhắn của GlitchTip kết nối đúng tới Telegram Bot quản trị.
  * Đã test nhận được tin nhắn cảnh báo khi giả lập lỗi `FATAL`.
- [ ] **4. Uptime Check hoạt động ổn định:**
  * GlitchTip Monitor VPS đã cấu hình ping HTTP GET tới `/health` của VPS giao dịch.
  * Đèn tín hiệu hiển thị màu xanh (UP).
- [ ] **5. Tích hợp Metrics Prometheus & Grafana:**
  * Prometheus của EAIS đã kết nối và kéo được dữ liệu từ endpoint `/metrics`.
  * Dashboard Grafana hiển thị chính xác các chỉ số tài sản, trạng thái Circuit Breaker.

---

## 2. Kiểm thử Tải & Giả lập Sự cố (Chaos Testing Guide)

Để đảm bảo hệ thống giám sát không bị treo hoặc mất dữ liệu khi thị trường biến động mạnh (Fast Breakouts):

1. **Giả lập lỗi hàng loạt (Burst Errors):**
   * Sử dụng lệnh curl gọi liên tục 50 webhook giả lập lỗi tới bot trong 5 giây.
   * *Yêu cầu:* GlitchTip không bị treo cơ sở dữ liệu, hiển thị lỗi phân nhóm thông minh (Grouped Events) và gửi cảnh báo gộp để tránh làm nhiễu Telegram.
2. **Giả lập sập kết nối mạng sàn (API Network Outage):**
   * Chặn tạm thời cổng kết nối tới API sàn Bybit/Weex trên tường lửa của VPS giao dịch.
   * Gửi tín hiệu trade thử nghiệm.
   * *Yêu cầu:* Bot tự động chuyển đổi sang sàn dự phòng, Sentry ghi nhận lỗi `CONNECTION_ERROR` với nhãn Warning/Error, và gửi thông báo Telegram về sự kiện chuyển hướng thành công.
3. **Giả lập sập nguồn VPS giao dịch (Power Outage Simulation):**
   * Tắt tạm thời FastAPI Server của bot giao dịch.
   * *Yêu cầu:* Trong vòng 180 giây, Monitor VPS gửi cảnh báo **[CRITICAL] Trading VPS is UNREACHABLE** tới Telegram của quản trị viên.

---

## 3. Quy trình Rút lui & Khôi phục (Rollback Protocol)

Nếu phát hiện hệ thống giám sát gây ảnh hưởng tiêu cực đến tốc độ đặt lệnh của bot giao dịch:

1. **Vô hiệu hóa Sentry khẩn cấp:**
   * Xóa hoặc comment dòng cấu hình `SENTRY_DSN` trong file `.env` hoặc `.env.production`.
   * Khởi động lại FastAPI Server. Sentry SDK sẽ tự động tắt và không gửi bất kỳ request mạng nào ra ngoài, trả lại 100% tài nguyên cho bot.
2. **Khôi phục cấu hình Prometheus:**
   * Tạm dừng hoặc xóa cấu hình scrape target `tradingview_project` trong file `prometheus.yml` trên Monitor VPS nếu I/O đĩa bị quá tải.
