"""
server/workers/liveness_monitor.py — Cross-Server Health Monitor (V4 + agy-bridge).

Runs on SERVER C and periodically checks /health on SERVER A and SERVER B.
Also monitors agy-bridge sidecar for:
  - Bridge down (HTTP unreachable)
  - Circuit Breaker OPEN (all requests rejected)
  - CLI degraded / parallel strategy (burning 2x tokens)

Sends Telegram alerts when a server goes down and again when it recovers.

V3 Smart Offline Logic:
  - After OFFLINE_THRESHOLD consecutive failures → mark OFFLINE
  - OFFLINE servers are SKIPPED (no more checks, no more Telegram spam)
  - When Server B comes back, it calls POST /api/server-announce on Server C
    → Server C marks it ONLINE and resumes health checks
  - Telegram alert sent ONCE on transition: online→offline, offline→online

V4 agy-bridge Monitoring:
  - Checks GET http://localhost:9100/health every cycle
  - Alerts on: bridge down, CB OPEN, strategy degraded
  - Same transition-based alerting (alert ONCE on state change)

Usage (via APScheduler in server/scheduler.py):
    from workers.liveness_monitor import run_liveness_check
    scheduler.add_job(run_liveness_check, "interval", minutes=5, id="liveness_check")

Or standalone test:
    python -m server.workers.liveness_monitor

Environment variables:
  SERVER_A_HEALTH_URL  — e.g. http://100.x.x.1:5000/health  (Tailscale IP)
  SERVER_B_HEALTH_URL  — e.g. http://100.x.x.2:5002/health  (Tailscale IP)
  AGY_BRIDGE_HEALTH_URL — default: http://localhost:9100/health
  LIVENESS_ALERT_AFTER_FAILURES = 2   (alert after N consecutive failures)
  LIVENESS_OFFLINE_THRESHOLD = 3      (mark offline after N consecutive failures)
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

# Display timezone: UTC+7 (ICT / Vietnam)
VN_TZ = timezone(timedelta(hours=7))


def _now_vn_str() -> str:
    """Current time in UTC+7 for display."""
    return datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m")

# ── Configuration ──────────────────────────────────────────────────────────────
ALERT_AFTER_FAILURES = int(os.getenv("LIVENESS_ALERT_AFTER_FAILURES", "2"))
OFFLINE_THRESHOLD    = int(os.getenv("LIVENESS_OFFLINE_THRESHOLD", "3"))
RECOVERY_NOTIFY      = True
CHECK_TIMEOUT_SEC    = 10.0
AGY_BRIDGE_HEALTH_URL = os.getenv("AGY_BRIDGE_HEALTH_URL", "http://localhost:9100/health")


# ── V4: agy-bridge health state tracker ─────────────────────────────────

@dataclass
class BridgeState:
    """Track agy-bridge health for transition-based alerting."""
    is_reachable: bool = True
    cb_state: str = "CLOSED"        # CLOSED | OPEN | HALF_OPEN
    strategy: str = "sequential"    # sequential | parallel
    alerted_down: bool = False
    alerted_cb_open: bool = False
    alerted_degraded: bool = False
    consecutive_failures: int = 0
    last_health: dict = field(default_factory=dict)


_bridge_state = BridgeState()


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
    """Check /health on all configured servers + agy-bridge.

    Called by APScheduler every 5 minutes (or standalone).
    V3: Skips servers marked as OFFLINE.
    V4: Also checks agy-bridge sidecar health.
    """
    servers = _get_servers()

    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SEC) as client:
        # ── Server health checks (V3) ────────────────────────────────
        for server in servers:
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

        # ── V4: agy-bridge health check ──────────────────────────────
        await _check_agy_bridge(client)


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
        f"Downtime: ~{downtime_min} phút\n"
        f"Thời điểm: <code>{_now_vn_str()}</code> (ICT)\n\n"
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
        f"Downtime: ~{downtime_min} phút\n"
        f"Thời điểm: <code>{_now_vn_str()}</code> (ICT)\n\n"
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
        f"Pending signals: {health_data.get('pending_count', '?')}\n"
        f"Thời điểm: <code>{_now_vn_str()}</code> (ICT)"
    )
    try:
        from notifier import notify_all
        await notify_all(msg)
    except Exception as exc:
        log.error(f"[LivenessMonitor] Failed to send recovery alert: {exc}")


# ── V4: agy-bridge monitoring ────────────────────────────────────────────

async def _check_agy_bridge(client: httpx.AsyncClient) -> None:
    """Check agy-bridge /health and alert on state transitions.

    Alerts fire ONCE per transition (same pattern as server health):
    - Bridge unreachable → alert once
    - Circuit breaker OPEN → alert once
    - Strategy degraded (parallel) → alert once
    - Recovery from any of the above → alert once
    """
    global _bridge_state
    bs = _bridge_state

    try:
        resp = await client.get(AGY_BRIDGE_HEALTH_URL)
        data = resp.json()
        bs.last_health = data
        bs.consecutive_failures = 0

        # ── Recovery from unreachable ──
        if not bs.is_reachable:
            bs.is_reachable = True
            bs.alerted_down = False
            log.info("✅ [agy-bridge] recovered — back online")
            await _send_bridge_alert(
                "✅ <b>AGY-BRIDGE RECOVERED</b>\n\n"
                f"Status: {data.get('status', '?')}\n"
                f"Strategy: {data.get('strategy', {}).get('strategy', '?')}\n"
                f"Circuit Breaker: {data.get('circuit_breaker', {}).get('state', '?')}\n"
                f"Uptime: {data.get('stats', {}).get('uptime_sec', 0):.0f}s\n"
                f"Thời điểm: <code>{_now_vn_str()}</code> (ICT)"
            )

        # ── Circuit Breaker state ──
        cb = data.get("circuit_breaker", {})
        cb_state = cb.get("state", "CLOSED")
        prev_cb = bs.cb_state
        bs.cb_state = cb_state

        if cb_state == "OPEN" and prev_cb != "OPEN":
            # Transition to OPEN
            if not bs.alerted_cb_open:
                bs.alerted_cb_open = True
                stats = data.get("stats", {})
                await _send_bridge_alert(
                    "🔴 <b>AGY-BRIDGE CIRCUIT BREAKER OPEN</b>\n\n"
                    f"Failures: {cb.get('failure_count', '?')}/{cb.get('threshold', '?')}\n"
                    f"Recovery in: {cb.get('recovery_timeout_sec', 120)}s\n"
                    f"Total requests: {stats.get('total_requests', '?')}\n"
                    f"Success rate: {stats.get('success', 0)}/{stats.get('total_requests', 0)}\n"
                    f"Thời điểm: <code>{_now_vn_str()}</code> (ICT)\n\n"
                    "⚠️ Tất cả AI analysis bị từ chối cho đến khi CB hồi phục!"
                )
        elif cb_state == "CLOSED" and prev_cb == "OPEN":
            # Recovery from OPEN
            bs.alerted_cb_open = False
            await _send_bridge_alert(
                "✅ <b>AGY-BRIDGE CB RECOVERED</b>\n\n"
                f"Circuit Breaker: CLOSED\n"
                f"Thời điểm: <code>{_now_vn_str()}</code> (ICT)\n\n"
                "AI analysis pipeline hoạt động bình thường."
            )

        # ── Strategy degraded (parallel = CLI unhealthy) ──
        strat = data.get("strategy", {})
        strategy = strat.get("strategy", "sequential")
        prev_strategy = bs.strategy
        bs.strategy = strategy

        if strategy == "parallel" and prev_strategy != "parallel":
            if not bs.alerted_degraded:
                bs.alerted_degraded = True
                await _send_bridge_alert(
                    "⚠️ <b>AGY-BRIDGE CLI DEGRADED</b>\n\n"
                    f"Strategy: sequential → <b>parallel</b> (2x token cost)\n"
                    f"Avg latency: {strat.get('avg_latency_ms', 0):.0f}ms\n"
                    f"Failure rate: {strat.get('failure_rate', 0):.0%}\n"
                    f"Consecutive failures: {strat.get('consecutive_failures', 0)}\n"
                    f"Thời điểm: <code>{_now_vn_str()}</code> (ICT)\n\n"
                    "agy CLI đang chậm/lỗi → bridge chạy cả CLI + SDK song song."
                )
        elif strategy == "sequential" and prev_strategy == "parallel":
            bs.alerted_degraded = False
            await _send_bridge_alert(
                "✅ <b>AGY-BRIDGE CLI RECOVERED</b>\n\n"
                f"Strategy: parallel → <b>sequential</b> (1x token cost)\n"
                f"Avg latency: {strat.get('avg_latency_ms', 0):.0f}ms\n"
                f"Thời điểm: <code>{_now_vn_str()}</code> (ICT)\n\n"
                "agy CLI hồi phục → tiết kiệm token."
            )

        log.info(
            f"✅ [agy-bridge] healthy "
            f"(CB={cb_state}, strategy={strategy}, "
            f"cache={data.get('cache', {}).get('entries', 0)}, "
            f"uptime={data.get('stats', {}).get('uptime_sec', 0):.0f}s)"
        )

    except (httpx.ConnectError, httpx.ReadTimeout) as exc:
        bs.consecutive_failures += 1
        if bs.is_reachable and bs.consecutive_failures >= ALERT_AFTER_FAILURES:
            bs.is_reachable = False
            if not bs.alerted_down:
                bs.alerted_down = True
                await _send_bridge_alert(
                    "🚨 <b>AGY-BRIDGE DOWN</b>\n\n"
                    f"URL: <code>{AGY_BRIDGE_HEALTH_URL}</code>\n"
                    f"Lỗi: {str(exc)[:200]}\n"
                    f"Failures: {bs.consecutive_failures} liên tiếp\n"
                    f"Thời điểm: <code>{_now_vn_str()}</code> (ICT)\n\n"
                    "⚠️ AI analysis pipeline offline! "
                    "Fallback to in-container Gemini SDK (if available)."
                )
        log.warning(f"❌ [agy-bridge] unreachable (attempt #{bs.consecutive_failures}): {exc}")

    except Exception as exc:
        log.error(f"[agy-bridge] unexpected error: {exc}")


async def _send_bridge_alert(msg: str) -> None:
    """Send agy-bridge alert via Telegram/Discord."""
    try:
        from notifier import notify_all
        await notify_all(msg)
    except Exception as exc:
        log.error(f"[LivenessMonitor] Failed to send bridge alert: {exc}")


def get_bridge_status() -> dict:
    """Return current agy-bridge state for API/dashboard."""
    bs = _bridge_state
    return {
        "is_reachable": bs.is_reachable,
        "cb_state": bs.cb_state,
        "strategy": bs.strategy,
        "consecutive_failures": bs.consecutive_failures,
        "last_health": bs.last_health,
    }


# ── Standalone entry-point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_liveness_check())
