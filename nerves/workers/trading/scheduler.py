from __future__ import annotations

"""
P6 — APScheduler
Cron job: Morning Brief tự động lúc 07:00 ICT (UTC+7) mỗi ngày.
"""
import logging


from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

import config

logger = logging.getLogger(__name__)

ICT = ZoneInfo("Asia/Ho_Chi_Minh")

_scheduler: AsyncIOScheduler | None = None


async def _run_morning_brief_job():
    """Wrapper cho APScheduler — import brief lazily để tránh circular."""
    try:
        from brief import generate_morning_brief

        logger.info("[Scheduler] Triggering scheduled morning brief...")
        await generate_morning_brief()
    except Exception as e:
        logger.error(f"[Scheduler] Morning brief job failed: {e}", exc_info=True)


async def check_and_keep_alive_tv_cdp():
    """
    Checks responsiveness of the TradingView Desktop tab via CDP port 9222.
    If the connection is down, page is crashed, or does not respond within 30 seconds,
    trigger a reload command of the TradingView tab via CDP.
    """
    import aiohttp
    import asyncio
    import websockets
    import json

    cdp_port = 9222
    url = f"http://localhost:{cdp_port}/json/list"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    raise Exception(f"HTTP status {resp.status}")
                targets = await resp.json()

        # Find tradingview chart page
        target = None
        for t in targets:
            url_str = t.get("url", "")
            if t.get("type") == "page" and (
                "tradingview.com/chart" in url_str or "tradingview" in url_str
            ):
                target = t
                break

        if not target:
            raise Exception("No TradingView chart page found in CDP targets list")

        ws_url = target.get("webSocketDebuggerUrl")
        if not ws_url:
            raise Exception("No webSocketDebuggerUrl in target info")

        # Check responsiveness: connect and evaluate
        async with asyncio.timeout(30):
            async with websockets.connect(ws_url) as ws:
                msg = {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {"expression": "1", "returnByValue": True},
                }
                await ws.send(json.dumps(msg))
                res = await ws.recv()
                res_data = json.loads(res)
                if (
                    "error" in res_data
                    or res_data.get("result", {}).get("result", {}).get("value") != 1
                ):
                    raise Exception("Invalid Runtime.evaluate response")
        logger.info("[Scheduler] CDP Keep-Alive: TradingView page is responsive.")

    except Exception as e:
        logger.warning(
            f"[Scheduler] CDP Keep-Alive check failed: {e}. Attempting reload."
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    targets = await resp.json()
            target = None
            for t in targets:
                url_str = t.get("url", "")
                if t.get("type") == "page" and (
                    "tradingview.com/chart" in url_str or "tradingview" in url_str
                ):
                    target = t
                    break
            if target and target.get("webSocketDebuggerUrl"):
                async with websockets.connect(target.get("webSocketDebuggerUrl")) as ws:
                    reload_msg = {
                        "id": 2,
                        "method": "Page.reload",
                        "params": {"ignoreCache": True},
                    }
                    await ws.send(json.dumps(reload_msg))
                    logger.info(
                        "[Scheduler] CDP Keep-Alive: Reload command sent successfully."
                    )
            else:
                logger.error(
                    "[Scheduler] CDP Keep-Alive: Cannot reload, no target found."
                )
        except Exception as reload_err:
            logger.error(
                f"[Scheduler] CDP Keep-Alive: Failed to reload page: {reload_err}"
            )


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the APScheduler instance."""
    scheduler = AsyncIOScheduler(timezone=ICT)

    scheduler.add_job(
        check_and_keep_alive_tv_cdp,
        trigger="interval",
        minutes=5,
        id="tv_cdp_keepalive",
        name="TradingView CDP Keepalive Check",
        replace_existing=True,
    )
    logger.info("[Scheduler] TradingView CDP Keepalive scheduled every 5 minutes")

    if config.BRIEF_ENABLED:
        # Parse HH:MM from config
        try:
            hour, minute = map(int, config.BRIEF_CRON_TIME.split(":"))
        except Exception:
            hour, minute = 7, 0
            logger.warning(
                f"Invalid BRIEF_CRON_TIME '{config.BRIEF_CRON_TIME}', defaulting to 07:00"
            )

        scheduler.add_job(
            _run_morning_brief_job,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=ICT),
            id="morning_brief",
            name="Morning Brief (Minervini × RAG × MCP)",
            replace_existing=True,
            misfire_grace_time=300,  # 5 min grace period
        )
        logger.info(
            f"[Scheduler] Morning Brief scheduled at {hour:02d}:{minute:02d} ICT daily"
        )
    else:
        logger.info("[Scheduler] BRIEF_ENABLED=false — no scheduled brief")

    # ── V2 Hardened: Monitoring Jobs ──────────────────────────────────────────
    # Only register when running in ANALYZER_MODE (SERVER C).
    # Gracefully skip if monitor modules are absent (e.g. on local Windows dev).

    import os as _os

    if _os.getenv("ANALYZER_MODE", "").lower() == "true":
        _register_monitoring_jobs(scheduler)

    return scheduler


def _register_monitoring_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register V2 monitoring APScheduler jobs on SERVER C."""

    # ── Liveness monitor: check SERVER A & B every 5 minutes ──────────────────
    try:
        from workers.liveness_monitor import run_liveness_check

        scheduler.add_job(
            run_liveness_check,
            trigger="interval",
            minutes=5,
            id="liveness_check",
            name="Cross-server Liveness Check (A + B from C)",
            replace_existing=True,
            misfire_grace_time=60,
        )
        logger.info("[Scheduler] V2: Liveness monitor scheduled every 5 min")
    except ImportError:
        logger.warning("[Scheduler] V2: liveness_monitor not found — skipping")

    # ── Disk space monitor: check every 30 minutes ────────────────────────────
    try:
        from workers.disk_monitor import check_disk_usage

        scheduler.add_job(
            check_disk_usage,
            trigger="interval",
            minutes=30,
            id="disk_monitor",
            name="Disk Space Monitor",
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info("[Scheduler] V2: Disk monitor scheduled every 30 min")
    except ImportError:
        logger.warning("[Scheduler] V2: disk_monitor not found — skipping")

    # ── NTP / clock drift monitor: check every 5 minutes ─────────────────────
    try:
        from workers.ntp_monitor import check_clock_drift

        scheduler.add_job(
            check_clock_drift,
            trigger="interval",
            minutes=5,
            id="ntp_monitor",
            name="Cross-server Clock Drift Monitor",
            replace_existing=True,
            misfire_grace_time=60,
        )
        logger.info("[Scheduler] V2: NTP drift monitor scheduled every 5 min")
    except ImportError:
        logger.warning("[Scheduler] V2: ntp_monitor not found — skipping")


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    _scheduler = create_scheduler()
    _scheduler.start()
    logger.info("[Scheduler] APScheduler started ✅")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[Scheduler] APScheduler stopped")
