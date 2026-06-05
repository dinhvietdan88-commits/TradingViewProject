param (
    [string]$Url = "http://localhost:5000/webhook",
    [string]$Action = "buy",
    [string]$Symbol = "BTCUSDT",
    [string]$Price = "65000.00",
    [string]$Interval = "60",
    [string]$Indicator = "",
    [string]$Strategy = "",
    [string]$Message = ""
)

# Đọc Secret từ file .env (nếu có), hoặc dùng mặc định
$EnvPath = Join-Path -Path $PSScriptRoot -ChildPath ".env"
$Secret = "change_me_in_dotenv"

if (Test-Path $EnvPath) {
    $EnvContent = Get-Content $EnvPath
    foreach ($Line in $EnvContent) {
        if ($Line -match "^WEBHOOK_SECRET=(.*)") {
            $Secret = $Matches[1].Trim()
            break
        }
    }
}

# Tạo thời gian hiện tại định dạng ISO 8601 (UTC)
$CurrentTime = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

# Xây dựng JSON Payload
$Payload = @{
    secret   = $Secret
    action   = $Action
    symbol   = $Symbol
    price    = $Price
    quoteQty = 50
    interval = $Interval
    time     = $CurrentTime
}

if ($Indicator) {
    $Payload["indicator"] = $Indicator
}
if ($Strategy) {
    $Payload["strategy"] = $Strategy
}
if ($Message) {
    $Payload["message"] = $Message
}

$Payload = $Payload | ConvertTo-Json

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "Gửi tín hiệu Webhook giả lập TradingView..." -ForegroundColor Cyan
Write-Host "URL: $Url" -ForegroundColor Yellow
Write-Host "Action: $Action | Symbol: $Symbol | Price: $Price" -ForegroundColor Yellow
Write-Host "Payload:" -ForegroundColor DarkGray
Write-Host $Payload -ForegroundColor DarkGray
Write-Host "==============================================" -ForegroundColor Cyan

# Gửi HTTP POST Request
try {
    $Response = Invoke-RestMethod -Uri $Url -Method Post -Body $Payload -ContentType "application/json"
    Write-Host "`n[+] KẾT QUẢ TỪ SERVER (200 OK):" -ForegroundColor Green
    $Response | ConvertTo-Json -Depth 3 | Write-Host -ForegroundColor Green
} catch {
    Write-Host "`n[-] LỖI KHI GỬI WEBHOOK:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red

    if ($_.ErrorDetails.Message) {
        Write-Host "Chi tiết:" -ForegroundColor Red
        Write-Host $_.ErrorDetails.Message -ForegroundColor Red
    }
}
