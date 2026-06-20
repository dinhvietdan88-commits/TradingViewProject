# CHANGELOG

Tất cả thay đổi quan trọng của dự án **Angati TradingView Webhook Server** được ghi lại tại đây.

Định dạng theo [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), phiên bản theo [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v7.0.0] — 2026-06-21 — Forward Test Integration

### ✨ Added
- **Forward Test DB Isolation** (`forward_trades.db`): Tách biệt hoàn toàn dữ liệu paper trading khỏi `trades.db` (live/backtest). Sequence ID bắt đầu từ `1_000_000`.
- **Dynamic DB Routing Layer** (`data/routing.py`): `get_db_path_by_signal_id()`, `get_db_path_by_mode()` — định tuyến tự động dựa trên ID hoặc `mode` string.
- **API Forward Mode**: Tất cả endpoints hỗ trợ `?mode=FORWARD` — `/trades`, `/trades/stats`, `/trades/equity`, `/api/signals`.
- **Backtest Signal Report Generator** (`scripts/generate_backtest_report.py`): Tổng hợp 1,100 tín hiệu (710 thực + 390 synthetic BTC/ETH/SOL), xuất HTML + Markdown với Chart.js.
- **Forward-Test Sample Report Generator** (`scripts/generate_forward_test_report.py`): Báo cáo mẫu 28 paper trades (BTC/ETH/SOL), equity curve, radar chart, trade log.
- **Integration Test** (`tests/integration/test_forward_test_routing.py`): Test suite riêng cho Forward Test routing.
- **docs/FORWARD_TEST_GUIDE.md**: Hướng dẫn vận hành đầy đủ (kiến trúc, cấu hình, payload, API, báo cáo, troubleshooting).
- **docs/REPORTS_INDEX.md**: Chỉ mục tổng hợp toàn bộ báo cáo hệ thống.

### 📊 Reports Generated
- `reports/backtest_signal_report.html` — 1,100 signals, WR 55.55%, PF 2.138, Expectancy +3.27%
- `reports/backtest_signal_report.md` — Tóm tắt Markdown với monthly breakdown
- `reports/forward_test_sample_report.html` — 28 paper trades, WR 64.29%, PF 3.147
- `reports/forward_test_sample_report.md` — Trade log đầy đủ

### 🔧 Modified
- `config.py`: Thêm `FORWARD_DB_PATH` config
- `database.py`: Dual-DB migrator (chạy migration trên cả `trades.db` và `forward_trades.db`)
- `persistence_store.py`: CRUD routing qua `data/routing.py`
- `query_service.py`: Query với mode-aware routing
- `main.py`: Mode detection từ webhook payload → routing

### 📝 Documentation Updated
- `README.md` → v7.0: Thêm Forward Test section, architecture diagram, roadmap
- `PROJECT.md` → Milestone M4-M8 DONE, M9-M10 PLANNED

### ✅ Tests
- 930 tests (unit + integration + stress) — 100% PASSED

---

## [v6.5.0] — 2026-06 — Advanced Testing & Crystallization

### ✨ Added
- **Advanced Testing Campaign** (`test(advanced)`): Monte Carlo simulation, Walk-Forward Analysis, Slippage modeling, Chaos testing
- **Strategy Crystallization Framework** (`feat(crystallization)`): 5-layer filter tree cho S5 & S6, dynamic parameter scaling
- **Parallel Signal Simulation** (`feat(backtest)`): Cache pre-warming, dynamic pathing, asset-specific scaled campaign

### 📊 Scenarios
- S4 (Tight SL): +423.14 USDT, PF 1.19 — sinh lợi nhất fixed sizing
- S5 (MTF): +342.06 USDT, PF 1.40 — Win Rate cao nhất 51.2%
- Compounding S5: +184,850 USDT (!!) với 2% risk/lệnh

---

## [v6.0.0] — 2026-05 — Security Hardening (SEC-01 → SEC-04)

### ✨ Added
- **SEC-01**: Ruff inline diagnostics — 0 open lint alerts
- **SEC-02**: Pre-commit hooks + local security gate
- **SEC-04**: Runtime Guards — `safe_path`, `validate_exchange_params`, `safe_log_input`
  - 56/56 attack scenarios BLOCKED
  - SSRF, Path Traversal, Log Injection, XSS

### 📝 Documentation
- `Bao_Cao_Nghiem_Thu_Doc_Lap.md` — SEC-04 Independent Audit
- `Security_Scars_Report.md` — Security lessons learned

---

## [v5.5.0] — 2026-04 — Decentralized Macro Filter

### ✨ Added
- `MacroTrendProcessor` — Decentralized macro filter module
- `macro_regime_conditions.md` — Knowledge base cho macro trend
- Tests: `test_sentiment.py`, `MacroTrendProcessor` unit tests

---

## [v5.0.0] — 2026-03 — P6: TradingView MCP × Morning Brief

### ✨ Added
- **TradingView MCP Bridge** (CDP:9222): 78 tools — chart state, Pine Script dev, screenshots, replay, alerts
- **Morning Brief Scheduler**: 07:00 ICT daily — scan watchlist, Trend Template, VCP, gửi Telegram
- **Watchlist Management API**: CRUD symbols, sync từ TradingView Desktop
- **Analysis Engine**: 8 Minervini Trend Template criteria + VCP detector

### 📡 New API Endpoints
- `GET /api/watchlist` — List symbols
- `POST /api/watchlist` — Add symbol
- `GET /api/scan/watchlist` — Scan on-demand
- `POST /api/brief/trigger` — Trigger morning brief
- `GET /api/brief/latest` — Get latest brief

---

## [v4.0.0] — 2026-02 — P5: RAG & AI Agent

### ✨ Added
- **ChromaDB Vector Database**: 36 Minervini knowledge chunks
- **RAG Query Engine**: Cosine similarity search, Top-3 context retrieval
- **Claude AI Integration**: Signal analysis với Minervini context
- **Telegram rich notifications**: AI analysis + screenshot

### 📡 New API Endpoints
- `GET /api/rag/query?q=...` — Knowledge base query
- `GET /api/rag/status` — Vector DB health

---

## [v3.0.0] — 2026-01 — P4: FastAPI Production Server

### ✨ Added
- FastAPI async server (:5000) — 17 endpoints
- IP Whitelist + Secret Auth middleware
- Dynamic order sizing (2% risk per trade)
- Async Binance/WEEX execution (aiohttp)
- Real-time Telegram/Discord notifications
- SQLite trade logging (`trades.db`)
- Performance Dashboard (Web UI)
- pytest test suite (P4 unit tests)

---

## [v2.0.0] — 2025-12 — Pine Script V2 + SEPA Strategy

### ✨ Added
- Pine Script V2: SEPA Strategy backtest
- SuperTrend VBS indicator
- VCP (Volatility Contraction Pattern) detector
- 8 Minervini Trend Template criteria

---

## [v1.0.0] — 2025-11 — Initial Release

### ✨ Added
- TradingView webhook receiver (Flask)
- Basic Binance order execution
- Initial Pine Script V1 (Trend Template Indicator)
- Minervini knowledge base setup
