# 📡 Hướng Dẫn Cấu Hình TradingView Webhook → Server A

> **Version:** 1.0 | **Date:** 2026-05-30  
> **Status:** ✅ Server A VBS Ready | 🔧 TradingView Cần Cập Nhật

---

## 🎯 Thông Tin Kết Nối

| Thông số | Giá trị |
|---------|---------|
| **Webhook URL** | `https://trading.utopiavn.co/ingest` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Auth Method** | Secret trong URL query params hoặc JSON body |

> [!IMPORTANT]
> TradingView **không hỗ trợ Custom Headers** → Phải dùng secret qua `?secret=...` trong URL hoặc field `"secret"` trong JSON body.

---

## 🔗 URL Đầy Đủ Để Dán Vào TradingView

```
https://trading.utopiavn.co/ingest?secret=9ea7c89fbfd63a8a2bc8644e99da54fc5b2c7e098fe1d9e2b10a4e320f781a7b
```

> [!CAUTION]
> URL trên chứa secret thực — **KHÔNG chia sẻ công khai**. Thay thế bằng biến môi trường khi cần.

---

## 📋 Mẫu Alert Message (JSON)

### Template 1: Trade Signal (BUY/SELL)

```json
{
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "price": {{close}},
  "exchange": "binance",
  "interval": "{{interval}}",
  "sl": "{{strategy.position_size}}",
  "tp": "",
  "source": "tradingview",
  "time": "{{timenow}}"
}
```

### Template 2: Indicator Alert (Chỉ thông báo)

```json
{
  "symbol": "{{ticker}}",
  "action": "alert",
  "source": "indicator",
  "indicator_name": "SEPA_Scanner",
  "price": {{close}},
  "exchange": "binance",
  "interval": "{{interval}}",
  "signal_type": "breakout",
  "confidence_score": 80,
  "time": "{{timenow}}"
}
```

### Template 3: Stealth Alert (Tín hiệu ẩn)

```json
{
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "price": {{close}},
  "exchange": "binance",
  "interval": "{{interval}}",
  "mode": "STEALTH",
  "source": "tradingview",
  "time": "{{timenow}}"
}
```

---

## 🖱️ Các Bước Cấu Hình Trong TradingView

### Bước 1: Tạo Alert trên biểu đồ

1. Mở TradingView → Vào biểu đồ của symbol cần trade.
2. Click biểu tượng **⏰ Alert** (thanh công cụ bên phải) hoặc nhấn `Alt+A`.
3. Chọn điều kiện trigger (ví dụ: EMA crossover, RSI > 70...).

### Bước 2: Cấu hình Notifications → Webhook

1. Trong cửa sổ Alert, click tab **"Notifications"**.
2. Bật checkbox **"Webhook URL"**.
3. Dán URL sau vào ô Webhook URL:

   ```
   https://trading.utopiavn.co/ingest?secret=9ea7c89fbfd63a8a2bc8644e99da54fc5b2c7e098fe1d9e2b10a4e320f781a7b
   ```

4. Trong ô **"Message"**, dán JSON template phù hợp (xem phần trên).

### Bước 3: Lưu và Test

1. Click **"Create"** để lưu Alert.
2. Trigger Alert thủ công (right-click lên biểu đồ → "Trigger Alert") để test.
3. Kiểm tra Telegram — sẽ nhận thông báo trong vài giây.

---

## 🧪 Kiểm Tra Kết Nối (Smoke Test)

Chạy từ local machine để xác nhận kết nối end-to-end:

```powershell
# Smoke test từ Windows (PowerShell)
$body = @{
    symbol        = "BTCUSDT"
    action        = "buy"
    price         = 65000
    exchange      = "binance"
    interval      = "1h"
    source        = "tradingview"
    indicator_name = "ManualTest"
    time          = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
} | ConvertTo-Json

$secret = "9ea7c89fbfd63a8a2bc8644e99da54fc5b2c7e098fe1d9e2b10a4e320f781a7b"
$url    = "https://trading.utopiavn.co/ingest?secret=$secret"

$response = Invoke-RestMethod -Uri $url -Method POST -ContentType "application/json" -Body $body
$response | ConvertTo-Json
```

**Expected response:**
```json
{
  "queued": true,
  "queue_id": 8,
  "expires_at": "2026-05-30 18:00:00",
  "status": "PENDING"
}
```

---

## ✅ Xác Nhận Luồng End-to-End

Sau khi gửi webhook, hệ thống tự động thực hiện:

```
TradingView Alert
    │ POST https://trading.utopiavn.co/ingest?secret=...
    ▼
Cloudflare Tunnel (trading.utopiavn.co → Server A :5000)
    │ 200 OK {"queued": true, "queue_id": N}
    ▼
Server A VBS (SQLite signal_queue: PENDING)
    │ Telegram: 📥 VBS Signal Queued BTCUSDT BUY
    ▼
Server C Analyzer (Long-Poll → nhận ngay < 1s)
    │ RAG ChromaDB + Gemini AI Analysis
    │ Position Sizing (2% risk)
    ▼
Server B Execution Vault (POST /api/execute-trade)
    │ X-Server-B-Secret verified
    ▼
Binance/Bybit/Weex Exchange API
    │ Order Placed
    ▼
Telegram: ✅ Trade Executed BIN-XXXXXXXX
```

---

## 🐛 Troubleshooting

| Vấn đề | Kiểm tra |
|--------|---------|
| TradingView báo "Webhook failed" | Kiểm tra URL đúng không, secret đúng không |
| Không nhận Telegram | `ssh server-a "docker logs tradingbot-vbs --tail 20"` |
| Nhận Telegram nhưng không execute | `ssh server-c "docker logs tradingbot-analyzer --tail 30"` |
| Server B không nhận lệnh | `ssh server-b` → kiểm tra execution server |
| 401 Unauthorized | Secret trong URL sai hoặc thiếu |
| 400 Bad Request | JSON format sai, thiếu required field |

---

## 📊 Các Fields Được Hỗ Trợ

| Field | Bắt buộc | Mô tả | TradingView Variable |
|-------|---------|-------|---------------------|
| `symbol` | ✅ | Mã tài sản | `{{ticker}}` |
| `action` | ✅ | `buy` / `sell` / `alert` | `{{strategy.order.action}}` |
| `price` | Khuyến nghị | Giá hiện tại | `{{close}}` |
| `exchange` | Không | Sàn giao dịch (mặc định: binance) | Hardcode |
| `interval` | Không | Khung thời gian | `{{interval}}` |
| `source` | Không | `tradingview` / `indicator` | Hardcode |
| `indicator_name` | Nếu `source=indicator` | Tên indicator | Hardcode |
| `signal_type` | Không | `breakout` / `pullback` / `info` | Hardcode |
| `confidence_score` | Không | Độ tin cậy 0-100 | Hardcode |
| `mode` | Không | `STEALTH` / `NORMAL` | Hardcode |
| `sl` | Không | Stop Loss price | Tự tính |
| `tp` | Không | Take Profit price | Tự tính |
| `time` | Không | Timestamp ISO | `{{timenow}}` |
