# Sprint 6.2 — Watchlist Management
**Branch:** `feat/p6-mcp-morning-brief`  
**Commit:** `c1013ef`  
**Status:** ✅ Done

---

## Mục tiêu

Hệ thống quản lý watchlist động — add/remove symbols dễ dàng qua API,
lưu trữ persistent, và sync từ TradingView Desktop.

---

## Kiến trúc

```
User / API Client
    ↓ REST API
FastAPI Endpoints (/api/watchlist/*)
    ↓
watchlist.py → watchlist.json (server/)
    ↓ (optional)
MCP sync ← TradingView Desktop watchlist
```

---

## Files

### [NEW] `server/watchlist.py`

**Core functions:**

| Function | Mô tả |
|----------|--------|
| `get_watchlist() → list[str]` | Đọc từ JSON file, fallback default |
| `add_symbol(symbol) → dict` | Thêm symbol, dedup, persist |
| `remove_symbol(symbol) → dict` | Xóa symbol, persist |
| `set_watchlist(symbols) → list` | Replace toàn bộ |
| `sync_from_tradingview(mcp) → dict` | Merge watchlist từ TradingView MCP |

**Persistence:** `server/watchlist.json`
```json
{
  "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
}
```

**Default symbols** (nếu file chưa tồn tại): `BTCUSDT, ETHUSDT, SOLUSDT`

### [MODIFY] `server/main.py`

4 endpoints mới:

| Method | Path | Mô tả |
|--------|------|--------|
| `GET` | `/api/watchlist` | List symbols + count |
| `POST` | `/api/watchlist` | Add `{"symbol": "FPT"}` |
| `DELETE` | `/api/watchlist/{symbol}` | Remove symbol |
| `PUT` | `/api/watchlist/sync` | Sync từ TradingView Desktop |

### [MODIFY] `.gitignore`

Thêm `server/watchlist.json` (runtime data, không track).

---

## API Examples

```bash
# List watchlist
curl http://localhost:5000/api/watchlist
# → {"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"], "count": 3}

# Add symbol
curl -X POST http://localhost:5000/api/watchlist \
  -H "Content-Type: application/json" \
  -d '{"symbol": "FPT"}'
# → {"added": true, "symbol": "FPT", "watchlist": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "FPT"]}

# Remove symbol
curl -X DELETE http://localhost:5000/api/watchlist/SOLUSDT
# → {"removed": true, "symbol": "SOLUSDT", "watchlist": ["BTCUSDT", "ETHUSDT", "FPT"]}

# Sync from TradingView
curl -X PUT http://localhost:5000/api/watchlist/sync
# → {"synced": true, "added": 5, "total": 8, "watchlist": [...]}
```

---

## Bug phát hiện trong Sprint này

### 🐛 `notifier.py` thiếu `send_telegram_message` & `send_telegram_photo`

**File:** `server/brief.py` line 17
```python
from notifier import send_telegram_message, send_telegram_photo  # ← ImportError!
```

**Root cause:** P6 `brief.py` được tạo trước khi kiểm tra notifier API surface.

**Fix:** Thêm vào `server/notifier.py`:
- `send_telegram_message(msg)` — sync wrapper
- `send_telegram_photo(photo_path, caption)` — upload via Telegram `sendPhoto` API
- Dependency: `requests>=2.31.0`

---

## Kết quả Sprint

- ✅ Watchlist CRUD hoạt động qua 4 endpoints
- ✅ JSON persistence — data giữ lại khi restart server
- ✅ TradingView sync (merge, deduplicate)
- ✅ Bug fix notifier.py
- ✅ P4 README.md tổng hợp (user requested)
