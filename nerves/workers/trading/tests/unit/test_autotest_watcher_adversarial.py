import os
import sys
import json
import asyncio
import logging
import pytest
import aiosqlite
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

# Add the project root to sys.path to ensure absolute imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import config
import database
import alert_manager
from scripts import autotest_watcher


class StopLoop(BaseException):
    """Exception used to gracefully exit infinite loops in tests."""

    pass


@pytest.fixture
async def temp_db(tmp_path):
    """Creates and initializes a temporary database for test isolation."""
    old_db_path = config.DB_PATH
    temp_db_file = str(tmp_path / "adversarial_test.db")
    config.DB_PATH = temp_db_file
    os.environ["DB_PATH"] = temp_db_file

    # Initialize schema
    await database.init_db()

    yield temp_db_file

    # Restore config
    config.DB_PATH = old_db_path
    os.environ["DB_PATH"] = old_db_path


@pytest.fixture
def temp_log(tmp_path):
    """Overrides test_runs.log file path to prevent pollution."""
    old_log_path = alert_manager.log_file_path
    temp_log_file = str(tmp_path / "test_runs_temp.log")

    # Update the handler filename
    logger = logging.getLogger("test_runs")
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            handler.close()
            logger.removeHandler(handler)

    new_handler = logging.FileHandler(temp_log_file, encoding="utf-8")
    new_handler.setFormatter(
        logging.Formatter("[%(asctime)s] | %(levelname)s | %(message)s")
    )
    logger.addHandler(new_handler)

    alert_manager.log_file_path = temp_log_file

    yield temp_log_file

    # Restore original handler
    new_handler.close()
    logger.removeHandler(new_handler)

    if os.path.exists(old_log_path):
        original_handler = logging.FileHandler(old_log_path, encoding="utf-8")
        original_handler.setFormatter(
            logging.Formatter("[%(asctime)s] | %(levelname)s | %(message)s")
        )
        logger.addHandler(original_handler)
    alert_manager.log_file_path = old_log_path


@pytest.mark.asyncio
async def test_health_check_failures_and_transitions(temp_db, temp_log):
    """
    Test 1: Health check failures.
    Simulate port 5000 / 9222 offline conditions.
    Verify the watcher logs the failure, updates 'health_api_server' / 'health_cdp' to 'ERROR' in settings,
    and triggers a Telegram alert on state transition.
    """
    # Keep track of alerts sent
    alerts_sent = []

    async def mock_send_telegram_alert(message):
        alerts_sent.append(message)

    # Database setting helper
    async def get_db_setting(key):
        async with aiosqlite.connect(temp_db) as conn:
            async with conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    # Step 1: Simulate all ports OK (Online)
    async def mock_open_connection_ok(host, port):
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        return AsyncMock(), mock_writer

    with (
        patch("asyncio.open_connection", side_effect=mock_open_connection_ok),
        patch("notifier.send_telegram_alert", side_effect=mock_send_telegram_alert),
        patch("asyncio.sleep", side_effect=StopLoop),
    ):
        try:
            await autotest_watcher.health_check_loop()
        except StopLoop:
            pass

        # Check DB states
        assert await get_db_setting("health_api_server") == "OK"
        assert await get_db_setting("health_cdp") == "OK"
        assert len(alerts_sent) == 0

    # Step 2: Simulate ports 5000 and 9222 ERROR (Offline)
    async def mock_open_connection_error(host, port):
        if port in (5000, 9222):
            raise ConnectionRefusedError(f"Connection refused on port {port}")
        mock_writer = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        return AsyncMock(), mock_writer

    with (
        patch("asyncio.open_connection", side_effect=mock_open_connection_error),
        patch("notifier.send_telegram_alert", side_effect=mock_send_telegram_alert),
        patch("asyncio.sleep", side_effect=StopLoop),
    ):
        try:
            await autotest_watcher.health_check_loop()
        except StopLoop:
            pass

        # Check DB states transitioned to ERROR
        assert await get_db_setting("health_api_server") == "ERROR"
        assert await get_db_setting("health_cdp") == "ERROR"

        # Verify Telegram alert triggered on transition
        assert len(alerts_sent) == 2
        assert "System Health Check Failed" in alerts_sent[0]
        assert "api_server" in alerts_sent[0]
        assert "cdp" in alerts_sent[1]

        # Verify failures are logged to temp_log
        with open(temp_log, "r", encoding="utf-8") as f:
            log_content = f.read()
            assert (
                "Health check 'api_server' failed: Connection refused on port 5000"
                in log_content
            )
            assert (
                "Health check 'cdp' failed: Connection refused on port 9222"
                in log_content
            )

    # Step 3: Run again in ERROR state (No further alerts should be sent since no state transition)
    alerts_sent.clear()
    with (
        patch("asyncio.open_connection", side_effect=mock_open_connection_error),
        patch("notifier.send_telegram_alert", side_effect=mock_send_telegram_alert),
        patch("asyncio.sleep", side_effect=StopLoop),
    ):
        try:
            await autotest_watcher.health_check_loop()
        except StopLoop:
            pass

        assert await get_db_setting("health_api_server") == "ERROR"
        assert await get_db_setting("health_cdp") == "ERROR"
        # No alert because they were already in ERROR state
        assert len(alerts_sent) == 0


