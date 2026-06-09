# 🚀 SERVER B — SETUP PROMPT
## Execution Vault (Windows Server) | Windows Server 2022/2025 (2U4G)

> **Mục tiêu:** Cài đặt Server thực thi lệnh từ số 0 đến trạng thái sẵn sàng trong ~20 phút  
> **RAM target:** ~600MB tổng (OS + Docker Container + Tailscale + SQLite)  
> **Vai trò:** Execution Vault — Nơi bảo mật tối đa API Keys giao dịch, nhận lệnh từ SERVER C và đặt lệnh trực tiếp lên Binance/Bybit/Weex.

---

## ⚡ BƯỚC 0: Thông Tin Cần Chuẩn Bị Trước

```
┌──────────────────────────────────────────────────────────┐
│  CHECKLIST TRƯỚC KHI BẮT ĐẦU                           │
│                                                          │
│  ☐ VPS Windows Server 2022 hoặc 2025 (2 CPU / 4GB RAM)   │
│  ☐ SSH Key hoặc Mật khẩu Administrator                    │
│  ☐ Tài khoản Tailscale (chung mạng với Server A và C)    │
│  ☐ API Keys sàn: Binance, Bybit, Weex (Keys thực tế)     │
│  ☐ Telegram Bot Token + Chat ID (báo cáo lệnh)           │
│  ☐ SERVER_B_SECRET (Khóa bí mật tạo ở Server C)          │
└──────────────────────────────────────────────────────────┘
```

---

## ⚡ BƯỚC 1: Cài Đặt SSH Server & Thiết Lập PowerShell Làm Mặc Định

Để thuận tiện cho việc CI/CD tự động deploy bằng GitHub Actions hoặc kiểm soát từ xa bằng dòng lệnh, ta sẽ cài đặt và cấu hình OpenSSH Server trên Windows.

Chạy **PowerShell (với quyền Administrator)** và thực thi:

```powershell
# 1. Cài đặt OpenSSH Server
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0

# 2. Khởi động dịch vụ SSHD và thiết lập Auto-start cùng OS
Start-Service sshd
Set-Service -Name sshd -StartupType 'Automatic'

# 3. Tạo rule tường lửa Windows Defender để cho phép cổng 22
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22

# 4. Ép OpenSSH sử dụng PowerShell làm Shell mặc định (Thay vì cmd.exe)
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name "DefaultShell" -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force

# 5. Cấu hình SSH Public Key cho Administrator (Thêm Deploy Key GitHub Actions)
$adminKeysFile = "C:\ProgramData\ssh\administrators_authorized_keys"
$deployKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEMVNH4cvW86zP84BLyQkOxW9GATWDQovGFn0imOVPLv"

if (Test-Path $adminKeysFile) {
    Add-Content -Path $adminKeysFile -Value $deployKey -Encoding utf8
} else {
    New-Item -ItemType File -Path $adminKeysFile -Force
    [System.IO.File]::WriteAllLines($adminKeysFile, @($deployKey), [System.Text.Encoding]::UTF8)
}

# Sửa phân quyền (ACL) bắt buộc cho administrators_authorized_keys
icacls.exe $adminKeysFile /inheritance:r
icacls.exe $adminKeysFile /grant:r "NT AUTHORITY\SYSTEM:F"
icacls.exe $adminKeysFile /grant:r "BUILTIN\Administrators:F"
```

---

## ⚡ BƯỚC 2: Cài Đặt Git, Docker & Python 3.11

Chạy các lệnh PowerShell sau để tự động cài đặt các công cụ cần thiết qua winget (trình quản lý gói chính thức của Windows):

```powershell
# 1. Cài đặt Git
winget install --id Git.Git -e --silent

# 2. Cài đặt Python 3.11
winget install --id Python.Python.3.11 -e --silent

# 3. Cài đặt Docker Desktop
winget install --id Docker.DockerDesktop -e --silent

# ⚠️ Yêu cầu khởi động lại máy để hoàn tất cài đặt biến môi trường và WSL2
Restart-Computer
```
*Sau khi restart, mở Docker Desktop thủ công lần đầu để hoàn thành cấu hình WSL2 Engine.*

