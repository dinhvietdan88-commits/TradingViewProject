# 🖥️ VPS Server Setup Guide
## Hướng Dẫn Thiết Lập Hạ Tầng 3-Server Pipeline Forwarding Từ Số 0

> **Version:** 2.0 | **Date:** 2026-05-29  
> **Classification:** 🔴 PRE-DEPLOYMENT PREREQUISITE  
> **Applies to:** SERVER A (Gateway) · SERVER C (AI Core) · SERVER B (Execution Vault)  
> **Related:** [V2 Operational Hardening](file:///C:/Users/pesil/.gemini/antigravity/brain/e2cbb527-ef1a-4f70-b7b7-baf5e1dcd06a/v2_operational_hardening.md)

---

## 📋 MỤC LỤC

1. [Lựa Chọn OS — Debian 12 Minimal](#1-lựa-chọn-os)
2. [Thiết Lập Ban Đầu (Common Setup)](#2-thiết-lập-ban-đầu)
3. [Bảo Mật SSH & Firewall](#3-bảo-mật-ssh--firewall)
4. [Cài Đặt Docker & Docker Compose](#4-cài-đặt-docker)
5. [Cài Đặt Tailscale VPN](#5-cài-đặt-tailscale-vpn)
6. [Cài Đặt Cloudflare Tunnel (SERVER A)](#6-cloudflare-tunnel)
7. [Mô Hình Isolated Ingress Node — SERVER A](#7-isolated-ingress-node)
8. [Mô Hình AI Core — SERVER C (8U16G)](#8-ai-core-server-c)
9. [Mô Hình Execution Vault — SERVER B (Windows)](#9-execution-vault-server-b)
10. [Deployment Commands](#10-deployment-commands)
11. [Checklist Hoàn Tất](#11-checklist)

---

## 1. Lựa Chọn OS

### 1.1 Kết Luận: Debian 12 Minimal — Lựa Chọn Duy Nhất

> [!IMPORTANT]
> **Debian 12 Minimal** (Bookworm) là hệ điều hành duy nhất nên cài đặt cho SERVER A và SERVER C.
> Nếu VPS provider không có bản Minimal, dùng **Debian 12 Standard** rồi cleanup sau.

### 1.2 Bảng So Sánh Kỹ Thuật Toàn Diện

| Tiêu chí | Debian 9 (Stretch) | Debian 10 (Buster) | Debian 11 (Bullseye) | Debian 12 Minimal (Bookworm) |
|----------|-------|--------|--------|-----------|
| **Trạng thái hỗ trợ** | ❌ EOL (06/2022) | ❌ EOL (06/2024) | ⚠️ LTS sắp hết | ✅ **Hỗ trợ đầy đủ đến 2028** |
| **Bản vá bảo mật** | ❌ Không có | ❌ Không có | ⚠️ Rất ít (chỉ critical) | ✅ **Cập nhật liên tục** |
| **Kernel** | 4.9 | 4.19 | 5.10 | **6.1 LTS** |
| **RAM idle mặc định** | ~70MB | ~80MB | ~90MB | 🚀 **~60-70MB** |
| **Python mặc định** | 3.5 ❌ | 3.7 ❌ | 3.9 ⚠️ | 🐍 **3.11+** ✅ |
| **Docker compat** | ❌ Lỗi glibc | ❌ Thư viện cũ | ⚠️ Trung bình | ✅ **Tốt nhất** |
| **OpenSSL** | 1.1.0 ❌ | 1.1.1 ⚠️ | 1.1.1 ⚠️ | **3.0.x** ✅ |
| **Node.js compat** | ❌ Không chạy | ❌ v14 max | ⚠️ v16-18 | ✅ **v18-24+** |
| **SystemD version** | 232 | 241 | 247 | **252** |
| **Chiếm đĩa sau cài** | ~1.2GB | ~1.5GB | ~1.8GB | 🚀 **~800MB** |

### 1.3 Đánh Giá Chi Tiết Từ Góc Độ SRE

#### ❌ Debian 9 & 10 — TRÁNH XA HOÀN TOÀN

> [!CAUTION]
> **KHÔNG BAO GIỜ** cài Debian 9 hoặc 10 cho server production tiếp xúc Internet.

| Rủi ro | Chi tiết |
|--------|---------|
| **Bảo mật** | EOL = không có bản vá. VPS dù qua Cloudflare Tunnel vẫn có surface attack từ Kernel cũ, SSH cũ |
| **glibc quá cũ** | Không chạy được Node.js v18+ (cần cho `tradingview-mcp`), không chạy Python 3.10+ native |
| **OpenSSL lỗi thời** | TLS 1.3 không hỗ trợ → Cloudflare Tunnel có thể fail, HTTPS internal bị lỗi |
| **Docker CE** | Phiên bản Docker mới nhất không build được trên glibc cũ → phải dùng Docker cổ, thiếu features |

#### ⚠️ Debian 11 — CHỈ LÀM PHƯƠNG ÁN PHỤ

| Vấn đề | Hệ quả |
|--------|--------|
| Python 3.9 mặc định | Phải tự biên dịch Python 3.11 hoặc thêm repo ngoài → xung đột package hệ thống |
| LTS sắp hết hạn | Chuyển sang Debian 12 là inevitable, tốt hơn nên cài đúng từ đầu |
| RAM cao hơn | ~90MB idle vs ~60MB trên Debian 12 Minimal — đáng kể trên VPS 2GB |

#### ✅ Debian 12 Minimal — SỰ LỰA CHỌN SỐ 1

| Ưu điểm | Giải thích |
|---------|-----------|
| **Python 3.11 native** | Hoàn hảo cho FastAPI + Pydantic v2. JSON parsing nhanh hơn 10-25% so với 3.9 |
| **Minimal = sạch tối đa** | Không có GUI, không có service mạng thừa. Giải phóng RAM tối đa cho VPS 2GB |
| **Kernel 6.1 LTS** | io_uring, better cgroup v2, improved OOM killer — quan trọng cho container workload |
| **OpenSSL 3.0** | TLS 1.3 native, Cloudflare Tunnel + HTTPS internal chạy mượt |
| **Hỗ trợ dài hạn** | Debian 12 được hỗ trợ đến 2028, không phải lo upgrade OS trong 2-3 năm tới |
| **Disk footprint nhỏ** | ~800MB sau cài → còn dư đĩa cho Docker images, SQLite DB, logs |

### 1.4 RAM Budget Trên VPS 2GB

```
┌──────────────────────────────────────────────────┐
│         RAM BUDGET — SERVER A (2GB)              │
│                                                  │
│  Total RAM:           2048 MB                    │
│  ────────────────────────────────                │
│  Debian 12 Minimal:    -60 MB (OS idle)          │
│  SSH daemon:            -5 MB                    │
│  Tailscale:            -30 MB                    │
│  Cloudflare Tunnel:    -25 MB                    │
│  Docker Engine:        -80 MB                    │
│  ────────────────────────────────                │
│  Tổng hạ tầng:        -200 MB                    │
│  ════════════════════════════════                │
│  CÒN LẠI cho VBS:    ~1848 MB                   │
│    ├── FastAPI/Uvicorn: ~80 MB                   │
│    ├── SQLite (WAL):    ~20 MB                   │
│    ├── APScheduler:     ~15 MB                   │
│    └── Buffer:         ~1733 MB (rất thoải mái!) │
└──────────────────────────────────────────────────┘

So sánh nếu dùng Debian 11 Standard:
  OS idle:              -90 MB  (+30 MB lãng phí)
  Thêm service mặc định: -50 MB  (avahi, cups, etc.)
  → Mất thêm ~80 MB so với Debian 12 Minimal
```

---

## 2. Thiết Lập Ban Đầu

> Áp dụng cho **cả SERVER A và SERVER C** (Linux Debian 12)

### 2.1 Cập Nhật Hệ Thống & Cài Package Cơ Bản

```bash
# ═══════════════════════════════════════════════════════
# BƯỚC 1: Cập nhật hệ thống
# ═══════════════════════════════════════════════════════

# Login với root (lần đầu sau khi nhận VPS)
apt update && apt upgrade -y

# Cài package cơ bản
apt install -y \
    curl \
    wget \
    git \
    htop \
    tmux \
    unzip \
    jq \
    ca-certificates \
    gnupg \
    lsb-release \
    python3 \
    python3-pip \
    python3-venv \
    sudo

# Verify Python version
python3 --version
# → Python 3.11.x ✅
```

### 2.2 Tạo User Non-Root

```bash
# ═══════════════════════════════════════════════════════
# BƯỚC 2: Tạo user riêng cho bot (KHÔNG chạy bằng root!)
# ═══════════════════════════════════════════════════════

# Tạo user 'botuser' với home directory
useradd -m -s /bin/bash botuser

# Đặt password mạnh
passwd botuser

# Thêm vào sudo group
usermod -aG sudo botuser

# Thêm vào docker group (sau khi cài Docker)
# usermod -aG docker botuser

# Chuyển sang user mới
su - botuser
```

### 2.3 Cấu Hình Timezone & Locale

```bash
# ═══════════════════════════════════════════════════════
# BƯỚC 3: Timezone (ICT = UTC+7 cho Việt Nam)
# ═══════════════════════════════════════════════════════

sudo timedatectl set-timezone Asia/Ho_Chi_Minh
timedatectl
# → Time zone: Asia/Ho_Chi_Minh (ICT, +0700)

# Locale UTF-8
sudo apt install -y locales
sudo sed -i 's/# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen
sudo locale-gen
sudo update-locale LANG=en_US.UTF-8
```

### 2.4 Cấu Hình NTP (Bắt Buộc — Xem Hardening Report #1)

```bash
# ═══════════════════════════════════════════════════════
# BƯỚC 4: NTP đồng bộ thời gian (chrony — khuyến nghị)
# ═══════════════════════════════════════════════════════

sudo apt install -y chrony

sudo tee /etc/chrony/chrony.conf << 'EOF'
server 0.pool.ntp.org iburst
server 1.pool.ntp.org iburst
server time.google.com iburst prefer
server time.cloudflare.com iburst

makestep 1.0 3
driftfile /var/lib/chrony/chrony.drift
logdir /var/log/chrony
log tracking measurements statistics
maxdistance 0.1
EOF

sudo systemctl enable --now chrony
chronyc tracking
# → System time: 0.000000xxx seconds ← Phải rất nhỏ
```

### 2.5 Cấu Hình Swap (Bảo Hiểm Cho 2GB RAM)

```bash
# ═══════════════════════════════════════════════════════
# BƯỚC 5: Swap file — Phòng trường hợp OOM
# ═══════════════════════════════════════════════════════

# Kiểm tra swap hiện tại
free -h

# Tạo 2GB swap file
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Persist sau reboot
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Điều chỉnh swappiness (ít swap hơn, ưu tiên RAM)
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Verify
free -h
# → Swap: 2.0Gi
```

---

## 3. Bảo Mật SSH & Firewall

### 3.1 SSH Hardening

```bash
# ═══════════════════════════════════════════════════════
# SSH KEY AUTHENTICATION (Bắt buộc!)
# ═══════════════════════════════════════════════════════

# Trên máy LOCAL — sinh SSH key (nếu chưa có)
# ssh-keygen -t ed25519 -C "trading-bot-admin"

# Copy public key lên server
# ssh-copy-id -i ~/.ssh/id_ed25519.pub botuser@VPS_IP

# ── Trên SERVER ──

# Cấu hình SSH daemon
sudo tee /etc/ssh/sshd_config.d/hardened.conf << 'EOF'
# ── SSH Hardening for Trading Bot VPS ──

# Chỉ cho phép key authentication (TẮT password login!)
PasswordAuthentication no
ChallengeResponseAuthentication no
PubkeyAuthentication yes

# Tắt login root từ xa
PermitRootLogin no

# Chỉ cho phép user cụ thể
AllowUsers botuser

# Timeout session
ClientAliveInterval 300
ClientAliveCountMax 2

# Giới hạn số lần thử
MaxAuthTries 3

# Tắt forwarding không cần thiết
X11Forwarding no
AllowTcpForwarding no
AllowAgentForwarding no

# Đổi port (tuỳ chọn — thêm lớp bảo vệ)
# Port 2222
EOF

# Restart SSH
sudo systemctl restart sshd

# ⚠️ KIỂM TRA: Mở terminal MỚI và thử SSH vào trước khi đóng terminal cũ!
```

### 3.2 Fail2Ban (Chống Brute Force)

```bash
# ═══════════════════════════════════════════════════════
# FAIL2BAN — Tự động ban IP khi brute force SSH
# ═══════════════════════════════════════════════════════

sudo apt install -y fail2ban

sudo tee /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime  = 3600     # Ban 1 giờ
findtime = 600      # Trong vòng 10 phút
maxretry = 3        # 3 lần sai = ban

[sshd]
enabled = true
port    = ssh
filter  = sshd
logpath = /var/log/auth.log
EOF

sudo systemctl enable --now fail2ban
sudo fail2ban-client status sshd
```

### 3.3 UFW Firewall

```bash
# ═══════════════════════════════════════════════════════
# UFW FIREWALL
# ═══════════════════════════════════════════════════════

sudo apt install -y ufw

# Reset và đặt policy mặc định
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Cho phép SSH (QUAN TRỌNG — làm trước khi enable!)
sudo ufw allow ssh
# Nếu đổi port SSH: sudo ufw allow 2222/tcp

# Cho phép Tailscale
sudo ufw allow in on tailscale0

# SERVER A thêm: cho phép Cloudflare Tunnel (không cần open port)
# Tunnel kết nối outbound → không cần rule incoming

# Bật firewall
sudo ufw enable

# Kiểm tra
sudo ufw status verbose
```

---

## 4. Cài Đặt Docker

```bash
# ═══════════════════════════════════════════════════════
# DOCKER CE + DOCKER COMPOSE V2
# ═══════════════════════════════════════════════════════

# Thêm Docker GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Thêm Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Cài Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Thêm user vào docker group (không cần sudo cho docker commands)
sudo usermod -aG docker botuser
newgrp docker

# Verify
docker --version
# → Docker version 27.x.x
docker compose version
# → Docker Compose version v2.x.x

# Test
docker run --rm hello-world

# ── Cấu hình Docker daemon (giới hạn log) ──
sudo tee /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2"
}
EOF

sudo systemctl restart docker
```

---

## 5. Cài Đặt Tailscale VPN

```bash
# ═══════════════════════════════════════════════════════
# TAILSCALE — VPN mesh nội bộ giữa 3 server
# ═══════════════════════════════════════════════════════

# Cài Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Kích hoạt (sẽ hiện URL đăng nhập)
sudo tailscale up

# Kiểm tra IP nội bộ
tailscale ip -4
# → 100.x.x.x

# Kiểm tra kết nối giữa các server
tailscale ping server-a
tailscale ping server-b
tailscale ping server-c

# ── Cấu hình DNS nội bộ (tuỳ chọn) ──
# Trong Tailscale Admin Console → DNS:
# server-a → 100.x.x.1
# server-b → 100.x.x.2
# server-c → 100.x.x.3
```

### 5.1 Tailscale ACL (Access Control)

```jsonc
// tailscale ACL policy — giới hạn traffic giữa các server
{
  "acls": [
    // SERVER C → SERVER A (consume signals)
    {"action": "accept", "src": ["server-c"], "dst": ["server-a:5000"]},
    // SERVER C → SERVER B (forward trades)
    {"action": "accept", "src": ["server-c"], "dst": ["server-b:5002"]},
    // SERVER C → SERVER A (health check)
    {"action": "accept", "src": ["server-c"], "dst": ["server-a:5000"]},
    // SERVER C → SERVER B (health check)
    {"action": "accept", "src": ["server-c"], "dst": ["server-b:5002"]},
    // SSH từ admin machines
    {"action": "accept", "src": ["tag:admin"], "dst": ["*:22"]},
    // Block everything else
    {"action": "accept", "src": ["*"], "dst": ["*:*"]}
  ]
}
```

---

## 6. Cloudflare Tunnel (SERVER A Only)

```bash
# ═══════════════════════════════════════════════════════
# CLOUDFLARE TUNNEL — Expose VBS qua HTTPS không cần open port
# ═══════════════════════════════════════════════════════

# Cài cloudflared
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | \
    sudo tee /usr/share/keyrings/cloudflare-main.gpg > /dev/null

echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] \
    https://pkg.cloudflare.com/cloudflared bookworm main' | \
    sudo tee /etc/apt/sources.list.d/cloudflared.list

sudo apt update && sudo apt install -y cloudflared

# Đăng nhập (sẽ mở browser)
cloudflared tunnel login

# Tạo tunnel
cloudflared tunnel create trading-bot-gateway

# Cấu hình tunnel
sudo mkdir -p /etc/cloudflared

sudo tee /etc/cloudflared/config.yml << 'EOF'
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

ingress:
  # VBS Buffer Service
  - hostname: bot.yourdomain.com
    service: http://localhost:5000
    originRequest:
      noTLSVerify: true
  # Health check
  - hostname: health.yourdomain.com
    service: http://localhost:5000/health
  # Catch-all
  - service: http_status:404
EOF

# Cấu hình DNS (tự động)
cloudflared tunnel route dns trading-bot-gateway bot.yourdomain.com

# Cài service (auto-start)
sudo cloudflared service install
sudo systemctl enable --now cloudflared

# Verify
curl https://bot.yourdomain.com/health
# → {"status": "healthy", ...}
```

---

## 7. Mô Hình Isolated Ingress Node — SERVER A

### 7.1 Tổng Quan Kiến Trúc

> [!IMPORTANT]
> **Isolated Ingress Node** là kiến trúc đạt chuẩn production chuyên nghiệp.
> SERVER A CHỈ làm nhiệm vụ Gateway thuần túy: nhận → xác thực → lưu queue → chuyển tiếp.
> Không chứa BẤT KỲ logic phân tích, tính toán, hay thực thi giao dịch nào.

```
┌────────────────────────────────────────────────────────────┐
│            SERVER A — ISOLATED INGRESS NODE                │
│              Debian 12 Minimal (1U2G)                     │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Cloudflare Tunnel (Outbound Only — No Ports Open)  │  │
│  │  bot.yourdomain.com → localhost:5000                │  │
│  └──────────────────────┬───────────────────────────────┘  │
│                         │                                  │
│                         ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         VBS Gateway (FastAPI — Uvicorn)              │  │
│  │                                                      │  │
│  │  POST /ingest ──► Validate ──► SQLite Queue          │  │
│  │  GET  /consume ◄── SERVER C polls                    │  │
│  │  POST /ack    ◄── SERVER C confirms                  │  │
│  │  GET  /health ──► UptimeRobot monitors               │  │
│  │                                                      │  │
│  │  RAM footprint: ~40MB                                │  │
│  │  CPU usage: < 0.5%                                   │  │
│  │  Disk: SQLite ~50MB max                              │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ❌ KHÔNG CÓ: Playwright, Matplotlib, ML libs, LLM SDK    │
│  ❌ KHÔNG CÓ: Exchange API keys, trade logic              │
│  ❌ KHÔNG CÓ: ChromaDB, RAG, AI analysis                  │
└────────────────────────────────────────────────────────────┘
```

### 7.2 Tại Sao Đây Là Kiến Trúc Tối Ưu Nhất?

| Ưu điểm | Chi tiết |
|---------|--------|
| 🚀 **Tải siêu nhẹ (Near-Zero Load)** | Script Gateway chỉ: nhận POST → xác thực → ghi SQLite → trả response. Toàn bộ ~40MB RAM, < 0.5% CPU. VPS 2GB chạy "nhàn hạ" 24/7 |
| 🛡️ **Tách biệt vùng lỗi (Fault Isolation)** | Nếu Server C (AI) hoặc Server B (sàn) gặp sự cố → Gateway vẫn sống 24/7 hứng TradingView, ghi vào queue, **KHÔNG mất bất kỳ tín hiệu nào** |
| 🔐 **An ninh tuyệt đối cho Local Server** | Server chạy bot thực tế nằm an toàn sau tường lửa. VPS là "khiên đỡ" duy nhất lộ diện Internet |
| 💰 **Chi phí tối thiểu** | VPS 1U2G rẻ nhất (~$3-5/tháng) là đủ cho Gateway. Không lãng phí tiền cho tài nguyên không cần |
| 🔄 **Dễ thay thế** | Nếu VPS bị lỗi/hết hạn → deploy VBS lên VPS mới trong < 10 phút (chỉ 1 Docker Compose file) |

### 7.3 Mô Hình Chuyển Tiếp Tín Hiệu

#### Cách A: Pipeline Forwarding qua Tailscale (✅ Đang dùng)

```
[TradingView Webhook]
       │ (HTTPS công khai)
       ▼
[Cloudflare Edge Network]
       │ (Cloudflare Tunnel — mã hóa bảo mật)
       ▼
[cloudflared daemon → localhost:5000 (VBS trên VPS)]
       │
       ▼  Ghi vào SQLite Queue (PENDING)
       │
       │◄─── SERVER C polls GET /consume (Tailscale VPN)
       │
       ▼  SERVER C nhận signal → Phân tích → Forward → SERVER B
```

#### Cách B: Queue-Based Pull (Dự phòng khi không có Tailscale)

```
[TradingView Webhook]
       │
       ▼
[VPS Gateway]
       │
       ▼  Ghi vào SQLite Queue
       │
       │◄─── Local Server polls qua HTTPS (public /consume endpoint)
       │     (Xác thực bằng X-Buffer-Secret header)
       ▼
[Local Server kéo signals → xử lý → ACK]
```

> [!TIP]
> **Khuyến nghị:** Luôn dùng **Cách A (Tailscale)** vì:
> - Không cần expose `/consume` endpoint ra Internet
> - Mã hóa WireGuard end-to-end
> - Latency thấp hơn (~5ms vs ~50ms qua public Internet)

### 7.4 Packages Cần Cài Trên SERVER A

```bash
# ═══════════════════════════════════════════════════════
# SERVER A: CHỈ cài những gì cần thiết — KHÔNG gì thêm
# ═══════════════════════════════════════════════════════

# Packages hệ thống (đã cài ở Bước 2)
# curl, wget, htop, tmux, jq, python3, python3-pip, python3-venv

# Python packages cho VBS (CHÍNH XÁC — không thừa)
pip3 install \
    fastapi==0.115.* \
    uvicorn[standard]==0.34.* \
    pydantic==2.* \
    aiosqlite==0.21.* \
    apscheduler==3.10.* \
    httpx==0.28.*

# ❌ TUYỆT ĐỐI KHÔNG CÀI trên SERVER A:
# - chromadb, langchain, openai, anthropic (→ để cho SERVER C)
# - ccxt, python-binance (→ để cho SERVER B)
# - playwright, matplotlib, pandas, numpy (→ quá nặng)
# - torch, transformers, tensorflow (→ cần GPU)

# Kiểm tra RAM sau khi cài
free -m
# → Used: ~120MB (OS + Python) — còn ~1900MB cho hoạt động
```

---

## 8. Mô Hình AI Core — SERVER C (8U16G)

### 8.1 Tổng Quan Kiến Trúc

> [!IMPORTANT]
> SERVER C là **bộ não** của toàn hệ thống — nơi tập trung mọi logic phân tích, AI, và quyết định giao dịch.
> Với 8 CPU / 16GB RAM, đây là server mạnh nhất và phải được tận dụng tối đa.

```
┌────────────────────────────────────────────────────────────────┐
│                SERVER C — AI CORE (8U16G)                      │
│                  Debian 12 Standard                            │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │           ChromaDB Server (:8000)                      │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │    │
│  │  │ SEPA Rules   │  │ Trading Book │  │ Market Data  │  │    │
│  │  │ Collection   │  │ Collection   │  │ Collection   │  │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │    │
│  │  RAM: ~2-4 GB (tuỳ dữ liệu)                           │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │           RAG Analyzer Worker                          │    │
│  │                                                        │    │
│  │  Poll A ──► ChromaDB Query ──► LLM Call ──► Sizing    │    │
│  │     │           │                 │            │       │    │
│  │     │      RAG Chunks       Claude/Gemini   Position   │    │
│  │     │                        (2s timeout)    Size      │    │
│  │     │                                          │       │    │
│  │     │         Circuit Breaker ──► Algorithmic  │       │    │
│  │     │         (Fallback)         Minervini     │       │    │
│  │     │                                          │       │    │
│  │     └────────── Forward to SERVER B ◄──────────┘       │    │
│  │                 POST /api/execute-trade                 │    │
│  │  RAM: ~500MB - 1GB                                     │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │           Monitoring Hub                               │    │
│  │  • Liveness Monitor (check A + B mỗi 5 phút)          │    │
│  │  • Clock Drift Monitor (NTP check mỗi 5 phút)         │    │
│  │  • Disk Space Monitor (check mỗi 30 phút)             │    │
│  │  RAM: ~50MB                                            │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │           Backtesting Engine (V3 — Future)             │    │
│  │  • Historical data processing                          │    │
│  │  • Strategy optimization                               │    │
│  │  • Performance analytics                               │    │
│  │  RAM: ~2-4 GB (khi chạy)                               │    │
│  └────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────┘
```

### 8.2 RAM Budget SERVER C (16GB)

```
┌──────────────────────────────────────────────────┐
│         RAM BUDGET — SERVER C (16GB)             │
│                                                  │
│  Total RAM:          16384 MB                    │
│  ────────────────────────────────                │
│  Debian 12:           -100 MB (OS)               │
│  SSH + Tailscale:      -35 MB                    │
│  Docker Engine:        -80 MB                    │
│  ────────────────────────────────                │
│  Tổng hạ tầng:        -215 MB                    │
│  ════════════════════════════════                │
│  CÒN LẠI:           ~16169 MB                   │
│    ├── ChromaDB:         ~3000 MB (100K docs)    │
│    ├── Analyzer Worker:   ~800 MB                │
│    ├── Monitoring Hub:     ~50 MB                │
│    ├── Backtesting (V3):  ~4000 MB               │
│    └── Free Buffer:      ~8319 MB (50%+ free!)   │
│                                                  │
│  ✅ Rất thoải mái — có thể mở rộng thêm         │
│     workers mà không lo RAM                      │
└──────────────────────────────────────────────────┘
```

### 8.3 Packages Cần Cài Trên SERVER C

```bash
# ═══════════════════════════════════════════════════════
# SERVER C: Full AI Stack
# ═══════════════════════════════════════════════════════

# Python packages cho RAG + AI Analyzer
pip3 install \
    fastapi==0.115.* \
    uvicorn[standard]==0.34.* \
    pydantic==2.* \
    httpx==0.28.* \
    apscheduler==3.10.* \
    chromadb==0.6.* \
    openai==1.* \
    anthropic==0.40.* \
    google-generativeai==0.8.* \
    langchain==0.3.* \
    langchain-community==0.3.* \
    psutil==6.* \
    aiosqlite==0.21.*

# Packages cho Backtesting (V3)
pip3 install \
    pandas==2.* \
    numpy==2.* \
    ta-lib \
    matplotlib==3.* \
    scipy==1.*

# Kiểm tra ChromaDB hoạt động
python3 -c "import chromadb; print(chromadb.__version__)"
```

### 8.4 ChromaDB Server Setup

```bash
# ═══════════════════════════════════════════════════════
# ChromaDB — chạy như standalone server trên cổng 8000
# ═══════════════════════════════════════════════════════

# Cách 1: Docker (Khuyến nghị — isolation tốt hơn)
docker run -d \
    --name chromadb \
    --restart unless-stopped \
    -p 127.0.0.1:8000:8000 \
    -v /opt/trading-bot/chroma-data:/chroma/chroma \
    -e IS_PERSISTENT=TRUE \
    -e ANONYMIZED_TELEMETRY=FALSE \
    chromadb/chroma:latest

# Cách 2: Native Python (nếu không dùng Docker)
chroma run --host 0.0.0.0 --port 8000 --path /opt/trading-bot/chroma-data

# Verify
curl http://localhost:8000/api/v1/heartbeat
# → {"nanosecond heartbeat": 1234567890}

# Kiểm tra collections
curl http://localhost:8000/api/v1/collections
```

### 8.5 Monitoring Hub (Chạy trên SERVER C)

SERVER C là nơi tốt nhất để chạy monitoring vì có dư tài nguyên:

| Monitor | Interval | Chức năng |
|---------|----------|----------|
| `liveness_monitor.py` | 5 phút | Check health SERVER A + B |
| `ntp_monitor.py` | 5 phút | Check clock drift 3 server |
| `disk_monitor.py` | 30 phút | Check disk usage local |
| Circuit Breaker logs | Real-time | Track LLM availability |

> Xem chi tiết implementation trong [V2 Operational Hardening](file:///C:/Users/pesil/.gemini/antigravity/brain/e2cbb527-ef1a-4f70-b7b7-baf5e1dcd06a/v2_operational_hardening.md)

---

## 9. Mô Hình Execution Vault — SERVER B (Windows)

### 9.1 Tổng Quan Kiến Trúc

> [!CAUTION]
> SERVER B là **hầm trú ẩn** chứa API keys và thực thi giao dịch thật.
> Server này **KHÔNG BAO GIỜ** tiếp xúc Internet trực tiếp.
> Chỉ accessible qua Tailscale VPN từ SERVER C.

```
┌────────────────────────────────────────────────────────────────┐
│            SERVER B — EXECUTION VAULT (Windows 2U4G)           │
│               Windows Server 2022                              │
│                                                                │
│  ┌──────────────────────────────────────────────┐              │
│  │  Windows Firewall                            │              │
│  │  ✅ Allow: 100.0.0.0/8:5002 (Tailscale only) │              │
│  │  ❌ Block: 0.0.0.0/0:5002 (Internet)          │              │
│  └──────────────────┬───────────────────────────┘              │
│                     │                                          │
│                     ▼                                          │
│  ┌────────────────────────────────────────────────────────┐    │
│  │         Execution Server (FastAPI — Port 5002)         │    │
│  │                                                        │    │
│  │  POST /api/execute-trade                               │    │
│  │    1. Verify X-Server-B-Secret (constant-time)         │    │
│  │    2. Validate payload (symbol, action, qty, sl, tp)   │    │
│  │    3. Call TradeEngine → Exchange API                   │    │
│  │    4. Log to trades.db                                  │    │
│  │    5. Send Telegram notification                        │    │
│  │    6. Return {order_id, fill_price, status}             │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │         TradeEngine                                    │    │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐               │    │
│  │  │ Binance │  │  Bybit  │  │  Weex   │               │    │
│  │  │  CCXT   │  │  CCXT   │  │  SDK    │               │    │
│  │  └─────────┘  └─────────┘  └─────────┘               │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │         Secure Credential Storage                      │    │
│  │  • Windows Credential Manager (API Keys)               │    │
│  │  • DPAPI encryption (at-rest)                          │    │
│  │  • Windows Defender (real-time scan)                    │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐    │
│  │         TradingView Desktop (V3 — CDP Automation)      │    │
│  │  • Electron app chạy local                             │    │
│  │  • Chrome DevTools Protocol cho chart interaction      │    │
│  │  • Screenshot, alert management                        │    │
│  └────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────┘
```

### 9.2 RAM Budget SERVER B (4GB)

```
┌──────────────────────────────────────────────────┐
│         RAM BUDGET — SERVER B (4GB Windows)      │
│                                                  │
│  Total RAM:           4096 MB                    │
│  ────────────────────────────────                │
│  Windows Server 2022:  -800 MB (OS baseline)     │
│  Windows Defender:     -150 MB                   │
│  Tailscale:             -40 MB                   │
│  ────────────────────────────────                │
│  Tổng hạ tầng:        -990 MB                    │
│  ════════════════════════════════                │
│  CÒN LẠI:            ~3106 MB                   │
│    ├── Execution Server:  ~100 MB                │
│    ├── TradeEngine:       ~150 MB                │
│    ├── TradingView App:   ~500 MB (V3)           │
│    ├── SQLite (trades):    ~50 MB                │
│    └── Free Buffer:      ~2306 MB (56% free)     │
│                                                  │
│  ✅ Đủ cho execution + TradingView Desktop       │
└──────────────────────────────────────────────────┘
```

### 9.3 Tại Sao Windows Server Cho Execution Vault?

| Lý do | Giải thích |
|-------|------------|
| 🖥️ **TradingView Desktop** | Electron app chạy trên Windows — cần cho CDP automation (V3) |
| 📦 **Exchange SDK** | Một số SDK sàn (đặc biệt Weex) có DLL dependencies chỉ chạy trên Windows |
| 🔐 **Credential Manager** | API Keys lưu trong Windows Credential Manager — mã hóa DPAPI, an toàn hơn `.env` plaintext |
| 🛡️ **Biệt lập bảo mật** | API Keys **KHÔNG BAO GIỜ** lưu trên Linux server tiếp xúc Internet |
| 🦠 **Windows Defender** | Real-time protection cho file chứa credentials |
| 🖱️ **RDP access** | Dễ troubleshoot, debug trực tiếp visual khi cần |

### 9.4 Cài Đặt Ban Đầu

```powershell
# ═══════════════════════════════════════════════════════
# SERVER B: Windows Server 2022 — Execution Vault
# ═══════════════════════════════════════════════════════

# 1. Windows Update
Install-Module PSWindowsUpdate -Force
Get-WindowsUpdate -Install -AcceptAll

# 2. Cài Python 3.11+
# Tải từ: https://www.python.org/downloads/
# ☑️ Tick "Add Python to PATH"
python --version
# → Python 3.11.x

# 3. Cài Python packages
pip install fastapi uvicorn[standard] ccxt httpx pydantic psutil

# 4. Cài Tailscale
# Tải từ: https://tailscale.com/download/windows
# Đăng nhập → Verify IP 100.x.x.2

# 5. NTP đồng bộ
w32tm /config /manualpeerlist:"time.google.com,0x9" /syncfromflags:manual /reliable:YES /update
Restart-Service w32time
w32tm /resync /force
```

### 9.5 Bảo Mật Nâng Cao

```powershell
# ═══════════════════════════════════════════════════════
# BẢO MẬT EXECUTION VAULT — MULTI-LAYER
# ═══════════════════════════════════════════════════════

# ── Layer 1: Windows Firewall ──
# Chỉ cho phép Tailscale subnet
New-NetFirewallRule -DisplayName "Trading Bot - Tailscale Only" `
    -Direction Inbound -Protocol TCP -LocalPort 5002 `
    -RemoteAddress 100.0.0.0/8 -Action Allow

# Block tất cả kết nối khác đến port 5002
New-NetFirewallRule -DisplayName "Trading Bot - Block WAN" `
    -Direction Inbound -Protocol TCP -LocalPort 5002 `
    -Action Block

# ── Layer 2: Windows Credential Manager ──
# Lưu API keys an toàn (DPAPI encrypted)
cmdkey /add:BINANCE_API_KEY /user:api_key /pass:<YOUR_BINANCE_KEY>
cmdkey /add:BINANCE_API_SECRET /user:api_secret /pass:<YOUR_BINANCE_SECRET>
cmdkey /add:BYBIT_API_KEY /user:api_key /pass:<YOUR_BYBIT_KEY>
cmdkey /add:BYBIT_API_SECRET /user:api_secret /pass:<YOUR_BYBIT_SECRET>
cmdkey /add:TELEGRAM_BOT_TOKEN /user:bot_token /pass:<YOUR_TOKEN>

# Đọc credentials trong Python:
# import keyring
# api_key = keyring.get_password("BINANCE_API_KEY", "api_key")

# ── Layer 3: Execution Server chạy như Windows Service ──
# Auto-start khi boot, tự restart khi crash
pip install pywin32 winsw

# Tạo service wrapper (winsw)
# Xem file: deploy/execution-service.xml

# ── Layer 4: Audit logging ──
# Bật Windows Security Audit cho folder chứa bot
auditpol /set /category:"Object Access" /success:enable /failure:enable
```

### 9.6 Network Isolation Diagram

```
         INTERNET
            │
     ╔══════╧══════╗
     ║ Cloudflare  ║
     ║   Edge      ║
     ╚══════╤══════╝
            │ Tunnel
            ▼
    ┌───────────────┐
    │  SERVER A     │
    │  (Gateway)    │──── Tailscale 100.x.x.1
    └───────────────┘           │
                                │
            ┌───────────────────┤
            │   Tailscale VPN   │
            │   (WireGuard)     │
            ▼                   ▼
    ┌───────────────┐   ┌───────────────┐
    │  SERVER C     │   │  SERVER B     │
    │  (AI Core)    │──▶│  (Execution)  │
    │  100.x.x.3   │   │  100.x.x.2   │
    └───────────────┘   └───────────────┘
           │                     │
     Chỉ Tailscale         Chỉ Tailscale
     Không WAN             Không WAN
     Không public IP       Không public IP

    🔐 SERVER B: API Keys chỉ tồn tại ở đây
    🔐 SERVER C: Chỉ gửi payload đã validate
    🔐 SERVER A: Không biết API keys
```

---

## 10. Deployment Commands

### 10.1 SERVER A — Gateway

```bash
# Clone project (chỉ cần thư mục vbs/)
mkdir -p /opt/trading-bot
cd /opt/trading-bot

# Copy vbs/ folder từ repo
# scp -r vbs/ botuser@server-a:/opt/trading-bot/

# Tạo .env từ template
cp vbs/.env.example vbs/.env
# → Sửa BUFFER_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# Sinh BUFFER_SECRET ngẫu nhiên
python3 -c "import secrets; print(secrets.token_hex(32))"
# → Copy vào .env

# Deploy với Docker Compose
docker compose -f deploy/docker-compose.server-a.yml up -d

# Kiểm tra logs
docker compose -f deploy/docker-compose.server-a.yml logs -f

# Test health
curl http://localhost:5000/health
```

### 10.2 SERVER C — AI Core

```bash
# Clone full project
mkdir -p /opt/trading-bot
cd /opt/trading-bot
git clone <repo_url> .

# Tạo .env
cp server/.env.example server/.env
# → Cấu hình:
#   CHROMA_REMOTE=false (local trên chính C)
#   VPS_BUFFER_URL=http://100.x.x.1:5000
#   VPS_BUFFER_SECRET=<same as BUFFER_SECRET on A>
#   SERVER_B_EXECUTE_URL=http://100.x.x.2:5002/api/execute-trade
#   SERVER_B_SECRET=<generate new secret>

# Deploy
docker compose -f deploy/docker-compose.server-c.yml up -d

# Kiểm tra ChromaDB
curl http://localhost:8000/api/v1/heartbeat

# Kiểm tra Analyzer logs
docker compose -f deploy/docker-compose.server-c.yml logs -f analyzer
```

### 10.3 SERVER B — Execution Vault

```powershell
# Clone/copy project
cd C:\trading-bot

# Tạo .env
copy server\.env.example server\.env
# → Cấu hình:
#   SERVER_B_SECRET=<same secret configured on SERVER C>
#   DEFAULT_EXCHANGE=binance
#   TELEGRAM_BOT_TOKEN=<your_token>
#   TELEGRAM_CHAT_ID=<your_chat>

# Chạy trực tiếp (dev/test)
cd server
python execution_server.py

# Hoặc chạy như Windows Service (production)
python execution_server.py --install-service
Start-Service TradingBotExecution
```

---

## 11. Checklist Hoàn Tất

### 11.1 SERVER A — Gateway (Debian 12 Minimal)

| # | Hạng mục | Trạng thái |
|---|----------|-----------|
| 1 | Debian 12 Minimal đã cài | ☑ |
| 2 | `apt update && apt upgrade` | ☑ |
| 3 | User `botuser` tạo, không dùng root | ☑ |
| 4 | SSH key-only auth, PasswordAuthentication no | ☑ |
| 5 | Fail2ban cấu hình và chạy | ☑ |
| 6 | UFW firewall bật, chỉ allow SSH + Tailscale | ☑ |
| 7 | NTP chrony đồng bộ (drift < 50ms) | ☑ |
| 8 | Swap 2GB tạo | ☑ |
| 9 | Docker CE + Compose V2 cài | ☑ |
| 10 | Docker log limit (10m × 3) cấu hình | ☑ |
| 11 | Tailscale VPN kết nối, IP 100.x.x.1 | ☑ |
| 12 | Cloudflare Tunnel → bot.yourdomain.com | ☑ |
| 13 | VBS container chạy, `/health` trả healthy | ☑ |
| 14 | BUFFER_SECRET sinh ngẫu nhiên (≥32 bytes) | ☑ |
| 15 | Telegram notification test thành công | ☑ |

### 11.2 SERVER C — AI Core (Debian 12)

| # | Hạng mục | Trạng thái |
|---|----------|-----------|
| 1 | Debian 12 đã cài (Standard OK cho 8U16G) | ☑ |
| 2 | User `botuser`, SSH hardened | ☑ |
| 3 | NTP chrony đồng bộ | ☑ |
| 4 | Docker CE + Compose V2 | ☑ |
| 5 | Tailscale VPN kết nối, IP 100.x.x.3 | ☑ |
| 6 | ChromaDB container chạy (:8000) | ☑ |
| 7 | Analyzer Worker container chạy | ☑ |
| 8 | Kết nối đến SERVER A `/consume` thành công | ☑ |
| 9 | Kết nối đến SERVER B `/api/execute-trade` thành công | ☑ |
| 10 | Liveness monitor cấu hình (check A + B) | ☑ |
| 11 | Disk monitor cấu hình | ☑ |
| 12 | Circuit Breaker LLM cấu hình | ☑ |

### 11.3 SERVER B — Execution Vault (Windows Server)

| # | Hạng mục | Trạng thái |
|---|----------|-----------|
| 1 | Windows Server 2022 cập nhật | ☑ |
| 2 | Python 3.11+ cài | ☑ |
| 3 | NTP w32time đồng bộ | ☑ |
| 4 | Tailscale VPN kết nối, IP 100.x.x.2 | ☑ |
| 5 | Firewall: port 5002 chỉ allow 100.0.0.0/8 | ☑ |
| 6 | Execution Server chạy | ☑ |
| 7 | SERVER_B_SECRET cấu hình | ☑ |
| 8 | Exchange API Keys cấu hình (Binance/Bybit/Weex) | ☑ |
| 9 | Test: POST `/api/execute-trade` từ SERVER C | ☑ |
| 10 | Telegram notification test | ☑ |

### 11.4 Cross-Server Verification

| # | Test | Trạng thái |
|---|------|-----------|
| 1 | SERVER C `ping` SERVER A qua Tailscale | ☑ |
| 2 | SERVER C `ping` SERVER B qua Tailscale | ☑ |
| 3 | Clock drift < 50ms giữa cả 3 server | ☑ |
| 4 | E2E: TradingView → A (ingest) → C (analyze) → B (execute) | ☑ |
| 5 | Telegram nhận đủ notification từ cả 3 server | ☑ |
| 6 | UptimeRobot/Cloudflare monitor đang active | ☑ |