@pytest.mark.asyncio
async def test_pytest_failure_capturing(temp_db, temp_log):
    """
    Test 2: Pytest failure capturing.
    Verify that:
       - The failure is captured, formatted as a shortened traceback (e.g. 8 lines), and logged to 'test_runs.log'.
       - The database status 'test_runner_status' transitions to 'FAILING'.
       - A Telegram message is sent with the test name and the traceback.
    """
    # Mock pytest output containing a failure block with more than 8 lines
    mock_stdout = """
================================== FAILURES ===================================
________________________ test_database_connection_loss ________________________

    async def test_database_connection_loss():
        connection = await connect_to_db()
        await connection.close()
        # Some intermediate setup lines to populate traceback
        line_1 = "foo"
        line_2 = "bar"
        line_3 = "baz"
>       assert connection.is_connected()
E       AssertionError: assert False

tests/unit/test_database.py:42: AssertionError
=========================== short test summary info ===========================
FAILED tests/unit/test_database.py::test_database_connection_loss - AssertionError: assert False
"""

    alerts_sent = []

    async def mock_send_telegram_alert(message):
        alerts_sent.append(message)

    # Mock asyncio.create_subprocess_exec to simulate pytest failure
    mock_process = AsyncMock()
    mock_process.returncode = 1
    mock_process.communicate.return_value = (mock_stdout.encode("utf-8"), b"")

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("notifier.send_telegram_alert", side_effect=mock_send_telegram_alert),
    ):
        await autotest_watcher.run_test_suite({"tests/unit/test_database.py"})

        # Verify DB status transitions to FAILING
        async with aiosqlite.connect(temp_db) as conn:
            async with conn.execute(
                "SELECT value FROM settings WHERE key = 'test_runner_status'"
            ) as cursor:
                row = await cursor.fetchone()
                assert row[0] == "FAILING"

            async with conn.execute(
                "SELECT value FROM settings WHERE key = 'last_test_run'"
            ) as cursor:
                row = await cursor.fetchone()
                last_run = json.loads(row[0])
                assert last_run["status"] == "FAILING"
                assert "AssertionError" in last_run["error_log"]

        # Verify shortened traceback is logged in test_runs.log
        with open(temp_log, "r", encoding="utf-8") as f:
            log_content = f.read()
            assert "Test Run FAILED:" in log_content
            # Check for traceback elements
            assert "AssertionError: assert False" in log_content

        # Verify Telegram alert was triggered with test name and traceback
        assert len(alerts_sent) == 1
        alert = alerts_sent[0]
        assert "Test Failure Detected" in alert
        assert "test_database_connection_loss" in alert
        assert "AssertionError" in alert
        # Check traceback is short
        tb_lines = alert.split("<pre>")[1].split("</pre>")[0].strip().splitlines()
        assert len(tb_lines) <= 8


@pytest.mark.asyncio
async def test_debounce_verification():
    """
    Test 3: Debounce verification.
    Trigger multiple rapid writes (e.g., 3 saves within 0.5s) on a watched file,
    and verify that pytest is executed only once.
    """
    suite_runs = []

    async def mock_run_test_suite(changed_files):
        suite_runs.append(changed_files)

    queue = asyncio.Queue()

    # Start the debounce consumer in the background
    with patch(
        "scripts.autotest_watcher.run_test_suite", side_effect=mock_run_test_suite
    ):
        consumer_task = asyncio.create_task(autotest_watcher.debounce_consumer(queue))

        # Push 3 events within 0.2s (less than the 1.0s debounce window)
        await queue.put("file1.py")
        await asyncio.sleep(0.05)
        await queue.put("file2.py")
        await asyncio.sleep(0.05)
        await queue.put("file3.py")

        # Wait for the debounce timeout to complete (window is 1.0s)
        await asyncio.sleep(1.5)

        # Verify test suite run only once
        assert len(suite_runs) == 1
        # Verify it was triggered with all 3 files
        assert suite_runs[0] == {"file1.py", "file2.py", "file3.py"}

        # Clean up task
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_liveness_protection(temp_db):
    """
    Test 4: Liveness.
    Ensure the daemon continues to run robustly even after a test fails or port check errors out.
    """
    # 1. Debouncer consumer should not crash when test suite execution returns non-zero (failed tests)
    run_counts = 0
    mock_process = AsyncMock()
    mock_process.returncode = 1
    mock_process.communicate.return_value = (
        b"FAILED test_dummy.py::test_fail - AssertionError",
        b"",
    )

    queue = asyncio.Queue()

    # Mock subprocess execution to simulate pytest failure
    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec,
        patch("notifier.send_telegram_alert") as mock_tg,
    ):
        consumer_task = asyncio.create_task(autotest_watcher.debounce_consumer(queue))

        # First trigger: test fails
        await queue.put("file_a.py")
        await asyncio.sleep(1.2)  # Wait for debounce to trigger run_test_suite
        assert mock_exec.call_count == 1
        assert not consumer_task.done(), "Debouncer crashed after test failure!"

        # Second trigger: debouncer should still run
        await queue.put("file_b.py")
        await asyncio.sleep(1.2)  # Wait for debounce
        assert mock_exec.call_count == 2
        assert not consumer_task.done(), (
            "Debouncer crashed on second run after failure!"
        )

        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

    # 2. Health check loop should not crash if database module throws an unhandled exception
    sleeps = 0

    async def mock_sleep(seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 2:
            raise StopLoop()

    async def mock_set_setting_crash(*args, **kwargs):
        raise ValueError("Critical DB connection failure")

    with (
        patch("database.set_setting", side_effect=mock_set_setting_crash),
        patch("asyncio.sleep", side_effect=mock_sleep),
        patch("asyncio.open_connection", return_value=(MagicMock(), MagicMock())),
        patch("notifier.send_telegram_alert") as mock_tg,
    ):
        try:
            await autotest_watcher.health_check_loop()
        except StopLoop:
            pass

        # Verify it went to the second iteration (sleeps == 2) instead of exiting on the first
        assert sleeps == 2
