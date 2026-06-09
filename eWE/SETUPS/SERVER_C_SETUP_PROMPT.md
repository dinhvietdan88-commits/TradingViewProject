# 🧠 SERVER C — SETUP PROMPT
## AI Core: ChromaDB + RAG Analyzer + Monitoring Hub | Debian 12 (8U16G)

> **Mục tiêu:** Từ VPS trắng → AI Core production chạy 24/7 trong ~20 phút  
> **RAM target:** ~4-5GB active (còn ~11GB free buffer)  
> **Vai trò:** Bộ não hệ thống — poll signals từ A → RAG + AI phân tích → forward lệnh sang B  
> **Prerequisite:** SERVER A đã chạy, có BUFFER_SECRET và Tailscale IP

---

## ⚡ BƯỚC 0: Thông Tin Cần Chuẩn Bị Trước

```
┌──────────────────────────────────────────────────────────┐
│  CHECKLIST TRƯỚC KHI BẮT ĐẦU                           │
│                                                          │
│  ☐ VPS đã mua (Debian 12, 8CPU/16GB RAM)               │
│  ☐ IP công khai VPS: ___.___.___.___ (SSH access)       │
│  ☐ Root password hoặc SSH key                           │
│  ☐ Tài khoản Tailscale (đã tạo, cùng network với A)    │
│                                                          │
│  TỪ SERVER A (ghi lại từ bước setup A):                 │
│  ☐ BUFFER_SECRET: ________________________________       │
│  ☐ Tailscale IP Server A: 100.___.___.___                │
│  ☐ VBS Port: 5000                                        │
│                                                          │
│  CHO SERVER B (tạo mới):                                │
│  ☐ SERVER_B_SECRET: _____________ (sinh ở Bước 8)       │
│  ☐ Tailscale IP Server B: 100.___.___.___                │
│                                                          │
│  API KEYS (cho AI):                                      │
│  ☐ Claude API Key (Anthropic)                            │
│  ☐ Gemini API Key (Google) — backup                      │
│  ☐ Telegram Bot Token + Chat ID                          │
└──────────────────────────────────────────────────────────┘
```

---

## ⚡ BƯỚC 1: SSH Vào VPS & Cập Nhật

### Option A: Debian 12 (Mặc định)
```bash
# SSH vào VPS
ssh root@<VPS_IP>

# Cập nhật hệ thống
apt update && apt upgrade -y

# Cài tools cơ bản + build dependencies cho ChromaDB
apt install -y curl wget git htop tmux jq \
    ca-certificates gnupg lsb-release \
    python3 python3-pip python3-venv sudo \
    build-essential python3-dev \
    libffi-dev libssl-dev

# Verify
python3 --version
# → Python 3.11.x ✅
```

### Option B: Oracle Linux (RHEL-based)
```bash
# SSH vào VPS
ssh root@<VPS_IP>

# Cập nhật hệ thống và cài đặt EPEL + Development Tools
sudo dnf upgrade -y
sudo dnf install -y epel-release
sudo dnf groupinstall -y "Development Tools"

# Cài tools cơ bản + build dependencies cho ChromaDB
sudo dnf install -y curl wget git htop tmux jq \
    python3 python3-pip python3-devel sudo \
    libffi-devel openssl-devel

# Verify
python3 --version
# → Python 3.x ✅
```

---

## ⚡ BƯỚC 2: Tạo User + SSH Hardening

```bash
# Tạo user
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

# Copy SSH key cho botuser & thêm Deploy Key cho CI/CD Github Actions
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
```

---

## ⚡ BƯỚC 3: Timezone + NTP + Swap

```bash
su - botuser

# Timezone Việt Nam (Chung cho cả 2 OS)
sudo timedatectl set-timezone Asia/Ho_Chi_Minh
```

### 3.1 Cấu hình NTP (Đồng bộ thời gian với Server A)

#### Dành cho Debian 12:
```bash
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
```

#### Dành cho Oracle Linux:
```bash
sudo dnf install -y chrony
sudo tee /etc/chrony.conf << 'EOF'
server time.google.com iburst prefer
server time.cloudflare.com iburst
server 0.pool.ntp.org iburst
makestep 1.0 3
driftfile /var/lib/chrony/chrony.drift
maxdistance 0.1
EOF
sudo systemctl enable --now chronyd
```

#### Xác thực NTP:
```bash
chronyc tracking | grep "System time"
# → System time: 0.00000xxxx seconds ✅
```

