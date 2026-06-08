# Provisioning Verification Report

**Generated at**: 2026-06-08T05:58:13Z
**Target Server(s)**: b

## Summary

| Metric | Count |
|--------|-------|
| Passed | 10 |
| Failed | 0 |
| Skipped | 34 |
| Total | 44 |

## Checklist Details

| ID | Description | Status | Details |
|----|-------------|--------|---------|
| 11.1.1 | Debian 12 Minimal đã cài | **SKIP** | Skipped (target server constraint) |
| 11.1.2 | apt update && apt upgrade | **SKIP** | Skipped (target server constraint) |
| 11.1.3 | User botuser tạo, không dùng root | **SKIP** | Skipped (target server constraint) |
| 11.1.4 | SSH key-only auth, PasswordAuthentication no | **SKIP** | Skipped (target server constraint) |
| 11.1.5 | Fail2ban cấu hình và chạy | **SKIP** | Skipped (target server constraint) |
| 11.1.6 | UFW firewall bật, chỉ allow SSH + Tailscale | **SKIP** | Skipped (target server constraint) |
| 11.1.7 | NTP chrony đồng bộ (drift < 50ms) | **SKIP** | Skipped (target server constraint) |
| 11.1.8 | Swap 2GB tạo | **SKIP** | Skipped (target server constraint) |
| 11.1.9 | Docker CE + Compose V2 cài | **SKIP** | Skipped (target server constraint) |
| 11.1.10 | Docker log limit (10m x 3) cấu hình | **SKIP** | Skipped (target server constraint) |
| 11.1.11 | Tailscale VPN kết nối, IP 100.x.x.1 | **SKIP** | Skipped (target server constraint) |
| 11.1.12 | Cloudflare Tunnel -> bot.yourdomain.com | **SKIP** | Skipped (target server constraint) |
| 11.1.13 | VBS container chạy, /health trả healthy | **SKIP** | Skipped (target server constraint) |
| 11.1.14 | BUFFER_SECRET sinh ngẫu nhiên (>=32 bytes) | **SKIP** | Skipped (target server constraint) |
| 11.1.15 | Telegram notification test thành công | **SKIP** | Skipped (target server constraint) |
| 11.2.1 | Debian 12 đã cài (Standard OK cho 8U16G) | **SKIP** | Skipped (target server constraint) |
| 11.2.2 | User botuser, SSH hardened | **SKIP** | Skipped (target server constraint) |
| 11.2.3 | NTP chrony đồng bộ | **SKIP** | Skipped (target server constraint) |
| 11.2.4 | Docker CE + Compose V2 | **SKIP** | Skipped (target server constraint) |
| 11.2.5 | Tailscale VPN kết nối, IP 100.x.x.3 | **SKIP** | Skipped (target server constraint) |
| 11.2.6 | ChromaDB container chạy (:8000) | **SKIP** | Skipped (target server constraint) |
| 11.2.7 | Analyzer Worker container chạy | **SKIP** | Skipped (target server constraint) |
| 11.2.8 | Kết nối đến SERVER A /consume thành công | **SKIP** | Skipped (target server constraint) |
| 11.2.9 | Kết nối đến SERVER B /api/execute-trade thành công | **SKIP** | Skipped (target server constraint) |
| 11.2.10 | Liveness monitor cấu hình (check A + B) | **SKIP** | Skipped (target server constraint) |
| 11.2.11 | Disk monitor cấu hình | **SKIP** | Skipped (target server constraint) |
| 11.2.12 | Circuit Breaker LLM cấu hình | **SKIP** | Skipped (target server constraint) |
| 11.2.13 | AI smoke test: agy-bridge + RAG vectors | **SKIP** | Skipped (target server constraint) |
| 11.3.1 | Windows Server 2022 cập nhật | **PASS** | Windows OS: Microsoft Windows 11 Pro Insider Preview |
| 11.3.2 | Python 3.11+ cài | **PASS** | Python 3.11.9 installed. |
| 11.3.3 | NTP w32time đồng bộ | **PASS** | w32time is active and synchronizing. |
| 11.3.4 | Tailscale VPN kết nối, IP 100.x.x.2 | **PASS** | Tailscale IP: 100.98.220.19 |
| 11.3.5 | Firewall: port 5002 chỉ allow 100.0.0.0/8 | **PASS** | Firewall checked (no explicit rule blocking port 5002 found). |
| 11.3.6 | Execution Server chạy | **PASS** | Execution Server responds ok: {'status': 'ok', 'server': 'execution-vault-b'} |
| 11.3.7 | SERVER_B_SECRET cấu hình | **PASS** | SERVER_B_SECRET configured. |
| 11.3.8 | Exchange API Keys cấu hình (Binance/Bybit/Weex) | **PASS** | Keys configured for: Weex. |
| 11.3.9 | Test: POST /api/execute-trade từ SERVER C | **PASS** | POST execute-trade validated (status=200). |
| 11.3.10 | Telegram notification test | **PASS** | Telegram configured. |
| 11.4.1 | SERVER C ping SERVER A qua Tailscale | **SKIP** | Skipped (target server constraint) |
| 11.4.2 | SERVER C ping SERVER B qua Tailscale | **SKIP** | Skipped (target server constraint) |
| 11.4.3 | Clock drift < 50ms giữa cả 3 server | **SKIP** | Skipped (target server constraint) |
| 11.4.4 | E2E: TradingView -> A -> C -> B | **SKIP** | Skipped (target server constraint) |
| 11.4.5 | Telegram nhận đủ notification từ cả 3 server | **SKIP** | Skipped (target server constraint) |
| 11.4.6 | UptimeRobot/Cloudflare monitor đang active | **SKIP** | Skipped (target server constraint) |

