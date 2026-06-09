# System Design Document (SDD): GlitchTip Monitoring Node

Tài liệu này đặc tả thiết kế hệ thống (System Design) của phân hệ giám sát **GlitchTip** tích hợp trong dự án `TradingViewProject` và liên kết với hạ tầng EAIS.

---

## 1. Kiến trúc Vật lý & Thành phần (Component Layout)

Hệ thống giám sát được chia làm hai khu vực vật lý độc lập nhằm bảo đảm khả năng hoạt động liên tục (High Availability):

```
+------------------------------------+       +------------------------------------+
|     VPS Giao Dịch (Trading VPS)     |       |     VPS Giám Sát (Monitor VPS)     |
|                                    |       |                                    |
|  [FastAPI App (Trading Server)]    |       |  [GlitchTip (Django + Postgres)]   |
|         |                          |       |         ^                          |
|         +---(Sentry SDK HTTPS)-----+-------+---------+                          |
|         |                          |       |                                    |
|  [Prometheus Exporter (/metrics)]  |       |  [Prometheus Scraper]              |
|         ^                          |       |         |                          |
|         +---(Metrics Scrape)-------+-------+---------+                          |
|                                    |       |         v                          |
|                                    |       |  [Grafana Visualization]           |
+------------------------------------+       +------------------------------------+
```

### Chi tiết các dịch vụ trên Monitor VPS:
1. **GlitchTip (Container `glitchtip-web` & `glitchtip-worker`):**
   * Django backend chạy ứng dụng web.
   * PostgreSQL (lưu trữ logs, projects, users, uptime check states).
   * Redis (hàng đợi tác vụ Celery).
2. **Prometheus:**
   * Cơ sở dữ liệu chuỗi thời gian (Time-series Database).
   * Scraper cấu hình định kỳ kéo dữ liệu từ endpoint `/metrics` của bot.
3. **Grafana:**
   * Nền tảng hiển thị đồ thị và trực quan hóa số liệu tài sản cũng như độ trễ của bot.

---

## 2. Luồng Dữ liệu (Data Flow Pipeline)

### Luồng 1: Bắt lỗi & Hiệu năng (APM Tracing)
1. Một sự kiện (ví dụ: đặt lệnh, phân tích chỉ báo) xảy ra trên Trading VPS.
2. `sentry-sdk` tạo một **Transaction** và các **Spans** đo lường thời gian thực hiện.
3. Nếu xảy ra lỗi hoặc hoàn tất transaction, SDK gửi payload JSON qua cổng HTTPS tới địa chỉ IP của Monitor VPS (endpoint `/api/5/store/` của GlitchTip).
4. GlitchTip lưu trữ, phân nhóm lỗi theo hàm và gửi tin nhắn cảnh báo qua Telegram Webhook.

### Luồng 2: Thu thập Số liệu (Metrics Collection)
1. Prometheus trên Monitor VPS định kỳ (mỗi 15 giây) gửi yêu cầu HTTP GET tới `http://<IP_Trading_VPS>:5000/metrics`.
2. Bot giao dịch phản hồi các chỉ số thời gian thực (độ trễ API sàn, số lượng lệnh đã đặt, trạng thái Circuit Breaker).
3. Prometheus lưu trữ dữ liệu dạng chuỗi thời gian.
4. Grafana truy vấn Prometheus để render lên dashboard.

---

## 3. Cấu hình & Quản trị (Storage & Resource Plan)

1. **PostgreSQL Retention:** Giới hạn lưu giữ sự kiện trong GlitchTip tối đa 30 ngày thông qua biến môi trường `GLITCHTIP_MAX_EVENT_LIFE_DAYS=30`.
2. **Prometheus Retention:** Giới hạn dữ liệu lưu trữ tối đa 60 ngày hoặc 10 GB dung lượng đĩa.
3. **Security (Mã hóa):**
   * Endpoint `/metrics` trên VPS giao dịch được bảo vệ bằng cơ chế Basic Auth hoặc giới hạn địa chỉ IP (chỉ cho phép Monitor VPS truy cập).
   * Kết nối Sentry SDK tới GlitchTip sử dụng SSL/TLS.
