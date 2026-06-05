# setup_tunnel.ps1 — Cloudflare Named Tunnel Auto-Setup Script
# Bypasses complex setup and automates configuration for mj-trading-tunnel.

$ErrorActionPreference = "Stop"

# --- Configuration Constants ---
$DefaultTunnelName = "mj-trading-tunnel"
$CloudflaredDir = "C:\Users\pesil\.cloudflared"
$DownloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
$LocalBinName = "cloudflared.exe"
$ConfigPath = Join-Path -Path $CloudflaredDir -ChildPath "config.yml"

Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host "     CLOUDFLARE PERMANENT TUNNEL SETUP (mj_trading) V2.0     " -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan

# --- Step 1: Directory Creation ---
Write-Host "`n[Step 1/5] Khởi tạo thư mục làm việc..." -ForegroundColor Yellow
if (-not (Test-Path $CloudflaredDir)) {
    New-Item -ItemType Directory -Path $CloudflaredDir | Out-Null
    Write-Host "[+] Đã tạo thư mục: $CloudflaredDir" -ForegroundColor Green
} else {
    Write-Host "[*] Thư mục $CloudflaredDir đã tồn tại." -ForegroundColor Gray
}

# --- Check & Locate/Download cloudflared.exe ---
$CloudflaredPath = ""
# Check System Path
$SysCmd = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($SysCmd) {
    $CloudflaredPath = $SysCmd.Source
    Write-Host "[+] Tìm thấy cloudflared trong System PATH: $CloudflaredPath" -ForegroundColor Green
} else {
    # Check local Program Files winget path
    $WingetPath = "C:\Program Files\Cloudflare\cloudflared\cloudflared.exe"
    if (Test-Path $WingetPath) {
        $CloudflaredPath = $WingetPath
        Write-Host "[+] Tìm thấy cloudflared tại Program Files: $CloudflaredPath" -ForegroundColor Green
    } else {
        # Check local working dir
        $LocalPath = Join-Path -Path $CloudflaredDir -ChildPath $LocalBinName
        if (Test-Path $LocalPath) {
            $CloudflaredPath = $LocalPath
            Write-Host "[+] Tìm thấy cloudflared cục bộ: $CloudflaredPath" -ForegroundColor Green
        } else {
            # Download from GitHub
            Write-Host "[!] Không tìm thấy cloudflared.exe. Tiến hành tải từ Cloudflare..." -ForegroundColor Cyan
            try {
                Invoke-WebRequest -Uri $DownloadUrl -OutFile $LocalPath -UseBasicParsing
                $CloudflaredPath = $LocalPath
                Write-Host "[+] Tải cloudflared.exe thành công và lưu tại: $CloudflaredPath" -ForegroundColor Green
            } catch {
                Write-Host "[-] Lỗi khi tải cloudflared.exe: $_" -ForegroundColor Red
                Exit 1
            }
        }
    }
}

# --- Step 2: Interactive OAuth Login ---
Write-Host "`n[Step 2/5] Đăng nhập Cloudflare Zero Trust (OAuth)..." -ForegroundColor Yellow
Write-Host "Trình duyệt của bạn sẽ tự động mở để xác thực tài khoản Cloudflare." -ForegroundColor Gray
try {
    Start-Process -FilePath $CloudflaredPath -ArgumentList "tunnel login" -Wait -NoNewWindow
    Write-Host "[+] Xác thực OAuth thành công!" -ForegroundColor Green
} catch {
    Write-Host "[-] Đăng nhập thất bại: $_" -ForegroundColor Red
    Exit 1
}

# --- Step 3: Tunnel Creation ---
Write-Host "`n[Step 3/5] Tạo Tunnel cố định: $DefaultTunnelName..." -ForegroundColor Yellow
$TunnelInfo = ""
try {
    # Run creation and capture output
    $Output = & $CloudflaredPath tunnel create $DefaultTunnelName
    Write-Host $Output -ForegroundColor Gray

    # Extract Tunnel ID (UUID format: e.g., 1234abcd-1234-abcd-1234-abcd1234abcd)
    if ($Output -match "Created tunnel \S+ with id ([a-f0-9\-]+)") {
        $TunnelId = $Matches[1]
        Write-Host "[+] Tạo Tunnel thành công! Tunnel ID: $TunnelId" -ForegroundColor Green
    } else {
        throw "Could not parse Tunnel ID from output."
    }
} catch {
    # Check if already exists
    if ($_.Exception.Message -match "already exists" -or $Output -match "already exists") {
        Write-Host "[*] Tunnel '$DefaultTunnelName' đã tồn tại. Đang khôi phục ID..." -ForegroundColor Cyan
        try {
            $ListOutput = & $CloudflaredPath tunnel list
            # Parse Tunnel ID from list
            foreach ($Line in $ListOutput) {
                if ($Line -match "([a-f0-9\-]{36})\s+$DefaultTunnelName") {
                    $TunnelId = $Matches[1]
                    Write-Host "[+] Lấy ID Tunnel cũ thành công: $TunnelId" -ForegroundColor Green
                    break
                }
            }
            if (-not $TunnelId) {
                throw "Không thể tìm thấy Tunnel ID của $DefaultTunnelName trong danh sách."
            }
        } catch {
            Write-Host "[-] Không thể khôi phục Tunnel cũ: $_" -ForegroundColor Red
            Exit 1
        }
    } else {
        Write-Host "[-] Lỗi khi tạo Tunnel: $_" -ForegroundColor Red
        Exit 1
    }
}

