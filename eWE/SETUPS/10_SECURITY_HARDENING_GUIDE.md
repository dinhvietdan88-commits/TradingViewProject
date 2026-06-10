# 🛡️ Server Security Hardening Guide

> **Date**: 2026-06-03
> **Status**: Server A ✅ | Server C ✅ | Server B (Windows) 🔲 Pending

---

## Table of Contents
1. [Overview](#overview)
2. [Server C — Oracle Linux 9 (AI Core)](#server-c--oracle-linux-9-ai-core)
3. [Server A — Debian 12 (Gateway)](#server-a--debian-12-gateway)
4. [Server B — Windows Pro (Execution Vault)](#server-b--windows-pro-execution-vault)
5. [Cross-Server Blocklist Sync](#cross-server-blocklist-sync)

---

## Overview

### Threat Summary
- Server C: **28,313** brute-force SSH attempts detected
- Server A: **1,467** brute-force SSH attempts detected
- Same botnet targeting both servers (45.148.10.0/24 subnet)

### Defense Stack

| Layer | Purpose | Server A | Server C |
|-------|---------|----------|----------|
| SSH Hardening | Key-only, no root | ✅ | ✅ |
| SSH Port | Non-standard port | 22 (default) | 10022 |
| Fail2ban | Auto-ban after 3 fails | ✅ recidive | ✅ recidive |
| IP Blocklist | Known attacker IPs | ✅ UFW | ✅ ipset |
| Firewall | Drop all by default | ✅ UFW | ✅ firewalld drop |
| Auto-Sync | Cron blocklist sync | ✅ 15 min | ✅ 15 min |
| Guardian | Hourly audit | — | ✅ |

---

## Server C — Oracle Linux 9 (AI Core)

### Prerequisites
- SSH access via Tailscale: `ssh server-c` (port 10022)
- Root access: `sudo -i`

### 1. SSH Hardening
```bash
# /etc/ssh/sshd_config
Port 10022
PermitRootLogin no
PasswordAuthentication no
MaxAuthTries 3
LoginGraceTime 20
AllowUsers botuser

# Apply
semanage port -a -t ssh_port_t -p tcp 10022
systemctl restart sshd
```

### 2. Firewall (firewalld)
```bash
# Default zone = drop (block everything)
firewall-cmd --set-default-zone=drop

# Allow SSH on custom port
firewall-cmd --permanent --add-port=10022/tcp
firewall-cmd --permanent --remove-service=ssh   # Remove port 22

# Trusted zone for Tailscale
firewall-cmd --permanent --zone=trusted --add-interface=tailscale0

# Reload
firewall-cmd --reload
```

### 3. Fail2ban
```bash
# /etc/fail2ban/jail.local
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
banaction = firewallcmd-ipset

[sshd]
enabled = true
port = 10022
maxretry = 3

[recidive]
enabled = true
logpath = /var/log/fail2ban.log
bantime = 604800
findtime = 86400
maxretry = 3
```

### 4. IP Blocklist (ipset)
```bash
# Create ipset
firewall-cmd --permanent --new-ipset=blocklist --type=hash:net

# Add known attackers
for ip in 81.177.6.131 185.156.73.233 213.209.159.56 \
  2.57.121.25 2.57.121.112 45.148.10.0/24; do
  firewall-cmd --permanent --ipset=blocklist --add-entry=$ip
done

# Apply DROP rule
firewall-cmd --permanent --add-rich-rule='rule source ipset="blocklist" drop'
firewall-cmd --reload
```

### 5. Guardian (Hourly Audit)
Location: `/usr/local/bin/guardian.sh`
Cron: `0 * * * * root /usr/local/bin/guardian.sh`

Monitors: disk usage, firewall rules, fail2ban status, user shells.

### 6. Docker Migration
```bash
# Move Docker root to /home partition
cat > /etc/docker/daemon.json << 'EOF'
{ "data-root": "/home/docker-data" }
EOF
systemctl stop docker
rsync -aP /var/lib/docker/ /home/docker-data/
systemctl start docker
# Verify: docker info | grep "Docker Root Dir"
```

---

## Server A — Debian 12 (Gateway)

### Prerequisites
- SSH access via Tailscale: `ssh server-a`
- Root access: `sudo -i`

### 1. SSH Hardening
```bash
# /etc/ssh/sshd_config
PermitRootLogin no
PasswordAuthentication no
MaxAuthTries 3
LoginGraceTime 20
AllowUsers botuser

systemctl restart sshd
```

### 2. Firewall (UFW)
```bash
ufw allow 22/tcp          # SSH
ufw allow on tailscale0   # Tailscale
ufw enable
```

### 3. Fail2ban
```bash
# /etc/fail2ban/jail.local
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
banaction = ufw

[sshd]
enabled = true
port = 22
maxretry = 3

[recidive]
enabled = true
logpath = /var/log/fail2ban.log
bantime = 604800
findtime = 86400
maxretry = 3
```

### 4. IP Blocklist (UFW)
```bash
for ip in 81.177.6.131 185.156.73.233 213.209.159.56 \
  2.57.121.25 2.57.121.112 45.148.10.0/24; do
  ufw insert 1 deny from $ip to any
done
```

---

## Server B — Windows Pro (Execution Vault)

> **Status**: 🔲 PENDING — to be configured manually

### 1. Windows Firewall Rules
```powershell
# Block known attacker IPs
$attackers = @(
  "81.177.6.131", "185.156.73.233", "213.209.159.56",
  "2.57.121.25", "2.57.121.112", "45.148.10.147",
  "45.148.10.151", "45.227.254.170", "45.148.10.152",
  "45.148.10.141", "45.148.10.157", "92.118.39.236",
  "182.188.24.243", "45.148.10.121", "80.94.95.116",
  "104.23.175.58"
)

# Create inbound block rule
New-NetFirewallRule -DisplayName "Block Known Attackers" `
  -Direction Inbound -Action Block `
  -RemoteAddress $attackers `
  -Profile Any

# Block subnet
New-NetFirewallRule -DisplayName "Block Botnet Subnet 45.148.10.0/24" `
  -Direction Inbound -Action Block `
  -RemoteAddress "45.148.10.0/24" `
  -Profile Any
```

### 2. Account Lockout Policy
```powershell
# Set lockout threshold (3 attempts)
net accounts /lockoutthreshold:3
net accounts /lockoutduration:30
net accounts /lockoutwindow:30
```

### 3. RDP Restrict to Tailscale Only
```powershell
# Allow RDP only from Tailscale subnet (100.64.0.0/10)
Set-NetFirewallRule -DisplayName "Remote Desktop*" `
  -RemoteAddress "100.64.0.0/10" -Enabled True

# Block RDP from all other sources
New-NetFirewallRule -DisplayName "Block RDP Public" `
  -Direction Inbound -Action Block `
  -LocalPort 3389 -Protocol TCP `
  -RemoteAddress "0.0.0.0/0" `
  -Profile Public,Private
```

### 4. Windows Defender Hardening
```powershell
# Enable real-time protection
Set-MpPreference -DisableRealtimeMonitoring $false

# Enable network protection
Set-MpPreference -EnableNetworkProtection Enabled

# Block untrusted processes
Set-MpPreference -AttackSurfaceReductionRules_Ids `
  "BE9BA2D9-53EA-4CDC-84E5-9B1EEEE46550" `
  -AttackSurfaceReductionRules_Actions Enabled
```

### 5. Blocklist Sync Script (PowerShell)
```powershell
# Save as C:\Scripts\sync_blocklist.ps1
# Schedule with Task Scheduler (every 15 min)

$BlocklistFile = "C:\Scripts\shared_blocklist.txt"

# Download shared blocklist from Server C via Tailscale
scp botuser@server-c:/opt/scripts/shared_blocklist.txt $BlocklistFile

# Apply to Windows Firewall
$ips = Get-Content $BlocklistFile | Where-Object { $_ -match '^\d' }
if ($ips.Count -gt 0) {
    Remove-NetFirewallRule -DisplayName "Synced Blocklist" -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "Synced Blocklist" `
      -Direction Inbound -Action Block `
      -RemoteAddress $ips -Profile Any
}

# Log
Add-Content "C:\Scripts\blocklist_sync.log" `
  "$(Get-Date): Synced $($ips.Count) IPs"
```

---

## Cross-Server Blocklist Sync

### Architecture
```
Server C (Master)                Server A              Server B
┌─────────────────┐         ┌──────────────┐      ┌──────────────┐
│ fail2ban         │         │ fail2ban      │      │ Windows FW   │
│ ↓ extract bans   │         │ ↓ extract     │      │              │
│ shared_blocklist │◄──scp──►│ blocklist     │      │              │
│ ↓ ipset apply    │         │ ↓ ufw apply   │      │ ← scp sync   │
│ firewalld drop   │         │ ufw deny      │      │ FW rule apply │
└─────────────────┘         └──────────────┘      └──────────────┘
       ↑ cron 15min              ↑ cron 15min         ↑ Task Sched
```

### Future: A2A Protocol
See [08_A2A_INTEGRATION_ROADMAP.md](./08_A2A_INTEGRATION_ROADMAP.md) for replacing cron-based sync with real-time Agent-to-Agent protocol via Tailscale VPN.
