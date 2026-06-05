# setup_server_c.ps1 — Server C (AI Core) Setup Script
# Automates the setup of ChromaDB and Analyzer Worker via Docker Compose.

$ErrorActionPreference = "Stop"

Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host "       SERVER C (AI CORE) DEPLOYMENT SCRIPT V1.0             " -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan

# --- Step 1: Check Prerequisites ---
Write-Host "`n[Step 1/3] Kiểm tra môi trường (Docker)..." -ForegroundColor Yellow

try {
    $dockerVersion = & docker --version
    Write-Host "[+] Tìm thấy Docker: $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host "[-] Lỗi: Docker chưa được cài đặt hoặc chưa chạy." -ForegroundColor Red
    Write-Host "Vui lòng cài đặt Docker Desktop và khởi động trước khi chạy script này." -ForegroundColor Red
    Exit 1
}

# --- Step 2: Environment Configuration ---
Write-Host "`n[Step 2/3] Cấu hình biến môi trường cho Server C..." -ForegroundColor Yellow

$envFilePath = Join-Path -Path $PSScriptRoot -ChildPath "deploy\.env"
$envDict = @{}

if (Test-Path $envFilePath) {
    Write-Host "[*] Tìm thấy file cấu hình cũ tại $envFilePath. Đang nạp cấu hình..." -ForegroundColor Gray
    foreach ($line in Get-Content $envFilePath) {
        if ($line -match "^([^#=]+)=(.*)$") {
            $envDict[$matches[1].Trim()] = $matches[2].Trim()
        }
    }
} else {
    Write-Host "[+] Tạo mới file cấu hình $envFilePath." -ForegroundColor Green
}

function Prompt-Var ($VarName, $PromptText, $DefaultValue) {
    $currentVal = $envDict[$VarName]
    if (-not [string]::IsNullOrEmpty($currentVal)) {
        $DefaultValue = $currentVal
    }

    $inputVal = Read-Host "$PromptText (Mặc định: $DefaultValue)"
    if ([string]::IsNullOrEmpty($inputVal)) {
        $inputVal = $DefaultValue
    }
    $envDict[$VarName] = $inputVal
}

Write-Host "Vui lòng nhập các thông số cấu hình mạng Tailscale và Secret:" -ForegroundColor White
Prompt-Var "SERVER_A_IP" "IP của SERVER A (Gateway) trên Tailscale" "100.x.x.1"
Prompt-Var "VPS_BUFFER_SECRET" "Buffer Secret của SERVER A" "your_buffer_secret"
Prompt-Var "SERVER_B_IP" "IP của SERVER B (Execution Vault) trên Tailscale" "100.x.x.2"
Prompt-Var "SERVER_B_SECRET" "Secret để gọi api execute của SERVER B" "your_server_b_secret"
Prompt-Var "LOCAL_EXECUTE_URL" "Local Execute URL (Dự phòng)" "http://localhost:5000"
Prompt-Var "LOCAL_EXECUTE_SECRET" "Local Execute Secret" "your_local_secret"
Prompt-Var "ANTHROPIC_API_KEY" "Anthropic API Key" "sk-ant-..."
Prompt-Var "GEMINI_API_KEY" "Gemini API Key" "AIza..."
Prompt-Var "AI_PROVIDER" "AI Provider (anthropic / gemini)" "anthropic"
Prompt-Var "RISK_PER_TRADE" "Risk Per Trade (Tỷ lệ phần trăm)" "0.02"
Prompt-Var "STOP_LOSS_PCT" "Stop Loss Percentage" "0.08"

# Write to deploy\.env
$envContent = ""
foreach ($key in $envDict.Keys) {
    $val = $envDict[$key]
    $envContent += "$key=$val`n"
}
[System.IO.File]::WriteAllText($envFilePath, $envContent, [System.Text.Encoding]::UTF8)
Write-Host "[+] Đã lưu cấu hình tại $envFilePath" -ForegroundColor Green

# --- Step 3: Run Docker Compose ---
Write-Host "`n[Step 3/3] Khởi chạy Server C (ChromaDB + Analyzer Worker)..." -ForegroundColor Yellow

$composeFile = Join-Path -Path $PSScriptRoot -ChildPath "deploy\docker-compose.server-c.yml"

# Ensure tailscale network exists to avoid Docker errors if using external network
try {
    $networkCheck = & docker network inspect tailscale 2>&1
    if ($LASTEXITCODE -ne 0 -and $networkCheck -match "No such network") {
        Write-Host "[!] Không tìm thấy Docker network 'tailscale', tiến hành tạo network mô phỏng..." -ForegroundColor Cyan
        & docker network create tailscale | Out-Null
    }
} catch {
    # Ignore errors here, let docker-compose handle it
}

try {
    Set-Location -Path (Join-Path -Path $PSScriptRoot -ChildPath "deploy")
    & docker compose -f docker-compose.server-c.yml up -d
    Write-Host "[+] Server C đang chạy ngầm (detached mode)!" -ForegroundColor Green
    Write-Host "Sử dụng lệnh sau để xem log:" -ForegroundColor White
    Write-Host "cd deploy && docker compose -f docker-compose.server-c.yml logs -f" -ForegroundColor Cyan
} catch {
    Write-Host "[-] Lỗi khi khởi chạy Docker Compose: $_" -ForegroundColor Red
    Exit 1
}

Write-Host "`n=============================================================" -ForegroundColor Green
Write-Host "          SERVER C (AI CORE) ĐÃ ĐƯỢC SETUP HOÀN TẤT!           " -ForegroundColor Green
Write-Host "=============================================================" -ForegroundColor Green
