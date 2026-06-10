# Sprint 7.6 — Web Dashboard v2
**Branch:** `feat/p7b-ai-vision-ux`  
**Commit:** `cc8699d`  
**Status:** ✅ Done

---

## Mục tiêu

Nâng cấp Dashboard từ **v1 (single-page performance view)** thành **premium 4-tab SPA**
với Morning Brief viewer, Scanner table, Watchlist management và System Status panel.

**Dashboard v1 chỉ có:** KPI cards + Equity chart + Trade history.  
**Dashboard v2 trở thành:** Trading command center đầy đủ.

---

## Kiến trúc Dashboard v2

```
┌─────────────────────────────────────────────────────────────────┐
│  📈 Minervini SEPA — Dashboard           11:10:30  🟢         │
├──────────┬───────────┬──────────────┬──────────────────────────┤
│ 🏠 Overview │ 📊 Scanner │ 📋 Watchlist 3 │ ⚡ Status          │
├──────────┴───────────┴──────────────┴──────────────────────────┤
│                                                                 │
│  [Active Tab Content]                                           │
│                                                                 │
│  Overview:   KPI Cards + Equity Curve + Briefs + Trade History  │
│  Scanner:    Sortable scan table + Run Scan + TT Score badges   │
│  Watchlist:  Symbol chips + Add/Remove + Sync from TradingView  │
│  Status:     Server, MCP, Scheduler, RAG, Telegram Bot, DB     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Auth System

### Simple Bearer Token

```
DASHBOARD_TOKEN=my-secret-token   # trong .env
```

| Path | Auth |
|------|------|
| `/dashboard`, `/`, `/static/*` | ❌ Không yêu cầu (serve HTML/CSS/JS) |
| `/webhook`, `/tv_health_check` | ❌ Không yêu cầu (TradingView cần gọi) |
| `/api/*`, `/trades*` | ✅ Bearer token hoặc `?token=...` |

**Nếu `DASHBOARD_TOKEN` rỗng** → open access (backward compatible).

---

## API Endpoints mới

### `GET /api/briefs`
Lịch sử morning briefs (pagination).

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5000/api/briefs?limit=20&offset=0"
```

Response:
```json
{
  "briefs": [
    {
      "id": 1,
      "created_at": "2026-05-04 07:00:12",
      "symbols_scanned": 3,
      "scan_data": [...],
      "ai_analysis": "Stage 2 uptrend...",
      "vision_data": {...},
      "brief_text": "🌅 MORNING BRIEF...",
      "success": 1
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### `GET /api/briefs/{id}`
Chi tiết một brief.

### `GET /api/system/status`
System health tổng hợp.

```json
{
  "server": { "version": "7.6", "uptime": "2h 15m 30s" },
  "mcp": { "enabled": true, "connected": true },
  "scheduler": { "enabled": true, "cron_time": "07:00", "last_brief": "..." },
  "rag": { "enabled": true, "vectors_count": 36 },
  "telegram_bot": { "enabled": true },
  "database": { "signals_count": 12, "trades_count": 8, "briefs_count": 3 },
  "auth_required": true
}
```

### `POST /api/scan/trigger`
Chạy scan watchlist on-demand (trả kết quả ngay, không qua brief pipeline).

---

## Files

### [MODIFY] `server/config.py`

| Config | Default | Mô tả |
|--------|---------|-------|
| `DASHBOARD_TOKEN` | `""` | Bearer token cho API auth. Rỗng = open access |
| `SERVER_START_TIME` | Auto | Timestamp khởi động server (tính uptime) |

### [MODIFY] `server/database.py`

**Schema mới:**
```sql
CREATE TABLE IF NOT EXISTS briefs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    symbols_scanned INTEGER,
    scan_data       TEXT,      -- JSON: scan_results array
    ai_analysis     TEXT,
    vision_data     TEXT,      -- JSON: vision result
    screenshot      TEXT,      -- file path
    brief_text      TEXT,      -- formatted telegram text
    success         INTEGER NOT NULL DEFAULT 1
);
```

**Functions mới:**

| Function | Purpose |
|----------|---------|
| `insert_brief()` | Lưu morning brief vào SQLite |
| `get_briefs(limit, offset)` | Query briefs với pagination + JSON parse |
| `get_brief_by_id(id)` | Lấy chi tiết 1 brief |
| `get_db_counts()` | Đếm records tất cả tables cho system status |

### [MODIFY] `server/brief.py`

- Import `database` module
- Step 9: Sau khi build brief dict → `await database.insert_brief(...)`
- Persist scan_data + ai_analysis + vision_data dạng JSON string

### [MODIFY] `server/main.py`

- Import `secrets` (auth comparison)
- Version bumped `7.0` → `7.6`
- **Auth middleware**: Bearer token validation cho `/api/*` và `/trades*`
- 4 new endpoints: `/api/briefs`, `/api/briefs/{id}`, `/api/system/status`, `/api/scan/trigger`

### [REWRITE] `server/static/dashboard.html`

4-tab SPA structure:
- Login overlay (nếu token required)
- Toast notification container
- Header: Logo + Clock + Server status dot
- Tab nav: Overview | Scanner | Watchlist | Status
- 4 tab panels với nội dung tương ứng

### [REWRITE] `server/static/css/dashboard.css`

490+ lines premium dark theme:
- Login overlay styling
- Tab navigation với active state
- Scanner table sort indicators
- Watchlist chip components
- Status card grid với pulse animations
- Brief card expand/collapse
- Toast slide-in animations
- Responsive: 3-col → 2-col → 1-col

### [REWRITE] `server/static/js/dashboard.js`

280+ lines modular JS:

| Module | Chức năng |
|--------|-----------|
| Auth | Token từ localStorage, login overlay, auto-detect |
| API | `apiFetch()` wrapper với Bearer header |
| Tabs | Hash-based navigation, lazy load khi switch tab |
| Toast | Non-blocking notifications (success/error/info), auto-dismiss 4s |
| KPI Stats | Load `/trades/stats`, render 6 KPI cards |
| Equity | Chart.js line chart với gradient fill |
| Briefs | Load `/api/briefs`, expand/collapse cards |
| Scanner | `/api/scan/trigger`, sortable columns, TT score badges |
| Watchlist | CRUD via `/api/watchlist`, optimistic UI updates |
| Status | `/api/system/status`, 6 health cards |

---

## Design System

| Token | Value |
|-------|-------|
| Background | `#0a0e17` + ambient glow orbs |
| Cards | `rgba(255,255,255,0.03)` + `backdrop-filter: blur(20px)` |
| Font | Inter (Google Fonts) |
| Green (positive) | `#10b981` |
| Red (negative) | `#ef4444` |
| Blue (neutral) | `#3b82f6` |
| Purple (accent) | `#8b5cf6` |
| Amber (warning) | `#f59e0b` |
| Border radius | 16px (cards), 10px (buttons), 6px (badges) |
| Transitions | `0.3s cubic-bezier(0.4, 0, 0.2, 1)` |

---

## Usage

### Chạy không auth
```bash
cd server && python main.py
# Dashboard: http://localhost:5000/dashboard
```

### Chạy có auth
```bash
# .env
DASHBOARD_TOKEN=my-secret-token-2026

# Hoặc inline
DASHBOARD_TOKEN=abc123 python main.py

# Dashboard sẽ hiện login overlay
# API calls cần header:
curl -H "Authorization: Bearer abc123" http://localhost:5000/api/system/status
```

### Watchlist management (từ Dashboard)
1. Mở tab **Watchlist**
2. Nhập symbol → **+ Add Symbol**
3. Click **×** trên chip để remove
4. Click **🔄 Sync from TradingView** để sync qua MCP

### Run Scanner (từ Dashboard)
1. Mở tab **Scanner**
2. Click **🔍 Run Scan**
3. Kết quả hiện trong table sortable
4. Click header column để sort (TT Score ▼, Change% ▲, v.v.)
