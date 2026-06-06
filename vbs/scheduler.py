import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import database
import notifier

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def stale_cleanup_job():
    """Find expired pending/dispatched signals and mark them as STALE."""
    try:
        log.info("Running scheduled Stale Cleanup Job...")
        stale_count = await database.stale_cleanup()
        if stale_count > 0:
            msg = f"❌ <b>VBS Notification</b>\n{stale_count} signal(s) expired without processing and marked as STALE."
            await notifier.send_telegram_alert(msg)
    except Exception as e:
        log.exception(f"Error in stale_cleanup_job: {e}")


async def requeue_timeouts_job():
    """Find dispatched signals that timed out without ACK and requeue or stale them."""
    try:
        log.info("Running scheduled Re-queue Timeouts Job...")
        requeued, stale_alerts = await database.requeue_timeouts(
            config.DISPATCH_TIMEOUT_MINUTES
        )

        # Notify about requeued signals
        if requeued > 0:
            log.info(f"Requeued {requeued} timed out signal(s).")

        # Alert about signals that hit max retries
        for item in stale_alerts:
            msg = (
                f"🚨 <b>VBS WARNING: Signal Processing Timeout</b>\n"
                f"Signal #{item['id']} for <b>{item['symbol']}</b> ({item['action'].upper()}) "
                f"dispatched but never ACKed. Max retries exceeded. Marked as STALE."
            )
            await notifier.send_telegram_alert(msg)
    except Exception as e:
        log.exception(f"Error in requeue_timeouts_job: {e}")


async def audit_cleanup_job():
    """Clean up old audit logs."""
    try:
        log.info("Running scheduled Audit Cleanup Job...")
        deleted = await database.audit_cleanup(config.AUDIT_RETENTION_DAYS)
        log.info(
            f"Cleaned up {deleted} audit log entries older than {config.AUDIT_RETENTION_DAYS} days."
        )
    except Exception as e:
        log.exception(f"Error in audit_cleanup_job: {e}")


def start_scheduler():
    """Start APScheduler background jobs."""
    if not scheduler.running:
        scheduler.add_job(
            stale_cleanup_job,
            "interval",
            minutes=config.CLEANUP_INTERVAL_MINUTES,
            id="stale_cleanup",
        )
        scheduler.add_job(
            requeue_timeouts_job, "interval", minutes=5, id="requeue_timeouts"
        )
        scheduler.add_job(audit_cleanup_job, "interval", hours=24, id="audit_cleanup")

        scheduler.start()
        log.info("VBS Scheduler started successfully.")


def stop_scheduler():
    """Stop APScheduler background jobs."""
    if scheduler.running:
        scheduler.shutdown()
        log.info("VBS Scheduler stopped.")