### 3.2 Thiết lập Swap 4GB (Bảo hiểm OOM)
```bash
# Swap 4GB (Chung cho cả 2 OS)
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

---

## ⚡ BƯỚC 4: Firewall

#### Fail2Ban (Chung cho cả 2 OS):
```bash
# Dành cho Debian:
# sudo apt install -y fail2ban
# Dành cho Oracle Linux:
# sudo dnf install -y fail2ban
sudo systemctl enable --now fail2ban
```

#### Dành cho Debian 12 (UFW):
```bash
# UFW Firewall — SERVER C KHÔNG expose port ra Internet
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow in on tailscale0
# ChromaDB chỉ lắng nghe localhost (không cần rule)
sudo ufw --force enable
sudo ufw status
```

#### Dành cho Oracle Linux (Firewalld):
```bash
# Firewalld — SERVER C KHÔNG expose port ra Internet
sudo dnf install -y firewalld
sudo systemctl enable --now firewalld

# Cho phép SSH và giao diện ảo Tailscale
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --zone=trusted --add-interface=tailscale0
sudo firewall-cmd --reload
sudo firewall-cmd --state
```

---

## ⚡ BƯỚC 5: Docker

#### Dành cho Debian 12:
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
```

#### Dành cho Oracle Linux:
```bash
# Thêm Docker Repository
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# Cài đặt Docker CE + Compose
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

#### Cấu hình User + Logs (Chung cho cả 2 OS):
```bash
sudo usermod -aG docker botuser
newgrp docker

# Giới hạn log Docker
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "5"},
  "storage-driver": "overlay2"
}
EOF
sudo systemctl restart docker
docker run --rm hello-world
```

---

## ⚡ BƯỚC 6: Tailscale VPN

```bash
# Cài Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# → Mở URL đăng nhập → Approve device

# Lấy IP nội bộ
tailscale ip -4
# → 100.x.x.3 ← GHI LẠI IP NÀY

# Đặt hostname
sudo tailscale set --hostname=server-c-ai-core

# ── Test kết nối đến SERVER A ──
tailscale ping server-a-gateway
# → pong from server-a-gateway ✅

curl http://100.x.x.1:5000/health
# → {"status": "healthy", ...} ✅
```

---

## ⚡ BƯỚC 7: ChromaDB Server

```bash
# Tạo thư mục data
sudo mkdir -p /opt/trading-bot/chroma-data
sudo chown botuser:botuser /opt/trading-bot/chroma-data

# Chạy ChromaDB container (lắng nghe localhost only)
docker run -d \
    --name chromadb \
    --restart unless-stopped \
    -p 127.0.0.1:8000:8000 \
    -v /opt/trading-bot/chroma-data:/chroma/chroma \
    -e IS_PERSISTENT=TRUE \
    -e ANONYMIZED_TELEMETRY=FALSE \
    chromadb/chroma:latest

# Verify
docker ps | grep chromadb
# → chromadb ... Up ... 127.0.0.1:8000->8000/tcp ✅

curl http://localhost:8000/api/v1/heartbeat
# → {"nanosecond heartbeat": 1234567890} ✅

curl http://localhost:8000/api/v1/collections
# → [] (trống, sẽ tự tạo khi RAG ingest data)
```

---

## ⚡ BƯỚC 8: Deploy Analyzer Worker

```bash
cd /opt/trading-bot

# Clone full project
git clone <REPO_URL> .

# Sinh SERVER_B_SECRET (cho giao tiếp C → B)
SERVER_B_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
echo "SERVER_B_SECRET=$SERVER_B_SECRET"
# → GHI LẠI SECRET NÀY (cần dùng cho SERVER B)

# Tạo .env
cat > /opt/trading-bot/server/.env << EOF
# ═══════════════════════════════════════════════
# SERVER C — AI CORE CONFIGURATION
# ═══════════════════════════════════════════════

# ── ChromaDB (local trên chính C) ──
CHROMA_REMOTE=false
CHROMA_PERSIST_DIR=/opt/trading-bot/chroma-data

# ── Kết nối đến SERVER A (Gateway) ──
VPS_BUFFER_ENABLED=true
VPS_BUFFER_URL=http://100.x.x.1:5000
VPS_BUFFER_SECRET=<THAY_BUFFER_SECRET_TỪ_SERVER_A>

# ── Kết nối đến SERVER B (Execution Vault) ──
SERVER_B_EXECUTE_URL=http://100.x.x.2:5002/api/execute-trade
SERVER_B_SECRET=$SERVER_B_SECRET

# ── AI / LLM Configuration ──
ANTHROPIC_API_KEY=<THAY_CLAUDE_API_KEY>
GOOGLE_API_KEY=<THAY_GEMINI_API_KEY>
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514

