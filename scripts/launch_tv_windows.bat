@echo off
REM Launch TradingView Desktop with Chrome DevTools Protocol
REM Required for tradingview-mcp bridge

set TV_PATH=%LOCALAPPDATA%\TradingView\TradingView.exe

if not exist "%TV_PATH%" (
    echo ERROR: TradingView Desktop not found at %TV_PATH%
    echo Install from: https://www.tradingview.com/desktop/
    exit /b 1
)

echo Launching TradingView with CDP on port 9222...
start "" "%TV_PATH%" --remote-debugging-port=9222
echo.
echo Waiting for startup...
timeout /t 5 /nobreak > nul
echo.
echo TradingView should now be running with debug port 9222.
echo Verify: curl http://localhost:9222/json
echo.
echo MCP bridge ready for Claude connection.
