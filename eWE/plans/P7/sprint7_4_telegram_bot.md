# Sprint 7.4 — Telegram Bot Interactive
**Branch:** `feat/p7b-ai-vision-ux`  
**Commit:** `67bc6d0`  
**Status:** ✅ Done

---

## Mục tiêu

Chuyển Telegram từ **push-only** (server gửi thông báo một chiều) sang **interactive bot**
với commands, cho phép trader tương tác trực tiếp từ Telegram.

---

## Kiến trúc

```
                     ┌─────────────────────────────┐
                     │   FastAPI Server (:5000)     │
                     │   ├── 17 REST endpoints      │
                     │   ├── Webhook handler         │
                     │   └── Lifespan manager        │
                     └──────────┬──────────────────┘
                                │ startup
                    ┌───────────▼──────────────┐
                    │  telegram_bot.py         │
                    │  (background thread)      │
                    │  ├── run_polling()        │
                    │  ├── 8 CommandHandlers    │
                    │  └── CallbackQueryHandler │
                    └───────────┬──────────────┘
                                │ Telegram Bot API
                    ┌───────────▼──────────────┐
                    │  📱 Telegram User         │
                    │  /start /brief /scan      │
                    │  /watchlist /add /remove   │
                    │  /status /help            │
                    │  + inline keyboard buttons │
                    └──────────────────────────┘
```

**Key design:** Bot chạy trong daemon thread riêng (polling mode) — không conflict với FastAPI async event loop.

---

## Files

### [NEW] `server/telegram_bot.py`

**8 Commands:**

| Command | Mô tả |
|---------|--------|
| `/start` | Giới thiệu bot + inline keyboard (4 buttons) |
| `/help` | Danh sách commands |
| `/status` | Server + MCP + RAG + Scheduler + Watchlist status |
| `/brief` | Chạy Morning Brief on-demand |
| `/scan` | Scan watchlist — TT score + VCP table |
| `/watchlist` | Xem danh sách symbols |
| `/add SYMBOL` | Thêm symbol (VD: `/add FPT`) |
| `/remove SYMBOL` | Xóa symbol (VD: `/remove SOLUSDT`) |

**Inline Keyboard (4 buttons):**
- 📊 Scan Watchlist → trigger scan
- 🌅 Morning Brief → trigger brief
- 📋 Watchlist → show list
- 🔧 Status → show status

**Lifecycle:**
- `start_bot()` — gọi trong FastAPI lifespan startup
- `stop_bot()` — daemon thread tự terminate

### [MODIFY] `server/main.py`

- Import `telegram_bot as tg_bot_module`
- Lifespan startup: `tg_bot_module.start_bot()` if `TELEGRAM_BOT_ENABLED`
- Lifespan shutdown: `tg_bot_module.stop_bot()`

### [MODIFY] `server/config.py`

```python
TELEGRAM_BOT_ENABLED = os.getenv("TELEGRAM_BOT_ENABLED", "false").lower() == "true"
```

### [MODIFY] `server/requirements.txt`

```
+ python-telegram-bot>=21.0
```

### [MODIFY] `server/.env.example`

```env
TELEGRAM_BOT_ENABLED=false
```

---

## Cách sử dụng

### 1. Cài đặt

```bash
pip install python-telegram-bot>=21.0
```

### 2. Cấu hình `.env`

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here    # Từ @BotFather
TELEGRAM_CHAT_ID=your_chat_id             # Chat ID của bạn
TELEGRAM_BOT_ENABLED=true                 # Bật bot
```

### 3. Chạy server

```bash
cd server
python main.py
# → Telegram Bot: ✅ Interactive bot started (polling mode).
```

### 4. Mở Telegram

Gửi `/start` cho bot → thấy inline keyboard.

---

## Output mẫu

### `/scan` response:
```
📊 Scan Results (3 symbols)

Symbol     Price       TT   VCP    Vol%
────────────────────────────────────────
BTCUSDT    68,500      7/8  ⭐     35%
ETHUSDT     3,850      5/8          82%
SOLUSDT       185      6/8          45%

🎯 VCP Setups:
• BTCUSDT — Vol: 35% avg, Pivot: 69,200.50
```

### `/status` response:
```
🔧 System Status

⏰ Server time: 2026-05-04 07:00:00
🌐 Server: FastAPI v6.0 on :5000
🧠 RAG: ✅ Enabled
🖥️ MCP (CDP:9222): ✅ Connected
⏰ Brief Scheduler: ✅ Active (07:00 ICT)
📱 Telegram: ✅ Connected
📋 Watchlist: 5 symbols
```
