<#
.SYNOPSIS
    Launch TradingView Desktop with Chrome DevTools Protocol (CDP) enabled.
.DESCRIPTION
    Required for tradingview-mcp bridge to connect Claude AI to TradingView.
    After launch, verify with: curl http://localhost:9222/json
#>

$tvPaths = @(
    "$env:LOCALAPPDATA\TradingView\TradingView.exe",
    "${env:ProgramFiles}\TradingView\TradingView.exe",
    "${env:ProgramFiles(x86)}\TradingView\TradingView.exe"
)

$tvPath = $tvPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $tvPath) {
    # Check MSIX package
    $pkg = Get-AppxPackage -Name "*TradingView*" -ErrorAction SilentlyContinue
    if ($pkg) {
        $tvPath = "$($pkg.InstallLocation)\TradingView.exe"
    }
}

if (-not $tvPath) {
    Write-Host "ERROR: TradingView Desktop not found." -ForegroundColor Red
    Write-Host "Install from: https://www.tradingview.com/desktop/"
    exit 1
}

Write-Host "Launching TradingView from: $tvPath" -ForegroundColor Cyan
Start-Process $tvPath -ArgumentList "--remote-debugging-port=9222"

Write-Host "Waiting for startup..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

try {
    $response = Invoke-WebRequest -Uri "http://localhost:9222/json" -UseBasicParsing -TimeoutSec 5
    Write-Host "CDP connection verified! Status: $($response.StatusCode)" -ForegroundColor Green
    Write-Host "TradingView MCP bridge is ready." -ForegroundColor Green
} catch {
    Write-Host "Warning: CDP port 9222 not ready yet." -ForegroundColor Yellow
    Write-Host "TradingView may still be loading. Try again in 10 seconds."
}
