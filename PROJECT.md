# Project: Angati TradingView Webhook Server — v7.0

## Overview

Hệ thống giao dịch tự động tích hợp TradingView + Binance/WEEX với AI (RAG/Claude), bảo mật SEC-04, và chế độ Forward Test paper trading.

## Architecture

- **Server A (Gateway VPS)**: Nhận webhook từ TradingView, lưu `signal_queue.db`, chuyển tiếp đến Server C
- **Server B (Local Engine)**: Thực thi lệnh Binance/WEEX
- **Server C (AI Core)**: FastAPI v7.0, RAG, MCP, routing layer, dual-DB Forward Test

## Milestones

| # | Name | Scope | Status |
|---|------|-------|--------|
| M1 | Linting & Code Quality | SEC-01 + SEC-02: 188 lint alerts → 0 | **DONE ✅** |
| M2 | SEC-04 Runtime Guards | SSRF, Path Traversal, Log Injection — 56/56 PASSED | **DONE ✅** |
| M3 | Final Pipeline Audit | SEC-03 CodeQL — 0 open critical alerts | **DONE ✅** |
| M4 | Forward Test DB Isolation | `forward_trades.db` tách biệt, routing layer | **DONE ✅** |
| M5 | Forward Test API | `?mode=FORWARD` trên tất cả endpoints trades/signals | **DONE ✅** |
| M6 | Back-test Signal Report | 1,100 signals — WR 55.55%, PF 2.138 | **DONE ✅** |
| M7 | Forward-Test Sample Report | 28 paper trades — WR 64.29%, PF 3.147 | **DONE ✅** |
| M8 | Test Suite | 930 tests unit/integration/stress — 100% PASSED | **DONE ✅** |
| M9 | Forward Test Live Run | Kết nối Server A ➔ Server C. Cấu hình webhook routing `dev/infra/forward-test-gateway-routing` & chạy thử nghiệm `dev/infra/forward-test-live-validation` | **DONE ✅** |
| M10 | Dashboard Dual-Mode | UI/API hiển thị LIVE + FORWARD song song. API layer `dev/infra/dashboard-dual-mode-api` & UI/UX `dev/ai/dashboard-dual-mode-ui` | **DONE ✅** |
| M11 | Telegram Dashboard Auth | Quick login via `/login` command, token-auth redirection. Branch: `dev/ai/easy-access-dashboard` | **ACTIVE 🔄** |
| M12 | Core & Security Gates | Security scan hook in Go daemon, bot notifications. Branch: `dev/ai/server-c-ai-core` | **ACTIVE 🔄** |
| M13 | FX Tactix Pine Generator | No-code strategy generator with multiple prompt levels. Branch: `dev/infra/fx-tactix` | **ACTIVE 🔄** |
| M14 | Indicator Filters V1.006 | Slope, Volume, ATR-trail filters & backtest matrix. Branch: `dev/infra/v1.006-filters` | **ACTIVE 🔄** |
| M15 | Regime Detection V1.007 | ADX + BB squeeze regime filters & combined strategies. Branch: `dev/infra/v1.007-regime` | **ACTIVE 🔄** |

## Branch Development & Issue Management

Để duy trì tính minh bạch và tránh xung đột khi làm việc trên nhiều nhánh tính năng đồng thời, các lỗi và thay đổi được quản lý và ghi nhận chi tiết theo từng nhánh phát triển tại thư mục `docs/branches/`:

- **Telegram Auth**: [dev-ai-easy-access-dashboard.md](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/docs/branches/dev-ai-easy-access-dashboard.md)
- **AI Core & Security**: [dev-ai-server-c-ai-core.md](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/docs/branches/dev-ai-server-c-ai-core.md)
- **FX Tactix**: [dev-infra-fx-tactix.md](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/docs/branches/dev-infra-fx-tactix.md)
- **Filters V1.006**: [dev-infra-v1.006-filters.md](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/docs/branches/dev-infra-v1.006-filters.md)
- **Regime V1.007**: [dev-infra-v1.007-regime.md](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/docs/branches/dev-infra-v1.007-regime.md)
- **Forward Test Validation**: [dev-infra-forward-test-live-validation.md](file:///c:/Users/pesil/working/mj_trading/TradingViewProject/docs/branches/dev-infra-forward-test-live-validation.md)

### Sử dụng `/git-commit-organizer` theo nhánh

Khi làm việc trên một nhánh phát triển hoặc thư mục worktree tương ứng, luôn sử dụng kỹ năng `git-commit-organizer` để tự động hóa khâu gom nhóm và commit an toàn:

1. **Phân tích thay đổi**:
   ```bash
   uv run python "C:\Users\pesil\.gemini\config\plugins\science\skills\git-commit-organizer\scripts\git_commit_organizer.py" analyze --output "scratch/proposal.json"
   ```
2. **Review và áp dụng**:
   ```bash
   uv run python "C:\Users\pesil\.gemini\config\plugins\science\skills\git-commit-organizer\scripts\git_commit_organizer.py" apply --input "scratch/proposal.json"
   ```


## Interface Contracts

- Tất cả file reads/writes phải dùng `safe_path` (SEC-04)
- Tất cả external HTTP calls phải qua `validate_exchange_params`
- Tất cả logs của user input phải qua `safe_log_input`
- Tín hiệu với `mode=FORWARD` được định tuyến sang `forward_trades.db`
- Tín hiệu với `mode=LIVE` hoặc không có mode → `trades.db`
- Sequence ID của Forward DB bắt đầu từ `1_000_000` để tránh collision

## Key Files — Forward Test Integration

| File | Mô tả |
| :--- | :--- |
| `nerves/workers/trading/data/routing.py` | Dynamic routing logic |
| `nerves/workers/trading/config.py` | `FORWARD_DB_PATH` config |
| `nerves/workers/trading/database.py` | Dual-DB migrator |
| `nerves/workers/trading/persistence_store.py` | CRUD với routing |
| `nerves/workers/trading/query_service.py` | Query với routing |
| `tests/integration/test_forward_test_routing.py` | Integration tests |
| `scripts/generate_backtest_report.py` | Back-test report generator |
| `scripts/generate_forward_test_report.py` | Forward-test sample report |
| `reports/backtest_signal_report.html` | 1,100 signals back-test |
| `reports/forward_test_sample_report.html` | 28 paper trades mẫu |

## Reports Summary

| Báo cáo | Tín hiệu | Win Rate | Profit Factor | Expectancy |
| :--- | :--- | :--- | :--- | :--- |
| Back-test Extended | 1,100 | 55.55% | 2.138 | +3.27% |
| Forward-Test Sample | 28 | 64.29% | 3.147 | +6.14% |
| Server A Signals | 285 | — | — | — |
