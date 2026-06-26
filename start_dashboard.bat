@echo off
:: Forward Test Dashboard Launcher
:: Starts API server (port 5000) + Dashboard HTTP server (port 8080)
echo ================================================================
echo  Forward Test Dashboard Launcher
echo  API: http://localhost:5000  ^|  Dashboard: http://localhost:8080
echo ================================================================

:: Set working directory to project root
cd /d "%~dp0"

:: Kill existing processes on ports 5000 and 8080
echo Cleaning up existing processes...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":5000 "') do (
    taskkill /PID %%a /F 2>nul
)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":8080 "') do (
    taskkill /PID %%a /F 2>nul
)
timeout /t 1 /nobreak >nul

:: Start API server (TradingView Webhook v7.6 with CORS + auth fixes)
echo Starting API server on port 5000...
start "TradingView API" /MIN python nerves\workers\trading\main.py

:: Wait for API startup
echo Waiting for server startup (10s)...
timeout /t 10 /nobreak >nul

:: Start dashboard HTTP server
echo Starting dashboard HTTP server on port 8080...
start "Dashboard HTTP" /MIN python -m http.server 8080 --directory reports

timeout /t 2 /nobreak >nul

:: Open dashboard in browser
echo Opening dashboard in browser...
start "" "http://localhost:8080/dashboard_live.html"

echo.
echo ================================================================
echo  Dashboard: http://localhost:8080/dashboard_live.html
echo  API:       http://localhost:5000/tv_health_check
echo  To stop:   Close the "TradingView API" and "Dashboard HTTP" windows
echo ================================================================
