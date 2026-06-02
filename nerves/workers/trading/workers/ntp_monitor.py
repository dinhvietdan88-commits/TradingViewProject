"""
server/workers/ntp_monitor.py — Cross-Server NTP Clock Drift Monitor (V2 Hardened).

Runs on SERVER C and checks clock drift between C (local) and the /health
endpoints of SERVER A and SERVER B every 5 minutes via APScheduler.

Requires:
  - /health endpoints on A and B return {"server_time_epoch": float, ...}
    (implemented in vbs/router.py and server/main.py V2 upgrades)

Usage (via APScheduler):
    from workers.ntp_monitor import check_clock_drift
    scheduler.add_job(check_clock_drift, "interval", minutes=5, id="ntp_monitor")

Alert threshold:
  DRIFT_THRESHOLD_MS = 500   (alert if drift > 500 ms)

Why this matters:
  Binance rejects orders with a timestamp drift > 1000 ms (±1 s) from their server.
  VCP/Breakout signal age is computed using timestamps from different servers —
  a 30+ s drift can incorrectly classify a valid signal as STALE and discard it.
"""

import asyncio
import logging
import os
import time

import httpx

log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
DRIFT_THRESHOLD_MS = int(os.getenv("NTP_DRIFT_THRESHOLD_MS", "500"))
CHECK_TIMEOUT_SEC  = 5.0

# Health URLs — same as liveness_monitor to avoid extra env var clutter
_SERVER_URLS: dict = {}
last_drift_results: dict = {}


def _get_server_urls() -> dict:
    global _SERVER_URLS
    if not _SERVER_URLS:
        a = os.getenv("SERVER_A_HEALTH_URL", "")
        b = os.getenv("SERVER_B_HEALTH_URL", "")
        if a:
            _SERVER_URLS["SERVER_A"] = a
        if b:
            _SERVER_URLS["SERVER_B"] = b
        if not _SERVER_URLS:
            log.warning(
                "[NtpMonitor] SERVER_A_HEALTH_URL / SERVER_B_HEALTH_URL not set. "
                "NTP monitoring disabled."
            )
    return _SERVER_URLS


# ── Main check function ────────────────────────────────────────────────────────

async def check_clock_drift() -> dict:
    """Compare server_time_epoch from each server's /health against local time.

    Returns:
        dict mapping server name → {"drift_ms": float, "ok": bool}
    """
    urls = _get_server_urls()
    if not urls:
        return {}

    results = {}
    local_time = time.time()

    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SEC) as client:
        for name, url in urls.items():
            try:
                t_before = time.time()
                resp = await client.get(url)
                t_after  = time.time()
                # One-way latency estimate (half of round-trip)
                rtt_ms = (t_after - t_before) * 500

                data = resp.json()
                remote_epoch = data.get("server_time_epoch")

                if remote_epoch is None:
                    log.warning(
                        f"[NtpMonitor] {name}: /health missing server_time_epoch. "
                        "Upgrade server to V2."
                    )
                    results[name] = {"drift_ms": None, "ok": None}
                    continue

                # Correct for network latency
                adjusted_remote = remote_epoch + (rtt_ms / 1000)
                drift_ms = abs(local_time - adjusted_remote) * 1000

                ok = drift_ms <= DRIFT_THRESHOLD_MS
                results[name] = {"drift_ms": round(drift_ms, 1), "ok": ok}

                if ok:
                    log.info(
                        f"⏰ NTP OK {name}: drift={drift_ms:.1f}ms "
                        f"(rtt≈{rtt_ms:.0f}ms)"
                    )
                else:
                    log.critical(
                        f"⏰ NTP ALERT {name}: drift={drift_ms:.1f}ms "
                        f"(threshold={DRIFT_THRESHOLD_MS}ms)"
                    )
                    await _send_drift_alert(name, drift_ms, url)

            except httpx.ConnectError:
                log.warning(f"[NtpMonitor] Cannot reach {name} ({url}): connection refused")
                results[name] = {"drift_ms": None, "ok": False}
            except Exception as exc:
                log.warning(f"[NtpMonitor] {name} error: {exc}")
                results[name] = {"drift_ms": None, "ok": False}

    last_drift_results.clear()
    last_drift_results.update(results)
    return results


async def _send_drift_alert(name: str, drift_ms: float, url: str) -> None:
    msg = (
        f"🚨 <b>CLOCK DRIFT ALERT</b>\n\n"
        f"Server: <b>{name}</b>\n"
        f"URL: <code>{url}</code>\n"
        f"Drift: <b>{drift_ms:.0f}ms</b>\n"
        f"Threshold: {DRIFT_THRESHOLD_MS}ms\n\n"
        f"⚠️ Hệ thống có thể gặp lỗi timestamp.\n"
        f"Kiểm tra NTP configuration ngay!\n\n"
        f"<b>Fix:</b>\n"
        f"• Linux: <code>sudo timedatectl set-ntp true</code>\n"
        f"• Windows: <code>w32tm /resync /force</code>"
    )
    try:
        from notifier import notify_all
        await notify_all(msg)
    except Exception as exc:
        log.error(f"[NtpMonitor] Failed to send drift alert: {exc}")


# ── Standalone entry-point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(check_clock_drift())
    print(result)
