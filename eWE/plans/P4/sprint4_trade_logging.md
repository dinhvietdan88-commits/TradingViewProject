# Sprint 4: Trade Logging — SQLite Database

## Mục tiêu

Thay thế logging thuần text (`trades.log`) bằng **SQLite database** có cấu trúc, cho phép:
- Lưu trữ mọi tín hiệu TradingView và kết quả giao dịch Binance
- Truy vấn lịch sử giao dịch qua API endpoint
- Tính toán metrics hiệu suất: Win Rate, Profit Factor, Max Drawdown
- Nền tảng cho Sprint 6 (Performance Dashboard)

## Quyết định kiến trúc

**SQLite + aiosqlite** — Không cần PostgreSQL, không cần Docker:
- File `.db` nằm ngay trong `server/`, portable
- `aiosqlite` cho async I/O khớp với FastAPI
- Không thêm dependency nặng, giữ project nhẹ

**Không dùng ORM (SQLAlchemy/SQLModel):**
- Chỉ có 2 bảng đơn giản, SQL thuần đủ rõ ràng
- Giảm dependency footprint
- Dễ debug, dễ export CSV

---

## Database Schema

### Bảng `signals` — Mọi tín hiệu nhận từ TradingView

```sql
CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    symbol      TEXT    NOT NULL,
    action      TEXT    NOT NULL,  -- buy | sell | alert
    price       REAL,
    quote_qty   REAL,
    source_ip   TEXT,
    payload     TEXT,              -- JSON gốc từ TradingView
    processed   INTEGER NOT NULL DEFAULT 0  -- 0=pending, 1=success, 2=failed
);
```

### Bảng `trades` — Kết quả thực thi trên Binance

```sql
CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id     INTEGER NOT NULL REFERENCES signals(id),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    symbol        TEXT    NOT NULL,
    side          TEXT    NOT NULL,  -- BUY | SELL
    order_id      TEXT,              -- Binance order ID
    status        TEXT,              -- FILLED | PARTIALLY_FILLED | REJECTED
    requested_qty REAL,
    executed_qty  REAL,
    executed_price REAL,
    commission    REAL,
    error_message TEXT,              -- NULL nếu thành công
    pnl           REAL              -- Profit/Loss (tính sau)
);
```

### Index

```sql
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_signal ON trades(signal_id);
```

---

## Phân bổ files

### [NEW] `server/database.py` — Database module

```
Chức năng:
- init_db()         → Tạo bảng khi khởi động
- insert_signal()   → Lưu tín hiệu mới, trả về signal_id
- insert_trade()    → Lưu kết quả giao dịch
- update_signal()   → Cập nhật trạng thái signal (processed)
- get_trades()      → Truy vấn lịch sử (filter by symbol, date range)
- get_stats()       → Tính Win Rate, Profit Factor, tổng P&L
```

### [MODIFY] `server/main.py` — Tích hợp database

```
Thay đổi:
- startup event: gọi init_db()
- webhook(): gọi insert_signal() trước khi xử lý
- execute_trade_and_notify(): gọi insert_trade() + update_signal()
- Thêm 2 endpoint mới:
    GET /trades         → Lịch sử giao dịch (pagination, filter)
    GET /trades/stats   → Metrics hiệu suất
```

### [MODIFY] `server/config.py` — Thêm DB path

```python
DB_PATH = os.getenv("DB_PATH", "trades.db")
```

### [MODIFY] `server/requirements.txt`

```
+ aiosqlite>=0.19.0
```

---

## API Endpoints mới

### GET `/trades`

```
Query params:
  - symbol   (optional): filter theo cặp giao dịch
  - limit    (optional): default 50, max 200
  - offset   (optional): default 0
  - from_date (optional): ISO format
  - to_date  (optional): ISO format

Response: { "trades": [...], "total": 123 }
```

### GET `/trades/stats`

```
Query params:
  - symbol (optional): filter theo cặp giao dịch

Response:
{
  "total_trades": 45,
  "winning_trades": 28,
  "losing_trades": 17,
  "win_rate": 62.2,
  "total_pnl": 1250.50,
  "profit_factor": 2.1,
  "avg_win": 89.32,
  "avg_loss": -42.15,
  "max_drawdown": -180.00,
  "best_trade": 320.00,
  "worst_trade": -95.00
}
```

---

## Kế hoạch thực thi (Auto-Pilot)

1. **Tạo `server/database.py`** — Module hoàn chỉnh với schema + CRUD
2. **Sửa `server/config.py`** — Thêm `DB_PATH`
3. **Sửa `server/requirements.txt`** — Thêm `aiosqlite`
4. **Sửa `server/main.py`** — Tích hợp DB + 2 endpoint mới
5. **Commit + Push** lên `feat/minervini-strategy`
6. **Merge → main** + Push

---

## Verification

```bash
# Khởi động server (tự tạo trades.db)
python main.py

# Test: Gửi tín hiệu
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"secret":"...","action":"buy","symbol":"BTCUSDT","price":"68000"}'

# Xem lịch sử
curl http://localhost:5000/trades

# Xem thống kê
curl http://localhost:5000/trades/stats
```
