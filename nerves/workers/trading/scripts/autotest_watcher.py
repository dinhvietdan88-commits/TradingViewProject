import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from typing import Set, Tuple

# Add parent directory to sys.path
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

import alert_manager  # noqa: E402

# Set up logging for watcher
logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
)
logger = logging.getLogger("autotest_watcher")

try:
    from watchfiles import awatch

    WATCHFILES_AVAILABLE = True
except ImportError:
    WATCHFILES_AVAILABLE = False


class PollingWatcher:
    def __init__(self, watch_paths, extensions=(".py", ".pine"), interval=0.5):
        self.watch_paths = watch_paths
        self.extensions = extensions
        self.interval = interval
        self.mtimes = {}

    def _scan(self):
        current_mtimes = {}
        for path in self.watch_paths:
            if not os.path.exists(path):
                continue
            for root, _dirs, files in os.walk(path):
                # Skip ignored folders
                if any(
                    ignored in root
                    for ignored in (".git", ".venv", ".agents", "__pycache__")
                ):
                    continue
                for file in files:
                    if file.endswith(self.extensions):
                        full_path = os.path.join(root, file)
                        try:
                            current_mtimes[full_path] = os.stat(full_path).st_mtime
                        except (OSError, PermissionError):
                            # Handle temporary file locks on Windows
                            pass
        return current_mtimes

    async def watch(self, queue: asyncio.Queue):
        # Initial scan to populate times
        self.mtimes = self._scan()
        while True:
            await asyncio.sleep(self.interval)
            current = self._scan()
            changed_files = []
            for path, mtime in current.items():
                if path not in self.mtimes:
                    changed_files.append(path)
                elif self.mtimes[path] != mtime:
                    changed_files.append(path)
            # Check for deleted files
            for path in list(self.mtimes.keys()):
                if path not in current:
                    changed_files.append(path)

            self.mtimes = current
            if changed_files:
                for file in changed_files:
                    await queue.put(file)


def parse_pytest_failures(stdout: str) -> list[dict]:
    failures = []
    lines = stdout.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("___") and line.endswith("___"):
            # We found a failure block header
            test_name = line.strip("_ ")
            failure_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if (
                    next_line.startswith("___") and next_line.endswith("___")
                ) or next_line.startswith("===="):
                    break
                failure_lines.append(next_line)
                i += 1

            tb_lines = [line for line in failure_lines if line.strip()]
            tb_short = (
                "\n".join(tb_lines[-8:]) if len(tb_lines) >= 8 else "\n".join(tb_lines)
            )
            failures.append({"test_name": test_name, "traceback_short": tb_short})
            continue
        i += 1
    return failures


def extract_failure_details(stdout: str, stderr: str) -> tuple[str, str]:
    failures = parse_pytest_failures(stdout)
    if failures:
        first_fail = failures[0]
        return first_fail["test_name"], first_fail["traceback_short"]

    # Fallback: find any line containing "FAILED" in short test summary info
    for line in stdout.splitlines():
        if line.startswith("FAILED "):
            parts = line.split("FAILED ")[1].split(" - ")
            test_name = parts[0]
            err_msg = parts[1] if len(parts) > 1 else "AssertionError"
            return test_name, err_msg

    # Ultimate fallback: last 8 lines of stdout
    lines = [line for line in stdout.splitlines() if line.strip()]
    tb_short = "\n".join(lines[-8:]) if len(lines) >= 8 else "\n".join(lines)
    return "pytest", tb_short


async def run_test_suite(changed_files: set[str]):
    logger.info(f"Triggering test suite run due to changes in: {changed_files}")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    trading_dir = os.path.abspath(os.path.join(script_dir, ".."))

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pytest",
            cwd=trading_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        success = proc.returncode == 0
        status_str = "PASSING" if success else "FAILING"

        summary = "All tests passed"
        if not success:
            summary = "Some tests failed"

        for line in reversed(stdout.splitlines()):
            if ("passed" in line or "failed" in line) and "in " in line:
                summary = line.strip("= ")
                break

        error_log = ""
        offending_file = "pytest"
        if not success:
            offending_file, error_log = extract_failure_details(stdout, stderr)
            await alert_manager.handle_test_failure_alert(offending_file, error_log)

        alert_manager.log_test_run(success, summary, error_log)
        await alert_manager.set_setting_async("test_runner_status", status_str)

        last_test_run_data = {
            "timestamp": datetime.now().isoformat(),
            "status": status_str,
            "summary": summary,
            "error_log": error_log,
        }
        await alert_manager.set_setting_async(
            "last_test_run", json.dumps(last_test_run_data)
        )
        logger.info(
            f"Test suite run completed. Status: {status_str}, Summary: {summary}"
        )

    except Exception as e:
        logger.error(f"Error running test suite: {e}")