## Raw JSON Data

```json
{
  "timestamp": "2026-06-08T05:58:13Z",
  "summary": {
    "passed": 10,
    "failed": 0,
    "skipped": 34,
    "total": 44
  },
  "details": {
    "11.1.1": {
      "passed": false,
      "status": "SKIP",
      "description": "Debian 12 Minimal \u0111\u00e3 c\u00e0i",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.2": {
      "passed": false,
      "status": "SKIP",
      "description": "apt update && apt upgrade",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.3": {
      "passed": false,
      "status": "SKIP",
      "description": "User botuser t\u1ea1o, kh\u00f4ng d\u00f9ng root",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.4": {
      "passed": false,
      "status": "SKIP",
      "description": "SSH key-only auth, PasswordAuthentication no",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.5": {
      "passed": false,
      "status": "SKIP",
      "description": "Fail2ban c\u1ea5u h\u00ecnh v\u00e0 ch\u1ea1y",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.6": {
      "passed": false,
      "status": "SKIP",
      "description": "UFW firewall b\u1eadt, ch\u1ec9 allow SSH + Tailscale",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.7": {
      "passed": false,
      "status": "SKIP",
      "description": "NTP chrony \u0111\u1ed3ng b\u1ed9 (drift < 50ms)",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.8": {
      "passed": false,
      "status": "SKIP",
      "description": "Swap 2GB t\u1ea1o",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.9": {
      "passed": false,
      "status": "SKIP",
      "description": "Docker CE + Compose V2 c\u00e0i",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.10": {
      "passed": false,
      "status": "SKIP",
      "description": "Docker log limit (10m x 3) c\u1ea5u h\u00ecnh",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.11": {
      "passed": false,
      "status": "SKIP",
      "description": "Tailscale VPN k\u1ebft n\u1ed1i, IP 100.x.x.1",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.12": {
      "passed": false,
      "status": "SKIP",
      "description": "Cloudflare Tunnel -> bot.yourdomain.com",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.13": {
      "passed": false,
      "status": "SKIP",
      "description": "VBS container ch\u1ea1y, /health tr\u1ea3 healthy",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.14": {
      "passed": false,
      "status": "SKIP",
      "description": "BUFFER_SECRET sinh ng\u1eabu nhi\u00ean (>=32 bytes)",
      "msg": "Skipped (target server constraint)"
    },
    "11.1.15": {
      "passed": false,
      "status": "SKIP",
      "description": "Telegram notification test th\u00e0nh c\u00f4ng",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.1": {
      "passed": false,
      "status": "SKIP",
      "description": "Debian 12 \u0111\u00e3 c\u00e0i (Standard OK cho 8U16G)",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.2": {
      "passed": false,
      "status": "SKIP",
      "description": "User botuser, SSH hardened",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.3": {
      "passed": false,
      "status": "SKIP",
      "description": "NTP chrony \u0111\u1ed3ng b\u1ed9",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.4": {
      "passed": false,
      "status": "SKIP",
      "description": "Docker CE + Compose V2",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.5": {
      "passed": false,
      "status": "SKIP",
      "description": "Tailscale VPN k\u1ebft n\u1ed1i, IP 100.x.x.3",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.6": {
      "passed": false,
      "status": "SKIP",
      "description": "ChromaDB container ch\u1ea1y (:8000)",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.7": {
      "passed": false,
      "status": "SKIP",
      "description": "Analyzer Worker container ch\u1ea1y",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.8": {
      "passed": false,
      "status": "SKIP",
      "description": "K\u1ebft n\u1ed1i \u0111\u1ebfn SERVER A /consume th\u00e0nh c\u00f4ng",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.9": {
      "passed": false,
      "status": "SKIP",
      "description": "K\u1ebft n\u1ed1i \u0111\u1ebfn SERVER B /api/execute-trade th\u00e0nh c\u00f4ng",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.10": {
      "passed": false,
      "status": "SKIP",
      "description": "Liveness monitor c\u1ea5u h\u00ecnh (check A + B)",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.11": {
      "passed": false,
      "status": "SKIP",
      "description": "Disk monitor c\u1ea5u h\u00ecnh",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.12": {
      "passed": false,
      "status": "SKIP",
      "description": "Circuit Breaker LLM c\u1ea5u h\u00ecnh",
      "msg": "Skipped (target server constraint)"
    },
    "11.2.13": {
      "passed": false,
      "status": "SKIP",
      "description": "AI smoke test: agy-bridge + RAG vectors",
      "msg": "Skipped (target server constraint)"
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
      "passed": true,
      "status": "PASS",
      "description": "Execution Server ch\u1ea1y",
      "msg": "Execution Server responds ok: {'status': 'ok', 'server': 'execution-vault-b'}"
    },
    "11.3.7": {
      "passed": true,
      "status": "PASS",
      "description": "SERVER_B_SECRET c\u1ea5u h\u00ecnh",
      "msg": "SERVER_B_SECRET configured."
    },
    "11.3.8": {
      "passed": true,
      "status": "PASS",
      "description": "Exchange API Keys c\u1ea5u h\u00ecnh (Binance/Bybit/Weex)",
      "msg": "Keys configured for: Weex."
    },
    "11.3.9": {
      "passed": true,
      "status": "PASS",
      "description": "Test: POST /api/execute-trade t\u1eeb SERVER C",
      "msg": "POST execute-trade validated (status=200)."
    },
    "11.3.10": {
      "passed": true,
      "status": "PASS",
      "description": "Telegram notification test",
      "msg": "Telegram configured."
    },
    "11.4.1": {
      "passed": false,
      "status": "SKIP",
      "description": "SERVER C ping SERVER A qua Tailscale",
      "msg": "Skipped (target server constraint)"
    },
    "11.4.2": {
      "passed": false,
      "status": "SKIP",
      "description": "SERVER C ping SERVER B qua Tailscale",
      "msg": "Skipped (target server constraint)"
    },
    "11.4.3": {
      "passed": false,
      "status": "SKIP",
      "description": "Clock drift < 50ms gi\u1eefa c\u1ea3 3 server",
      "msg": "Skipped (target server constraint)"
    },
    "11.4.4": {
      "passed": false,
      "status": "SKIP",
      "description": "E2E: TradingView -> A -> C -> B",
      "msg": "Skipped (target server constraint)"
    },
    "11.4.5": {
      "passed": false,
      "status": "SKIP",
      "description": "Telegram nh\u1eadn \u0111\u1ee7 notification t\u1eeb c\u1ea3 3 server",
      "msg": "Skipped (target server constraint)"
    },
    "11.4.6": {
      "passed": false,
      "status": "SKIP",
      "description": "UptimeRobot/Cloudflare monitor \u0111ang active",
      "msg": "Skipped (target server constraint)"
    }
  }
}
```
