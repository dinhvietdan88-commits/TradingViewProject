# Plan: Add `/minervini-assess` Quick-Access Skill

## Context
Hiện tại để phân tích 1 cổ phiếu theo phương pháp Minervini SEPA, user phải:
1. Mở TradingView, set symbol, đọc chart bằng mắt
2. Tra cứu thủ công các chunks trong `docs/knowledge/trading_wizard/`
3. Tự tổng hợp đánh giá

Mục tiêu: tạo 1 skill gọn `/minervini-assess <SYMBOL>` trong Claude Code để tự động hóa luồng này — **chạy hoàn toàn local trong Claude Code session, không qua server FastAPI, không tốn API credit** (dùng subscription quota). Hai MCP cần thiết đã được wire sẵn (theo memory `claude_desktop_mcp.md`):
- `tradingview` MCP → đọc chart/OHLCV/indicators
- `minervini-rag` MCP → query KB ChromaDB

## Phạm vi
Chỉ thêm **1 file skill mới**. Không sửa code server, không đụng config, không tạo plan doc khác.

## File sẽ tạo
`.claude/skills/minervini-assess/SKILL.md`

## Nội dung skill (cấu trúc)

```markdown
---
name: minervini-assess
description: Đánh giá nhanh 1 cổ phiếu theo Minervini SEPA (Trend Template + VCP + Stage). Trigger khi user gõ /minervini-assess <SYMBOL> hoặc yêu cầu "phân tích <ticker> theo Minervini / SEPA / Trend Template / VCP".
---

# /minervini-assess <SYMBOL>

## Bước 1 — Đọc chart qua TradingView MCP
- `mcp__tradingview__chart_set_symbol` → SYMBOL
- `mcp__tradingview__chart_set_timeframe` → "1D"
- `mcp__tradingview__data_get_ohlcv` → 250 bars (đủ cho MA200)
- `mcp__tradingview__quote_get` → giá hiện tại + 52w high/low
- (optional) `mcp__tradingview__data_get_indicator` cho MA50/MA150/MA200, RS Rating nếu có

## Bước 2 — Tra Minervini KB
- `mcp__minervini-rag__query_minervini_kb` với các query:
  - "Trend Template 8 criteria"
  - "VCP volatility contraction pattern stages"
  - "Stage 2 uptrend characteristics"
- Nếu cần chi tiết: `mcp__minervini-rag__read_chunk` chunks 002/003/004

## Bước 3 — Đánh giá Trend Template (8 tiêu chí)
Tính từ OHLCV + MA:
1. Price > MA150 & MA200
2. MA150 > MA200
3. MA200 trending up ≥1 tháng
4. MA50 > MA150 > MA200
5. Price > MA50
6. Price ≥ 30% trên 52w low
7. Price ≤ 25% dưới 52w high
8. RS Rating ≥ 70 (nếu lấy được)

Output: PASS/FAIL từng tiêu chí + score X/8.

## Bước 4 — Stage analysis & VCP
- Xác định stage (1/2/3/4) dựa MA slope + price action
- Quét VCP: số đợt contraction, % giảm mỗi đợt, volume dry-up

## Bước 5 — Kết luận
- Verdict: BUY-WATCH / HOLD / AVOID
- Pivot point đề xuất (nếu có VCP hoàn thành)
- Stop loss gợi ý (-7% hoặc dưới base)
- Trích dẫn chunk KB làm căn cứ

## Ràng buộc
- KHÔNG thực hiện lệnh giao dịch
- KHÔNG ghi log vào EAIS global (per CLAUDE.md isolation rule)
- Nếu TV Desktop chưa mở port 9222 → nhắc user chạy `/tv-start` trước
```

## Files đã verify tồn tại (reuse, không tạo mới)
- KB chunks: `docs/knowledge/trading_wizard/chunks/chunk_001..036.md`
- Reports: `docs/knowledge/trading_wizard/reports/*.md` (SEPA Blueprint, Trend Template, Risk)
- MCP `minervini-rag` (tools `query_minervini_kb`, `read_chunk`, `list_kb_chapters`) — đã có trong deferred tool list
- MCP `tradingview` (chart_*, data_*, quote_get) — đã có

## Verification
1. Trong Claude Code session: gõ `/minervini-assess NVDA`
2. Kỳ vọng: skill được trigger, gọi tuần tự TV MCP → minervini-rag MCP → in báo cáo Trend Template 8 mục + verdict
3. Edge case: SYMBOL không hợp lệ → skill phải báo lỗi từ `chart_set_symbol` chứ không crash
4. Nếu TV Desktop không chạy: skill phải nhắc `/tv-start`

## Out of scope (sẽ làm sau, plan riêng)
- (b)(c) Switch provider `claude_cli` trong `server/rag.py` — plan riêng
- Server-side webhook test với `AI_PROVIDER=claude_cli`
- Plan doc `docs/plans/claude_cli_integration.md`
