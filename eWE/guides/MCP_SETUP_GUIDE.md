# TradingView MCP Setup Guide

> Huong dan ket noi Claude AI voi TradingView Desktop de doc chart thuc,
> doc indicator values, va tu dong hoa Pine Script workflow.

## Kien truc

```
TradingView Desktop (Chrome DevTools Protocol, port 9222)
        |
        v
tradingview-mcp (Node.js MCP Server)
        |
        v
Claude Code / Antigravity (MCP Client)
```

## Prerequisites

1. **TradingView Desktop** — https://www.tradingview.com/desktop/
   - Can **Essential** subscription tro len de co real-time data
2. **Node.js** >= 18 — https://nodejs.org/
3. **Claude Code** hoac Antigravity voi MCP support

## Setup

### Buoc 1: Install dependencies

```bash
cd tradingview-mcp
npm install
```

### Buoc 2: Launch TradingView voi Debug Port

**PowerShell:**
```powershell
.\scripts\launch_tv_windows.ps1
```

**CMD:**
```cmd
scripts\launch_tv_windows.bat
```

**Manual:**
```
"C:\Users\{username}\AppData\Local\TradingView\TradingView.exe" --remote-debugging-port=9222
```

### Buoc 3: Verify CDP connection

```bash
curl http://localhost:9222/json
```

Neu tra ve JSON voi thong tin tab TradingView -> thanh cong.

### Buoc 4: MCP Config

File `.mcp.json` da duoc tao san o root project:

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

Restart Claude Code de load MCP server.

### Buoc 5: Test trong Claude

Yeu cau Claude:
- "Use tv_health_check to verify TradingView connection"
- "Read the current chart data"
- "Take a screenshot of the chart"
- "What symbol and timeframe is currently displayed?"

## Key MCP Tools

| Tool | Chuc nang |
|------|-----------|
| `tv_health_check` | Kiem tra ket noi |
| `tv_launch` | Auto-launch TradingView |
| `quote_get` | Lay gia OHLCV hien tai |
| `data_get_study_values` | Doc indicator values (RSI, MACD, MA...) |
| `chart_set_symbol` | Doi symbol tren chart |
| `chart_set_timeframe` | Doi timeframe |
| `pine_set_source` | Inject Pine Script code |
| `pine_compile` | Compile Pine Script |
| `alert_create` | Tao alert |
| `screenshot` | Chup anh chart |

## Use Cases voi Minervini SEPA

### 1. Kiem tra Trend Template tren chart thuc

```
"Doc cac gia tri SMA 50, SMA 150, SMA 200 tren chart hien tai
va kiem tra xem co dat 8 tieu chi Minervini Trend Template khong."
```

### 2. Scan VCP Pattern

```
"Analyze volume pattern va price contraction trong 20 ngay gan nhat.
Co dau hieu VCP (Volatility Contraction Pattern) khong?"
```

### 3. Auto-inject Strategy

```
"Them strategy Minervini SEPA v2 vao chart va chay backtest."
```

### 4. Screenshot + Analysis

```
"Chup screenshot chart hien tai va phan tich xem co nen vao lenh khong
dua tren cac tieu chi Minervini."
```

## Troubleshooting

| Van de | Giai phap |
|--------|-----------|
| CDP port khong mo | Dam bao TradingView launch voi `--remote-debugging-port=9222` |
| MCP tool timeout | Restart TradingView va doi 10s truoc khi dung tool |
| Indicator values rong | Can mo chart va add indicator truoc khi doc |
| Permission denied | Chay Claude Code voi quyen admin |