# --- Step 4: Config Generation ---
Write-Host "`n[Step 4/5] Yêu cầu tên miền tùy chỉnh (Custom Domain)..." -ForegroundColor Yellow
$CustomDomain = Read-Host "Nhập domain của sếp (ví dụ: bot.yourdomain.com)"
$CustomDomain = $CustomDomain.Trim().ToLower()

if ([string]::IsNullOrEmpty($CustomDomain)) {
    Write-Host "[-] Domain không hợp lệ. Thoát." -ForegroundColor Red
    Exit 1
}

Write-Host "Đang sinh cấu hình config.yml cho domain: $CustomDomain..." -ForegroundColor Gray
$CredFile = Join-Path -Path $CloudflaredDir -ChildPath "$TunnelId.json"

# Fallback path check (cloudflared on Windows default credentials folder is ~/.cloudflared)
$UserHome = [System.Environment]::GetFolderPath("UserProfile")
$DefaultCredFile = Join-Path -Path $UserHome -ChildPath ".cloudflared\$TunnelId.json"
if (Test-Path $DefaultCredFile -and -not (Test-Path $CredFile)) {
    Copy-Item $DefaultCredFile $CredFile
}

$ConfigContent = @"
tunnel: $TunnelId
credentials-file: $CredFile

ingress:
  - hostname: $CustomDomain
    service: http://localhost:5000
  - service: http_status:404
"@

# Fix SCAR-002: UTF-8 Enforced write using System.IO
try {
    [System.IO.File]::WriteAllText($ConfigPath, $ConfigContent, [System.Text.Encoding]::UTF8)
    Write-Host "[+] Đã lưu cấu hình config.yml tại: $ConfigPath" -ForegroundColor Green
} catch {
    Write-Host "[-] Không thể tạo file cấu hình: $_" -ForegroundColor Red
    Exit 1
}

# --- Step 5: DNS Mapping ---
Write-Host "`n[Step 5/5] Ánh xạ DNS CNAME trên Cloudflare..." -ForegroundColor Yellow
try {
    & $CloudflaredPath tunnel route dns $DefaultTunnelName $CustomDomain
    Write-Host "[+] DNS CNAME trỏ thành công domain $CustomDomain về Tunnel!" -ForegroundColor Green
} catch {
    Write-Host "[-] Cảnh báo DNS: Không thể tự động tạo bản ghi DNS. Sếp có thể phải tạo thủ công bản ghi CNAME từ domain phụ trỏ đến $TunnelId.cfargotunnel.com" -ForegroundColor Red
}

# --- Success Message & Instructions ---
Write-Host "`n=============================================================" -ForegroundColor Green
Write-Host "               THIẾT LẬP HOÀN TẤT THÀNH CÔNG!                 " -ForegroundColor Green
Write-Host "=============================================================" -ForegroundColor Green
Write-Host "1. File cấu hình đã sẵn sàng tại: $ConfigPath" -ForegroundColor White
Write-Host "2. Khởi chạy Tunnel bất cứ lúc nào bằng lệnh:" -ForegroundColor White
Write-Host "   cloudflared tunnel --config `"$ConfigPath`" run $DefaultTunnelName" -ForegroundColor Cyan
Write-Host "3. Địa chỉ Webhook cố định của bạn là:" -ForegroundColor White
Write-Host "   https://$CustomDomain/webhook" -ForegroundColor Green
Write-Host "=============================================================" -ForegroundColor Green
Write-Host "`n[*] HƯỚNG DẪN BYPASS CLOUDFLARE ACCESS (DÀNH CHO TRADINGVIEW):" -ForegroundColor Yellow
Write-Host "Nếu domain phụ trên bị chặn bởi Cloudflare Zero Trust OTP/MFA, TradingView sẽ không thể gửi webhook."
Write-Host "Sếp hãy làm theo các bước sau trong Zero Trust Dashboard:"
Write-Host "  1. Vào Zero Trust -> Access -> Applications -> Add an Application -> Self-Hosted."
Write-Host "  2. Đặt Domain là: $CustomDomain và Path là: webhook"
Write-Host "  3. Trong tab Policies, chọn Action: BYPASS."
Write-Host "  4. Đặt điều kiện: IP Ranges (Điền các dải IP của TradingView) HOẶC chọn Everyone."
Write-Host "  5. Lưu lại. TradingView sẽ gửi tín hiệu qua trơn tru mà Dashboard vẫn được bảo mật!"
Write-Host "=============================================================" -ForegroundColor Green
