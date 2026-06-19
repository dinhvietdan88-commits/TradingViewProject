# Provisioning Verification Report

**Generated at**: 2026-06-17T02:01:21Z
**Target Server(s)**: all

## Summary

| Metric | Count |
|--------|-------|
| Passed | 21 |
| Failed | 23 |
| Skipped | 0 |
| Total | 44 |

## Checklist Details

| ID | Description | Status | Details |
|----|-------------|--------|---------|
| 11.1.1 | Debian 12 Minimal đã cài | **PASS** | Debian 12 Minimal detected. |
| 11.1.2 | apt update && apt upgrade | **PASS** | Apt packages up to date. |
| 11.1.3 | User botuser tạo, không dùng root | **PASS** | User botuser exists. |
| 11.1.4 | SSH key-only auth, PasswordAuthentication no | **PASS** | SSH hardened (root disallowed or password authentication disabled). |
| 11.1.5 | Fail2ban cấu hình và chạy | **PASS** | Fail2ban is active. |
| 11.1.6 | UFW firewall bật, chỉ allow SSH + Tailscale | **PASS** | UFW is active. |
| 11.1.7 | NTP chrony đồng bộ (drift < 50ms) | **PASS** | Chrony NTP sync active. |
| 11.1.8 | Swap 2GB tạo | **PASS** | Swap space is 2047 MB. |
| 11.1.9 | Docker CE + Compose V2 cài | **PASS** | Docker installed: Docker version 29.5.2, build 79eb04c (Docker Compose version v5.1.4) |
| 11.1.10 | Docker log limit (10m x 3) cấu hình | **PASS** | Docker logging limited to 10m x 3. |
| 11.1.11 | Tailscale VPN kết nối, IP 100.x.x.1 | **PASS** | Tailscale IP: 100.92.13.100 |
| 11.1.12 | Cloudflare Tunnel -> bot.yourdomain.com | **PASS** | Cloudflare tunnel is active. |
| 11.1.13 | VBS container chạy, /health trả healthy | **PASS** | VBS is running. Health: {"status":"healthy","uptime_seconds":765410,"server_time_epoch":1781661640.9258223,"server_time_iso":"2026-06-17T02:00:40.925847+00:00","hostname":"c053f4217a0f","db":"ok","pending_count":0} |
| 11.1.14 | BUFFER_SECRET sinh ngẫu nhiên (>=32 bytes) | **PASS** | BUFFER_SECRET configured securely (length=169). |
| 11.1.15 | Telegram notification test thành công | **PASS** | Telegram token configured. |
| 11.2.1 | Debian 12 đã cài (Standard OK cho 8U16G) | **FAIL** | OS matched:  |
| 11.2.2 | User botuser, SSH hardened | **FAIL** | No valid deployment users found. |
| 11.2.3 | NTP chrony đồng bộ | **FAIL** | Chrony NTP inactive. |
| 11.2.4 | Docker CE + Compose V2 | **FAIL** | Docker/Compose not found. |
| 11.2.5 | Tailscale VPN kết nối, IP 100.x.x.3 | **FAIL** | Tailscale not connected. |
| 11.2.6 | ChromaDB container chạy (:8000) | **FAIL** | ChromaDB not responding: SSH connection failed: cached connection failure for Server C. |
| 11.2.7 | Analyzer Worker container chạy | **FAIL** | Analyzer container not found or not running. |
| 11.2.8 | Kết nối đến SERVER A /consume thành công | **FAIL** | Connection to Server A failed: SSH connection failed: cached connection failure for Server C. |
| 11.2.9 | Kết nối đến SERVER B /api/execute-trade thành công | **FAIL** | Connection to Server B failed: SSH connection failed: cached connection failure for Server C. |
| 11.2.10 | Liveness monitor cấu hình (check A + B) | **FAIL** | Liveness script not found. |
| 11.2.11 | Disk monitor cấu hình | **FAIL** | Disk monitor script not found. |
| 11.2.12 | Circuit Breaker LLM cấu hình | **FAIL** | Circuit Breaker not configured. |
| 11.2.13 | AI smoke test: agy-bridge + RAG vectors | **FAIL** | AGY_BRIDGE_SECRET not found — cannot run AI smoke test. |
| 11.3.1 | Windows Server 2022 cập nhật | **PASS** | Windows OS: Microsoft Windows 11 Pro Insider Preview |
| 11.3.2 | Python 3.11+ cài | **PASS** | Python 3.11.9 installed. |
| 11.3.3 | NTP w32time đồng bộ | **PASS** | w32time is active and synchronizing. |
| 11.3.4 | Tailscale VPN kết nối, IP 100.x.x.2 | **PASS** | Tailscale IP: 100.98.220.19 |
| 11.3.5 | Firewall: port 5002 chỉ allow 100.0.0.0/8 | **PASS** | Firewall checked (no explicit rule blocking port 5002 found). |
| 11.3.6 | Execution Server chạy | **FAIL** | Connection failed: HTTPConnectionPool(host='localhost', port=5002): Max retries exceeded with url: /health (Caused by NewConnectionError("HTTPConnection(host='localhost', port=5002): Failed to establish a new connection: [WinError 10061] No connection could be made because the target machine actively refused it")) |
| 11.3.7 | SERVER_B_SECRET cấu hình | **FAIL** | SERVER_B_SECRET missing. |
| 11.3.8 | Exchange API Keys cấu hình (Binance/Bybit/Weex) | **FAIL** | No exchange credentials configured. |
| 11.3.9 | Test: POST /api/execute-trade từ SERVER C | **FAIL** | Connection failed: HTTPConnectionPool(host='localhost', port=5002): Max retries exceeded with url: /api/execute-trade (Caused by NewConnectionError("HTTPConnection(host='localhost', port=5002): Failed to establish a new connection: [WinError 10061] No connection could be made because the target machine actively refused it")) |
| 11.3.10 | Telegram notification test | **FAIL** | Telegram credentials missing. |
| 11.4.1 | SERVER C ping SERVER A qua Tailscale | **FAIL** | Ping failed. |
| 11.4.2 | SERVER C ping SERVER B qua Tailscale | **FAIL** | Ping failed. |
| 11.4.3 | Clock drift < 50ms giữa cả 3 server | **FAIL** | Clock drift check failed. |
| 11.4.4 | E2E: TradingView -> A -> C -> B | **FAIL** | One or more pipeline nodes inactive. |
| 11.4.5 | Telegram nhận đủ notification từ cả 3 server | **FAIL** | Telegram not configured on all nodes. |
| 11.4.6 | UptimeRobot/Cloudflare monitor đang active | **PASS** | Cloudflare ingress is active. |