# ── Trading Parameters ──
RISK_PER_TRADE=0.02
STOP_LOSS_PCT=0.05
MAX_POSITION_SIZE=1000

# ── Analyzer Worker ──
ANALYZER_POLL_INTERVAL=15
ANALYZER_CONSUMER_ID=server-c-analyzer

# ── Telegram Notifications ──
TELEGRAM_BOT_TOKEN=<THAY_TOKEN>
TELEGRAM_CHAT_ID=<THAY_CHAT_ID>

# ── Logging ──
LOG_LEVEL=INFO
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5
EOF

# Deploy với Docker Compose
docker compose -f deploy/docker-compose.server-c.yml up -d

# Kiểm tra containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
# → chromadb      Up    127.0.0.1:8000->8000/tcp
# → analyzer      Up  
```

---

## ⚡ BƯỚC 9: Setup Monitoring Hub

```bash
# ── Tạo thư mục monitoring ──
mkdir -p /opt/trading-bot/monitoring

# ── Disk Monitor (cron mỗi 30 phút) ──
cat > /opt/trading-bot/monitoring/disk_check.sh << 'SCRIPT'
#!/bin/bash
USAGE=$(df / --output=pcent | tail -1 | tr -d ' %')
if [ "$USAGE" -gt 85 ]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=⚠️ SERVER C disk usage: ${USAGE}%"
fi
SCRIPT
chmod +x /opt/trading-bot/monitoring/disk_check.sh

# ── Liveness Monitor (check A + B mỗi 5 phút) ──
cat > /opt/trading-bot/monitoring/liveness_check.sh << 'SCRIPT'
#!/bin/bash
# Check SERVER A
A_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://100.x.x.1:5000/health)
if [ "$A_STATUS" != "200" ]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=🔴 SERVER A (Gateway) DOWN! HTTP: ${A_STATUS}"
fi

# Check SERVER B
B_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://100.x.x.2:5002/health)
if [ "$B_STATUS" != "200" ]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=🔴 SERVER B (Execution) DOWN! HTTP: ${B_STATUS}"
fi
SCRIPT
chmod +x /opt/trading-bot/monitoring/liveness_check.sh

# ── Đăng ký Cron ──
(crontab -l 2>/dev/null; echo "*/5 * * * * /opt/trading-bot/monitoring/liveness_check.sh") | crontab -
(crontab -l 2>/dev/null; echo "*/30 * * * * /opt/trading-bot/monitoring/disk_check.sh") | crontab -

# Verify cron
crontab -l

# ── Log Rotation ──
sudo tee /etc/logrotate.d/trading-bot << 'EOF'
/opt/trading-bot/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    maxsize 50M
}
EOF
```

---

## ⚡ BƯỚC 10: Verify Toàn Bộ

```bash
# ═══════════════════════════════════════════════════════
# VERIFICATION SUITE — SERVER C
# ═══════════════════════════════════════════════════════

# ── Test 1: ChromaDB heartbeat ──
curl -s http://localhost:8000/api/v1/heartbeat | python3 -m json.tool
# → {"nanosecond heartbeat": ...} ✅

# ── Test 2: Tailscale → SERVER A ──
curl -s http://100.x.x.1:5000/health | python3 -m json.tool
# → {"status": "healthy", "queue_size": 0} ✅

# ── Test 3: Tailscale → SERVER B ──
curl -s http://100.x.x.2:5002/health | python3 -m json.tool
# → {"status": "healthy"} ✅
# (Nếu SERVER B chưa setup → skip, verify sau)

# ── Test 4: Analyzer Worker logs ──
docker logs analyzer --tail 20
# → "Polling SERVER A for signals..." ✅
# → "No signals in queue" (bình thường khi chưa có alert)

# ── Test 5: Consume từ SERVER A ──
curl -s "http://100.x.x.1:5000/consume?consumer_id=server-c-analyzer&secret=<BUFFER_SECRET>"
# → [] (trống = OK, chưa có signals)

# ── Test 6: NTP drift check ──
chronyc tracking | grep "System time"
# → System time: 0.00000xxxx ✅ (drift < 50ms)

# ── Test 7: RAM check ──
free -m
# → Used: ~3000-5000MB ✅ (target: ~4-5GB active)

# ── Test 8: Docker containers ──
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
# chromadb    Up X minutes    127.0.0.1:8000->8000/tcp
# analyzer    Up X minutes

# ── Test 9: Disk usage ──
df -h /
# → Used: ~5-8GB / Xgb ✅

