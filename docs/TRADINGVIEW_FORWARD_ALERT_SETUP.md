# Cấu hình TradingView Alert cho Forward Test

Tài liệu này hướng dẫn cách cấu hình Alert trên giao diện TradingView để gửi tín hiệu Webhook về Server C chạy chế độ **Forward Test (Paper Trading)**.

---

## 1. Payload Mẫu (JSON Alert Message)

Copy toàn bộ nội dung JSON dưới đây và dán vào phần **Message** khi tạo Alert trên TradingView:

```json
{
  "secret": "your_webhook_secret_here",
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "price": "{{close}}",
  "quoteQty": 100,
  "interval": "{{interval}}",
  "mode": "FORWARD",
  "exchange": "BINANCE",
  "sl": "{{plot_0}}",
  "tp": "{{plot_1}}"
}
```

> [!IMPORTANT]
> - Thay thế `"your_webhook_secret_here"` bằng giá trị `WEBHOOK_SECRET` thực tế được cấu hình trong file `.env` của máy chủ.
> - Đảm bảo cờ `"mode": "FORWARD"` được giữ nguyên để hệ thống tự động lưu trữ tín hiệu vào cơ sở dữ liệu ảo `forward_trades.db` thay vì tài khoản Live.

---

## 2. Webhook URL

Điền đường dẫn sau vào mục **Webhook URL** trong tab **Notifications**:

```
https://YOUR_CLOUDFLARE_TUNNEL/webhook
```
*(Thay thế `YOUR_CLOUDFLARE_TUNNEL` bằng tên miền Cloudflare Tunnel thực tế trỏ tới Server C của bạn)*

---

## 3. Checklist Cấu Hình (5 Bước)

- [ ] **Bước 1**: Mở TradingView và truy cập vào biểu đồ cặp giao dịch mong muốn (ví dụ: `BTCUSDT`, `ETHUSDT`, hoặc `SOLUSDT`).
- [ ] **Bước 2**: Click vào biểu tượng **Alert** (hình chiếc đồng hồ) trên thanh công cụ phía trên hoặc nhấn tổ hợp phím `Alt + A` để mở bảng **Create Alert**.
- [ ] **Bước 3**: Chuyển qua tab **Notifications** và tích chọn ô **Webhook URL**.
- [ ] **Bước 4**: Nhập địa chỉ Webhook URL của bạn: `https://YOUR_CLOUDFLARE_TUNNEL/webhook`.
- [ ] **Bước 5**: Chuyển qua tab **Settings** / **Alert message** và dán đoạn JSON payload mẫu ở trên vào ô **Message** (nhớ cập nhật `secret` và các trường tuỳ chỉnh nếu cần), sau đó nhấn **Create**.

---

## 4. Xác Minh Tín Hiệu (Verification)

Sau khi Alert kích hoạt (Alert Fires), bạn có thể kiểm tra xem tín hiệu đã được nhận thành công và định tuyến vào DB Forward hay chưa bằng cách:

### Cách 1: Gọi API Xem Danh Sách Tín Hiệu
Gửi yêu cầu HTTP GET tới Server C (hoặc localhost nếu chạy thử nghiệm):
```bash
curl "http://<SERVER_C_IP>:5000/api/signals?mode=FORWARD" 
```

### Cách 2: Truy Vấn Trực Tiếp Vào SQLite DB
Kết nối vào cơ sở dữ liệu `forward_trades.db` trên Server C và chạy truy vấn sau:
```sql
SELECT id, symbol, action, mode, state FROM signals WHERE mode='FORWARD' ORDER BY id DESC LIMIT 5;
```

### Tiêu Chí Thành Công ✅
- ID tín hiệu được tạo phải `>= 1,000,000`.
- Cột `mode` ghi nhận giá trị `"FORWARD"`.
- Cột `symbol` và `action` khớp chính xác với Alert trên TradingView.
