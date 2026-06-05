"""
server/workers/disk_monitor.py — Disk Space Monitor (V2 Hardened).

Runs on SERVER C (8U16G) and also recommended on SERVER A (1U2G — critical).
Checks total disk usage and log directory size every 30 minutes via APScheduler.

Usage (via APScheduler in server/scheduler.py):
    from workers.disk_monitor import check_disk_usage
    scheduler.add_job(check_disk_usage, "interval", minutes=30, id="disk_monitor")

Thresholds:
  DISK_WARNING_THRESHOLD_PCT  = 80  (Telegram warning)
  DISK_CRITICAL_THRESHOLD_PCT = 90  (Telegram critical + remediation guide)
"""

import asyncio
import logging
import os
import shutil

log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────
DISK_WARNING_THRESHOLD_PCT = int(os.getenv("DISK_WARNING_THRESHOLD_PCT", "80"))
DISK_CRITICAL_THRESHOLD_PCT = int(os.getenv("DISK_CRITICAL_THRESHOLD_PCT", "90"))
LOG_DIR = os.getenv("LOG_DIR", "logs/")
PARTITION = os.getenv("DISK_MONITOR_PARTITION", "/")


# ── Main check function ────────────────────────────────────────────────────────


async def check_disk_usage() -> dict:
    """Check disk usage and alert via Telegram if thresholds are exceeded.

    Returns:
        dict with keys: used_pct, free_gb, total_gb, log_size_mb, status
    """
    total, used, free = shutil.disk_usage(PARTITION)

    used_pct = (used / total) * 100
    free_gb = free / (1024**3)
    total_gb = total / (1024**3)

    # Calculate log directory size
    log_size_mb = _get_dir_size_mb(LOG_DIR)

    result = {
        "used_pct": round(used_pct, 1),
        "free_gb": round(free_gb, 2),
        "total_gb": round(total_gb, 2),
        "log_size_mb": round(log_size_mb, 1),
        "status": "ok",
    }

    if used_pct >= DISK_CRITICAL_THRESHOLD_PCT:
        result["status"] = "critical"
        log.critical(f"🚨 DISK CRITICAL: {used_pct:.0f}% used, {free_gb:.1f} GB free")
        await _send_disk_alert("CRITICAL", used_pct, free_gb, log_size_mb)

    elif used_pct >= DISK_WARNING_THRESHOLD_PCT:
        result["status"] = "warning"
        log.warning(f"⚠️ DISK WARNING: {used_pct:.0f}% used, {free_gb:.1f} GB free")
        await _send_disk_alert("WARNING", used_pct, free_gb, log_size_mb)

    else:
        log.info(
            f"💾 Disk OK: {used_pct:.0f}% used, {free_gb:.1f} GB free, "
            f"logs={log_size_mb:.1f} MB"
        )

    return result


def _get_dir_size_mb(path: str) -> float:
    """Return total size of all files in `path` in megabytes."""
    if not os.path.exists(path):
        return 0.0
    total = 0
    for entry in os.scandir(path):
        if entry.is_file(follow_symlinks=False):
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    return total / (1024 * 1024)


async def _send_disk_alert(
    severity: str, used_pct: float, free_gb: float, log_size_mb: float
) -> None:
    icon = "🚨" if severity == "CRITICAL" else "⚠️"
    msg = (
        f"{icon} <b>DISK {severity}</b>\n\n"
        f"Dung lượng: <b>{used_pct:.0f}%</b> đã sử dụng\n"
        f"Còn trống: <b>{free_gb:.1f} GB</b>\n"
        f"Log dir: {log_size_mb:.1f} MB\n\n"
    )
    if severity == "CRITICAL":
        msg += (
            "⚠️ <b>HÀNH ĐỘNG CẦN THIẾT:</b>\n"
            "• Xoá log cũ: <code>rm logs/*.log.*</code>\n"
            "• Dọn Docker: <code>docker system prune -f</code>\n"
            "• Kiểm tra DB: <code>ls -lh data/*.db</code>"
        )
    try:
        from notifier import notify_all

        await notify_all(msg)
    except Exception as exc:
        log.error(f"[DiskMonitor] Failed to send disk alert: {exc}")


# ── Standalone entry-point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(check_disk_usage())
    print(result)
