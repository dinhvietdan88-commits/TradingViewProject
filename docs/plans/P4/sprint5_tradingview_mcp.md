# Sprint 5: TradingView MCP Integration — Claude Doc Chart Thuc

## Muc tieu

Kich hoat cau noi giua **Claude AI** va **TradingView Desktop** thong qua
`tradesdontlie/tradingview-mcp` — cho phep Claude doc chart thuc, doc indicator
values, va tu dong hoa Pine Script workflow.

## Hien trang

- `tradingview-mcp/` da co trong project nhu orphaned git submodule (commit
  `4795784`) nhung chua duoc cai dat (thu muc rong, khong co `.gitmodules`)
- ONBOARDING.md da mo ta workflow can thiet
- TradingView Desktop chua duoc launch voi debug port

---

## Kien truc tich hop

```
TradingView Desktop (port 9222 CDP)
        |
        v
tradingview-mcp (Node.js MCP Server)
        |
        v
Claude Code / Antigravity (MCP Client)
        |
        v
FastAPI Webhook Server (Python — port 5000)
```

**tradingview-mcp** cho phep Claude:
- Doc chart data (OHLCV, indicator values, drawn objects)
- Chup screenshot de visual analysis
- Thay doi symbol, timeframe
- Inject va compile Pine Script
- Tao/quan ly alerts

---

## Ke hoach thuc thi

### Buoc 1: Fix submodule — clone dung cach

Submodule hien tai bi "orphaned" (co commit ref nhung khong co `.gitmodules`).
Can xu ly sach:

```bash
# Xoa reference cu
git rm --cached tradingview-mcp
# Clone lai dung cach
git submodule add https://github.com/tradesdontlie/tradingview-mcp.git tradingview-mcp
git submodule update --init --recursive
```

### Buoc 2: Cai dat dependencies

```bash
cd tradingview-mcp
npm install
```

### Buoc 3: Tao `.mcp.json` config cho project

File `.mcp.json` o root project de Claude Code tu dong load MCP server:

```json
{
  "mcpServers": {
    "tradingview": {
      "command": "node",
      "args": ["tradingview-mcp/src/server.js"]
    }
  }
}
```

### Buoc 4: Tao script launch TradingView Debug Mode

**Windows:** `scripts/launch_tv_windows.bat`

```bat
@echo off
REM Launch TradingView Desktop with Chrome DevTools Protocol
start "" "%LOCALAPPDATA%\TradingView\TradingView.exe" --remote-debugging-port=9222
echo TradingView launched on debug port 9222
echo Waiting for startup...
timeout /t 5
echo Ready for MCP connection.
```

**PowerShell:** `scripts/launch_tv_windows.ps1`

```powershell
# Launch TradingView with CDP enabled
$tvPath = "$env:LOCALAPPDATA\TradingView\TradingView.exe"
if (Test-Path $tvPath) {
    Start-Process $tvPath -ArgumentList "--remote-debugging-port=9222"
    Write-Host "TradingView launched on debug port 9222"
    Start-Sleep -Seconds 5
    # Health check
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:9222/json" -UseBasicParsing
        Write-Host "CDP connection verified: $($response.StatusCode)"
    } catch {
        Write-Host "Warning: CDP port not ready yet. Try again in a few seconds."
    }
} else {
    Write-Host "ERROR: TradingView Desktop not found at $tvPath"
    Write-Host "Install from: https://www.tradingview.com/desktop/"
}
```

### Buoc 5: Cap nhat documentation

- Cap nhat `README.md` roadmap: Sprint 5 done
- Tao `docs/guides/MCP_SETUP_GUIDE.md` voi huong dan tung buoc

### Buoc 6: Tao server/mcp_bridge.py (Optional API endpoint)

Expose MCP capabilities qua REST API de webhook server co the trigger
chart analysis tu dong khi nhan tin hieu:

```python
# GET /mcp/status   — Kiem tra MCP connection
# GET /mcp/chart    — Lay thong tin chart hien tai
# POST /mcp/analyze — Trigger AI chart analysis
```

---

## Files se tao/sua

| File | Hanh dong |
|------|-----------|
| `tradingview-mcp/` | Fix submodule, npm install |
| `.gitmodules` | [NEW] Git submodule config |
| `.mcp.json` | [NEW] MCP server config cho Claude Code |
| `scripts/launch_tv_windows.ps1` | [NEW] Launch script Windows |
| `scripts/launch_tv_windows.bat` | [NEW] Launch script bat |
| `docs/guides/MCP_SETUP_GUIDE.md` | [NEW] Setup guide day du |
| `README.md` | [MODIFY] Cap nhat roadmap |

---

## Verification

1. Launch TradingView: `scripts/launch_tv_windows.ps1`
2. Verify CDP: `curl http://localhost:9222/json`
3. Trong Claude Code: su dung tool `tv_health_check`
4. Test: yeu cau Claude doc chart data hien tai
