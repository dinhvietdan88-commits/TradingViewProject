# 🚀 SERVER A — SETUP PROMPT
## Gateway VBS + Cloudflare Tunnel | Debian 12 Minimal (1U2G)

> **Mục tiêu:** Từ VPS trắng → Gateway production chạy 24/7 trong ~15 phút  
> **RAM target:** ~200MB tổng (OS + VBS + Tunnel + Tailscale)  
> **Vai trò:** Isolated Ingress Node — chỉ nhận webhook → lưu queue → chờ SERVER C consume

---

## ⚡ BƯỚC 0: Thông Tin Cần Chuẩn Bị Trước

```
┌──────────────────────────────────────────────────────────┐
│  CHECKLIST TRƯỚC KHI BẮT ĐẦU                           │
│                                                          │
│  ☐ VPS đã mua (Debian 12 Minimal, 1CPU/2GB RAM)        │
│  ☐ IP công khai VPS: ___.___.___.___ (SSH access)       │
│  ☐ Root password hoặc SSH key                           │
│  ☐ Domain đã trỏ về Cloudflare (bot.yourdomain.com)    │
│  ☐ Tài khoản Cloudflare (đã login)                     │
│  ☐ Tài khoản Tailscale (đã tạo)                        │
│  ☐ Telegram Bot Token + Chat ID (cho notifications)    │
└──────────────────────────────────────────────────────────┘
```

---

## ⚡ BƯỚC 1: SSH Vào VPS & Cập Nhật

```bash
# SSH vào VPS
ssh root@<VPS_IP>

# Cập nhật hệ thống
apt update && apt upgrade -y

# Cài tools cơ bản
apt install -y curl wget git htop tmux jq \
    ca-certificates gnupg lsb-release \
    python3 python3-pip python3-venv sudo

# Verify
python3 --version
# → Python 3.11.x ✅
```

---

## ⚡ BƯỚC 2: Tạo User + SSH Hardening

```bash
# Tạo user (KHÔNG chạy bot bằng root!)
useradd -m -s /bin/bash botuser
passwd botuser
usermod -aG sudo botuser

# SSH Hardening
cat > /etc/ssh/sshd_config.d/hardened.conf << 'EOF'
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AllowUsers botuser
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
X11Forwarding no
EOF

# ⚠️ TRƯỚC KHI RESTART: Copy SSH key cho botuser & thêm Deploy Key cho CI/CD Github Actions
mkdir -p /home/botuser/.ssh
cp ~/.ssh/authorized_keys /home/botuser/.ssh/
# Thêm public key deploy để Github Actions có thể SSH vào deploy
echo "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEMVNH4cvW86zP84BLyQkOxW9GATWDQovGFn0imOVPLv" >> /home/botuser/.ssh/authorized_keys
chown -R botuser:botuser /home/botuser/.ssh
chmod 700 /home/botuser/.ssh
chmod 600 /home/botuser/.ssh/authorized_keys

# Restart SSH
systemctl restart sshd

# ⚠️ MỞ TERMINAL MỚI TEST: ssh botuser@<VPS_IP>
# Chỉ đóng terminal cũ sau khi confirm login thành công!
```

---

## ⚡ BƯỚC 3: Timezone + NTP + Swap

```bash
# Chuyển sang botuser
su - botuser

# Timezone Việt Nam
sudo timedatectl set-timezone Asia/Ho_Chi_Minh

# NTP (chrony)
sudo apt install -y chrony
sudo tee /etc/chrony/chrony.conf << 'EOF'
server time.google.com iburst prefer
server time.cloudflare.com iburst
server 0.pool.ntp.org iburst
makestep 1.0 3
driftfile /var/lib/chrony/chrony.drift
maxdistance 0.1
EOF
sudo systemctl enable --now chrony

# Verify NTP
chronyc tracking | grep "System time"
# → System time: 0.00000xxxx seconds ✅

# Swap 2GB (bảo hiểm OOM)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

---

## ⚡ BƯỚC 4: Firewall + Fail2Ban

```bash
# Fail2Ban
sudo apt install -y fail2ban
sudo tee /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 3
[sshd]
enabled = true
EOF
sudo systemctl enable --now fail2ban

