# Kế hoạch Nâng cấp TradingView Webhook (Auto-Pilot Sprints)

Dựa trên yêu cầu, quá trình nâng cấp hệ thống Webhook được chia thành các **Sprint** rõ ràng để đảm bảo hệ thống chuyển đổi từ một Webhook thử nghiệm (Flask) thành một **Trading Bot Production-Ready** với hiệu năng cao (Async), bảo mật chặt chẽ và đầy đủ cảnh báo.

## Quyết định (Decision Log)

**Về vấn đề Thông báo (Notifications) - Trực tiếp vs OpenClaw:**
**Khuyến nghị:** Tích hợp **TRỰC TIẾP** (Direct Integration) tại đây.
*Lý do:* Hệ thống Trading yêu cầu độ trễ (latency) thấp nhất có thể. Việc gửi trực tiếp một HTTP Request bất đồng bộ (async) đến Telegram/Discord từ con bot này sẽ mất chưa tới 0.1 giây và không có điểm lỗi trung gian (single point of failure). Nếu đẩy qua OpenClaw, bạn sẽ phải tốn thêm thời gian serialize message, duy trì worker, và tăng rủi ro delay lệnh. Mình sẽ code một module Notification cực kỳ gọn nhẹ ở ngay trong `server/`.

---

## Phân bổ Sprints

### Sprint 1: Async Refactoring & Security Hardening (FastAPI) ✅ DONE
Thay vì dùng Flask chặn luồng (blocking), chuyển sang **FastAPI** để đạt tốc độ xử lý hàng ngàn tín hiệu mỗi giây mà không treo máy.

- ✅ Cài đặt `fastapi`, `uvicorn`, `aiohttp`.
- ✅ Viết lại hàm nhận Webhook bằng `async def webhook()`.
- ✅ **IP Whitelisting + WEBHOOK_SECRET** tạo thành lớp bảo mật kép.
- ✅ **Dashboard Token Auth:** `DASHBOARD_TOKEN` + URL passthrough `?token=xxx` (Session 46047f83)

### Sprint 2: Dynamic Order Sizing & Robust Execution ✅ DONE
Loại bỏ việc hardcode lệnh mua 10 USDT, cho phép linh hoạt từ biểu đồ.

- ✅ Đọc thêm tham số `size` hoặc `quoteOrderQty` từ JSON payload của TradingView.
- ✅ Viết lại hàm `_place_binance_order` thành `async def` (dùng `aiohttp` thay cho `requests`).
- ✅ Thêm khối lệnh `try...except` để bắt lỗi Binance (Không đủ số dư, API Key hết hạn).

### Sprint 3: Real-time Notifications (Telegram / Discord) ✅ DONE
Gửi báo cáo khớp lệnh ngay tức khắc.

- ✅ Tạo file `server/notifier.py` chứa các hàm `async def send_telegram_alert(message)`.
- ✅ Telegram Bot thread launched (polling mode, IPv4-forced cho Windows).
- ✅ **Send Photo + Caption:** Ảnh chart kèm AI analysis (Session 46047f83).

### Sprint 4: AI Vision Pipeline (Stealth Capture) ✅ DONE
Tích hợp AI phân tích hình ảnh chart tự động.

- ✅ `mcp_client.py` — Stealth screenshot qua Chrome DevTools Protocol (CDP:9222)
- ✅ `_crop_chart_area()` — Pillow auto-crop loại bỏ UI chrome TradingView (Session 46047f83)
- ✅ `vision.py` — Multi-provider: Gemini 2.5 / Anthropic Claude Vision
- ✅ `brief.py` — Provider-agnostic gate fix (không còn hardcode Anthropic) (Session 46047f83)
- ✅ `database.insert_brief()` — Persist vision results vào SQLite (Session 46047f83)
- ✅ `/api/vision/history` + `/api/vision/screenshot/{id}` — API endpoints (Session 46047f83)

### Sprint 5: Dashboard UI ✅ DONE
Dashboard web cho quick trade, indicators, notifications, phân tích.

- ✅ Tab Overview: KPI cards, equity chart, recent trades
- ✅ Tab Indicators: Pine V1/V2 signal scores
- ✅ Tab Orders: Đặt lệnh nhanh (Market/Limit, SL/TP, R:R calculator)
- ✅ Tab Notifications: Webhook log, Telegram alerts
- ✅ Tab **Phân Tích**: Vision History với chart images + AI analysis (Session 46047f83)
- ✅ Tab Scanner: Multi-symbol scanning

---

## Trạng thái Hiện tại (2026-05-14)

```
Server: FastAPI + Uvicorn :5000
  → Khởi động: python start_server.py (SO_REUSEADDR + UTF-8)
  → Dashboard: http://localhost:5000/dashboard?token=<DASHBOARD_TOKEN>

Vision Pipeline:
  Webhook → MCP CDP Screenshot → Pillow Crop → Gemini Vision → DB Persist → Telegram Photo

Active Issues (GitHub):
  #1 (open) mcp_client.py connected=false bug
  #2 (open) Gemini 2.5 Vision Scoring refactor
  #3 (open) Chart crop bug fix
  #4 (open) Vision skip gemini gate
  #5 (open) Vision history dashboard
  #6 (open) Dashboard 401 lockout
```

---

## Roadmap (Next Sprints)

### Sprint 6: WebSocket Real-time Notifications
- Nâng cấp từ polling `loadNotifications()` → WebSocket sub-second latency
- FastAPI WebSocket endpoint `/ws/notifications`

### Sprint 7: Production Hardening
- HTTPS / Nginx reverse proxy
- Health check endpoint `/health` cho monitoring
- Auto-restart on crash (Windows Service hoặc PM2)
- `BRIEF_ENABLED=true` + schedule Morning Brief 7AM

### Sprint 8: Pine V2 Optimization
- Refine `indicator_MTT_v1.001.pine` maximize vision confidence
- A/B test Pine V1 vs V2 signals với backtest data

---

## Server Restart SOP

```powershell
# Kill existing
netstat -ano | findstr ":5000" | findstr "LISTENING"
taskkill /PID <PID> /F

# Start (SO_REUSEADDR + UTF-8)
cd server
python start_server.py --port 5000
```

**SCAR-TVP-001:** NEVER use `Start-Process` powershell for uvicorn → zombie socket.
**SCAR-TVP-002:** ALWAYS force UTF-8 stdout/stderr before imports on Windows.

---

## Các Bước Triển Khai (Brainstorming & Execution)
(Cập nhật liên tục trong quá trình Auto-Pilot).

Session Reports:
- [`SESSION_46047f83_vision_hardening.md`](./reports/SESSION_46047f83_vision_hardening.md) — 2026-05-14