## Raw JSON Data

```json
{
  "timestamp": "2026-06-17T02:01:21Z",
  "summary": {
    "passed": 21,
    "failed": 23,
    "skipped": 0,
    "total": 44
  },
  "details": {
    "11.1.1": {
      "passed": true,
      "status": "PASS",
      "description": "Debian 12 Minimal \u0111\u00e3 c\u00e0i",
      "msg": "Debian 12 Minimal detected."
    },
    "11.1.2": {
      "passed": true,
      "status": "PASS",
      "description": "apt update && apt upgrade",
      "msg": "Apt packages up to date."
    },
    "11.1.3": {
      "passed": true,
      "status": "PASS",
      "description": "User botuser t\u1ea1o, kh\u00f4ng d\u00f9ng root",
      "msg": "User botuser exists."
    },
    "11.1.4": {
      "passed": true,
      "status": "PASS",
      "description": "SSH key-only auth, PasswordAuthentication no",
      "msg": "SSH hardened (root disallowed or password authentication disabled)."
    },
    "11.1.5": {
      "passed": true,
      "status": "PASS",
      "description": "Fail2ban c\u1ea5u h\u00ecnh v\u00e0 ch\u1ea1y",
      "msg": "Fail2ban is active."
    },
    "11.1.6": {
      "passed": true,
      "status": "PASS",
      "description": "UFW firewall b\u1eadt, ch\u1ec9 allow SSH + Tailscale",
      "msg": "UFW is active."
    },
    "11.1.7": {
      "passed": true,
      "status": "PASS",
      "description": "NTP chrony \u0111\u1ed3ng b\u1ed9 (drift < 50ms)",
      "msg": "Chrony NTP sync active."
    },
    "11.1.8": {
      "passed": true,
      "status": "PASS",
      "description": "Swap 2GB t\u1ea1o",
      "msg": "Swap space is 2047 MB."
    },
    "11.1.9": {
      "passed": true,
      "status": "PASS",
      "description": "Docker CE + Compose V2 c\u00e0i",
      "msg": "Docker installed: Docker version 29.5.2, build 79eb04c (Docker Compose version v5.1.4)"
    },
    "11.1.10": {
      "passed": true,
      "status": "PASS",
      "description": "Docker log limit (10m x 3) c\u1ea5u h\u00ecnh",
      "msg": "Docker logging limited to 10m x 3."
    },
    "11.1.11": {
      "passed": true,
      "status": "PASS",
      "description": "Tailscale VPN k\u1ebft n\u1ed1i, IP 100.x.x.1",
      "msg": "Tailscale IP: 100.92.13.100"
    },
    "11.1.12": {
      "passed": true,
      "status": "PASS",
      "description": "Cloudflare Tunnel -> bot.yourdomain.com",
      "msg": "Cloudflare tunnel is active."
    },
    "11.1.13": {
      "passed": true,
      "status": "PASS",
      "description": "VBS container ch\u1ea1y, /health tr\u1ea3 healthy",
      "msg": "VBS is running. Health: {\"status\":\"healthy\",\"uptime_seconds\":765410,\"server_time_epoch\":1781661640.9258223,\"server_time_iso\":\"2026-06-17T02:00:40.925847+00:00\",\"hostname\":\"c053f4217a0f\",\"db\":\"ok\",\"pending_count\":0}"
    },
    "11.1.14": {
      "passed": true,
      "status": "PASS",
      "description": "BUFFER_SECRET sinh ng\u1eabu nhi\u00ean (>=32 bytes)",
      "msg": "BUFFER_SECRET configured securely (length=169)."
    },
    "11.1.15": {
      "passed": true,
      "status": "PASS",
      "description": "Telegram notification test th\u00e0nh c\u00f4ng",
      "msg": "Telegram token configured."
    },
    "11.2.1": {
      "passed": false,
      "status": "FAIL",
      "description": "Debian 12 \u0111\u00e3 c\u00e0i (Standard OK cho 8U16G)",
      "msg": "OS matched: "
    },
    "11.2.2": {
      "passed": false,
      "status": "FAIL",
      "description": "User botuser, SSH hardened",
      "msg": "No valid deployment users found."
    },
    "11.2.3": {
      "passed": false,
      "status": "FAIL",
      "description": "NTP chrony \u0111\u1ed3ng b\u1ed9",
      "msg": "Chrony NTP inactive."
    },
    "11.2.4": {
      "passed": false,
      "status": "FAIL",
      "description": "Docker CE + Compose V2",
      "msg": "Docker/Compose not found."
    },
    "11.2.5": {
      "passed": false,
      "status": "FAIL",
      "description": "Tailscale VPN k\u1ebft n\u1ed1i, IP 100.x.x.3",
      "msg": "Tailscale not connected."
    },
    "11.2.6": {
      "passed": false,
      "status": "FAIL",
      "description": "ChromaDB container ch\u1ea1y (:8000)",
      "msg": "ChromaDB not responding: SSH connection failed: cached connection failure for Server C."
    },
    "11.2.7": {
      "passed": false,
      "status": "FAIL",
      "description": "Analyzer Worker container ch\u1ea1y",
      "msg": "Analyzer container not found or not running."
    },
    "11.2.8": {
      "passed": false,
      "status": "FAIL",
      "description": "K\u1ebft n\u1ed1i \u0111\u1ebfn SERVER A /consume th\u00e0nh c\u00f4ng",
      "msg": "Connection to Server A failed: SSH connection failed: cached connection failure for Server C."
    },
    "11.2.9": {
      "passed": false,
      "status": "FAIL",
      "description": "K\u1ebft n\u1ed1i \u0111\u1ebfn SERVER B /api/execute-trade th\u00e0nh c\u00f4ng",
      "msg": "Connection to Server B failed: SSH connection failed: cached connection failure for Server C."
    },
    "11.2.10": {
      "passed": false,
      "status": "FAIL",
      "description": "Liveness monitor c\u1ea5u h\u00ecnh (check A + B)",
      "msg": "Liveness script not found."
    },
    "11.2.11": {
      "passed": false,
      "status": "FAIL",
      "description": "Disk monitor c\u1ea5u h\u00ecnh",
      "msg": "Disk monitor script not found."
    },
    "11.2.12": {
      "passed": false,
      "status": "FAIL",
      "description": "Circuit Breaker LLM c\u1ea5u h\u00ecnh",
      "msg": "Circuit Breaker not configured."
    },
    "11.2.13": {
      "passed": false,
      "status": "FAIL",
      "description": "AI smoke test: agy-bridge + RAG vectors",
      "msg": "AGY_BRIDGE_SECRET not found \u2014 cannot run AI smoke test."
    },
    "11.3.1": {
      "passed": true,
      "status": "PASS",
      "description": "Windows Server 2022 c\u1eadp nh\u1eadt",
      "msg": "Windows OS: Microsoft Windows 11 Pro Insider Preview"
    },
    "11.3.2": {
      "passed": true,
      "status": "PASS",
      "description": "Python 3.11+ c\u00e0i",
      "msg": "Python 3.11.9 installed."
    },
    "11.3.3": {
      "passed": true,
      "status": "PASS",
      "description": "NTP w32time \u0111\u1ed3ng b\u1ed9",
      "msg": "w32time is active and synchronizing."
    },
    "11.3.4": {
      "passed": true,
      "status": "PASS",
      "description": "Tailscale VPN k\u1ebft n\u1ed1i, IP 100.x.x.2",
      "msg": "Tailscale IP: 100.98.220.19"
    },
    "11.3.5": {
      "passed": true,
      "status": "PASS",
      "description": "Firewall: port 5002 ch\u1ec9 allow 100.0.0.0/8",
      "msg": "Firewall checked (no explicit rule blocking port 5002 found)."
    },
    "11.3.6": {
      "passed": false,
      "status": "FAIL",
      "description": "Execution Server ch\u1ea1y",
      "msg": "Connection failed: HTTPConnectionPool(host='localhost', port=5002): Max retries exceeded with url: /health (Caused by NewConnectionError(\"HTTPConnection(host='localhost', port=5002): Failed to establish a new connection: [WinError 10061] No connection could be made because the target machine actively refused it\"))"
    },
    "11.3.7": {
      "passed": false,
      "status": "FAIL",
      "description": "SERVER_B_SECRET c\u1ea5u h\u00ecnh",
      "msg": "SERVER_B_SECRET missing."
    },
    "11.3.8": {
      "passed": false,
      "status": "FAIL",
      "description": "Exchange API Keys c\u1ea5u h\u00ecnh (Binance/Bybit/Weex)",
      "msg": "No exchange credentials configured."
    },
    "11.3.9": {
      "passed": false,
      "status": "FAIL",
      "description": "Test: POST /api/execute-trade t\u1eeb SERVER C",
      "msg": "Connection failed: HTTPConnectionPool(host='localhost', port=5002): Max retries exceeded with url: /api/execute-trade (Caused by NewConnectionError(\"HTTPConnection(host='localhost', port=5002): Failed to establish a new connection: [WinError 10061] No connection could be made because the target machine actively refused it\"))"
    },
    "11.3.10": {
      "passed": false,
      "status": "FAIL",
      "description": "Telegram notification test",
      "msg": "Telegram credentials missing."
    },
    "11.4.1": {
      "passed": false,
      "status": "FAIL",
      "description": "SERVER C ping SERVER A qua Tailscale",
      "msg": "Ping failed."
    },
    "11.4.2": {
      "passed": false,
      "status": "FAIL",
      "description": "SERVER C ping SERVER B qua Tailscale",
      "msg": "Ping failed."
    },
    "11.4.3": {
      "passed": false,
      "status": "FAIL",
      "description": "Clock drift < 50ms gi\u1eefa c\u1ea3 3 server",
      "msg": "Clock drift check failed."
    },
    "11.4.4": {
      "passed": false,
      "status": "FAIL",
      "description": "E2E: TradingView -> A -> C -> B",
      "msg": "One or more pipeline nodes inactive."
    },
    "11.4.5": {
      "passed": false,
      "status": "FAIL",
      "description": "Telegram nh\u1eadn \u0111\u1ee7 notification t\u1eeb c\u1ea3 3 server",
      "msg": "Telegram not configured on all nodes."
    },
    "11.4.6": {
      "passed": true,
      "status": "PASS",
      "description": "UptimeRobot/Cloudflare monitor \u0111ang active",
      "msg": "Cloudflare ingress is active."
    }
  }
}
```
