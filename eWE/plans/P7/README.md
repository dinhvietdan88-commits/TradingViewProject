# P7 — Production Hardening + AI Vision (Option C: Hybrid)
**Status:** 📋 Planning  
**Base:** `main` (v6.0 — P6 merged)  
**Strategy:** 2 parallel branches, merge to main khi sprint complete

---

## 🔀 Branch Strategy

```
main (v6.0) ─────────────────────────────────────────────────────→ main (v7.0)
    │                                                                ↑
    ├── feat/p7a-production-hardening ──→ merge ─────────────────────┤
    │   ├── Sprint 7.1: E2E Test MCP                                │
    │   ├── Sprint 7.2: Binance OCO Orders                          │
    │   └── Sprint 7.3: Docker Deploy                               │
    │                                                                │
    └── feat/p7b-ai-vision-ux ──────────→ merge ────────────────────┘
        ├── Sprint 7.4: Telegram Bot Interactive
        ├── Sprint 7.5: AI Vision (chart screenshot analysis)
        └── Sprint 7.6: Web Dashboard v2
```

---

## 🏗️ Branch A: `feat/p7a-production-hardening`
> Focus: Safety-first — OCO orders, risk management, deployment

### Sprint 7.1 — E2E Test MCP
- Launch TradingView Desktop với `--remote-debugging-port=9222`
- Test all P6 endpoints: `/api/mcp/status`, `/api/watchlist`, `/api/scan/watchlist`
- Test morning brief: `POST /api/brief/trigger` → verify Telegram
- Fix integration bugs

### Sprint 7.2 — Binance OCO Orders
- `server/binance_client.py` — refactor từ inline code trong main.py
- OCO order logic: entry + stop-loss (8%) + take-profit (20%)
- Position sizing: risk % × account balance
- Telegram confirmation kèm SL/TP levels
- Safety: dry-run mode, testnet toggle

### Sprint 7.3 — Docker Deploy
- `Dockerfile` (Python 3.11 + uvicorn)
- `docker-compose.yml` (server + volumes for SQLite + ChromaDB)
- `.env.production` template
- Health check endpoint
- Systemd service file cho VPS

---

## 🧠 Branch B: `feat/p7b-ai-vision-ux`
> Focus: Intelligence + UX — close FX Tactix gap

### Sprint 7.4 — Telegram Bot Interactive ✅
- `python-telegram-bot` integration
- Commands: `/brief`, `/scan`, `/watchlist`, `/add SYMBOL`, `/remove SYMBOL`, `/status`
- Inline keyboard cho quick actions
- Chuyển từ push-only → interactive bot

### Sprint 7.5 — AI Vision (Chart Analysis) ✅
- Claude Vision API: gửi screenshot chart → pattern recognition
- Tích hợp vào morning brief: algorithmic TT + visual confirmation
- Pattern types: VCP, cup-with-handle, ascending base, flat base
- Confidence score: algorithmic + visual combined

### Sprint 7.6 — Web Dashboard v2 ✅
- **4-tab SPA:** Overview | Scanner | Watchlist | Status
- Morning Brief history viewer (SQLite persistence)
- Scanner: sortable table + on-demand scan trigger + TT score badges
- Watchlist: CRUD chips + TradingView sync
- System status: Server, MCP, RAG, Scheduler, Telegram, DB health cards
- **Auth:** Simple bearer-token middleware (`DASHBOARD_TOKEN`)
- **Design:** Premium glassmorphism dark theme, micro-animations, responsive

---

## 📋 Execution Order (Option C)

```
Week 1:  Sprint 7.1 (E2E test) → Sprint 7.2 (OCO orders)     [Branch A]
Week 2:  Sprint 7.4 (Telegram Bot)                             [Branch B]
Week 3:  Sprint 7.3 (Docker) + Sprint 7.5 (AI Vision)         [A + B parallel]
Week 4:  Sprint 7.6 (Dashboard v2) + Merge all → main          [Finalize]
```

---

## 📌 Open Questions

> [!IMPORTANT]
> 1. **Binance:** Testnet hay mainnet? OCO cần specific permissions.
> 2. **VPS:** Có sẵn VPS chưa? Specs (RAM, CPU)?
> 3. **Telegram Bot:** Bot riêng hay dùng chung bot hiện tại?
> 4. **Priority sprint nào trước?** A (production) hay B (AI/UX)?
