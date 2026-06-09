# Risk & Drawdown Assessment (RDA): Observability Specification

Tài liệu này đặc tả cơ chế đánh giá rủi ro (Risk Assessment) và kiểm soát mức sụt giảm tài sản (Drawdown) thông qua hệ thống đo lường của **GlitchTip** và **Prometheus/Grafana**.

---

## 1. Định nghĩa Chỉ số Rủi ro & Ngưỡng Ranh giới (Risk Metrics)

Hệ thống theo dõi 4 chỉ số rủi ro cốt lõi để đánh giá tính an toàn của tài khoản thực:

| Chỉ số (Metric) | Kênh theo dõi | Ngưỡng Cảnh báo (Warning) | Ngưỡng Khóa (Shutdown) |
| :--- | :--- | :--- | :--- |
| **Daily Loss** (Mức lỗ trong ngày) | Prometheus + SQLite | $\ge 7.0$ USDT | $\ge 10.0$ USDT |
| **Rolling Drawdown** (Mức sụt giảm từ đỉnh) | Prometheus + SQLite | $\ge 4.0\%$ | $\ge 5.0\%$ |
| **API Latency** (Độ trễ đặt lệnh) | GlitchTip APM Spans | $\ge 1.0$ giây | $\ge 1.5$ giây (Cảnh báo mạng) |
| **Orphan Positions** (Vị thế mất OCO) | GlitchTip Errors | N/A | $\ge 1$ vị thế (Hành động ngay) |

---

## 2. Thiết lập Thu thập Dữ liệu qua Prometheus Exporter

Bot giao dịch cung cấp endpoint `/metrics` để xuất các chỉ số rủi ro dưới dạng định dạng chuẩn của Prometheus:

```prometheus
# HELP trading_daily_loss_usdt Mức thua lỗ trong ngày tính bằng USDT.
# TYPE trading_daily_loss_usdt gauge
trading_daily_loss_usdt{exchange="weex"} 0.0
trading_daily_loss_usdt{exchange="bybit"} 2.50

# HELP trading_drawdown_percent Mức sụt giảm tài khoản lăn từ đỉnh (%).
# TYPE trading_drawdown_percent gauge
trading_drawdown_percent 1.25

# HELP trading_circuit_breaker_status Trạng thái của Circuit Breaker (0=CLOSED, 1=HALF-OPEN, 2=OPEN).
# TYPE trading_circuit_breaker_status gauge
trading_circuit_breaker_status{exchange="weex"} 0
trading_circuit_breaker_status{exchange="bybit"} 0
```

---

## 3. Bản đồ Đồ thị Grafana (Grafana Risk Dashboard)

Dashboard rủi ro của Grafana được chia làm 3 khu vực trực quan hóa:

1. **Khu vực 1: Trạng thái Sức khỏe Hệ thống (Liveness & Latency)**
   * Biểu đồ Sparkline thể hiện độ trễ phản hồi API của Binance, Bybit, Weex.
   * Đèn trạng thái (Status Indicator) của Circuit Breaker từng sàn.
2. **Khu vực 2: Kiểm soát Tài sản & Drawdown**
   * Đồ thị diện tích (Area Chart) thể hiện Equity Curve (Đường cong tài sản thực tế).
   * Cột đo (Gauge) thể hiện Rolling Drawdown hiện tại với vùng màu đỏ cảnh báo khi vượt mức 4%.
3. **Khu vực 3: Lịch sử Giao dịch & Phân bổ Vị thế**
   * Số lượng vị thế đang mở và mức rủi ro trên mỗi lệnh (`RISK_PER_TRADE`).

---

## 4. Quản lý Tín hiệu Cảnh báo qua GlitchTip

* Khi Prometheus phát hiện `trading_daily_loss_usdt` vượt ngưỡng khóa ($10.0$ USDT), Alertmanager gửi một webhook tới GlitchTip.
* GlitchTip ghi nhận đây là sự kiện bất thường cấp độ nghiêm trọng cao, kích hoạt gửi tin nhắn Telegram khẩn cấp, yêu cầu tạm khóa toàn bộ việc nhận tín hiệu mới cho đến khi qua ngày giao dịch tiếp theo.
* Việc này đảm bảo tính nhất quán của **Chính sách Kỷ luật Thép** (Minervini SEPA rules) khi giao dịch tiền thật.
