# Automatic Risk Response Design (ARD): Observability Safety Gates

Tài liệu này xác lập cơ chế phản hồi rủi ro tự động (Automatic Risk Response) dựa trên tín hiệu giám sát từ **GlitchTip** nhằm bảo vệ vốn khi xảy ra sự cố nghiêm trọng trên tài khoản thực.

---

## 1. Bản đồ Phản hồi Rủi ro Tự động (Mitigation Mapping)

Khi xảy ra các lỗi nghiêm trọng, hệ thống không chỉ ghi nhận log mà sẽ kích hoạt ngay lập tức các hành động giảm thiểu rủi ro vật lý:

```
                  +--------------------------------+
                  |  Sự cố nghiêm trọng xảy ra!    |
                  +----------------+---------------+
                                   |
                                   v
             [Sentry/GlitchTip phân loại Severity Level]
                                   |
         +-------------------------+-------------------------+
         | FATAL                                             | ERROR
         v                                                   v
+--------------------------------+          +--------------------------------+
|  Tripped Circuit Breaker       |          |  Định tuyến lại (Failover)      |
|  - Trạng thái khóa: OPEN       |          |  - Đổi sàn (Binance <-> Bybit) |
|  - Ngăn chặn lệnh mới tức thời|          |  - Ping cảnh báo qua Telegram  |
|  - Alert khẩn cấp tới Telegram  |          +--------------------------------+
+--------------------------------+
```

---

## 2. Các Quy tắc Phản hồi Chi tiết

### Quy tắc 1: Cảnh báo & Khóa trạng thái khi lỗi OCO (Orphan Position Risk)
* **Nguy cơ:** Khi lệnh MARKET vào vị thế (entry) thành công, nhưng lệnh OCO thoát thế (stop-loss/take-profit) thất bại do lỗi kỹ thuật của sàn hoặc mất kết nối. Vị thế sẽ bị "mồ côi" (orphan) và không được bảo vệ bởi stop-loss.
* **Hành động tự động:**
  1. `sentry_sdk` bắt exception lỗi OCO của sàn giao dịch và gán thẻ `severity="fatal"` kèm theo `tag:orphan_risk=true`.
  2. GlitchTip nhận sự kiện lỗi này, lập tức gửi tin nhắn Telegram kèm theo nút bấm tương tác khẩn cấp (Interactive Button): **[ĐÓNG VỊ THẾ KHẨN CẤP]** hoặc **[ĐẶT LẠI SL/TP THỦ CÔNG]**.
  3. Cổng an toàn nội bộ tự động chuyển trạng thái Circuit Breaker sang `OPEN` cho sàn giao dịch đó để ngăn chặn tất cả các tín hiệu vào lệnh mới tiếp theo.

### Quy tắc 2: Tự động Trip Circuit Breaker khi vượt ngưỡng Drawdown
* **Nguy cơ:** Tài khoản thực bị sụt giảm quá mức quy định (Drawdown > 5% trong ngày hoặc 10% tổng tài sản).
* **Hành động tự động:**
  1. Prometheus scrape số liệu số dư tài khoản và phát hiện mức sụt giảm vượt ngưỡng.
  2. Hệ thống phát sự kiện `CircuitBreakerTripped` nội bộ.
  3. `sentry_sdk` ghi nhận và phân loại đây là một lỗi mức `FATAL`.
  4. Trạng thái của sàn giao dịch bị khóa cứng ở chế độ `OPEN` (Không cho phép vào lệnh). Hệ thống chỉ mở lại khi có lệnh can thiệp thủ công từ quản trị viên (`/bypass` hoặc restart qua Telegram).

### Quy tắc 3: Tự động đổi sàn khi API Key hoặc Sàn lỗi (Automatic Failover Routing)
* **Nguy cơ:** API sàn Binance bị lỗi kết nối hoặc bị khóa API Key, khiến bot không thể đặt lệnh.
* **Hành động tự động:**
  1. Khi `execute_smart_order` ném ra `ExchangeError` mức `AUTHENTICATION_ERROR` hoặc `CONNECTION_ERROR`.
  2. Sentry SDK ghi nhận và gán nhãn sự kiện.
  3. Exchange Router lập tức chuyển hướng (failover) lệnh sang sàn dự phòng đã cấu hình sẵn (ví dụ: chuyển từ Weex sang Bybit hoặc Bybit sang Binance).
  4. GlitchTip nhận log sự kiện và gửi tin nhắn cảnh báo: *"⚠️ Lỗi kết nối sàn chính, đã tự động chuyển hướng lệnh sang sàn dự phòng."*
