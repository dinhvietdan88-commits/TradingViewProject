# 📦 VPS Buffer Service (VBS) — Quickstart Deployment Guide

Tài liệu này hướng dẫn cách deploy VPS Buffer Service (VBS) lên server VPS và cấu hình Local Bot để kết nối và kéo tín hiệu.

---

## 1. Cấu Hình & Chạy VPS Buffer Service (VBS) Trên VPS

VBS là một ứng dụng FastAPI độc lập chạy trong môi trường Docker trên VPS của bạn.

### Bước 1.1: Chuẩn bị trên VPS
Copy thư mục `vbs/` và file `docker-compose.vbs.yml` lên VPS của bạn.
Cấu trúc thư mục tối thiểu trên VPS:
```text
/opt/trading-bot-vbs/
├── vbs/
│   ├── main.py
│   ├── router.py
│   ├── database.py
│   ├── scheduler.py
│   ├── notifier.py
│   ├── models.py
│   ├── config.py
│   ├── requirements.txt
│   └── Dockerfile
└── docker-compose.vbs.yml
```

### Bước 1.2: Tạo file `.env` trên VPS
Tạo file `/opt/trading-bot-vbs/vbs/.env` với nội dung cấu hình:

```dotenv
PORT=5000
HOST=0.0.0.0

# Sinh ngẫu nhiên secret 32 bytes (Ví dụ: python -c "import secrets; print(secrets.token_hex(32))")
BUFFER_SECRET=9a4bc1d8aefc562e84...

# Time to Live cho tín hiệu (mặc định 4 giờ)
SIGNAL_TTL_HOURS=4.0

# Thời gian Local Bot cần ACK trước khi tín hiệu bị re-queue (mặc định 5 phút)
DISPATCH_TIMEOUT_MINUTES=5.0

# Giới hạn queue pending (mặc định 1000)
MAX_QUEUE_SIZE=1000

# Telegram Notification (dùng chung bot token với Local Bot)
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=YOUR_TELEGRAM_CHAT_ID
```

### Bước 1.3: Khởi chạy Container
Di chuyển vào thư mục và chạy lệnh:
```bash
docker compose -f docker-compose.vbs.yml up -d --build
```
Lệnh này sẽ build image và start container `vbs-1` chạy ở cổng `5000` của VPS.

### Bước 1.4: Cấu hình Cloudflare Tunnel
Trỏ Cloudflare Tunnel trỏ subdomain của bạn (ví dụ: `bot.yourdomain.com`) về port `5000` trên VPS.
- Service type: `HTTP`
- URL: `localhost:5000` hoặc `127.0.0.1:5000`

Kiểm tra health bằng cách gọi:
```bash
curl https://bot.yourdomain.com/health
# Trả về: {"status":"healthy","uptime_seconds":X,"db":"ok","pending_count":0}
```

---

## 2. Cấu Hình Local Bot Consumer

Trên máy tính cá nhân (Local Bot), bạn chỉ cần bật tính năng VBS Consumer trong file `.env` để bot kéo tín hiệu về thay vì hứng trực tiếp từ Cloudflare Tunnel.

### Bước 2.1: Cấu hình `.env` của Local Bot
Thêm hoặc chỉnh sửa các dòng sau ở cuối file `.env`:

```dotenv
# ── VPS Buffer Consumer ─────────────────────────────────
VPS_BUFFER_ENABLED=true
VPS_BUFFER_URL=https://bot.yourdomain.com
VPS_BUFFER_SECRET=YOUR_SAME_SECRET_KEY_AS_VPS_BUFFER_SECRET
VPS_CONSUMER_ID=local-01
VPS_POLL_INTERVAL_SECONDS=30
VPS_STARTUP_PULL_LIMIT=50
MAX_SIGNAL_AGE_MINUTES=240
```

### Bước 2.2: Khởi chạy Local Bot
Khởi động Local Bot bình thường:
```bash
python start_server.py
```
Kiểm tra log của Local Bot để xác nhận kết nối thành công:
```text
INFO: VPS Buffer Consumer: ✅ Running background poller.
INFO: [VpsConsumer] Running startup signal recovery from VPS Buffer...
INFO: [VpsConsumer] Startup recovery complete: No pending signals found.
```

---

## 3. Quy Trình Test Hoạt Động (Smoke Test)

### Test 1: Đẩy signal giả lập lên VPS
Mở terminal và gửi POST request giả lập tín hiệu từ TradingView lên VPS:
```bash
curl -X POST https://bot.yourdomain.com/ingest \
  -H "X-Buffer-Secret: YOUR_SAME_SECRET_KEY_AS_VPS_BUFFER_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"action":"buy","symbol":"BTCUSDT","price":"68000","quoteQty":"100","exchange":"binance","source":"strategy"}'
```
**Kết quả mong đợi:**
1. VPS trả về `{"queued":true,"queue_id":X,"expires_at":"...","status":"PENDING"}`.
2. Telegram nhận được tin nhắn: `📥 VBS Signal Queued`.
3. Dashboard tab System hiển thị `Pending Queue: 1 signals`.

### Test 2: Local Bot kéo và xử lý tín hiệu
Khi Local Bot đang bật, sau tối đa 30 giây (hoặc ngay lập tức khi khởi động lại bot), bot sẽ kéo tín hiệu này về:
**Kết quả mong đợi:**
1. Log Local Bot: `[VpsConsumer] Processing signal #X for BTCUSDT BUY (age: Ym)`.
2. Lệnh được chuyển tiếp vào EventBus và TradeEngine chạy (trong chế độ DRY_RUN hoặc thực tế).
3. Sau khi TradeEngine hoàn tất, Local Bot gửi ACK lên VPS.
4. Dashboard tab System hiển thị `Pending Queue: 0 signals`, `ACKed Today: X signals`.
5. Tab Overview hiển thị tín hiệu đã xử lý trong phần `Recent Signals`.
