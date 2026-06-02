# Original User Request

## Initial Request — 2026-05-21T04:31:17+07:00

Implement a version checking and warning mechanism for `angati.exe` inside the `TradingViewProject` workspace when the hook server starts.

Working directory: c:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development

## Requirements

### R1. Boot-time Version Checking
On startup of the hook service, compare the local `angati.exe` binary with the main Antigravity Brain's `angati.exe` (found under the App Data Directory `C:\Users\pesil\.gemini\antigravity\tools\angati` or similar).

### R2. Non-blocking Warning Output
If a version mismatch is detected, print a warning to `stderr` requesting the user to manually restart the server to synchronize the binary. The check must be completely non-blocking and not interfere with the startup of the SRA Hook Server.

### R3. Automated Testing
Extend `test_angati_integration.py` or add a unit test to verify that the version checking logic triggers correctly when the files differ (using a temporary mock mismatch file) and handles missing files gracefully.

## Acceptance Criteria

### Boot Validation
- [ ] Startup logs include a version check status.
- [ ] If the local file matches the main Brain binary, no action or a normal status message is printed.
- [ ] If a mismatch is detected, a prominent warning is printed to `stderr` indicating the files differ.

### Test Coverage
- [ ] Test suite executes successfully with `python -m unittest` or the integration runner.
- [ ] The test confirms that a mismatched version triggers the stderr warning.

## Follow-up — 2026-05-21T05:09:33+07:00

The goal of this project is to perform a comprehensive stability and safety evaluation of the TradingView Edge Node ecosystem, verifying runtime reliability, CDP browser automation connectivity, and Telegram notifications under stress and failure states.

Working directory: C:\Users\pesil\working\mj_trading\TradingViewProject

## Requirements

### R1. Webhook Edge Node Stability Verification
- Validate the FastAPI Edge Node webhook under high concurrency and boundary inputs (invalid price, format, token).
- Check that circuit breakers successfully isolate non-1H signals.

### R2. TradingView CDP & Browser Integration Audit
- Verify the connection to the TradingView Desktop app via Chrome DevTools Protocol (CDP) on port 9222.
- Perform sanity tests to check that indicator alerts and chart interfaces load correctly.

### R3. Telegram Notification & Interactive Hub Verification
- Audit the Telegram Bot service, ensuring message dispatch and interactive trade approvals return correctly structured message coordinates.
- Ensure no silent return type mismatches between components.

## Acceptance Criteria

### Security & Error Handling
- [ ] No unauthorized payloads bypass the webhook gate.
- [ ] Webhook rate limits (15 req/min) trigger HTTP 429 successfully and recover automatically.

### System Interoperability
- [ ] CDP debug connection returns valid version JSON from local TradingView desktop app.
- [ ] Interactive approval callbacks map accurately to their respective active signal trackers without silent failures.

## Follow-up — 2026-05-23T03:40:30Z

Gather, compile, and structure the complete Weex API documentation (Spot and Contract V2 API specifications, WebSocket, signatures, and integrations) into unified Markdown reference documents, separate Knowledge Items (KIs), and nodes/edges in both the local L1 Hybrid Memory and Graph Memory.

Working directory: `C:/Users/pesil/EAIS/.agents/lobes/knowledge`
Integrity mode: development

## Requirements

### R1. Crawl & Extract Weex API Documentation (Scope: API & Docs)
Scrape and parse all Weex API documentation URLs specified:
1. `https://www.weex.com/api-doc`
2. `https://www.weex.com/api-doc/spot/introduction/APIBriefIntroduction`
3. `https://www.weex.com/api-doc/contract/intro`
4. `https://www.weex.com/api-doc/contract/QuickStart/IntegrationPreparation`
5. `https://www.weex.com/api-doc/contract/V2/log/changelog`
6. Any other linked sub-domains/sub-pages related specifically to APIs or documentation (e.g. `docs.weex.com`, `api.weex.com` or paths within `weex.com/api-doc/*`).

### R2. Synthesize Markdown Reference Documents
Generate a comprehensive, professionally structured Markdown reference document containing all API endpoints, request/response models, signatures, and quickstart guides.

### R3. Generate Knowledge Items (KIs)
Extract core concepts, schemas, integration rules, and changelogs from the compiled docs, and save them as individual `.md` files in BOTH of the following locations:
- **Core EAIS Path:** `C:/Users/pesil/EAIS/.agents/lobes/knowledge/weex/`
- **Workspace Path:** `c:/Users/pesil/working/mj_trading/TradingViewProject/lobes/knowledge/weex/`

### R4. Dual Knowledge Graph (KG) & L1 Memory Ingestion
Ingest the synthesized API elements and KIs into the local memories:
1. **L1 Hybrid Memory (sqlite-vec):** Store semantic memories via the `angati/memory_store` MCP tool (using `category: "knowledge"`).
2. **Graph Memory (Entities/Relations):** Create nodes and relations using the `memory/create_entities` and `memory/create_relations` MCP tools to map API endpoint dependencies and structures.

## Acceptance Criteria

### Content Completeness & Formatting
- [ ] Synthesized markdown contains Spot API, Contract V2 API, WebSocket, and Demo Mode specifications.
- [ ] Synthesized markdown is fully valid Markdown with proper heading structures, table models, and code block formatting.
- [ ] No placeholder text exists in the generated documents.

