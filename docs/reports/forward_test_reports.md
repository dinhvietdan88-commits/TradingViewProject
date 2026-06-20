# 📊 Hướng Dẫn Tiến Hành Forward Test & Danh Mục Báo Cáo

Tài liệu này hướng dẫn cách vận hành chế độ **Forward Test** thời gian thực và tổng hợp danh mục các báo cáo phân tích hiệu suất giao dịch hiện có trong hệ thống.

---

## 🚀 1. Hướng Dẫn Tiến Hành Forward Test

Hệ thống đã được cấu hình với luồng cơ sở dữ liệu và xử lý rủi ro độc lập hoàn toàn cho chế độ Forward Test (tiền ảo chạy thời gian thực).

### Bước 1: Khởi động Webhook Server (FastAPI)
Chạy server trên máy chủ/VPS nhận tín hiệu bằng lệnh:
```bash
uv run python start_server.py --port 5000
```
*Lưu ý:* Cổng mặc định là `5000`. Server sẽ tự động giải phóng socket nếu có tiến trình zombie cũ đang chạy để tránh lỗi xung đột cổng (`SO_REUSEADDR`).

### Bước 2: Cấu hình Tín hiệu từ Server A gửi về
Server A (hoặc TradingView Alert) gửi HTTP POST webhook về địa chỉ:
`http://<IP_SERVER_C>:5000/webhook`

**Đặc tả JSON Payload:**
Để kích hoạt luồng Forward Test và lưu trữ vào cơ sở dữ liệu riêng biệt `forward_trades.db`, payload gửi đi **phải** chứa trường `"mode": "FORWARD"` và khoá `"secret"` khớp với cấu hình trong file `.env`.

*Ví dụ Payload (BTCUSDT Buy):*
```json
{
  "secret": "your_webhook_secret_here",
  "symbol": "BTCUSDT",
  "action": "buy",
  "price": "67500.00",
  "quoteQty": 100.0,
  "interval": "15",
  "mode": "FORWARD",
  "exchange": "binance",
  "sl": "66000.00",
  "tp": "70000.00"
}
```

### Bước 3: Xem kết quả Forward Test qua API
Các chỉ số giao dịch giả lập được lưu trữ riêng biệt tại `forward_trades.db`. Bạn có thể truy xuất dữ liệu này qua các API bằng cách thêm tham số `mode=FORWARD`:

- **Xem danh sách tín hiệu**: `GET /api/signals?mode=FORWARD`
- **Xem danh sách lệnh đã khớp**: `GET /trades?mode=FORWARD`
- **Xem hiệu số PnL, Win Rate**: `GET /trades/stats?mode=FORWARD`
- **Xem biểu đồ số dư (Equity Curve)**: `GET /trades/equity?mode=FORWARD`
- **Phân tích chi tiết lệnh**: `GET /trades/analysis?mode=FORWARD`

---

## 📈 2. Danh Mục Các Báo Cáo Phân Tích (Reports)

Dưới đây là danh mục các báo cáo phân tích hiệu suất, kiểm thử tĩnh và kiểm toán bảo mật hiện có trong hệ thống:

### 📋 2.1. Báo cáo Tín hiệu & Lệnh Giao dịch
- 📈 [Báo cáo Tổng hợp Tín hiệu từ Server A](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/reports/backtest_signal_report.md)
  - *Nội dung:* Thống kê chi tiết tín hiệu nhận được từ Server A, phân loại theo trạng thái hàng đợi, lý do bị từ chối từ bộ lọc AI và lỗi kết nối.
- 🔄 [Báo cáo Nhật ký Giao dịch Replay](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/reports/trade_replay.html)
  - *Nội dung:* Báo cáo trực quan HTML chi tiết về quá trình replay lệnh trên dữ liệu lịch sử để kiểm thử chiến thuật.

### 🔬 2.2. Báo cáo Kiểm thử Chiến thuật (Backtest / Walk-forward)
- 📊 [Tóm Tắt Chiến Thuật Giao Dịch (Strategy Summary)](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/reports/strategy_summary.html)
  - *Nội dung:* Báo cáo HTML trực quan về hiệu suất chiến thuật, phân bổ tỷ trọng và các biểu đồ thống kê lệnh đóng/mở.
- 📉 [Biểu đồ Equity Curve của Supertrend](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/reports/supertrend_equity_curve.html)
  - *Nội dung:* Biểu đồ tăng trưởng tài khoản theo thời gian dựa trên các chỉ báo Supertrend.
- 📐 [Walk-forward Validation Report](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/reports/walkforward_validation.html)
  - *Nội dung:* Kết quả xác thực tối ưu hóa tham số cuốn chiếu (Walk-Forward Analysis) trên các tập dữ liệu huấn luyện và kiểm thử liên tiếp.
- ⏱️ [Walk-forward Rolling](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/reports/walkforward_rolling.html) | [3-Month Report](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/reports/walkforward_3month.html)
  - *Nội dung:* Phân tích chi tiết mô hình tối ưu hóa lăn bánh theo chu kỳ 3 tháng.

### 🛡️ 2.3. Báo cáo Kiểm toán Bảo mật & Nghiệm thu
- 🛡️ [Báo cáo Nghiệm thu Độc lập SEC-04](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/Bao_Cao_Nghiem_Thu_Doc_Lap.md)
  - *Nội dung:* Nghiệm thu các biện pháp phòng vệ Runtime chống lỗ hổng SSRF và Path Traversal. Xác nhận kịch bản tấn công giả lập đều bị chặn đứng thành công (`PASSED`).
- 🔒 [Security Scars Report](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/Security_Scars_Report.md)
  - *Nội dung:* Báo cáo chi tiết các bài học kinh nghiệm và biện pháp khắc phục bảo mật tĩnh trên toàn dự án TradingViewProject.
