# Sprint 6.1 — MCP Foundation
**Branch:** `feat/p6-mcp-morning-brief`  
**Commit:** `cf76141`  
**Status:** ✅ Done

---

## Mục tiêu

Tạo Python wrapper gọi TradingView MCP CLI qua subprocess, cho phép server
đọc dữ liệu chart và chụp screenshot mà không cần biết MCP internals.

---

## Kiến trúc

```
FastAPI Server (Python)
    ↓ subprocess
mcp_client.py → node tradingview-mcp/src/cli/index.js <command> --json
    ↓ Chrome DevTools Protocol
TradingView Desktop (port 9222)
```

---

## Files

### [NEW] `server/mcp_client.py`

**MCPClient class** — async wrapper:

| Method | Mô tả | MCP CLI Command |
|--------|--------|----------------|
| `health_check()` | Check CDP connection | `tv status` |
| `get_quote(symbol)` | Price + OHLCV | `tv symbol <sym>` + `tv quote` |
| `get_ohlcv_summary(sym, tf)` | Compact stats (500B) | `tv ohlcv --summary` |
| `get_study_values(sym, tf)` | MA50/150/200, Volume, ATR | `tv values` |
| `capture_screenshot(sym, tf)` | Chart screenshot → PNG file | `tv screenshot -r chart` |
| `set_symbol(sym, tf)` | Switch chart | `tv symbol` + `tv timeframe` |
| `batch_run(symbols)` | Scan multi-symbol sequentially | Loop of above |

**Data classes:**
- `QuoteData` — symbol, close, open, high, low, volume, change_pct
- `StudyValues` — sma50, sma150, sma200, volume_avg20, atr14, rs_line, high/low_52w

**Singleton:** `get_mcp_client()` returns global instance.

### [MODIFY] `server/config.py`

Thêm:
```python
MCP_ENABLED = os.getenv("MCP_ENABLED", "false")     # Bật/tắt MCP
MCP_CDP_PORT = int(os.getenv("MCP_CDP_PORT", 9222))  # CDP port
MCP_NODE_PATH = os.getenv("MCP_NODE_PATH", "node")   # Node.js path
```

### [MODIFY] `server/.env.example`

Thêm section `MCP / Morning Brief (P6)`.

### [MODIFY] `server/main.py`

- Import `mcp_client as _mcp_module`
- Lifespan: `mcp.health_check()` khi startup (warning nếu không connected)
- `GET /api/mcp/status` → `{"enabled": true, "connected": true/false, "cdp_port": 9222}`

---

## Verification

```bash
# TradingView Desktop phải đang chạy với CDP
curl http://localhost:5000/api/mcp/status
# → {"enabled": true, "connected": true, "cdp_port": 9222, ...}
```
