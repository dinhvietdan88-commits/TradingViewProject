# Sprint 7.5 — AI Vision (Claude Chart Analysis)
**Branch:** `feat/p7b-ai-vision-ux`  
**Commit:** `b87e2f7`  
**Status:** ✅ Done

---

## Mục tiêu

Cho Claude **nhìn** chart screenshot và nhận diện pattern trực quan — kết hợp với
TT scoring algorithmics để cho ra **combined intelligence score**.

**Đây là gap cuối cùng với FX Tactix được close.**

---

## Kiến trúc AI Vision

```
                    ┌────────────────────┐
                    │  TradingView MCP   │
                    │  (CDP screenshot)  │
                    └────────┬───────────┘
                             │ PNG image
                    ┌────────▼───────────┐
                    │  vision.py         │
                    │  ├── base64 encode │
                    │  ├── Claude Vision │
                    │  ├── Pattern parse │
                    │  └── Combined score│
                    └────────┬───────────┘
                             │ Analysis dict
                    ┌────────▼───────────┐
                    │  Outputs:          │
                    │  ├── brief.py      │ ← Morning Brief pipeline
                    │  ├── telegram_bot  │ ← /vision command
                    │  └── /api/vision   │ ← REST endpoint
                    └────────────────────┘
```

---

## Scoring System

### Combined Score Formula

```
Combined = (Algorithmic × 0.6) + (Visual × 0.4)

Algorithmic = (TT Score / 8) × 10     # Trend Template normalized
Visual      = Claude Vision confidence  # 1-10 from response
```

### Verdict Mapping

| Combined Score | Verdict |
|---------------|---------|
| ≥ 8.0 + VCP | 🟢 STRONG BUY SETUP |
| ≥ 6.0 | 🟡 WATCHLIST — Monitor for breakout |
| ≥ 4.0 | 🟠 NEUTRAL — Base building |
| < 4.0 | 🔴 AVOID — Weak setup |

---

## Files

### [NEW] `server/vision.py`

**Core functions:**

| Function | Purpose |
|----------|---------|
| `analyze_chart_vision()` | Main async — encode image + call Claude Vision + parse results |
| `_encode_image()` | Base64 encode PNG/JPG for API |
| `_get_media_type()` | Detect image MIME type |
| `_build_algo_context()` | Format scan result as context string |
| `_parse_confidence()` | Extract confidence score 1-10 from Claude response |
| `_parse_patterns()` | Extract detected pattern names |
| `format_vision_telegram()` | Format result for Telegram display |

**Supported patterns (20 types):**
VCP, Cup-with-Handle, Ascending Base, Flat Base, High Tight Flag, Double Bottom,
Triple Bottom, Bull Flag, Pennant, Breakout, Pivot, Accumulation, Stage 2, Stage 1

### [MODIFY] `server/brief.py`

- Import `vision` module
- Step 4b: AI Vision analysis after screenshot capture
- Step 6b: Append vision text to brief output
- Cache includes `vision` result

### [MODIFY] `server/main.py`

- Import `vision as vision_module`
- New endpoint: `POST /api/vision/analyze?symbol=BTCUSDT&image_path=...`
- Version bumped to `7.0`

### [MODIFY] `server/telegram_bot.py`

- New command: `/vision SYMBOL` — AI chart analysis
- 9 commands total (was 8)
- Version strings updated to v7.0
- Smart fallback: MCP capture → existing screenshot search

---

## Usage

### Telegram Bot
```
/vision BTCUSDT
```

### REST API
```bash
curl -X POST "http://localhost:5000/api/vision/analyze?symbol=BTCUSDT&image_path=screenshots/chart.png"
```

### Morning Brief (automatic)
Vision analysis runs automatically when screenshot is captured during 07:00 ICT brief.

---

## Output mẫu

### `/vision BTCUSDT` response:
```
👁️ VISUAL ANALYSIS — BTCUSDT

📊 Pattern: VCP hình thành rõ ràng — 3 contractions với volume
giảm dần. Đáy nâng: $65,200 → $66,800 → $67,500.

📈 Trend: Stage 2 uptrend — MAs xếp đúng thứ tự (50 > 150 > 200).
Price đang squeeze gần pivot.

📉 Volume: Dry-up rõ — 35% avg volume trong base cuối.
Chờ volume breakout 150%+ avg.

🎯 Key Levels:
• Pivot breakout: $69,200
• Support: $67,500
• Resistance: $69,500

✅ Visual Confidence: 8/10
Lý do: VCP textbook setup, volume confirms accumulation

📊 Combined Score: 8.3/10
📋 Verdict: 🟢 STRONG BUY SETUP
🔍 Patterns: VCP, Breakout, Accumulation, Stage 2
```
