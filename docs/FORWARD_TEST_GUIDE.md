# 🚀 Hướng Dẫn Vận Hành Forward Test

> **Forward Test** (Paper Trading thời gian thực): Chạy chiến lược giao dịch với tín hiệu thật từ Server A nhưng dùng tiền ảo, không rủi ro vốn thật. Dữ liệu được lưu riêng trong `forward_trades.db`, tách biệt hoàn toàn khỏi `trades.db` (Live/Back-test).

---

## 📋 Mục Lục

1. [Kiến Trúc Forward Test](#1-kiến-trúc-forward-test)
2. [Cấu Hình Môi Trường](#2-cấu-hình-môi-trường)
3. [Khởi Động Server](#3-khởi-động-server)
4. [Gửi Tín Hiệu Forward Test](#4-gửi-tín-hiệu-forward-test)
5. [Xem Kết Quả Qua API](#5-xem-kết-quả-qua-api)
6. [Giao Diện Dashboard (Interactive Sync & Sandbox)](#6-giao-diện-dashboard-interactive-sync--sandbox)
7. [Tạo Báo Cáo](#7-tạo-báo-cáo)
8. [Kiến Trúc DB Routing](#8-kiến-trúc-db-routing)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Kiến Trúc Forward Test

```
TradingView Alert
      │
      ▼
  Server A (Gateway VPS)
  signal_queue.db
      │  mode: "FORWARD"
      ▼
  Server C (AI Core — FastAPI :5000)
  gateway/webhook.py
      │
      ├── mode == "FORWARD" ──► forward_trades.db  (ID ≥ 1,000,000)
      │                         [Paper Trading — tiền ảo]
      │
      └── mode == "LIVE" ──────► trades.db          (ID < 1,000,000)
                                 [Live Trading — tiền thật]
```

**Nguyên tắc cốt lõi:**
- Hai DB **không chia sẻ** sequence ID (Forward bắt đầu từ `1_000_000`)
- Tất cả CRUD thao tác đều đi qua `data/routing.py`
- Back-test data trong `trades.db` **không bị ảnh hưởng**

---

## 2. Cấu Hình Môi Trường

Thêm vào file `.env` hoặc `.env.local`:

```env
# ─── Database ────────────────────────────────────────────
TRADES_DB_PATH=nerves/workers/trading/trades.db
FORWARD_DB_PATH=nerves/workers/trading/forward_trades.db

# ─── Forward Test Mode ───────────────────────────────────
FORWARD_TEST_ENABLED=true
FORWARD_TEST_INITIAL_CAPITAL=10000.0   # USDT paper balance
FORWARD_TEST_POSITION_SIZE=100.0       # USDT per trade

# ─── Webhook Secret (same for all modes) ─────────────────
WEBHOOK_SECRET=your_webhook_secret_here
```

---

## 3. Khởi Động Server

```bash
# Phương pháp 1: Dùng uv (khuyến nghị)
uv run python nerves/workers/trading/main.py --port 5000

# Phương pháp 2: Dùng Python trực tiếp
cd nerves/workers/trading
python main.py --port 5000

# Phương pháp 3: Docker
docker-compose up -d server-c
```

Kiểm tra server đang chạy:
```bash
curl http://localhost:5000/tv_health_check
# → {"status": "ok", "version": "7.0.0", "forward_test": true}
```

---

## 4. Gửi Tín Hiệu Forward Test

### 4.1. Payload JSON — Kích hoạt FORWARD mode

Trường bắt buộc: `"mode": "FORWARD"`

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

### 4.2. Gửi thủ công (curl / PowerShell)

```powershell
# PowerShell
$body = @{
  secret   = "your_webhook_secret_here"
  symbol   = "BTCUSDT"
  action   = "buy"
  price    = "67500.00"
  quoteQty = 100.0
  interval = "15"
  mode     = "FORWARD"
  exchange = "binance"
  sl       = "66000.00"
  tp       = "70000.00"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:5000/webhook" -Method Post -Body $body -ContentType "application/json"
```

```bash
# Linux/Mac (curl)
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"secret":"your_webhook_secret","symbol":"BTCUSDT","action":"buy","price":"67500","quoteQty":100,"mode":"FORWARD","sl":"66000","tp":"70000"}'
```

### 4.3. Cấu hình TradingView Alert

Trong TradingView Alert → Message:
```json
{
  "secret": "{{YOUR_SECRET}}",
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

Webhook URL: `https://YOUR_CLOUDFLARE_TUNNEL/webhook`

### 4.4. Kịch bản ETH và SOL

**ETHUSDT Forward Sell:**
```json
{
  "secret": "your_secret",
  "symbol": "ETHUSDT",
  "action": "sell",
  "price": "3420.00",
  "quoteQty": 100.0,
  "mode": "FORWARD",
  "exchange": "binance",
  "sl": "3700.00",
  "tp": "2736.00"
}
```

**SOLUSDT Forward Buy:**
```json
{
  "secret": "your_secret",
  "symbol": "SOLUSDT",
  "action": "buy",
  "price": "148.50",
  "quoteQty": 100.0,
  "mode": "FORWARD",
  "exchange": "binance",
  "sl": "136.00",
  "tp": "178.20"
}
```

---

## 5. Xem Kết Quả Qua API

Tất cả endpoints hỗ trợ tham số `?mode=FORWARD`:

### 5.1. Danh sách tín hiệu Forward Test
```
GET /api/signals?mode=FORWARD
```

```json
{
  "signals": [
    {"id": 1000001, "symbol": "BTCUSDT", "action": "buy", "price": 67500, "mode": "FORWARD", ...}
  ],
  "total": 42
}
```

### 5.2. Lịch sử lệnh Forward Test
```
GET /trades?mode=FORWARD
```

### 5.3. Thống kê Forward Test
```
GET /trades/stats?mode=FORWARD
```

```json
{
  "total_trades": 42,
  "wins": 27,
  "losses": 15,
  "win_rate": 64.29,
  "total_pnl": 171.76,
  "profit_factor": 3.15,
  "mode": "FORWARD"
}
```

### 5.4. Equity Curve Forward Test
```
GET /trades/equity?mode=FORWARD
```

---

## 6. Giao Diện Dashboard (Interactive Sync & Sandbox)

Dashboard hỗ trợ giám sát thời gian thực các tín hiệu Forward Test tại `/forward-test`. Các tính năng tương tác nâng cao bao gồm:

### 6.1. Đồng bộ hóa Biểu đồ và Bảng (Bi-directional Sync)
- **Highlight tín hiệu hiển thị**: Các tín hiệu đang hiển thị dạng mũi tên trên chart sẽ tự động highlight màu xanh dương nhạt trong bảng tín hiệu và bảng tự động cuộn (auto-scroll) đến tín hiệu đầu tiên.
- **Rê chuột trên biểu đồ (Crosshair Move)**: Khi di chuyển con trỏ crosshair trên biểu đồ, hàng tương ứng trong bảng sẽ được highlight viền nét đứt (`.crosshair-highlight`) và tự động cuộn tới vị trí đó.
- **Click chọn tín hiệu**: Click trực tiếp vào một marker tín hiệu trên biểu đồ sẽ tự động kích hoạt click mở chi tiết của hàng tín hiệu đó trong bảng.
- **Đồng bộ hóa Replay/Cuộn biểu đồ**: Khi cuộn thang thời gian của biểu đồ, hàng tín hiệu gần nhất đang hiển thị sẽ tự động được chọn và cuộn vào tầm nhìn.

### 6.2. Kịch bản Mô Phỏng & Preset Sandbox
- **Preset Buttons**: Các nhóm thiết lập nhanh (Conservative, Aggressive, Trend Template, v.v.) hiển thị highlight sáng khi được chọn.
- **Reset tự động**: Khi người dùng tự tay tích chọn các kịch bản (S1–S6) hoặc đổi logic bộ lọc (`AND`/`OR`), highlight của nút Preset sẽ tự động tắt để biểu thị trạng thái tùy biến.
- **Sticky Sidebar**: Cột bên phải (biểu đồ và hộp cát Sandbox) được thiết kế sticky (dính) bên cạnh bảng tín hiệu dài khi xem trên màn hình máy tính desktop, giúp dễ dàng thao tác lọc kịch bản mà không bị trôi hay đè lên thanh header.

---

## 7. Tạo Báo Cáo

### 7.1. Báo cáo Back-test (1,100+ signals)
```bash
$env:PYTHONIOENCODING='utf-8'
python scripts/generate_backtest_report.py
```
Output:
- `reports/backtest_signal_report.html` — Biểu đồ đầy đủ (equity curve, monthly P&L, symbol breakdown)
- `reports/backtest_signal_report.md` — Tóm tắt Markdown

**Kết quả:**

| Chỉ Số | Giá Trị |
| :--- | :--- |
| Tổng tín hiệu | 1,100 |
| Win Rate | 55.55% |
| Profit Factor | 2.138 |
| Expectancy | +3.27%/lệnh |
| Total P&L | +3,592.89% |

### 7.2. Báo cáo Forward-Test mẫu (28 paper trades)
```bash
$env:PYTHONIOENCODING='utf-8'
python scripts/generate_forward_test_report.py
```
Output:
- `reports/forward_test_sample_report.html` — Paper trading dashboard
- `reports/forward_test_sample_report.md` — Trade log đầy đủ

---

## 8. Kiến Trúc DB Routing

### File: `nerves/workers/trading/data/routing.py`

```python
def get_db_path_by_signal_id(signal_id: int) -> str:
    """Trả về đường dẫn DB dựa trên signal ID."""
    if signal_id >= FORWARD_ID_THRESHOLD:  # 1_000_000
        return config.FORWARD_DB_PATH
    return config.TRADES_DB_PATH

def get_db_path_by_mode(mode: str) -> str:
    """Trả về đường dẫn DB dựa trên mode string."""
    if mode and mode.upper() == "FORWARD":
        return config.FORWARD_DB_PATH
    return config.TRADES_DB_PATH
```

### Nguyên tắc Atomic Write
Khi một tín hiệu được xử lý:
1. Ghi vào DB tương ứng (FORWARD hoặc LIVE)
2. **Back-test DB không bị ảnh hưởng** — chỉ cập nhật khi có `mode=LIVE` hoặc không có mode

### Schema `forward_trades.db`
Giống hệt `trades.db`, ngoại trừ:
- Sequence ID bắt đầu từ `1_000_000`
- Column `mode` luôn là `"FORWARD"`

---

## 9. Troubleshooting

### Vấn đề: Tín hiệu FORWARD không xuất hiện trong `forward_trades.db`

**Kiểm tra:**
```python
import sqlite3
conn = sqlite3.connect("nerves/workers/trading/forward_trades.db")
print(conn.execute("SELECT COUNT(*) FROM signals").fetchone())
conn.close()
```

**Nguyên nhân thường gặp:**
- Thiếu trường `"mode": "FORWARD"` trong payload → kiểm tra JSON
- `FORWARD_DB_PATH` chưa được set trong `.env`
- Server chưa chạy migration → restart server

### Vấn đề: `forward_trades.db` không tồn tại

```bash
# Migration sẽ tự tạo DB khi server khởi động
uv run python nerves/workers/trading/main.py --port 5000
# Hoặc chạy migration thủ công:
uv run python nerves/workers/trading/database.py --migrate-forward
```

### Vấn đề: ID collision giữa Forward và Live DB

Kiểm tra:
```python
import sqlite3
for db in ["trades.db", "forward_trades.db"]:
    conn = sqlite3.connect(f"nerves/workers/trading/{db}")
    max_id = conn.execute("SELECT MAX(id) FROM signals").fetchone()[0]
    print(f"{db}: max_id = {max_id}")
    conn.close()
```

Forward DB ID phải >= `1_000_000`. Nếu không, chạy:
```bash
python scripts/fix_forward_db_sequence.py
```

---

## 📎 Tài Liệu Liên Quan

- [README.md](../README.md) — Tổng quan hệ thống
- [REPORTS_INDEX.md](REPORTS_INDEX.md) — Chỉ mục toàn bộ báo cáo
- [Bao_Cao_Nghiem_Thu_Doc_Lap.md](../Bao_Cao_Nghiem_Thu_Doc_Lap.md) — SEC-04 audit
- [Security_Scars_Report.md](../Security_Scars_Report.md) — Security lessons

---

*Tài liệu này được cập nhật lần cuối: 2026-06-26 · Angati v7.1 · Branch: `dev/infra/forward-test-live-validation`*
