---
name: fx-tactix
description: Sinh Pine Script v5 từ mô tả tiếng Việt theo phong cách FX Tactix Claude (no-code prompt → code). Dùng khi user gõ /fx-tactix <mô tả strategy> hoặc hỏi "tạo strategy/indicator Pine từ mô tả ...". 5 levels: brief / strategy / backtest_review / mtf / alert.
---

# FX Tactix Claude — Pine Generator

Sinh Pine Script v5 từ mô tả tự nhiên, lưu vào `pine/v2/generated/`.
**Chạy trực tiếp trong phiên Claude Code — không tốn API credit.**

## Bước thực hiện

1. **Xác định LEVEL** từ `$ARGUMENTS`:
   - Có "morning brief" / "đọc chart sáng" → level 1
   - Có "strategy" / "indicator" / mô tả entry/exit → level 2 (mặc định)
   - Có "backtest" / "kết quả" / "tinh chỉnh" → level 3
   - Có "đa khung" / "multi timeframe" / "MTF" → level 4
   - Có "alert" / "webhook" / "bot" → level 5

2. **Đọc prompt template** tương ứng tại `docs/fx_tactix/prompts/level_{N}_*.md`.

3. **Điền biến** từ `$ARGUMENTS`. Nếu thiếu thông tin bắt buộc (description, symbol, strategy name…), hỏi user 1 lần ngắn gọn rồi tiếp tục.

4. **Sinh output**:
   - Level 1, 3, 4: trả markdown text trong response.
   - Level 2, 5: sinh Pine v5 code → **ghi file** vào `pine/v2/generated/fx_<slug>_<YYYYMMDD_HHMMSS>.pine`.
     - Slug = snake_case của description (≤ 40 ký tự).
     - Tạo thư mục `pine/v2/generated/` nếu chưa có.

5. **Kiểm tra cú pháp** (chỉ với level 2, 5):
   - Nếu TradingView MCP đang chạy (`mcp__tradingview__tv_health_check` ok):
     - `mcp__tradingview__pine_new` → `mcp__tradingview__pine_set_source` → `mcp__tradingview__pine_smart_compile`
     - Nếu có error → đọc `mcp__tradingview__pine_get_errors`, fix, retry 1 lần.
   - Nếu MCP không có → báo user chạy `/tv-start` để compile, vẫn lưu file.

6. **Báo cáo** (≤ 5 dòng):
   - Level + slug + đường dẫn file (markdown link)
   - Trạng thái compile (✅ pass / ⚠️ chưa kiểm / ❌ error)
   - Gợi ý next step (paste vào Pine Editor / chạy backtest / wire alert)

## Quy tắc Pine v5 bắt buộc

- `//@version=5` ở dòng đầu.
- `strategy()` / `indicator()` có `shorttitle`, `overlay` rõ ràng.
- Mọi magic number → `input.int/float/bool` với tooltip.
- Strategy: `strategy.entry`, `strategy.exit` với `stop=`, `limit=`.
- Risk mặc định: SL 8%, TP 20%, R:R ≥ 2.5 (đúng với `config.STOP_LOSS_PCT` / `TAKE_PROFIT_PCT`).
- Có ít nhất 1 `alertcondition()` với message JSON match webhook schema (xem level 5 prompt).
- KHÔNG dùng `request.security(..., lookahead=barmerge.lookahead_on)` (repaint).

## Không làm

- Không tự động backtest — user quyết định.
- Không commit file generated — `pine/v2/generated/` thường nằm trong `.gitignore`.
- Không gọi `anthropic` API — đã chạy trong Claude Code rồi, redundant.
- Không sinh code nếu user yêu cầu strategy có yếu tố insider trading, pump & dump, hoặc bypass exchange ToS.

## Liên kết

- Workflow doc: `docs/fx_tactix/README.md`
- API endpoint tương đương: `POST /api/fx-tactix/generate` (server/fx_tactix.py)
- So sánh với hệ thống chính: `docs/doithu/fx_tactix_vs_our_project.md`
