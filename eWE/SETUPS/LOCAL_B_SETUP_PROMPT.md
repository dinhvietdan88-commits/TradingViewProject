# 🚀 LOCAL SERVER B — SETUP PROMPT
## Execution Vault (Local Windows Machine) | Windows 10 / Windows 11 (Desktop Environment)

> **Mục tiêu:** Cài đặt Máy chủ Thực thi lệnh ngay trên máy tính Local cá nhân (PC/Laptop Windows) đạt trạng thái an toàn, chạy ngầm 24/7 và sẵn sàng nhận lệnh từ Server C qua mạng riêng ảo Tailscale.
> **RAM target:** ~80-150MB nếu chạy thông qua Python Virtual Environment (Khuyên dùng cho máy cá nhân) hoặc ~500MB nếu chạy qua Docker Desktop.
> **Vai trò:** Execution Vault — Nơi lưu giữ cục bộ các API Keys sàn giao dịch, hoàn toàn cô lập khỏi Internet công cộng.

---

## ⚡ BƯỚC 0: Checklist Chuẩn Bị & Chống Sleep Máy Local

Vì máy Local (PC/Laptop) chạy Windows 10/11 có cơ chế tự động ngủ (Sleep/Hibernate) khi không tương tác, ta cần cấu hình để máy luôn hoạt động (bật 24/7) khi cắm nguồn điện.

```
┌─────────────────────────────────────────────────────────────┐
│  CHECKLIST TRƯỚC KHI BẮT ĐẦU                                │
│                                                             │
│  ☐ Hệ điều hành: Windows 10 hoặc Windows 11 (Pro/Home)       │
│  ☐ Đã cắm nguồn điện liên tục (đối với Laptop)              │
│  ☐ Tài khoản Tailscale (đã đăng nhập chung mạng VPS A/C)     │
│  ☐ API Keys sàn: Binance, Bybit, Weex (Thực tế hoặc Testnet) │
│  ☐ SERVER_B_SECRET (Khóa bảo mật trùng với Server C)         │
└─────────────────────────────────────────────────────────────┘
```

Mở **PowerShell (Run as Administrator)** và thực thi các cấu hình chống ngủ máy tính:

```powershell
# 1. Chống Sleep ổ cứng và CPU khi cắm nguồn (AC)
powercfg /change monitor-timeout-ac 15
powercfg /change disk-timeout-ac 0
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

# 2. Vô hiệu hóa tính năng Fast Startup (Tránh lỗi driver mạng khi reboot)
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power" -Name "HiberbootEnabled" -Value 0
```

---

## ⚡ BƯỚC 1: Cấu Hình Mạng Tailscale Chạy Dưới Dạng Dịch Vụ (Windows Service)

Mặc định, Tailscale trên Windows Desktop sẽ tự tắt khi bạn Log out hoặc khóa màn hình. Chúng ta cần ép Tailscale chạy dưới dạng **Windows Service** (chạy ngầm kể cả khi bạn chưa đăng nhập).

1. Nhấp chuột phải vào biểu tượng Tailscale ở khay hệ thống, chọn **Exit**.
2. Mở **PowerShell (Administrator)** và khởi động Tailscale ở chế độ chạy ngầm:
   ```powershell
   # Chạy daemon Tailscale dưới quyền hệ thống
   tailscale login
   ```
3. Lấy IP Tailscale nội bộ của máy local:
   ```powershell
   tailscale ip -4
   # → Ghi lại IP dạng 100.x.x.2 (Đây là IP tĩnh của máy local trong mạng VPN)
   ```
4. Đặt tên hostname cố định trong mạng Tailscale:
   ```powershell
   tailscale set --hostname=local-b-execution
   ```

---

## ⚡ BƯỚC 2: Cấu Hình Tường Lửa Windows Defender (Firewall) Cho Cổng 5002