### File Outputs & Sync
- [ ] Knowledge Items (KIs) are successfully saved as `.md` files in `C:/Users/pesil/EAIS/.agents/lobes/knowledge/weex/`.
- [ ] Knowledge Items (KIs) are successfully saved as `.md` files in `c:/Users/pesil/working/mj_trading/TradingViewProject/lobes/knowledge/weex/`.

### Knowledge Ingestion Verification
- [ ] The L1 Hybrid Memory contains stored memories under category `knowledge` containing the term "Weex".
- [ ] The Graph Memory contains entities/relationships matching "Weex API" or specific endpoints.
- [ ] A verification script or query test verifies that memory retrieval for Weex-related terms is functional.

## Follow-up — 2026-05-26T23:34:26+07:00

Implement an automated "Scan All" background feature for the trading bot server to dynamically retrieve all active USDT-M futures contract pairs on Weex (using suffix `_UMCBL`) and all configured exchanges in `.env`, and scan them for VCP (Volatility Contraction Pattern) and Minervini Trend Template setups.

Working directory: `c:/Users/pesil/working/mj_trading/TradingViewProject`
Integrity mode: development

## Requirements

### R1. Dynamic Symbol Discovery
- Implement a method to dynamically query the active exchanges (e.g. Weex V2 contract symbol lists at `/api/v2/contract/public/symbols` and other configured exchanges) to retrieve all active linear trading pairs dynamically rather than a static watchlist.

### R2. Complete Unfiltered Scanning
- Scan all discovered pairs dynamically without pre-filtering.
- Implement a robust concurrency queue and rate-limiting handler (e.g., exponential back-off on HTTP 429) to ensure all pairs are successfully scanned without getting blocked by the exchanges.

### R3. API Endpoints & Telegram Commands
- Implement `GET /api/scan/all` which triggers the complete scan-all operation and returns ranked setups.
- Register a Telegram command `/scan_all` to execute the scan and broadcast the top setups (Trend Template score >= 6 or VCP detected) directly to the Telegram chat.

## Acceptance Criteria

### Functionality
- [ ] Successfully retrieves active pairs dynamically from Weex and other configured exchanges.
- [ ] Scans 100+ active pairs concurrently without getting rate-limit blocked.
- [ ] Correctly computes Trend Template & VCP scores for Weex futures contract pairs.

### Integration
- [ ] Endpoint `/api/scan/all` is active and returns valid JSON output.
- [ ] Telegram bot command `/scan_all` functions and broadcasts results.

## Follow-up — 2026-05-26T23:46:29+07:00

The user has updated `nerves/workers/trading/exchanges/weex_adapter.py` to add `get_active_symbols()` which fetches active futures symbols dynamically:
```python
    async def get_active_symbols(self) -> List[str]:
        if self.dry_run:
            return ["BTCUSDT_UMCBL", "ETHUSDT_UMCBL", "SOLUSDT_UMCBL", "ADAUSDT_UMCBL", "XRPUSDT_UMCBL"]
        try:
            data = await self._request("GET", "/api/v2/contract/public/symbols")
            symbols_list = data.get("data", [])
            active_symbols = []
            for s in symbols_list:
                sym = s.get("symbol", "")
                status = s.get("status", "")
                if sym.endswith("_UMCBL") and status == "Trading":
                    active_symbols.append(sym)
            return active_symbols
        except Exception as e:
            log.error(f"Error fetching active symbols from Weex: {e}")
            return ["BTCUSDT_UMCBL", "ETHUSDT_UMCBL"]
```
Please utilize this method for implementing R1 (Dynamic Symbol Discovery) on the Weex exchange.


## Follow-up — 2026-05-27T06:05:42Z

Implement Multi-Timeframe (MTF) Nested Chart Inset Layouts in the Stealth Capture Studio.

Working directory: c:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development

## Requirements

### R1. Timeframe Mappings and Concurrent Data Fetching
- Define mappings for nested timeframes: `15m` (parent `1H`) and `1H` (parent `4H`).
- When a nested timeframe is captured, fetch both target and parent timeframe candles concurrently using exchange adapters and fallbacks.
- Store parent timeframe candles in the payload.