async def debounce_consumer(queue: asyncio.Queue):
    while True:
        first_event = await queue.get()
        queue.task_done()

        last_event_time = asyncio.get_event_loop().time()
        changed_files = {first_event}

        while True:
            now = asyncio.get_event_loop().time()
            time_since_last = now - last_event_time
            time_remaining = 1.0 - time_since_last

            if time_remaining <= 0:
                break

            try:
                file_event = await asyncio.wait_for(queue.get(), timeout=time_remaining)
                changed_files.add(file_event)
                queue.task_done()
                last_event_time = asyncio.get_event_loop().time()
            except TimeoutError:
                break

        await run_test_suite(changed_files)


async def watcher_loop(queue: asyncio.Queue):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    trading_dir = os.path.abspath(os.path.join(script_dir, ".."))
    project_root = os.path.abspath(os.path.join(trading_dir, "..", "..", ".."))
    pine_dir = os.path.join(project_root, "pine")

    watch_dirs = [trading_dir]
    if os.path.exists(pine_dir):
        watch_dirs.append(pine_dir)

    logger.info(f"Starting watcher for directories: {watch_dirs}")

    if WATCHFILES_AVAILABLE:
        try:
            logger.info("Using watchfiles.awatch as the primary watcher.")
            async for changes in awatch(*watch_dirs):
                for _change_type, path in changes:
                    if path.endswith((".py", ".pine")):
                        if any(
                            ignored in path
                            for ignored in (".git", ".venv", ".agents", "__pycache__")
                        ):
                            continue
                        logger.info(f"File change detected (watchfiles): {path}")
                        await queue.put(path)
            return
        except Exception as e:
            logger.warning(
                f"watchfiles failed or encountered an error: {e}. Falling back to PollingWatcher."
            )

    logger.info("Using custom PollingWatcher fallback.")
    watcher = PollingWatcher(watch_dirs)
    await watcher.watch(queue)


async def health_check_loop():
    logger.info("Starting background health check loop.")
    while True:
        try:
            # 1. Database Connection Check
            db_status = "OK"
            db_err = ""
            try:
                import time

                import database

                ts = str(time.time())
                await database.set_setting("health_check_ping", ts)
                ping_val = await database.get_setting("health_check_ping")
                if ping_val != ts:
                    db_status = "ERROR"
                    db_err = f"Ping mismatch: expected {ts}, got {ping_val}"
            except Exception as e:
                db_status = "ERROR"
                db_err = str(e)

            await alert_manager.handle_health_check_transition(
                "database", db_status, db_err
            )

            # 2. API Server Liveness Check
            api_status = "OK"
            api_err = ""
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", 5000), timeout=5.0
                )
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                api_status = "ERROR"
                api_err = str(e)

            await alert_manager.handle_health_check_transition(
                "api_server", api_status, api_err
            )

            # 3. TradingView CDP Liveness Check
            cdp_status = "OK"
            cdp_err = ""
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", 9222), timeout=5.0
                )
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                cdp_status = "ERROR"
                cdp_err = str(e)

            await alert_manager.handle_health_check_transition(
                "cdp", cdp_status, cdp_err
            )

        except Exception as e:
            logger.error(f"Error in health check loop: {e}")

        await asyncio.sleep(30)


async def main():
    logger.info("Initializing Autotest Watcher & Health Monitor Daemon")
    queue = asyncio.Queue()

    # Start health check loop
    asyncio.create_task(health_check_loop())

    # Start watcher
    watcher_task = asyncio.create_task(watcher_loop(queue))

    # Start debouncer consumer
    consumer_task = asyncio.create_task(debounce_consumer(queue))

    await asyncio.gather(watcher_task, consumer_task)


if __name__ == "__main__":
    asyncio.run(main())