---

## ⚡ BƯỚC 3: Cài Đặt Tailscale VPN & Kết Nối Mạng Nội Bộ

1. Tải và cài đặt Tailscale trên Windows từ link: `https://tailscale.com/download/windows`
2. Mở ứng dụng Tailscale, đăng nhập tài khoản của sếp để join vào mạng mesh cùng **Server A** và **Server C**.
3. Lấy IP Tailscale của Server B:
   ```powershell
   tailscale ip -4
   # → Ghi lại IP dạng 100.x.x.2 (Đây sẽ là IP nhận lệnh từ Server C)
   ```
4. Thiết lập tên máy ảo trong Tailscale (tuỳ chọn):
   ```powershell
   tailscale set --hostname=server-b-execution
   ```

---

## ⚡ BƯỚC 4: Cấu Hình Tường Lửa Chỉ Cho Phép Server C Truy Cập

Vì tính bảo mật tối thượng của **Execution Vault**, ta chỉ cho phép kết nối đến endpoint `/api/execute-trade` trên cổng `5002` từ IP của **Server C (100.x.x.3)** thông qua Tailscale.

Chạy **PowerShell (Administrator)**:

```powershell
# Chặn cổng 5002 từ tất cả mọi nơi
New-NetFirewallRule -DisplayName "Block 5002 Public" -Direction Inbound -LocalPort 5002 -Protocol TCP -Action Block

# Chỉ cho phép duy nhất IP của Server C kết nối cổng 5002 qua mạng Tailscale
New-NetFirewallRule -DisplayName "Allow Server C on 5002" -Direction Inbound -LocalPort 5002 -Protocol TCP -RemoteAddress 100.x.x.3 -Action Allow
```

---

## ⚡ BƯỚC 5: Sao Chép Code & Cấu Hình `.env`

Tạo thư mục làm việc `/opt/trading-bot` (hoặc `C:\opt\trading-bot`):

```powershell
mkdir C:\opt\trading-bot
cd C:\opt\trading-bot

# Clone repo code từ GitHub
git clone <REPO_URL> .
```

Tạo file biến môi trường `C:\opt\trading-bot\.env` chứa API keys và khóa bí mật xác thực:

```ini
# ═══ SERVER B CONFIG ═══
EXECUTION_MODE=true
HOST=0.0.0.0
PORT=5002

# Khóa xác thực trùng khớp với cấu hình tại Server C
SERVER_B_SECRET=thay_mã_bí_mật_server_b_tại_đây

# ═══ DATABASE PATH ═══
DB_PATH=/app/data/trades.db

# ═══ TELEGRAM SETTINGS ═══
TELEGRAM_BOT_TOKEN=thay_bot_token_telegram
TELEGRAM_CHAT_ID=thay_chat_id_telegram

# ═══ SÀN GIAO DỊCH ═══
DEFAULT_EXCHANGE=binance

# Binance Keys (Cấu hình True/False tùy ý đặt lệnh thật hay test)
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
BINANCE_TESTNET=true
BINANCE_DRY_RUN=true

# Bybit Keys
BYBIT_API_KEY=your_bybit_api_key
BYBIT_API_SECRET=your_bybit_api_secret
BYBIT_TESTNET=true
BYBIT_DRY_RUN=true

# Weex Keys
WEEX_API_KEY=your_weex_api_key
WEEX_API_SECRET=your_weex_api_secret
WEEX_PASSPHRASE=your_weex_passphrase
WEEX_TESTNET=true
WEEX_DRY_RUN=true
```

---

## ⚡ BƯỚC 6: Khởi Chạy Execution Server Bằng Docker