Chúng ta phải chặn tuyệt đối mọi kết nối từ mạng Internet bên ngoài (WAN/Wi-Fi công cộng) truy cập vào cổng `5002` của máy local, chỉ cho phép duy nhất IP của **Server C (100.x.x.3)** đi qua mạng Tailscale kết nối vào.

Chạy **PowerShell (Administrator)**:

```powershell
# 1. Xóa các rule cũ nếu có liên quan đến cổng 5002
Remove-NetFirewallRule -DisplayName "Block 5002 Public" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "Allow Server C on 5002" -ErrorAction SilentlyContinue

# 2. Chặn tất cả kết nối Inbound đến cổng 5002 trên profile Public và Private
New-NetFirewallRule -DisplayName "Block 5002 Public" `
    -Direction Inbound `
    -LocalPort 5002 `
    -Protocol TCP `
    -Action Block `
    -Profile Any

# 3. Cho phép duy nhất IP của Server C kết nối cổng 5002 qua mạng Tailscale
New-NetFirewallRule -DisplayName "Allow Server C on 5002" `
    -Direction Inbound `
    -LocalPort 5002 `
    -Protocol TCP `
    -RemoteAddress 100.x.x.3 `
    -Action Allow `
    -Profile Any
```

---

## ⚡ BƯỚC 3: Triển Khai Mã Nguồn (Chọn 1 trong 2 Phương Án)

Do chạy trên máy cá nhân, ta nên ưu tiên **Phương án A (Python Venv)** để tiết kiệm tài nguyên RAM (chỉ tốn ~80MB). Nếu máy của bạn cấu hình mạnh và đã có Docker, hãy chọn **Phương án B (Docker)**.

### 💡 PHƯƠNG ÁN A: Chạy Bằng Python Virtual Environment (Khuyên dùng)

Mở PowerShell tại thư mục làm việc của bạn (ví dụ `C:\opt\trading-bot`):

```powershell
# 1. Di chuyển vào thư mục code server
cd C:\opt\trading-bot\server

# 2. Tạo virtual environment
python -m venv .venv

# 3. Kích hoạt venv
.venv\Scripts\Activate.ps1

# 4. Cài đặt các thư viện cần thiết cho Execution Server
pip install -r requirements.txt
```

### 📦 PHƯƠNG ÁN B: Chạy Bằng Docker Desktop

Mở PowerShell tại thư mục `C:\opt\trading-bot`:

```powershell
# Khởi chạy container Server B ngầm
docker compose -f deploy/docker-compose.server-b.yml up -d --build
```

---

## ⚡ BƯỚC 4: Tạo File Cấu Hình `.env` Bảo Mật Cho Local B

Tạo file `C:\opt\trading-bot\server\.env` (nếu dùng Python venv) hoặc `C:\opt\trading-bot\.env` (nếu dùng Docker).

> [!WARNING]
> Không bao giờ commit file `.env` này lên GitHub. Set quyền hạn chỉ tài khoản User Windows hiện tại của bạn có quyền Đọc/Ghi đối với file này.

```ini
# ══════════ LOCAL SERVER B CONFIG ══════════
EXECUTION_MODE=true
HOST=0.0.0.0
PORT=5002

# Khóa xác thực - Phải trùng khớp 100% với cấu hình SERVER_B_SECRET trên Server C
SERVER_B_SECRET=thay_mã_bí_mật_server_b_của_bạn_tại_đây

# ══════════ DATABASE PATH ══════════
# Nếu chạy Python venv trực tiếp trên Windows:
DB_PATH=C:\opt\trading-bot\server\data\trades.db
# Nếu chạy Docker:
# DB_PATH=/app/data/trades.db

# ══════════ TELEGRAM NOTIFICATIONS ══════════
TELEGRAM_BOT_TOKEN=thay_bot_token_telegram
TELEGRAM_CHAT_ID=thay_chat_id_telegram

# ══════════ API KEYS SÀN GIAO DỊCH (BẢO MẬT TUYỆT ĐỐI) ══════════
DEFAULT_EXCHANGE=binance