# UFW Firewall
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow in on tailscale0
sudo ufw --force enable
sudo ufw status
```

---

## ⚡ BƯỚC 5: Docker

```bash
# Docker GPG + Repo
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) \
    signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/debian \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker botuser
newgrp docker

# Giới hạn log Docker (tránh đầy đĩa)
sudo tee /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"},
  "storage-driver": "overlay2"
}
EOF
sudo systemctl restart docker

# Test
docker run --rm hello-world
```

---

## ⚡ BƯỚC 6: Tailscale VPN

```bash
# Cài Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# → Mở URL hiện trên màn hình để đăng nhập
# → Approve device trong Tailscale Admin Console

# Lấy IP nội bộ
tailscale ip -4
# → 100.x.x.1 ← GHI LẠI IP NÀY

# Đặt hostname (tuỳ chọn)
sudo tailscale set --hostname=server-a-gateway
```

---

## ⚡ BƯỚC 7: Cloudflare Tunnel

```bash
# Cài cloudflared
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | \
    sudo tee /usr/share/keyrings/cloudflare-main.gpg > /dev/null

echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] \
    https://pkg.cloudflare.com/cloudflared bookworm main' | \
    sudo tee /etc/apt/sources.list.d/cloudflared.list

sudo apt update && sudo apt install -y cloudflared

# Đăng nhập Cloudflare
cloudflared tunnel login
# → Mở URL → chọn domain → Authorize

# Tạo tunnel
cloudflared tunnel create trading-gateway
# → Ghi lại TUNNEL_ID từ output

# Cấu hình
sudo mkdir -p /etc/cloudflared
sudo tee /etc/cloudflared/config.yml << 'EOF'
tunnel: <THAY_TUNNEL_ID_VÀO_ĐÂY>
credentials-file: /home/botuser/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: bot.yourdomain.com
    service: http://localhost:5000
  - hostname: health.yourdomain.com
    service: http://localhost:5000/health
  - service: http_status:404
EOF

# Route DNS
cloudflared tunnel route dns trading-gateway bot.yourdomain.com

# Cài service auto-start
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
# → Active: active (running) ✅
```

---

## ⚡ BƯỚC 8: Deploy VBS

```bash
# Tạo thư mục project
mkdir -p /opt/trading-bot
cd /opt/trading-bot

# Clone hoặc copy code
# Option A: Git clone
git clone <REPO_URL> .

# Option B: SCP từ local
# scp -r vbs/ deploy/ botuser@<VPS_IP>:/opt/trading-bot/

# Sinh BUFFER_SECRET
BUFFER_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
echo "BUFFER_SECRET=$BUFFER_SECRET"
# → GHI LẠI SECRET NÀY (cần dùng cho SERVER C)

# Tạo .env
cat > /opt/trading-bot/vbs/.env << EOF
# ═══ VBS Gateway Config ═══
BUFFER_SECRET=$BUFFER_SECRET
VBS_PORT=5000
VBS_HOST=0.0.0.0

# ═══ SQLite ═══
VBS_DB_PATH=/data/vbs_queue.db

# ═══ Cleanup Scheduler ═══
SIGNAL_EXPIRY_HOURS=24

# ═══ Telegram Notifications ═══
TELEGRAM_BOT_TOKEN=<THAY_TOKEN>
TELEGRAM_CHAT_ID=<THAY_CHAT_ID>
EOF

# Deploy với Docker Compose
docker compose -f deploy/docker-compose.server-a.yml up -d

# Kiểm tra
docker compose -f deploy/docker-compose.server-a.yml logs -f
# → Uvicorn running on http://0.0.0.0:5000 ✅
```

---

## ⚡ BƯỚC 9: Verify

```bash
# ── Test 1: Health Check Local ──
curl http://localhost:5000/health
# → {"status": "healthy", "queue_size": 0, ...} ✅

# ── Test 2: Health Check qua Cloudflare ──
curl https://bot.yourdomain.com/health
# → {"status": "healthy", ...} ✅

# ── Test 3: Ingest Test Signal ──
curl -X POST https://bot.yourdomain.com/ingest \
    -H "Content-Type: application/json" \
    -H "X-Buffer-Secret: $BUFFER_SECRET" \
    -d '{
        "source": "indicator",
        "symbol": "BTCUSDT.P",
        "action": "BUY",
        "indicator_name": "MIS_v1",
        "timeframe": "4h"
    }'
