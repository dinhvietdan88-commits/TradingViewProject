"""
server/workers/liveness_monitor.py — Cross-Server Health Monitor (V3 Smart Offline).

Runs on SERVER C and periodically checks /health on SERVER A and SERVER B.
Sends Telegram alerts when a server goes down and again when it recovers.

V3 Smart Offline Logic:
  - After OFFLINE_THRESHOLD consecutive failures → mark OFFLINE
  - OFFLINE servers are SKIPPED (no more checks, no more Telegram spam)
  - When Server B comes back, it calls POST /api/server-announce on Server C
    → Server C marks it ONLINE and resumes health checks
  - Telegram alert sent ONCE on transition: online→offline, offline→online

Usage (via APScheduler in server/scheduler.py):
    from workers.liveness_monitor import run_liveness_check
    scheduler.add_job(run_liveness_check, "interval", minutes=5, id="liveness_check")

Or standalone test:
    python -m server.workers.liveness_monitor

Environment variables:
  SERVER_A_HEALTH_URL  — e.g. http://100.x.x.1:5000/health  (Tailscale IP)
  SERVER_B_HEALTH_URL  — e.g. http://100.x.x.2:5002/health  (Tailscale IP)
  LIVENESS_ALERT_AFTER_FAILURES = 2   (alert after N consecutive failures)
  LIVENESS_OFFLINE_THRESHOLD = 3      (mark offline after N consecutive failures)
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
ALERT_AFTER_FAILURES = int(os.getenv("LIVENESS_ALERT_AFTER_FAILURES", "2"))
OFFLINE_THRESHOLD    = int(os.getenv("LIVENESS_OFFLINE_THRESHOLD", "3"))
RECOVERY_NOTIFY      = True
CHECK_TIMEOUT_SEC    = 10.0


# ── Server health tracker ──────────────────────────────────────────────────────

@dataclass
class ServerHealth:
    """Track health state of a single server endpoint."""
    name:                  str
    url:                   str
    consecutive_failures:  int   = 0
    last_success:          float = 0.0
    last_check:            float = 0.0
    is_healthy:            bool  = True
    is_offline:            bool  = False   # V3: True = skip checks entirely
    last_error:            str   = ""
    alerted_down:          bool  = False   # V3: True = already sent DOWN alert


# Dynamic server list — read from env so Tailscale IPs can be configured
# without code changes.
def _build_server_list() -> List[ServerHealth]:
    servers = []
    a_url = os.getenv("SERVER_A_HEALTH_URL", "")
    b_url = os.getenv("SERVER_B_HEALTH_URL", "")
    if a_url:
        servers.append(ServerHealth(name="SERVER_A (Gateway)", url=a_url))
    if b_url:
        servers.append(ServerHealth(name="SERVER_B (Execution Vault)", url=b_url))
    if not servers:
        log.warning(
            "[LivenessMonitor] SERVER_A_HEALTH_URL and SERVER_B_HEALTH_URL not set. "
            "No servers will be monitored."
        )
    return servers


# Module-level server list (initialised on first check)
_servers: Optional[List[ServerHealth]] = None


def _get_servers() -> List[ServerHealth]:
    global _servers
    if _servers is None:
        _servers = _build_server_list()
    return _servers


# ── V3: Server Announce (called by Server B on startup) ────────────────────────

def announce_server_online(server_name: str) -> dict:
    """Mark a server as ONLINE again. Called via POST /api/server-announce.

    When Server B starts up, it should call this endpoint on Server C
    to resume health monitoring.

    Args:
        server_name: Name fragment to match (e.g. "SERVER_B" or "Execution")

    Returns:
        dict with status and matched server name
    """
    servers = _get_servers()
    matched = None
    for server in servers:
        if server_name.upper() in server.name.upper():
            was_offline = server.is_offline
            server.is_offline = False
            server.is_healthy = True
            server.consecutive_failures = 0
            server.alerted_down = False
            server.last_error = ""
            matched = server.name
            log.info(
                f"🟢 [LivenessMonitor] {server.name} announced ONLINE "
                f"(was_offline={was_offline})"
            )
            break

    if matched:
        return {"status": "ok", "server": matched, "monitoring": "resumed"}
    return {"status": "error", "message": f"No server matching '{server_name}'"}


def get_server_status() -> List[dict]:
    """Return current status of all monitored servers."""
    servers = _get_servers()
    return [
        {
            "name": s.name,
            "url": s.url,
            "is_healthy": s.is_healthy,
            "is_offline": s.is_offline,
            "consecutive_failures": s.consecutive_failures,
            "last_error": s.last_error,
        }
        for s in servers
    ]


# ── Main check function ────────────────────────────────────────────────────────

async def run_liveness_check() -> None:
    """Check /health on all configured servers.

    Called by APScheduler every 5 minutes (or standalone).
    V3: Skips servers marked as OFFLINE.
    """
    servers = _get_servers()
    if not servers:
        return

    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SEC) as client:
        for server in servers:
            # V3: Skip offline servers — they must self-announce to resume
            if server.is_offline:
                log.debug(
                    f"⏭️ {server.name} is OFFLINE — skipping health check "
                    f"(waiting for self-announce)"
                )
                continue

            server.last_check = time.time()
            try:
                resp = await client.get(server.url)
                data = resp.json()

                if resp.status_code == 200 and data.get("status") in ("healthy", "ok"):
                    was_unhealthy = not server.is_healthy
                    server.is_healthy            = True
                    server.consecutive_failures  = 0
                    server.last_success          = time.time()
                    server.last_error            = ""
                    server.alerted_down          = False

                    uptime    = data.get("uptime_seconds", "?")
                    pending   = data.get("pending_count", "?")
                    log.info(
                        f"✅ {server.name} healthy "
                        f"(uptime={uptime}s, pending={pending})"
                    )

                    if was_unhealthy and RECOVERY_NOTIFY:
                        await _send_recovery_alert(server, data)
                else:
                    await _handle_failure(
                        server, f"Degraded response: {data.get('status','?')}"
                    )

            except httpx.ConnectError as exc:
                await _handle_failure(server, f"Connection refused ({exc})")
            except httpx.ReadTimeout:
                await _handle_failure(
                    server, f"Read timeout (>{CHECK_TIMEOUT_SEC}s)"
                )
            except Exception as exc:
                await _handle_failure(server, str(exc)[:200])


async def _handle_failure(server: ServerHealth, error: str) -> None:
    server.consecutive_failures += 1
    server.is_healthy = False
    server.last_error = error
    log.warning(
        f"❌ {server.name} FAILED "
        f"(attempt #{server.consecutive_failures}): {error}"
    )

    # V3: 3-strike offline logic
    if server.consecutive_failures >= OFFLINE_THRESHOLD:
        if not server.is_offline:
            server.is_offline = True
            log.warning(
                f"🔴 {server.name} marked OFFLINE after "
                f"{server.consecutive_failures} consecutive failures. "
                f"Health checks SUSPENDED until self-announce."
            )
            # Send ONE final alert — then silence
            if not server.alerted_down:
                await _send_offline_alert(server, error)
                server.alerted_down = True
    elif server.consecutive_failures >= ALERT_AFTER_FAILURES:
        # Still under threshold — send warning (but only once)
        if not server.alerted_down:
            await _send_down_alert(server, error)
            server.alerted_down = True


async def _send_down_alert(server: ServerHealth, error: str) -> None:
    downtime_min = 0
    if server.last_success > 0:
        downtime_min = int((time.time() - server.last_success) / 60)

    msg = (
        f"🚨 <b>SERVER DOWN</b>\n\n"
        f"Server: <b>{server.name}</b>\n"
        f"URL: <code>{server.url}</code>\n"
        f"Lỗi: {error}\n"
        f"Failures: {server.consecutive_failures} liên tiếp\n"
        f"Downtime: ~{downtime_min} phút\n\n"
        f"⚠️ Signal pipeline có thể bị gián đoạn!"
    )
    try:
        from notifier import notify_all
        await notify_all(msg)
    except Exception as exc:
        log.error(f"[LivenessMonitor] Failed to send down alert: {exc}")


async def _send_offline_alert(server: ServerHealth, error: str) -> None:
    """V3: Send final OFFLINE alert — no more alerts after this."""
    downtime_min = 0
    if server.last_success > 0:
        downtime_min = int((time.time() - server.last_success) / 60)

    msg = (
        f"🔴 <b>SERVER OFFLINE</b>\n\n"
        f"Server: <b>{server.name}</b>\n"
        f"URL: <code>{server.url}</code>\n"
        f"Failures: {server.consecutive_failures} liên tiếp\n"
        f"Downtime: ~{downtime_min} phút\n\n"
        f"🔕 Health checks SUSPENDED.\n"
        f"Server sẽ tự khai báo online khi khởi động lại."
    )
    try:
        from notifier import notify_all
        await notify_all(msg)
    except Exception as exc:
        log.error(f"[LivenessMonitor] Failed to send offline alert: {exc}")


async def _send_recovery_alert(server: ServerHealth, health_data: dict) -> None:
    msg = (
        f"✅ <b>SERVER RECOVERED</b>\n\n"
        f"Server: <b>{server.name}</b>\n"
        f"Status: healthy\n"
        f"Uptime: {health_data.get('uptime_seconds', 0)}s\n"
        f"Pending signals: {health_data.get('pending_count', '?')}"
    )
    try:
        from notifier import notify_all
        await notify_all(msg)
    except Exception as exc:
        log.error(f"[LivenessMonitor] Failed to send recovery alert: {exc}")


# ── Standalone entry-point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_liveness_check())