# Binance API Keys
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
BINANCE_TESTNET=true
BINANCE_DRY_RUN=true

# Bybit API Keys
BYBIT_API_KEY=your_bybit_api_key
BYBIT_API_SECRET=your_bybit_api_secret
BYBIT_TESTNET=true
BYBIT_DRY_RUN=true

# Weex API Keys
WEEX_API_KEY=your_weex_api_key
WEEX_API_SECRET=your_weex_api_secret
WEEX_PASSPHRASE=your_weex_passphrase
WEEX_TESTNET=true
WEEX_DRY_RUN=true
```

---

## ⚡ BƯỚC 5: Thiết Lập Tự Động Khởi Chạy Cùng Hệ Điều Hành (Auto-start)

Để đảm bảo bot luôn tự khởi động bất cứ khi nào máy tính Local bật lên mà bạn không cần phải mở dòng lệnh thủ công:

### Đối với Phương án A (Python Venv) — Chạy ngầm qua VBScript & Startup:
1. Tạo một file script tại `C:\opt\trading-bot\server\run_execution.vbs` để chạy ngầm tiến trình (không hiện cửa sổ đen cmd):
   ```vbs
   Set WshShell = CreateObject("WScript.Shell")
   WshShell.Run "powershell.exe -ExecutionPolicy Bypass -Command ""cd C:\opt\trading-bot\server; .venv\Scripts\activate; uvicorn execution_server:app --host 0.0.0.0 --port 5002""", 0, False
   ```
2. Nhấn tổ hợp phím `Windows + R`, gõ `shell:startup` và nhấn Enter để mở thư mục Startup của Windows.
3. Tạo một **Shortcut** trỏ đến file `run_execution.vbs` vừa tạo trong thư mục Startup này.
4. *Từ nay, mỗi khi bạn đăng nhập vào Windows, Execution Server sẽ tự khởi chạy ngầm trên cổng 5002.*

---

## ⚡ BƯỚC 6: Kiểm Tra Liên Thông & Xác Minh Kết Nối

### 1. Kiểm tra liveness tại local:
Mở PowerShell và chạy:
```powershell
Invoke-RestMethod -Uri "http://localhost:5002/health" -Method Get
# Trả về: {"status": "healthy", "exchange": "binance", "dry_run": true} ✅
```

### 2. Kiểm tra cuộc gọi từ Server C (AI Core):
SSH vào **Server C (Oracle Linux 9)** và thực thi lệnh kiểm tra ping mạng Tailscale và API cổng 5002:
```bash
# 1. Ping sang máy local qua Tailscale
ping -c 3 100.x.x.2

# 2. Curl kiểm tra API health của Local B từ xa
curl -sf http://100.x.x.2:5002/health
# Trả về kết quả status: healthy từ Local B ✅
```

---

## ❌ CÁC SAI LẦM CẦN TRÁNH TRÊN MÁY LOCAL B

| Hành động cấm kỵ | Hậu quả | Giải pháp đúng |
| :--- | :--- | :--- |
| **❌ Cho máy đi vào trạng thái Sleep/Standby** | Mạng bị ngắt, Server C không thể đặt lệnh và bot bị treo luồng. | Chạy lệnh `powercfg` ở Bước 0 hoặc cài đặt phần mềm như *Caffeine* để giữ máy luôn wake. |
| **❌ Mở cổng 5002 trên router Wi-Fi/Modem nhà** | API keys bị lộ ra ngoài Internet công cộng qua port forwarding. | **Không cần port forward**. Tailscale đã tạo một kết nối VPN ngang hàng (P2P) an toàn đi xuyên qua NAT/Firewall. |
| **❌ Chạy Docker Desktop không giới hạn RAM** | WSL2 (vmmem) ngốn hết 100% RAM của máy tính cá nhân. | Ưu tiên dùng **Python Venv** trực tiếp, hoặc giới hạn tài nguyên WSL trong file `.wslconfig` ở thư mục User. |