# → {"id": "...", "status": "PENDING"} ✅

# ── Test 4: Consume (giả lập SERVER C) ──
curl "http://localhost:5000/consume?consumer_id=test&secret=$BUFFER_SECRET"
# → [{"id": "...", "symbol": "BTCUSDT.P", ...}] ✅

# ── Test 5: Tailscale ping từ SERVER C ──
# Trên SERVER C chạy: tailscale ping server-a-gateway

# ── Test 6: RAM Check ──
free -m
# → Used: ~180-220MB ✅ (target: ~200MB)

# ── Test 7: Disk Check ──
df -h /
# → Used: ~2-3GB / 20GB ✅
```

---

## ⚡ BƯỚC 10: Monitoring Setup

```bash
# ── Log Rotation (tránh đầy đĩa) ──
sudo tee /etc/logrotate.d/trading-bot << 'EOF'
/opt/trading-bot/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    maxsize 10M
}
EOF

# ── UptimeRobot / Cloudflare Monitor ──
# Vào https://uptimerobot.com → Add Monitor:
#   Type: HTTP(s)
#   URL: https://health.yourdomain.com
#   Interval: 5 min
#   Alert: Telegram / Email

# ── Kiểm tra service auto-restart sau reboot ──
sudo reboot
# → Sau khi reboot, SSH lại và verify:
docker ps
# → VBS container running ✅
sudo systemctl status cloudflared
# → active (running) ✅
```

---

## 📊 RAM Budget Cuối Cùng

```
┌──────────────────────────────────────────────────┐
│       SERVER A — RAM THỰC TẾ SAU SETUP           │
│                                                  │
│  Debian 12 Minimal:    ~60 MB                    │
│  SSH daemon:            ~5 MB                    │
│  chrony (NTP):          ~3 MB                    │
│  fail2ban:              ~8 MB                    │
│  Tailscale:            ~30 MB                    │
│  cloudflared:          ~25 MB                    │
│  Docker Engine:        ~80 MB                    │
│  ──────────────────────────────                  │
│  Hạ tầng:             ~211 MB                    │
│                                                  │
│  VBS Container:                                  │
│    FastAPI/Uvicorn:    ~60 MB                    │
│    SQLite (WAL):       ~10 MB                    │
│    APScheduler:        ~10 MB                    │
│  ──────────────────────────────                  │
│  VBS:                  ~80 MB                    │
│  ══════════════════════════════                  │
│  TỔNG SỬ DỤNG:       ~291 MB                    │
│  CÒN TRỐNG:         ~1757 MB (86% free!)        │
│                                                  │
│  ✅ Cực kỳ nhàn hạ cho VPS 2GB                  │
└──────────────────────────────────────────────────┘
```

---

## 🔑 Secrets Cần Ghi Lại

```
┌──────────────────────────────────────────────────┐
│  GHI LẠI CÁC GIÁ TRỊ NÀY (cần cho SERVER C)   │
│                                                  │
│  BUFFER_SECRET: ________________________________ │
│  Tailscale IP:  100.___.___.___                  │
│  Tunnel Domain: bot.____________________.com     │
│  Health Domain: health.____________________.com  │
│  VBS Port:      5000                             │
│                                                  │
│  ⚠️ LƯU Ở NƠI AN TOÀN — KHÔNG ĐỂ TRÊN SERVER  │
└──────────────────────────────────────────────────┘
```

---

## ❌ KHÔNG LÀM Trên SERVER A

| Hành động | Lý do |
|-----------|-------|
| ❌ Cài chromadb, langchain, openai | Quá nặng, không cần — SERVER C lo |
| ❌ Cài ccxt, python-binance | API keys không được lưu ở đây |
| ❌ Cài playwright, matplotlib | Tốn RAM vô ích |
| ❌ Lưu Exchange API keys | Bảo mật — chỉ SERVER B có |
| ❌ Chạy bot trading trực tiếp | Gateway CHỈ nhận + queue |
| ❌ Mở port 5000 ra Internet | Cloudflare Tunnel lo — UFW block |
| ❌ Chạy bằng root | Luôn dùng `botuser` |
