# FX Tactix Claude — Phương án bổ sung

> Phương án **AI-assisted no-code** triển khai song song với hệ thống autonomous v6.0.
> Đối tượng: trader phổ thông muốn nhanh chóng prototype strategy bằng prompt thay vì code thủ công.
>
> Xem so sánh chi tiết: [fx_tactix_vs_our_project.md](../doithu/fx_tactix_vs_our_project.md)

## Kiến trúc

```
┌─────────────────────────────────────────────────────────────┐
│  3 lớp truy cập FX Tactix Claude                            │
├─────────────────────────────────────────────────────────────┤
│  Lớp 1 — Skill        : /fx-tactix trong Claude Code        │
│  Lớp 2 — Prompt docs  : prompts/*.md (copy vào Claude UI)   │
│  Lớp 3 — API endpoint : POST /api/fx-tactix/generate        │
└─────────────────────────────────────────────────────────────┘
         ↓                ↓                   ↓
   Claude Code      Claude Desktop      Webhook / curl
   (free, OAuth)    (manual paste)      (programmatic)
```

Tất cả 3 lớp đều output Pine Script v5 vào `pine/v2/generated/` để Strategy Tester của TradingView nuốt được.

## Quick start

### 1. Skill (khuyến nghị — chạy trong Claude Code)

```
/fx-tactix Tạo strategy mua khi giá vượt EMA50 với volume > 2x trung bình 20 phiên, SL 8%, TP 20%
```

Skill sẽ:
1. Đọc context Minervini KB nếu liên quan
2. Sinh Pine v5 code
3. Ghi ra `pine/v2/generated/<slug>_<timestamp>.pine`
4. (Tùy chọn) Mở file trong TradingView qua MCP `pine_set_source` → `pine_smart_compile`

### 2. Prompt template (manual — Claude Desktop)

Mở [prompts/level_2_strategy.md](prompts/level_2_strategy.md), điền `{{description}}`, paste vào Claude Desktop.

### 3. API endpoint

```bash
curl -X POST http://localhost:5000/api/fx-tactix/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $WEBHOOK_SECRET" \
  -d '{
    "description": "Mua khi RSI(14) cắt lên 30, SL dưới swing low gần nhất",
    "style": "strategy",
    "save": true
  }'
```

Response:
```json
{
  "status": "ok",
  "pine_code": "//@version=5\nstrategy(...) ...",
  "file_path": "pine/v2/generated/rsi_oversold_20260520_141233.pine",
  "tokens_used": 1284,
  "provider": "claude_cli"
}
```

## 5 Levels FX Tactix

| Level | Tên | File prompt | Endpoint param |
|-------|-----|-------------|----------------|
| 1 | Morning Brief | [level_1_morning.md](prompts/level_1_morning.md) | `style=brief` |
| 2 | Custom Strategy / Indicator | [level_2_strategy.md](prompts/level_2_strategy.md) | `style=strategy` |
| 3 | Backtest review | [level_3_backtest.md](prompts/level_3_backtest.md) | `style=backtest_review` |
| 4 | Multi-timeframe | [level_4_mtf.md](prompts/level_4_mtf.md) | `style=mtf` |
| 5 | Alert + bot wiring | [level_5_alert.md](prompts/level_5_alert.md) | `style=alert` |

## Provider routing

Endpoint tự động chọn provider theo `config.AI_PROVIDER`:

- `claude_cli` (mặc định, **free** qua subscription) — gọi qua `claude_cli/sdk_client.py`
- `anthropic` — Anthropic API key
- `gemini` — Google GenAI

## Tích hợp với hệ thống hiện có

- **Không** thay thế Minervini-based pipeline. Chạy song song.
- Output đi vào `pine/v2/generated/` (gitignored mặc định) — user review trước khi commit.
- Skill log mỗi lần generate vào `trades.db` bảng `fx_tactix_runs` (tạo lazy nếu chưa tồn tại).
- KHÔNG tự động backtest — quyền quyết định backtest thuộc về user.

## Khi nào dùng FX Tactix vs Minervini-engine?

| Tình huống | Khuyến nghị |
|------------|-------------|
| Prototype ý tưởng mới trong 5 phút | FX Tactix |
| Strategy production-grade, dài hạn | Minervini engine (đã có) |
| Trader không biết Pine | FX Tactix |
| Cần backtest có log + dashboard | Minervini engine |
| Cần điểm Trend Template / VCP score | Minervini engine |

## Files

- `prompts/` — 5 prompt templates Vietnamese
- `examples/` — ví dụ Pine Script đã generate
- `../../server/fx_tactix.py` — module FastAPI
- `../../.claude/skills/fx-tactix/SKILL.md` — Claude Code skill
