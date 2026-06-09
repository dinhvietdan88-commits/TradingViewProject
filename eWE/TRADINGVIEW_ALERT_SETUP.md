# TradingView Alert → FastAPI Webhook Setup (V2)

Hệ thống đã được nâng cấp lên kiến trúc **FastAPI Async**, hỗ trợ xử lý không độ trễ, đặt lệnh Binance động và tự động gửi thông báo qua Telegram/Discord.

End-to-end flow:

```
TradingView Alert  →  Cloudflare Tunnel  →  localhost:5000/webhook  →  Binance API
                                                                    ↘ Telegram / Discord
```

## 1. Cài đặt và Cấu hình Môi trường (.env)

Mở thư mục `server/` và cài đặt các thư viện mới nhất:
```bash
cd server
pip install -r requirements.txt
```

Cấu hình file `server/.env` với các thông số bắt buộc:
```env
# Server
PORT=5000
DEBUG=true

# Security (Khớp với cấu hình trong TradingView)
WEBHOOK_SECRET=your_super_secret_key
ENABLE_IP_WHITELIST=false  # Đổi thành true khi chạy thực tế (Production)

# Binance API (Để trống nếu chỉ muốn nhận tín hiệu mà không Trade)
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_secret
BINANCE_TESTNET=true

# Notifications (Nhận cảnh báo về điện thoại)
TELEGRAM_BOT_TOKEN=7xxx:AAH_xxx
TELEGRAM_CHAT_ID=123456789
DISCORD_WEBHOOK_URL=
```

## 2. Khởi chạy Server và Cloudflared tunnel

Khởi chạy Webhook Server (FastAPI):
```bash
python main.py
```
*(Server sẽ lắng nghe ở cổng `5000`)*

Mở một Terminal khác để chạy Cloudflare Quick Tunnel:
```bash
cloudflared tunnel --url http://localhost:5000
```
Khi lệnh khởi chạy, Cloudflare sẽ in ra một public URL như:
```text
https://<random-words>.trycloudflare.com
```
Sao chép URL này và dùng làm Webhook URL trong TradingView, ví dụ:
```text
https://<random-words>.trycloudflare.com/webhook
```

Sanity check:
```bash
curl https://<random-words>.trycloudflare.com/tv_health_check
```

## 3. Cấu hình Pine Script (TradingView)

Trong Pine Script V2 (`pine/v2/minervini_strategy.pine` hoặc file báo động của bạn), JSON Payload gửi đi **bắt buộc** phải chứa `secret` và có thể tùy biến khối lượng lệnh (`quoteQty` hoặc `size`).

Ví dụ Payload chuẩn:
```json
{
  "secret": "your_super_secret_key",
  "action": "buy",
  "symbol": "BTCUSDT",
  "price": "{{close}}",
  "quoteQty": 50,
  "interval": "{{interval}}",
  "time": "{{timenow}}"
}
```

Ví dụ Payload cho Indicator Signal (được phân tích bởi AI & SEPA Rules):
```json
{
  "secret": "your_super_secret_key",
  "action": "buy",
  "symbol": "BTCUSDT",
  "indicator": "RSI",
  "strategy": "Oversold",
  "message": "RSI fell below 30",
  "price": "{{close}}",
  "interval": "{{interval}}"
}
```
*Lưu ý:*
*   Nếu không gửi `quoteQty`, bot sẽ mặc định đánh khối lượng 10 USDT.
*   Trường hợp có `indicator` và `strategy`, bot sẽ áp dụng luật Risk Management động theo file `server/data/sepa_rules.json` (tự động quyết định cần AI Confirmation hay khớp lệnh ngay).

Workflow trên TradingView:
1. Thêm Indicator/Strategy vào biểu đồ.
2. Click chuột phải → Add alert.
3. **Webhook URL**: Điền đường dẫn `https://<random>.trycloudflare.com/webhook`
4. **Message**: Dán đoạn mã JSON như trên (Hoặc Pine Script của bạn đã tự động sinh ra JSON này trong hàm `alert()`).
5. Create.

## 4. Manual end-to-end test (Kiểm thử thủ công)

Thay thế URL và Secret của bạn để giả lập TradingView bắn tín hiệu:
```bash
curl -X POST "https://<random>.trycloudflare.com/webhook" \
  -H "Content-Type: application/json" \
  -d '{"secret":"your_super_secret_key","action":"buy","symbol":"BTCUSDT","price":"68000","quoteQty":15}'
```

Expected response:
```json
{"received": true, "status": "processing_async"}
```
Ngay lập tức, bạn sẽ nhận được tin nhắn trên Telegram báo cáo trạng thái khớp lệnh trên Binance, đồng thời server ghi log vào `server/trades.log`.

## 5. Troubleshooting (Xử lý sự cố)

| Symptom | Cause / Fix |
|---------|-------------|
| `401 Unauthorized` | Sai `WEBHOOK_SECRET` — Kiểm tra lại file `.env` và JSON trên TradingView. |
| `403 Forbidden` | Bị chặn IP do bật `ENABLE_IP_WHITELIST=true`. Chỉ bật khi TradingView bắn tín hiệu thật. Nếu dùng Postman/Curl để test, hãy để `false` hoặc chạy local qua `127.0.0.1`. |
| TradingView "Webhook URL must be HTTPS" | Dùng URL của `trycloudflare.com`, không dùng `localhost`. |
| `trycloudflare.com` URL stops working | Tunnels miễn phí thay đổi URL mỗi lần tắt mở lại. Khởi chạy lại `cloudflared` và cập nhật URL trong TradingView. |
| Không nhận được tin Telegram | Kiểm tra `TELEGRAM_BOT_TOKEN` và `TELEGRAM_CHAT_ID`. Đảm bảo bạn đã nhắn tin cho bot trước để nó có quyền gửi tin lại. |