```powershell
# Chạy container chứa Execution FastAPI server
docker compose -f deploy/docker-compose.server-b.yml up -d --build

# Xem log kiểm tra khởi động
docker compose -f deploy/docker-compose.server-b.yml logs -f
# → Uvicorn running on http://0.0.0.0:5002 ✅
```

---

## ⚡ BƯỚC 7: Kiểm Tra Liveness & Verify

```powershell
# ── Test 1: Kiểm tra endpoint Health cục bộ ──
Invoke-RestMethod -Uri "http://localhost:5002/health" -Method Get
# → {"status": "healthy", "exchange": "binance", "dry_run": true} ✅

# ── Test 2: Thử gọi API đặt lệnh sai Secret (Bị chặn) ──
try {
    Invoke-RestMethod -Uri "http://localhost:5002/api/execute-trade" -Method Post -Headers @{"X-Server-B-Secret" = "wrong_secret"} -Body '{}'
} catch {
    $_.Exception.Response.StatusCode
    # → Unauthorized (401) ✅
}

# ── Test 3: Gửi payload đặt lệnh giả lập (Sử dụng đúng Secret) ──
$headers = @{"X-Server-B-Secret" = "mã_bí_mật_server_b_tại_đây"}
$body = @{
    symbol = "BTCUSDT"
    action = "buy"
    price = 65000.0
    quantity = 0.002
    sl_price = 60000.0
    tp_price = 75000.0
    exchange = "binance"
    rag_advice = "📊 Smoke Test — Strong Bullish Structure"
    ai_confidence = 90
    vbs_queue_id = 9999
} | ConvertTo-Json

$response = Invoke-RestMethod -Uri "http://localhost:5002/api/execute-trade" -Method Post -Headers $headers -Body $body -ContentType "application/json"
$response
# → Trả về thông tin lệnh test thành công và gửi thông báo Telegram ✅
```

---

## 📊 RAM Budget Cho Server B

Mặc dù chạy Windows Server ngốn RAM hệ điều hành nhiều hơn Linux, nhưng cấu trúc tách biệt giúp chúng ta giải phóng hoàn toàn các dịch vụ nặng, giữ cho VPS 4GB cực kỳ an toàn:

```
┌──────────────────────────────────────────────────┐
│      SERVER B — RAM THỰC TẾ TRÊN VPS 4GB         │
│                                                  │
│  Windows Server (OS Idle):   ~1.8 - 2.2 GB       │
│  Tailscale daemon:           ~40 MB              │
│  Docker Desktop Service:     ~400 MB             │
│  ──────────────────────────────                  │
│  Hạ tầng:                    ~2.6 GB             │
│                                                  │
│  Execution Container:                            │
│    FastAPI/Uvicorn:          ~60 MB              │
│    SQLite (trades.db):       ~10 MB              │
│  ──────────────────────────────                  │
│  Execution App:              ~70 MB              │
│  ══════════════════════════════                  │
│  TỔNG SỬ DỤNG:               ~2.7 GB             │
│  CÒN TRỐNG:                  ~1.3 GB (32% free)  │
│                                                  │
│  ✅ Hoàn toàn an toàn cho VPS 4GB RAM            │
└──────────────────────────────────────────────────┘
```

---

## ❌ KHÔNG LÀM Trên SERVER B

| Hành động | Lý do |
|-----------|-------|
| ❌ Cài đặt ChromaDB Server | Quá nặng, không cần thiết. Chỉ lưu trữ tại Server C. |
| ❌ Gọi các API AI (Claude/Gemini) | Tốn RAM và không nằm trong nhiệm vụ thực thi. |
| ❌ Mở cổng 5002 ra mạng WAN | Đảm bảo an toàn API Keys — chỉ lắng nghe Tailscale và chặn bằng Firewall. |
| ❌ Đặt file source code chính của bot ở các ổ đĩa công cộng | API keys và secrets lưu trong `.env` phải được set quyền chỉ Administrator được đọc. |
