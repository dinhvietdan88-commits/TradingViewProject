# P6 — TradingView MCP × RAG Morning Brief
**Branch:** `feat/p6-mcp-morning-brief`  
**Status:** ✅ Implementation Complete  
**Commits:** `3367de9` → `cf76141` → `c1013ef`  
**Depends on:** P5 (RAG + ChromaDB + Claude) ✅  
**MCP Source:** [tradesdontlie/tradingview-mcp](https://github.com/tradesdontlie/tradingview-mcp) (78 tools via CDP)

---

## 🎯 Mục tiêu P6

Khai thác **TradingView MCP** đã sẵn có trong project, kết hợp với **RAG System (P5)** để tạo ra:

1. **Morning Brief tự động** — mỗi sáng 07:00 ICT, Claude đọc chart thực + tra Minervini rules → gửi báo cáo qua Telegram
2. **Real-time Visual Confirmation** — khi webhook nhận signal, Claude capture screenshot chart + xác nhận VCP pattern
3. **Watchlist Scanner** — tự động scan multi-symbol, filter theo Trend Template, gửi cảnh báo

> **Gap P5 còn lại:** Claude hiện chỉ đọc số liệu JSON. P6 cho Claude đọc biểu đồ trực quan (thứ FX Tactix đang làm) + screenshot chart.

---

## 🔌 MCP Capabilities (Đã khảo sát)

MCP dùng **Chrome DevTools Protocol (CDP port 9222)** — kết nối vào TradingView Desktop đang chạy.

### Tools dùng cho P6

| MCP Tool | Dùng cho |
|----------|---------|
| `quote_get` | Lấy price, OHLC, volume realtime |
| `data_get_ohlcv --summary` | Compact bar stats (500B) |
| `data_get_study_values` | Đọc MA50, MA150, MA200, RSI, Volume |
| `chart_set_symbol` | Switch sang symbol cần scan |
| `chart_set_timeframe` | Switch timeframe (D, W) |
| `capture_screenshot` | Chụp chart → gửi Telegram kèm phân tích |
| `watchlist_get` | Đọc watchlist TradingView của user |
| `batch_run` | Chạy action trên nhiều symbol cùng lúc |
| `tv_health_check` | Kiểm tra kết nối CDP |

### Khởi động MCP

```bash
# 1. Init submodule
git submodule update --init tradingview-mcp
cd tradingview-mcp && npm install

# 2. Launch TradingView với debug port
scripts\launch_tv_windows.bat   # Script đã có trong project!

# 3. Verify
node src/cli/index.js status
```

> ⚠️ **Lưu ý:** TradingView Desktop phải đang chạy với `--remote-debugging-port=9222`

---

## 📋 Sprint Docs

| Sprint | Nội dung | Docs | Status |
|--------|---------|------|--------|
| **Sprint 6.1** | MCP Foundation — MCPClient wrapper | [sprint6_1_mcp_foundation.md](sprint6_1_mcp_foundation.md) | ✅ Done |
| **Sprint 6.2** | Watchlist Management — CRUD + JSON | [sprint6_2_watchlist.md](sprint6_2_watchlist.md) | ✅ Done |
| **Sprint 6.3** | Analysis Engine — TT + VCP | [sprint6_3_analysis_engine.md](sprint6_3_analysis_engine.md) | ✅ Done |
| **Sprint 6.4** | Morning Brief + Scheduler | [sprint6_4_morning_brief.md](sprint6_4_morning_brief.md) | ✅ Done |

---

## 🏗️ Kiến trúc P6

```mermaid
flowchart TD
    subgraph SCHEDULER ["⏰ APScheduler"]
        CRON["`Cron: 07:00 ICT daily
        hoặc POST /api/brief/trigger`"]
    end

    subgraph MCP_LAYER ["🖥️ TradingView MCP (CDP:9222)"]
        TV["`TradingView Desktop
        đang chạy local`"]
        TOOLS["`78 MCP Tools:
        quote_get, data_get_study_values
        chart_set_symbol, capture_screenshot
        batch_run, watchlist_get`"]
        TV <--> TOOLS
    end

    subgraph ANALYSIS ["🧠 P5 RAG + Claude"]
        VDB[("`ChromaDB
        36 Minervini chunks`")]
        CLAUDE["`Claude Sonnet
        claude-sonnet-4-5`"]
    end

    subgraph OUTPUT ["📤 Output"]
        TG["`📱 Telegram
        Morning Brief + Screenshot`"]
        API["`FastAPI
        GET /api/brief/latest
        GET /api/scan/watchlist`"]
    end

    CRON --> TOOLS
    TOOLS -->|"price, MA, volume, screenshot"| ANALYSIS
    VDB -->|"Top 3 Minervini chunks"| CLAUDE
    CLAUDE --> TG
    CLAUDE --> API

    style SCHEDULER fill:#1a1a2e,stroke:#f59e0b,color:#fff
    style MCP_LAYER fill:#1a1a2e,stroke:#3b82f6,color:#fff
    style ANALYSIS fill:#1a1a2e,stroke:#8b5cf6,color:#fff
    style OUTPUT fill:#1a1a2e,stroke:#10b981,color:#fff
```

---

## 📋 Features

### Feature 1: Morning Brief (Priority: HIGH ⭐)

**Trigger:** `07:00 ICT` hàng ngày hoặc `POST /api/brief/trigger`

**Quy trình:**
```
APScheduler 07:00
    ↓
batch_run(watchlist) → quote_get + data_get_study_values + ohlcv(summary)
    ↓
Tính Trend Template score (0/8) cho từng symbol
Phát hiện VCP candidates (volume < 50% avg + narrow range < 0.5×ATR)
    ↓
capture_screenshot(region=chart) cho top candidates
    ↓
RAG query "Morning market scan Stage 2 VCP"
    ↓
Claude generate Morning Brief report
    ↓
Telegram: Text report + Chart screenshot
```

**Output Telegram mẫu:**
```
🌅 MORNING BRIEF — 04/05/2026 07:00 ICT

📊 Watchlist Scan (8 symbols):
• BTCUSDT  $65,200 (+2.3%)  TT: 7/8 ✅  Vol: 1.2× avg
• ETHUSDT  $3,100  (+1.1%)  TT: 6/8 ✅  Vol: 0.9× avg
• FPT      89,500  (+0.8%)  TT: 8/8 ⭐  Vol: 0.4× avg ← VCP!

🎯 VCP Setup đáng chú ý:
• FPT: Volume giảm 60% (contraction thứ 3) — pivot 91,000

🧠 Minervini AI:
"FPT đang trong VCP contraction chuẩn. Theo Rule #7 Minervini,
volume giảm liên tiếp 3 lần với biên độ hẹp là dấu hiệu tích cực.
Chờ breakout pivot 91,000 với volume >150% avg."

📸 [Chart screenshot FPT attached]
⚠️ Market risk: Neutral
```

### Feature 2: Webhook Visual Confirmation (Priority: MEDIUM)

Khi `/webhook` nhận BUY signal:
1. `chart_set_symbol(symbol)` + `chart_set_timeframe("D")`
2. `capture_screenshot(region="chart")`
3. Claude xem screenshot + RAG context → xác nhận/từ chối tín hiệu
4. Append vào Telegram: *"📸 Chart xác nhận VCP pattern: ..."*

### Feature 3: Watchlist Scanner API (Priority: MEDIUM)

```
GET /api/scan/watchlist?symbols=BTCUSDT,ETHUSDT,FPT&timeframe=D
```

Response:
```json
{
  "scanned": 3,
  "timestamp": "2026-05-04T07:00:00+07:00",
  "results": [
    {
      "symbol": "FPT",
      "price": 89500,
      "trend_template_score": 8,
      "vcp_detected": true,
      "volume_ratio": 0.41,
      "ai_note": "Contraction thứ 3, pivot 91,000"
    }
  ]
}
```

### Feature 4: Manual Trigger API (Priority: LOW)

```
POST /api/brief/trigger          → Chạy morning brief ngay lập tức
GET  /api/brief/latest           → Lấy brief mới nhất (JSON + text)
GET  /api/mcp/status             → Kiểm tra CDP connection
```

---

## 🗂️ Files cần tạo/sửa

```
server/
├── mcp_client.py        [NEW] Python wrapper gọi MCP CLI (subprocess)
├── brief.py             [NEW] Morning brief generator
├── watchlist.py         [NEW] Multi-symbol Trend Template scanner
├── scheduler.py         [NEW] APScheduler cron setup
├── main.py              [MODIFY] Thêm /api/brief/* /api/scan/* /api/mcp/* endpoints
└── config.py            [MODIFY] WATCHLIST_SYMBOLS, BRIEF_CRON_TIME, MCP_CDP_PORT

tradingview-mcp/         [INIT SUBMODULE] git submodule update --init

docs/plans/P6/
├── README.md            ← File này
└── architecture_mermaid.md
```

---

## 🔧 Dependencies (đã thêm vào `requirements.txt`)

```txt
apscheduler>=3.10.4      # Cron scheduler (async-compatible)
pillow>=10.0.0           # Image processing cho screenshot
requests>=2.31.0         # Telegram photo upload
```

Node.js (cho MCP):
```bash
cd tradingview-mcp && npm install
```

---

## ⚙️ Config mới trong `.env`

```env
# === P6: MCP Morning Brief ===
MCP_ENABLED=true
MCP_CDP_PORT=9222                           # Chrome DevTools Protocol port
MCP_TRADINGVIEW_PATH=C:\...\TradingView.exe # Auto-detect nếu để trống

# Watchlist (comma-separated)
WATCHLIST_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,FPT,VCB,MWG

# Morning Brief schedule (cron format, Asia/Ho_Chi_Minh)
BRIEF_CRON_TIME=07:00                       # HH:MM
BRIEF_ENABLED=true
```

---

## 🔄 Luồng Morning Brief Chi tiết

```mermaid
sequenceDiagram
    participant CRON as APScheduler
    participant MCP as MCP Client (subprocess)
    participant TV as TradingView Desktop
    participant CALC as Trend Template Calc
    participant RAG as ChromaDB (P5)
    participant CLAUDE as Claude API
    participant TG as Telegram

    CRON->>MCP: batch_run(watchlist_symbols)
    MCP->>TV: CDP quote_get + data_get_study_values per symbol
    TV-->>MCP: {price, MA50, MA150, MA200, vol, ATR, ...}
    MCP-->>CALC: raw market data

    CALC->>CALC: Score Trend Template (0-8 per symbol)
    CALC->>CALC: Detect VCP (vol < 50% avg + narrow range)
    CALC-->>MCP: [sorted by TT score + VCP flag]

    MCP->>TV: chart_set_symbol(top_vcp_candidate)
    MCP->>TV: capture_screenshot(region="chart")
    TV-->>MCP: screenshot.png

    MCP->>RAG: query_knowledge("Morning brief VCP Stage 2")
    RAG-->>MCP: Top 3 Minervini chunks

    MCP->>CLAUDE: generate_morning_brief(data + context + screenshot_desc)
    CLAUDE-->>MCP: Formatted brief text

    MCP->>TG: Send text + screenshot.png
```

---

## ✅ Acceptance Criteria

- [x] `tv_health_check` → `{"connected": true}` khi TradingView chạy với CDP
- [x] Morning Brief engine hoạt động (scan → analyze → format → send)
- [x] Brief bao gồm: TT score, VCP candidates, AI assessment, screenshot
- [x] `POST /api/brief/trigger` hoạt động on-demand
- [x] `GET /api/scan/watchlist` trả đúng JSON
- [x] `GET /api/mcp/status` trả trạng thái CDP connection
- [x] APScheduler cron 07:00 ICT daily
- [x] Watchlist CRUD API (GET, POST, DELETE, PUT/sync)
- [ ] `git submodule update --init tradingview-mcp` hoạt động
- [ ] End-to-end test với TradingView Desktop chạy thật
- [ ] Tests cho `mcp_client.py`, `brief.py`, `watchlist.py`

---

## 📌 Decisions Made

| Question | Answer |
|----------|--------|
| TradingView Desktop (paid)? | ✅ Có |
| Watchlist symbols? | Dynamic — add/remove qua API, default: BTCUSDT, ETHUSDT, SOLUSDT |
| Brief time? | 07:00 ICT (UTC+7) |
| Screenshot kèm Telegram? | ✅ Có — send_telegram_photo() |
| MCP approach? | subprocess CLI (không cần MCP SDK) |

> [!WARNING]
> TradingView MCP dùng Chrome DevTools Protocol — cần TradingView Desktop **đang chạy** trên cùng máy. Không hoạt động với TradingView Web app.