### R2. PiP Inset Chart Layout Rendering
- Modify the chart HTML rendering (`chart_template.html`) to dynamically overlay a nested parent timeframe chart if parent candles are present in the payload.
- Apply modern glassmorphism styling to the floating container: `#1e222d` background, `8px` border radius, and `rgba(255,255,255,0.08)` border.
- Include a text label identifying the parent timeframe (e.g. "4H Parent Trend").
- Render an SVG arrow indicator (#2962ff) pointing from the inset chart to the main chart area.

## Acceptance Criteria

### Functionality & Routing
- [ ] Querying `/api/vision/capture` for `1H` timeframe concurrently fetches `1H` and `4H` data, and renders both charts on the returned image with a directional arrow.
- [ ] Querying `/api/vision/capture` for `15m` timeframe concurrently fetches `15m` and `1H` data, and renders both charts on the returned image with a directional arrow.
- [ ] Single timeframes like `4H`, `1D`, or `1W` render a single chart without nested insets.
- [ ] Fallback matplotlib rendering succeeds as a single chart without exceptions if Playwright fails.

## Follow-up — 2026-05-27T19:12:33+07:00

Automate connecting to TradingView Desktop via Chrome DevTools Protocol (CDP) on port 9222 (including auto-launching and MSIX packaging path resolution), extracting live study values and dynamic active symbols from the active chart page, and validating the integration by sending simulated real data payloads to the webhook ingress.

Working directory: c:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development (Forbidden to read test source code or hardcode verification assertion responses)

## Requirements

### R1. TradingView CDP Auto-Launch & Discovery
- Attempt to connect to port 9222. If disconnected, automatically locate and launch TradingView Desktop with `--remote-debugging-port=9222`.
- Resolve MSIX / Windows Store installations of TradingView using PowerShell `Get-AppxPackage` if standard program directories are empty.
- Verify connectivity to the Chrome DevTools Protocol server before proceeding.

### R2. Dynamic Symbol & Study Value Extraction
- Dynamically parse the active symbol name directly from the open TradingView DOM layout. 
- Use `BTCUSDT` or `TAOUSDT` as fallback tickers only if the active symbol name cannot be parsed from the DOM.
- Extract the current chart parameters, including the latest close price, timeframe interval, and study indicators (SMA50, SMA150, SMA200, and ATR14).

### R3. Webhook E2E Simulation
- Assemble a valid indicator payload matching the schema requirements of `/webhook`.
- Populate it with the dynamically extracted symbol, price, and ATR parameters.
- POST the payload to `/webhook` with `"source": "indicator"` and confirm it is successfully accepted (HTTP 200) and persisted in the local SQLite database.

## Acceptance Criteria

### Connection & Discovery
- [ ] Script successfully launches and connects to TradingView CDP (port 9222).
- [ ] Dynamically parses the currently active ticker from the TradingView interface.
- [ ] Dynamic extraction successfully returns non-empty stats for price, interval, and ATR.

### Webhook Verification
- [ ] Successfully sends the dynamic payload to `/webhook` and receives a HTTP 200/202 confirmation.
- [ ] A query on `/api/indicator-signals` confirms the dynamically fetched symbol, price, and ATR metadata have been persisted in the `indicator_signals` table.

## Follow-up — 2026-05-27T22:49:02+07:00

Thiết lập và mở rộng hệ thống tích hợp tín hiệu TradingView về Local Server thông qua Webhook và Chrome DevTools Protocol (CDP), bổ sung các tính năng tự động xác thực, quản lý vốn thích ứng ATR, tự động khôi phục kết nối và lọc nhiễu bằng AI.

Working directory: c:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development

## Requirements

### R1. Auto-Validation & Dynamic Slippage Control
Hệ thống tự động so khớp giá kích hoạt của Webhook (`price`) với giá Market thực tế từ sàn giao dịch (Binance) tại thời điểm nhận tín hiệu. Nếu độ lệch (trượt giá) vượt quá 0.5%:
- Chuyển lệnh từ Market Order sang Limit Order tại mức giá mong muốn của Webhook.
- Nếu không khớp sau 30 giây, hủy lệnh và gửi cảnh báo "Slippage Warning" qua Telegram.

### R2. ATR-Based Adaptive Position Sizing
Tự động điều chỉnh kích thước vị thế giao dịch dựa trên độ biến động thực tế:
- Trích xuất `atr_value` từ payload Webhook.
- Tính toán Stop Loss = Entry Price - (2 * ATR) cho lệnh Long.
- Tính toán khối lượng giao dịch (`quoteQty`) sao cho rủi ro tối đa cho mỗi lệnh không vượt quá 1.0% số dư khả dụng trên tài khoản sàn giao dịch.

### R3. CDP Automatic Health Check & Keep-Alive
Xây dựng module giám sát hoạt động của TradingView Desktop qua Chrome DevTools Protocol (CDP):
- Định kỳ (mỗi 5 phút) kiểm tra phản hồi của tab TradingView.
- Nếu tab bị treo (crash), mất kết nối WebSocket hoặc không phản hồi trang trong 30 giây, tự động phát lệnh reload tab thông qua CDP kết nối ở cổng `9222`.

### R4. AI Market Regime Filter
Tích hợp bộ lọc phân loại bối cảnh thị trường trước khi thực thi tín hiệu từ chiến lược A.007 + MIS:
- Sử dụng công cụ phân tích hình ảnh biểu đồ qua Gemini Vision (tại `vision.py`) hoặc thuật toán Heuristic (được tính toán từ dữ liệu nến gần nhất) để xác định trạng thái thị trường: `TREND` hay `CHOP` (Sideway).
- Nếu thị trường là `CHOP`, tự động giảm 50% khối lượng đặt lệnh hoặc bỏ qua các tín hiệu breakout của A.007.

## Acceptance Criteria

### Webhook & Slippage Control
- [ ] Thực hiện so khớp giá webhook và giá thị trường thực tế ngay khi nhận payload.
- [ ] Lệnh giao dịch được chuyển thành lệnh Limit khi slippage > 0.5%.

### ATR Position Sizing
- [ ] Khối lượng giao dịch được tính toán động dựa trên `atr_value` của payload và số dư tài khoản thực tế.
- [ ] Mức Stop Loss và Take Profit của lệnh OCO được đặt chuẩn xác theo công thức ATR.

### CDP Keep-Alive
- [ ] Phát hiện trạng thái offline hoặc crash của tab TradingView.
- [ ] Thực hiện reload tab thành công qua kết nối CDP cổng 9222.

### AI Regime Filter
- [ ] Tín hiệu giao dịch được phân loại theo trạng thái thị trường (Trend/Chop) trước khi gửi tới Trade Engine.
- [ ] Khối lượng lệnh hoặc quyết định bỏ qua lệnh được thực thi chính xác theo trạng thái Trend/Chop được phân loại.

## Follow-up — 2026-05-28T00:43:55+07:00

Xây dựng hệ thống tự động kiểm thử (Auto-Test Runner) chạy dưới dạng Watcher tự động giám sát mã nguồn (Python & Pine Script). Khi phát hiện thay đổi, hệ thống chạy lại các bài kiểm thử và xác thực hệ thống (Database, API, CDP). Nếu thất bại, hệ thống ghi log, cập nhật Dashboard và gửi cảnh báo qua Telegram.

Working directory: c:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development

## Requirements

### R1. Watcher-Based Auto-Test Execution
Xây dựng một module Watcher giám sát thư mục mã nguồn (`nerves/workers/trading/`) và thư mục Pine Script (`pine/`). 
- Khi phát hiện thay đổi trên các file `.py` hoặc `.pine`, tự động kích hoạt `pytest` chạy lại các bài kiểm thử liên quan.
- Đảm bảo cơ chế debounce để tránh chạy liên tiếp nhiều lần khi lưu nhiều file cùng lúc.

### R2. System Health & Integration Verification
Bên cạnh kiểm thử code, Watcher sẽ tự động xác thực:
- Trạng thái kết nối cơ sở dữ liệu `trades.db`.
- Liveness check của API Server (cổng 5000) và CDP (cổng 9222).
- Cập nhật trạng thái sức khỏe này vào một bảng dữ liệu hoặc biến cấu hình hệ thống (Dashboard state) để hiển thị trực quan.

### R3. Multi-Channel Alerting on Failure
Khi phát hiện bài test thất bại hoặc dịch vụ ngắt kết nối:
- Ghi log chi tiết lỗi ra file `test_runs.log`.
- Cập nhật trạng thái lỗi lên Dashboard.
- Gửi tin nhắn khẩn cấp qua Telegram Bot kèm thông tin file bị lỗi và thông điệp lỗi (traceback rút gọn).

## Acceptance Criteria

### Watcher Behavior
- [ ] Watcher phát hiện chính xác khi thay đổi/lưu file `.py` hoặc `.pine` và tự động chạy `pytest`.
- [ ] Áp dụng debounce (tối thiểu 1 giây) thành công.

### Diagnostics & Dashboard Update
- [ ] Kiểm tra được kết nối SQLite, API (5000) và CDP (9222).
- [ ] Trạng thái kết quả chạy test và sức khỏe hệ thống được lưu trữ và cập nhật thành công lên Dashboard state (settings/DB).

### Alerting & Logs
- [ ] Lỗi kiểm thử được ghi nhận đầy đủ vào `test_runs.log`.
- [ ] Tin nhắn Telegram được gửi đi chính xác khi có kiểm thử thất bại.

## Follow-up — 2026-05-29T01:41:19+07:00

# Teamwork Project Prompt — Draft

> Status: Launched — Đội ngũ Agent đang thực thi kiểm tra hệ thống
> Goal: Chạy xác minh độc lập bằng teamwork_preview để đảm bảo không còn lỗi hồi quy (regression) và rò rỉ bộ nhớ.

Kiểm tra và xác minh toàn bộ các thay đổi kiến trúc tối ưu hóa Telegram Bot, MCP Client, và REST Fallback đã thực hiện trong dự án.

Working directory: `C:\Users\pesil\working\mj_trading\TradingViewProject`

## Requirements

### R1. Kiểm tra tính ổn định và Concurrency của MCP Client
- Xác minh xem cơ chế `asyncio.gather` và `asyncio.Semaphore(5)` trong `mcp_client.py` có chạy ổn định dưới điều kiện thực tế (ví dụ: quét 10-15 symbols liên tục).
- Đảm bảo không xảy ra hiện tượng chồng chéo tài nguyên (Resource collision) hoặc rò rỉ tiến trình con Node.js.

### R2. Xác minh tính phản hồi của Telegram Bot
- Xác minh các lệnh `/scan`, `/scan_all`, `/scan_mtf`, `/recommend` hoạt động trơn tru trên môi trường thực tế.
- Kiểm tra xem các background tasks có bị "lạc trôi" (orphan tasks) khi người dùng spam lệnh hoặc hủy phiên chat không.

### R3. Kiểm tra hồi quy toàn bộ hệ thống (Regression Testing)
- Chạy toàn bộ 434 tests của hệ thống để xác định nguyên nhân gây treo/deadlock khi chạy chung toàn bộ test suite.
- Sửa đổi hoặc tối ưu hóa các phần test bị ảnh hưởng để đảm bảo toàn bộ test suite chạy thành công 100% không bị treo.

## Acceptance Criteria

### Verification & Stability
- Tất cả 434 tests trong bộ test suite của hệ thống chạy hoàn tất thành công (PASSED) mà không gặp bất kỳ lỗi treo hay deadlock nào.
- Xác minh độc lập cơ chế Semaphore của MCP Client hoạt động chính xác trong môi trường multi-threaded/multi-process.

## Follow-up — 2026-05-29T05:00:10+07:00

Implement a true Multi-Timeframe (MTF) execution in the consolidated Pine Script strategy and compile a central optimized parameters matrix for BTC, ETH, and SOL.

Working directory: c:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development

## Requirements

### R1. True Multi-Timeframe (MTF) Pine Script Upgrade
- Upgrade `pine/v2/minervini_strategy.pine` to support true MTF calculations.
- When `strat_mode` is set to "Daily Trend Follower (MTT v1.005-b)", calculate EMA 20/50/100 from the Daily timeframe even when the strategy is run on lower timeframes (e.g., 1H, 4H).
- Enforce strict lookahead-free security calculations using `barmerge.lookahead_off` and series indexing offsets (e.g., `[1]`) to prevent any future lookahead bias in backtests.

### R2. Central Configuration Matrix
- Create `docs/knowledge/trading_wizard/OPTIMIZED_PARAMETERS_MATRIX.md` containing a structured matrix/table of optimal parameters for BTC, ETH, and SOL.
- For ETH and SOL, adapt parameters from BTC and scale position sizing/ATR multipliers based on historical relative volatility (e.g., standard beta multipliers).
- The parameters should include MA configurations, ATR Multipliers, Stop-Loss/Take-Profit thresholds, Position Sizing, and Webhook payload parameters.

### R3. Multi-Asset Performance Summary
- Update `docs/reports/STRATEGY_GENEALOGY.md` to map out the strategy evolution including performance metrics (Profit Factor, Max Drawdown, Recovery Factor, Expectancy, Win Rate) across BTC, ETH, and SOL.

## Acceptance Criteria

### Pine Script Compilation & Lookahead Validation
- [ ] The updated `pine/v2/minervini_strategy.pine` compiles in TradingView (or conforms perfectly to v5 syntax rules without syntax errors).
- [ ] No lookahead bias is present in the `request.security` calls (verifiable by using `[1]` offset on requested variables).

### Documentation Correctness
- [ ] `docs/knowledge/trading_wizard/OPTIMIZED_PARAMETERS_MATRIX.md` contains complete, non-placeholder tables for BTC, ETH, and SOL.
- [ ] `docs/reports/STRATEGY_GENEALOGY.md` has updated performance comparison tables for all three assets.

## Follow-up — 2026-05-29T20:15:55Z

Fix the deployment failure on Server A (Linux Gateway) in the CI/CD production pipeline action run.

Working directory: C:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development

## Requirements

### R1. Diagnose and Fix Deploy Server A Error
Diagnose the root cause of the failure during the "Deploy Server A (Gateway)" step in the GitHub Actions workflow and implement the necessary fixes to ensure the server starts and passes its health checks.

### R2. Verify Local Setup and CI/CD Script Parity
Ensure deployment files (e.g., docker-compose.server-a.yml, deploy.sh, and related scripts) are updated and consistent so that subsequent deployments pass successfully.

## Acceptance Criteria

### CI/CD Deployment Health
- [ ] The deployment script / compose config is corrected such that the Gateway (Server A) starts successfully.
- [ ] Gateway health check `curl -sf http://localhost:5000/health` or equivalent is healthy.
- [ ] No regression introduced to other deployments (Server B/C).

## Follow-up — 2026-05-29T23:13:04Z

Build a provisioning verification suite that programmatically checks all 43 infrastructure items from the VPS deployment checklist, and auto-ticks the checklist markdown when items pass. CI/CD deployment is already complete — this project ONLY verifies that the one-time server provisioning (OS, users, SSH, firewall, NTP, Docker, VPN, tunnels) was done correctly on each server.

Working directory: c:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development

## Architecture Reference

| Server | Role | OS | Location | Specs |
|--------|------|----|----------|-------|
| A | Ingest Gateway (VBS) | Debian 12 Minimal | Remote VPS | 1U2G |
| B | Execution Vault | Windows | Local Machine | 2U4G |
| C | AI Core (RAG + Analyzer) | **Oracle Linux 9** | Remote VPS | 8U16G |

**Network**: All 3 servers connected via Tailscale VPN (100.x.x.0/8). Server A also has Cloudflare Tunnel for public ingress.

**What already exists (DO NOT rebuild):**
- `scripts/init_server_debian.sh` — Debian 12 provisioning (Server A)
- `scripts/init_server_ol9.sh` — Oracle Linux 9 provisioning (Server C)
- `setup_tunnel.ps1` — Cloudflare Tunnel setup (Server A)
- `setup_server_c.ps1` — Server C deployment wizard
- `.github/workflows/deploy.yml` — Full CI/CD pipeline (lint → test → deploy A/C/B)
- `deploy/docker-compose.server-{a,b,c}.yml` — Per-server Docker Compose
- All health endpoints already implemented in application code

**Health endpoints (already live):**
- Server A: `GET :5000/health` → `{"status":"healthy", "pending_count": N}`
- Server B: `GET :5002/health` → `{"status":"ok", "server":"execution-vault-b"}`
- Server C ChromaDB: `GET :8000/api/v1/heartbeat`

**The checklist to verify** is in `docs/SETUPS/01_VPS_SERVER_SETUP_GUIDE.md`, Section 11 (lines 1091-1155), containing 43 items across 4 subsections:
- 11.1 SERVER A (15 items): OS, apt, botuser, SSH, Fail2Ban, UFW, NTP, Swap, Docker, log limits, Tailscale, Cloudflare, VBS health, BUFFER_SECRET, Telegram
- 11.2 SERVER C (12 items): OS, botuser+SSH, NTP, Docker, Tailscale, ChromaDB, Analyzer, connect→A, connect→B, liveness monitor, disk monitor, circuit breaker
- 11.3 SERVER B (10 items): Windows Update, Python 3.11+, NTP, Tailscale, Firewall, Execution Server, SERVER_B_SECRET, API Keys, test execute-trade, Telegram
- 11.4 Cross-Server (6 items): ping A↔C, ping B↔C, clock drift <50ms, E2E pipeline, Telegram from all 3, UptimeRobot active

## Requirements

### R1. Per-Server Provisioning Verification Probes

Create a Python verification module (`scripts/verify_provisioning.py`) that can SSH into each server (or run locally for Server B) and check infrastructure provisioning status. For each of the 43 checklist items, implement a concrete probe:

- **SSH-based probes** (Server A + C): Check OS version, user existence, SSH config, service status (fail2ban, chrony/chronyd, docker, tailscale, cloudflared, ufw/firewalld), swap, docker log config, Tailscale IP
- **Local probes** (Server B): Check Python version, Windows service status, firewall rules, Tailscale connection, NTP sync
- **HTTP probes** (all): Hit health endpoints over Tailscale IPs to verify application layer
- Each probe returns a structured result: `{item_id, server, description, status: PASS|FAIL|SKIP, detail}`
- Support `--server a|b|c|all` flag to target specific servers
- Support `--dry-run` to show what would be checked without running probes

### R2. Cross-Server E2E Verification

Implement the 6 cross-server verification checks from Section 11.4:
- Tailscale ping between C↔A and C↔B
- NTP clock drift measurement across all 3 servers (must be <50ms)
- E2E signal flow test: simulate a webhook → verify it arrives at A's queue → verify C can consume → verify C can reach B's endpoint (connectivity only, no real trade)
- Telegram delivery verification from each server
- UptimeRobot/Cloudflare monitoring status check

### R3. Checklist Auto-Ticker

After verification runs, auto-update the checklist in `docs/SETUPS/01_VPS_SERVER_SETUP_GUIDE.md`:
- Replace `☐` with `☑` for items that PASS
- Leave `☐` unchanged for FAIL or SKIP items
- Also update the identical copy at `docs/reports/01_VPS_SERVER_SETUP_GUIDE.md`
- Generate a summary report (JSON + human-readable markdown) saved to `docs/reports/provisioning_verification_report.md`
- Support `--no-tick` flag to generate the report without modifying checklist files

## Acceptance Criteria

### Verification Coverage
- [ ] `verify_provisioning.py --server a --dry-run` lists all 15 Server A items with their probe descriptions
- [ ] `verify_provisioning.py --server c --dry-run` lists all 12 Server C items (using Oracle Linux 9 probes, NOT Debian)
- [ ] `verify_provisioning.py --server b --dry-run` lists all 10 Server B items (Windows-native checks)

### Probe Accuracy
- [ ] SSH probes correctly detect: OS version (Debian 12 vs Oracle Linux 9), running services (systemctl/firewalld), user existence, SSH config values
- [ ] HTTP probes correctly distinguish healthy vs unreachable endpoints with proper timeout handling (5s connect, 10s read)
- [ ] Cross-server NTP drift measurement uses `chronyc tracking` (Linux) and `w32tm /stripchart` (Windows) and correctly compares timestamps

### Checklist Updates
- [ ] Running `verify_provisioning.py --all --auto-tick` updates BOTH copies of the checklist (docs/SETUPS/ and docs/reports/) consistently
- [ ] Only PASS items get ticked; FAIL/SKIP items remain `☐`

## Follow-up — 2026-05-31T00:39:19+07:00

Implement and deploy a decentralized signal logging, RAG SEPA AI analysis, and trade forwarding pipeline on Server C that polls raw signals from Server A, analyzes them, and forwards the execution commands to Server B.

Working directory: ~/teamwork_projects/vps_signal_pipeline
Integrity mode: development

## Requirements

### R1. Signal Consumer Long-polling (Server C)
- Implement a background service/daemon (`vps_consumer.py`) on Server C that pulls pending signals from Server A Ingress Gateway (VBS service) using long-polling to keep latency < 1s.
- Store consumed signals locally in `server/trades.db` under the `indicator_signals` and `signals` tables, maintaining idempotency based on `vbs_queue_id`.

### R2. RAG and SEPA AI Analysis (Server C)
- Set up local ChromaDB vector DB access on Server C to query SEPA chunks from `docs/knowledge/trading_wizard/chunks`.
- Run SEPA analysis on entry/exit signals using Gemini as the primary AI provider (leveraging the valid GEMINI_API_KEY from env) via the Antigravity SDK, determining Mark Minervini alignment and calculating stop-loss and take-profit levels using ATR.

### R3. Safe Trade Command Forwarding (Server C -> Server B)
- When a valid entry/exit signal is analyzed and approved, forward the finalized trade execution payload to Server B's execution endpoint at `http://${SERVER_B_IP}:5002/api/execute-trade`.
- Secure transmission by signing the request with `X-Server-B-Secret` header authentication.

## Acceptance Criteria

### Ingestion & Analysis Verification
- [ ] Implement a mock simulation harness (`scripts/simulate_pipeline.py`) that mocks Server A's queue endpoints (`/consume` and `/ack`) and Server B's execution endpoint.
- [ ] Confirm the long-polling consumer retrieves queued signals within < 1 second.
- [ ] Verify that SEPA analysis is generated and stored in the database.
- [ ] Verify that HTTP requests to Server B are properly formatted and include the required security headers.


## Follow-up — 2026-05-31T03:58:48+07:00

Implement local Telegram Bot signal synchronization (Option 2) in the 3-server decentralized pipeline. This ensures signals requiring human approval are held on Server B (Local/Windows) and handled interactively via the Telegram bot running inside the execution server.

Working directory: c:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development

## Requirements

### R1. Lifespan and Bot Initialization in Execution Server
- Start and stop the interactive Telegram bot daemon inside the `execution_server.py` application's lifespan if `TELEGRAM_BOT_ENABLED=true` in `.env`.
- Ensure all event handlers for `trade_engine` and `notification_hub` are registered on the EventBus when `execution_server.py` starts, so that events such as `TradeApproved`, `TradeExecuted`, and `TradeFailed` are correctly handled.

### R2. Human-in-the-Loop Gating in Execution Server
- In `execution_server.py`, modify the `POST /api/execute-trade` endpoint:
  - Check if the incoming payload has `"hold_for_approval": true` or if its `"ai_confidence"` is between 50 and 79.
  - If held for approval, persist the signal in the database and register it in `PENDING_TRADES` (shared memory).
  - Trigger the interactive Telegram approval card using `telegram_bot.send_interactive_trade_approval(...)` instead of executing the trade immediately.
  - If approved by the user via Telegram callback, pop it from `PENDING_TRADES` and trigger trade execution through the normal event pipeline.

### R3. Confidence-Based Flagging in AI Analyzer
- In `vps_analyzer.py` (Server C), update signal evaluation to check the calculated confidence score (`ai_confidence` between 0-100).
- If the confidence score is between 50 and 79, set `"hold_for_approval": true` in the forwarded trade payload so that Server B holds it for manual approval.
- Ensure the signal is still forwarded to Server B for manual gating.

## Acceptance Criteria

### Interactive Gating & Flow Correctness
- [ ] Implement a unit/integration test suite at `server/tests/test_decentralized_approval.py` that verifies:
  - Forwarded trade command with `hold_for_approval=True` is intercepted and added to `PENDING_TRADES`.
  - The Telegram bot interactive approval function is called with correct signal details.
  - High confidence signals (confidence >= 80) bypass approval and execute immediately.
  - Low confidence signals (confidence < 50) are auto-rejected by the analyzer.
  - Simulated button callback triggers `TradeApproved` and executes successfully via the engine.
- [ ] Run the complete test suite (`pytest server/tests/`) and confirm all tests pass.

## Follow-up — 2026-06-01T17:26:08+07:00

Extract all API documentation from the WEEX platform (https://www.weex.com/api-doc/) and update the local knowledge files inside the project's knowledge base.

Working directory: C:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development

## Requirements

### R1. Comprehensive Crawling of WEEX API Docs
Extract all pages and subpages of the WEEX API documentation starting from https://www.weex.com/api-doc/. This includes, but is not limited to:
*   Spot Trading (V1, V3)
*   Futures/Contract Trading (V2, V3, USDT-M, Coin-M)
*   Copy Trading & Social Trading APIs
*   WebSocket API (public and private channels)
*   Signature Calculation & Authentication mechanisms
*   Rate limits and weight specifications
*   Supported trading pairs and announcements

The crawling can utilize automated scripts (such as Python BeautifulSoup, Playwright, or direct requests) to fetch the dynamic content.

### R2. Update and Organize Local Knowledge Base (KIs)
Update existing markdown files and create new markdown files inside the local knowledge base directory:
`C:\Users\pesil\working\mj_trading\TradingViewProject\lobes\knowledge\weex`
The files should be cleanly structured, readable, and written in Markdown. All API models, endpoints, request parameters, response schemas, and code snippets must be preserved.

### R3. Automated Link & Schema Audit
Implement a validation check or audit step to ensure:
*   There are no broken relative links or placeholders in the generated markdown files.
*   All code examples (Python/Go/Curl) are syntactically valid and match WEEX requirements.

## Acceptance Criteria

### Documentation Completeness & Structure
- [ ] Every document category found on https://www.weex.com/api-doc/ has a corresponding `.md` file in `lobes/knowledge/weex`.
- [ ] No placeholders, draft notes, or unfinished sections are present in the final documents.
- [ ] The signature rules explicitly detail BOTH the V2 and V3 signing logic (differentiating query parameter concatenation).

### Verification
- [ ] A verification script runs and confirms all generated `.md` files contain valid markdown structure.
- [ ] An endpoint index file is generated listing all crawled endpoints and their mapped markdown files.

## Follow-up — 2026-06-01T18:04:56+07:00

Create a Master Plan to record the results of dry-run tests (Option 1) and plan the deployment and execution of real micro-volume trades on the WEEX Mainnet (Option 2).

Working directory: C:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development

## Requirements

### R1. Document Dry-Run Analysis (Option 1)
Execute the dry-run test (`test_weex_trial.py`) to gather real-time data from WEEX. Document the results including the scanned candle data, mock order execution success, simulated slippage/latencies, and the computed SEPA risk parameters (risk amount, position sizing, and stop-loss/take-profit boundaries).

### R2. Mainnet Deployment Strategy (Option 2 Plan)
Draft a strategic roadmap to transition from dry-run to real mainnet execution using minimal trade volumes. The plan must detail:
1.  **Credential Setup**: Securing and injecting production credentials securely in `.env`.
2.  **Safety Thresholds**: Hard limits on maximum order sizes, max daily losses, and drawdowns.
3.  **Failover & Rejection Handling**: How to catch connectivity errors (e.g. `getaddrinfo failed` or HTTP 4xx/5xx) and route trades to fallbacks (Binance/Bybit) or Telegram notifications.
4.  **Verification Steps**: Minimal smoke tests to perform before allowing automated TradingView webhook signals to execute.

### R3. Output Target File
Save the resulting master plan document as a clean, structured Markdown file at:
`C:\Users\pesil\working\mj_trading\TradingViewProject\lobes\knowledge\weex\weex_master_plan.md`

## Acceptance Criteria

### Master Plan Structure & Completeness
- [ ] The file `lobes/knowledge/weex/weex_master_plan.md` contains a summary section for Option 1 and a detailed checklist/strategy for Option 2.
- [ ] Option 1 records actual mock execution values (price, timestamp, size) parsed from the dry-run output logs.
- [ ] Option 2 contains concrete checklist items for safety parameters, error handlers, and fallback rules.

### Validation
- [ ] The generated Markdown file has valid links, syntax, and follows standard knowledge base formatting.

## Follow-up — 2026-06-02T00:09:32Z

Deep analysis, system design, and implementation/verification of Server C (AI Core) gaps including a FastAPI HTTP health endpoint, automated ChromaDB seeding, structured JSON logging, metrics collection, and graceful shutdown handling.

Working directory: `C:\Users\pesil\working\mj_trading\TradingViewProject\nerves\workers\trading`
Integrity mode: benchmark

## Requirements

### R1. System Design & Knowledge Base Documentation
Create detailed architecture design, API specs, and a knowledge base under `docs/` summarizing the decentralized 3-server system design, interaction sequence diagrams, and security model.

### R2. FastAPI HTTP Health Server on Server C
Implement a FastAPI app running on Server C (port 8000) that exposes a `/health` endpoint returning a structured JSON status report including:
- Liveness check results of Server A & B.
- Disk usage and log directory space usage.
- NTP clock drift status (verified against A & B).
- Circuit Breaker current state (CLOSED, OPEN, HALF_OPEN) and failure metrics.

### R3. Automated ChromaDB Seeding
Implement a reliable initialization and data seeding process that ensures knowledge chunks (from `docs/knowledge/trading_wizard/chunks/`) are successfully loaded and upserted into ChromaDB upon startup, even when running in remote mode.

### R4. Structured JSON Logging & Metrics Export
Implement structured JSON formatting for all core worker logs (analyzer, monitors). Expose prometheus-style or JSON-formatted operational metrics (LLM latency, RAG query latency, signal count, circuit breaker transitions).

### R5. Graceful Shutdown Handling
Implement proper capture of SIGTERM and SIGINT signals in `vps_analyzer.py` and monitoring workers. Ensure any active async network sessions (aiohttp sessions) are cleanly closed, pending files flushed, and shutdown status logged.

## Verification & Acceptance Criteria

### Automated Tests & Checks
- [ ] A script `verify_server_c_gaps.py` exists in the `scripts/` directory to run verification.
- [ ] Running `verify_server_c_gaps.py` automatically checks and confirms:
  - FastAPI health server is reachable and `/health` returns status `200` with JSON keys: `status`, `liveness_monitors`, `disk_usage`, `clock_drift`, `circuit_breaker`.
  - ChromaDB remote/local client successfully connects and retrieves the loaded `minervini_knowledge` collection count (should be >0).
  - Logs are written in valid JSON format.
  - Sending SIGTERM to the analyzer worker results in a log entry confirming graceful shutdown.

### Documentation Check
- [ ] Comprehensive System Design document exists in the project's documentation folder (`docs/`) detailing the architecture of the 3-server pipeline, the sequence diagram of signal analysis, and security configurations.

## Follow-up — 2026-06-03T05:38:40+07:00

Implement three types of advanced tests for the TradingViewProject system: Cross-Server Integration Test (Server A -> Consumer C -> RAG Analyze -> Server B), Confidence Edge Case Test (Auto-rejection behavior around confidence score 50), and Exchange Routing Fallback Recovery Test (when both Primary and Fallback servers are unavailable).

Working directory: c:\Users\pesil\working\mj_trading\TradingViewProject
Integrity mode: development

## Requirements

### R1. Cross-Server Integration Test
Implement a comprehensive cross-server integration test that covers the end-to-end signal flow: Signal received at Server A -> Consumer on C pulls the signal -> RAG analyze -> Forward to Server B using mock servers.

### R2. Confidence Edge Case Test
Implement verification for confidence score filtering, specifically targeting edge cases (e.g., scores 49, 50, and 51) where the auto-rejection threshold is set to 50.

### R3. Fallback Routing & Recovery Test
Implement testing for exchange routing failure scenarios, specifically verifying recovery behavior when both Primary and Fallback exchanges (e.g., Server B) are temporarily down and subsequently recover.

### R4. End-to-End Duplicate Signals Test
Implement end-to-end checks to detect and properly handle duplicate signals sharing the same price and timestamp.

## Acceptance Criteria

### Integration Test Success
- [ ] Integration test suite executes successfully, showcasing a signal traversing Server A, Consumer C (with local ChromaDB/RAG query), and routing to Server B.
- [ ] Edge cases for confidence scores (49, 50, 51) are tested, proving that scores < 50 are rejected and >= 50 are accepted.
- [ ] Recovery mechanism is tested and verified when Primary + Fallback exchanges are down and recover.
- [ ] E2E duplicate detection prevents redundant order placements/signals at the end of the pipeline.

## Follow-up — 2026-06-02T22:39:38Z

Hi team, the user has requested to refine our focus. We should now concentrate primarily on the "Cross-Server Integration Test (Server A -> C)".

Please update your briefing, task checklists, and current plan to reflect this priority. We want to test the full pipeline from Server A (VBS) to Server C (VpsAnalyzerWorker) including the long-poll, processing (RAG, validation, confidence edge cases), and ACK flow.

Please adjust the project orchestrator's focus accordingly. Let me know once you have updated the plan.