# ── Test 10: Cron jobs registered ──
crontab -l
# → */5 * * * * liveness_check.sh ✅
# → */30 * * * * disk_check.sh ✅
```

---

## ⚡ E2E Test: Toàn Bộ Pipeline A → C

```bash
# ── Gửi test signal vào SERVER A ──
curl -X POST http://100.x.x.1:5000/ingest \
    -H "Content-Type: application/json" \
    -H "X-Buffer-Secret: <BUFFER_SECRET>" \
    -d '{
        "source": "indicator",
        "symbol": "BTCUSDT.P",
        "action": "BUY",
        "indicator_name": "MIS_v1",
        "timeframe": "4h",
        "price": 68500.50
    }'
# → {"id": "...", "status": "PENDING"} ✅

# ── Chờ 15s → Analyzer tự động consume ──
sleep 20

# ── Kiểm tra Analyzer đã xử lý ──
docker logs analyzer --tail 30
# → "Received signal: BTCUSDT.P BUY"
# → "RAG query completed"
# → "AI analysis: ..."
# → "Forwarding to SERVER B" (hoặc "SERVER B unreachable" nếu B chưa setup)

# ── Kiểm tra signal đã ACK trên SERVER A ──
curl -s "http://100.x.x.1:5000/consume?consumer_id=test&secret=<BUFFER_SECRET>"
# → [] (trống = signal đã được consume và ACK) ✅
```

---

## 📊 RAM Budget Cuối Cùng

```
┌──────────────────────────────────────────────────┐
│       SERVER C — RAM THỰC TẾ SAU SETUP           │
│                                                  │
│  Debian 12:            ~100 MB (OS)              │
│  SSH + chrony:           ~8 MB                   │
│  fail2ban:               ~8 MB                   │
│  Tailscale:             ~30 MB                   │
│  Docker Engine:         ~80 MB                   │
│  ──────────────────────────────                  │
│  Hạ tầng:              ~226 MB                   │
│                                                  │
│  ChromaDB Container:                             │
│    Server process:    ~500 MB (khởi tạo)         │
│    Vector data:      ~2000 MB (tuỳ collection)   │
│  ──────────────────────────────                  │
│  ChromaDB:           ~2500 MB                    │
│                                                  │
│  Analyzer Worker:                                │
│    Python process:    ~200 MB                    │
│    LLM SDK + httpx:   ~100 MB                   │
│    RAG chunks cache:  ~200 MB                    │
│  ──────────────────────────────                  │
│  Analyzer:            ~500 MB                    │
│                                                  │
│  Monitoring scripts:   ~50 MB                    │
│  ══════════════════════════════                  │
│  TỔNG SỬ DỤNG:      ~3276 MB                    │
│  CÒN TRỐNG:        ~13108 MB (80% free!)        │
│                                                  │
│  ✅ Dư sức cho Backtesting Engine (V3)           │
│  ✅ Có thể chạy thêm workers khi scale          │
└──────────────────────────────────────────────────┘
```

---

## 🔑 Secrets Tổng Hợp

```
┌──────────────────────────────────────────────────┐
│  SERVER C GIỮ CÁC SECRETS SAU:                  │
│                                                  │
│  BUFFER_SECRET:    _________ (từ SERVER A)       │
│  SERVER_B_SECRET:  _________ (tạo ở Bước 8)     │
│  ANTHROPIC_API_KEY: sk-ant-________________      │
│  GOOGLE_API_KEY:   AI_______________________     │
│  TELEGRAM_BOT_TOKEN: ________________________   │
│  TELEGRAM_CHAT_ID:   ________________________   │
│                                                  │
│  CHIA SẺ CHO SERVER B:                           │
│  SERVER_B_SECRET:  _________ (cùng giá trị)     │
│  Tailscale IP C:   100.___.___.___               │
│                                                  │
│  ⚠️ SERVER C KHÔNG CÓ Exchange API Keys!        │
│  ⚠️ Chỉ SERVER B mới có quyền đặt lệnh sàn!   │
└──────────────────────────────────────────────────┘
```

---

## ❌ KHÔNG LÀM Trên SERVER C

| Hành động | Lý do |
|-----------|-------|
| ❌ Lưu Exchange API Keys | Chỉ SERVER B có — không bao giờ để trên C |
| ❌ Mở port 8000 ra Internet | ChromaDB chỉ bind localhost |
| ❌ Cài Cloudflare Tunnel | SERVER C không cần public endpoint |
| ❌ Chạy TradeEngine trực tiếp | C chỉ phân tích → forward payload sang B |
| ❌ Chạy bằng root | Luôn dùng `botuser` |
| ❌ Tắt Swap | Cần swap cho ChromaDB large queries |
