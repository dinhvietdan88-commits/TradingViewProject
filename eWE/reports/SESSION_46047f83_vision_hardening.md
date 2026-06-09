# Session Report — Sovereign Vision Pipeline Hardening
**Date:** 2026-05-14 | **Session:** 46047f83 | **Era:** Epoch 7 / P7.5

---

## Tổng kết Session

Session này hoàn tất việc hardening toàn bộ pipeline **Stealth Capture → Vision AI → Telegram → Dashboard**, đồng thời stabilize server restart workflow trên Windows.

---

## 1. Bugs Đã Fix

### BUG-01: Stealth Capture — Ảnh chụp toàn màn hình, nến bị mờ
- **File:** `server/mcp_client.py`
- **Root Cause:** MCP CLI chụp fullscreen (toolbar + sidebar + watchlist của TradingView)
- **Fix:** Thêm `_crop_chart_area()` dùng Pillow — crop theo tỉ lệ % (resolution-independent):
  - Top 7% (toolbar), Left 4.5% (sidebar), Right 21% (watchlist), Bottom 4% (status bar)
- **Commit:** `dc15635`

### BUG-02: Vision Analysis Skip khi `AI_PROVIDER=gemini`
- **File:** `server/brief.py`
- **Root Cause:** Gate check `if config.ANTHROPIC_API_KEY` → luôn False khi dùng Gemini
- **Fix:** Provider-agnostic check: `(gemini AND GEMINI_API_KEY) OR (anthropic AND valid key)`
- **Commit:** `dc15635`

### BUG-03: Stealth Capture không persist DB, Telegram chỉ gửi text
- **File:** `server/main.py`
- **Root Cause:** `process_alert_stealth_capture()` không gọi `database.insert_brief()`
- **Fix:**
  - Screenshot lưu với tên timestamp: `stealth_{symbol}_{ts}.png`
  - Persist vision result vào `briefs` SQLite table
  - Telegram nhận ảnh chart + caption AI analysis
- **Commit:** `dc15635`

### BUG-04: Dashboard 401 Lockout
- **File:** `server/static/js/dashboard-core.js`, `server/main.py`
- **Root Cause:** Không có flow inject Bearer token cho API calls
- **Fix:** URL token passthrough (`?token=xxx` → localStorage) + Login form + Webhook bypass cho dashboard token
- **Commit:** `a1e0cab`

### BUG-05: Windows Zombie Socket — Port 5000 conflict khi restart
- **File:** `server/start_server.py` (NEW)
- **Root Cause:** `Start-Process powershell` tạo zombie socket process sau khi kill
- **Fix:** `start_server.py` — pre-bind port với `SO_REUSEADDR` trước khi pass cho uvicorn
- **SCAR:** `SCAR-TVP-001` — Never use `Start-Process` for uvicorn
- **Commit:** `260a6d9`

### BUG-06: UnicodeEncodeError — emoji crash trên Windows cp1252
- **File:** `server/main.py`, `server/start_server.py`
- **Root Cause:** `logging.StreamHandler()` dùng Windows default `cp1252` → crash khi log emoji ✅ 🤖
- **Fix:** Force UTF-8 cho `sys.stdout/stderr` trước mọi import + `StreamHandler(sys.stdout)` explicit
- **SCAR:** `SCAR-TVP-002` — Force UTF-8 at process boot on Windows
- **Commit:** `260a6d9`

---

## 2. Features Mới

### Vision Analysis History Dashboard
- **Endpoint mới:** `GET /api/vision/history` — list Stealth Captures + Morning Briefs có vision data
- **Endpoint mới:** `GET /api/vision/screenshot/{brief_id}` — serve chart PNG
- **Dashboard tab Phân Tích:** Section `Vision Analysis History` với:
  - Ảnh chart (click để zoom)
  - Confidence score màu (green/yellow/red)
  - Patterns detected
  - SEPA Verdict
  - Badge `STEALTH` vs `BRIEF`
- **Commit:** `dc15635`

---

## 3. GitHub Issues Created

| # | Title | Labels |
|---|-------|--------|
| #3 | [BUG-FIX] Stealth Capture chart crop | bug, vision, mcp |
| #4 | [BUG-FIX] Vision skip khi AI_PROVIDER=gemini | bug, vision, gemini |
| #5 | [FEATURE] Vision History Dashboard + DB Persist | enhancement, dashboard |
| #6 | [BUG-FIX] Dashboard 401 Lockout + Auth Token | bug, security |

---

## 4. Scars Đăng Ký (Session)

| ID | Pattern | Rule |
|----|---------|------|
| `SCAR-TVP-001` | Start-Process zombie socket | NEVER use Start-Process for uvicorn. Use `python start_server.py` |
| `SCAR-TVP-002` | StreamHandler cp1252 crash | Force UTF-8 stdout/stderr BEFORE any import in server entry point |

---

## 5. Server Restart SOP (Standard Operating Procedure)

```powershell
# Kill existing server
netstat -ano | findstr ":5000" | findstr "LISTENING"
# → note PID, then:
taskkill /PID <PID> /F

# Start fresh (SO_REUSEADDR + UTF-8 fix)
cd server
python start_server.py --port 5000
```

**Dashboard URL:**
```
http://localhost:5000/dashboard?token=<DASHBOARD_TOKEN>
```

---

## 6. Architecture State (End of Session)

```
FastAPI :5000
├── /api/vision/history          [NEW] Vision analysis history
├── /api/vision/screenshot/{id}  [NEW] Serve chart PNG
├── /api/vision/analyze          Vision on-demand
├── /api/briefs                  Morning briefs
├── /webhook                     TradingView signals
├── /trades                      Trade history
└── /dashboard                   Dashboard UI (auth-gated)

Vision Pipeline:
  Webhook Alert
    → mcp_client.capture_screenshot()
    → _crop_chart_area() [Pillow crop]     [FIXED]
    → vision.analyze_chart_vision()        [FIXED: gemini gate]
    → database.insert_brief()              [NEW: persist]
    → send_telegram_photo(chart, caption)  [FIXED: was text-only]
    → /api/vision/history visible          [NEW]
```

---

## 7. Commits This Session

| Hash | Message |
|------|---------|
| `260a6d9` | fix: UnicodeEncodeError cp1252 - force UTF-8 stdout/stderr + SO_REUSEADDR launcher |
| `dc15635` | fix: stealth capture chart crop + vision history dashboard + DB persist |
| `a1e0cab` | feat: stabilize dashboard UI, implement auth token passthrough, and wire real APIs |

---

## 8. Next Steps

1. **WebSocket Notifications:** Nâng cấp từ polling `loadNotifications()` → WebSocket để đạt sub-second latency
2. **Pine V2 Hardening:** Refine `indicator_MTT_v1.001.pine` để maximize vision confidence score
3. **RAG HealthCheck:** FastEmbed service trên :9999 đang offline → cần `cognitive-telemetry` audit
4. **Morning Brief Enable:** Set `BRIEF_ENABLED=true` trong `.env` + chọn giờ chạy auto
5. **HTTPS/Reverse Proxy:** Nginx với SSL trước khi deploy production (hiện HTTP-only)
