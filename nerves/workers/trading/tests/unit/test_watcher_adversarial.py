import asyncio
import logging

# Ensure nerves/workers/trading is in path
import pathlib
import sqlite3
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

trading_dir = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(trading_dir))

import alert_manager  # noqa: E402
import config  # noqa: E402
from scripts.autotest_watcher import (  # noqa: E402
    debounce_consumer,
    health_check_loop,
    run_test_suite,
)


@pytest.mark.asyncio
async def test_health_check_failures_and_alerts(tmp_path):
    """
    1. Health check failures: Simulate or mock port 5000 / 9222 offline conditions.
    Verify the watcher logs the failure, updates 'health_api_server' / 'health_cdp' to 'ERROR'
    in the settings table, and triggers a Telegram alert on state transition.
    """
    # Override DB path for isolation
    test_db = str(tmp_path / "test_health.db")
    config.DB_PATH = test_db

    # Initialize DB (create tables)
    import database

    await database.init_db()

    # Clear/mock Telegram alert notifier
    with patch("notifier.send_telegram_alert", new_callable=AsyncMock) as mock_tg:
        # We will mock asyncio.open_connection to fail (port offline)
        async def mock_open_connection_fail(host, port):
            raise ConnectionRefusedError(f"Connection refused on port {port}")

        with (
            patch("asyncio.open_connection", side_effect=mock_open_connection_fail),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        ):
            # Run one iteration of the health check loop
            try:
                await health_check_loop()
            except asyncio.CancelledError:
                pass

        # Verification:
        # 1. Check settings table updates
        api_status = await alert_manager.get_setting_async("health_api_server")
        cdp_status = await alert_manager.get_setting_async("health_cdp")
        db_status = await alert_manager.get_setting_async("health_database")

        assert api_status == "ERROR"
        assert cdp_status == "ERROR"
        assert db_status == "OK"  # database should be fine since we initialized it

        # 2. Check Telegram alert was triggered on transition (from None/OK to ERROR)
        # Should be called for api_server and cdp (2 calls)
        assert mock_tg.call_count == 2

        # Get calls content
        calls = [call[0][0] for call in mock_tg.call_args_list]
        assert any("api_server" in msg and "ERROR" in msg for msg in calls)
        assert any("cdp" in msg and "ERROR" in msg for msg in calls)

        # Reset mock to test no-alert on same state (still ERROR)
        mock_tg.reset_mock()

        # Run again with same offline condition
        with (
            patch("asyncio.open_connection", side_effect=mock_open_connection_fail),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        ):
            try:
                await health_check_loop()
            except asyncio.CancelledError:
                pass

        # Since it is still in ERROR state, no new Telegram alert should be triggered
        assert mock_tg.call_count == 0

        # Now transition back to OK (mock connection success)
        async def mock_open_connection_ok(host, port):
            mock_reader = AsyncMock()
            mock_writer = MagicMock()
            mock_writer.close = MagicMock()
            mock_writer.wait_closed = AsyncMock()
            return mock_reader, mock_writer

        with (
            patch("asyncio.open_connection", side_effect=mock_open_connection_ok),
            patch("asyncio.sleep", side_effect=asyncio.CancelledError),
        ):
            try:
                await health_check_loop()
            except asyncio.CancelledError:
                pass

        # Verification: status is OK now
        api_status_ok = await alert_manager.get_setting_async("health_api_server")
        cdp_status_ok = await alert_manager.get_setting_async("health_cdp")
        assert api_status_ok == "OK"
        assert cdp_status_ok == "OK"

        # No alert triggered because transition is ERROR -> OK (alerts only on failures)
        assert mock_tg.call_count == 0


@pytest.mark.asyncio
async def test_pytest_failure_capturing(tmp_path):
    """
    2. Pytest failure capturing: Inject a failing test under the tests directory. Verify:
       - The failure is captured, formatted as a shortened traceback (e.g. 8 lines), and logged to 'test_runs.log'.
       - The database status 'test_runner_status' transitions to 'FAILING'.
       - A Telegram message is sent with the test name and the traceback.
    """
    # Setup test DB
    test_db = str(tmp_path / "test_failure.db")
    config.DB_PATH = test_db
    import database

    await database.init_db()

    # Inject a temporary failing test
    failing_test_dir = trading_dir / "tests" / "unit"
    failing_test_file = failing_test_dir / "test_temp_forced_failure.py"

    # Ensure directory exists
    failing_test_dir.mkdir(parents=True, exist_ok=True)

    with open(failing_test_file, "w", encoding="utf-8") as f:
        f.write(
            "\n".join(
                ["def test_forced_fail():", "    assert False, 'EXPECTED_FAILURE_MSG'"]
            )
        )

    # Clear / Mock log file and Telegram
    original_log_file = alert_manager.log_file_path
    temp_log_file = tmp_path / "test_runs.log"

    # Patch the alert_manager log file path to avoid writing to production test_runs.log
    alert_manager.log_file_path = str(temp_log_file)
    # Reconfigure the test_runs logger handler to use the temp log file
    logger = alert_manager.test_runs_logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    file_handler = logging.FileHandler(temp_log_file, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("[%(asctime)s] | %(levelname)s | %(message)s")
    )
    logger.addHandler(file_handler)

    original_create_subprocess = asyncio.create_subprocess_exec

    async def mock_create_subprocess(*args, **kwargs):
        modified_args = list(args)
        if len(modified_args) >= 3 and modified_args[2] == "pytest":
            modified_args.append(str(failing_test_file))
        return await original_create_subprocess(*modified_args, **kwargs)

    try:
        with (
            patch("notifier.send_telegram_alert", new_callable=AsyncMock) as mock_tg,
            patch("asyncio.create_subprocess_exec", side_effect=mock_create_subprocess),
        ):
            # We call run_test_suite directly or simulate file change. Let's run the suite!
            # Since the failing test is in tests/unit/test_temp_forced_failure.py, running pytest
            # will run this test and it will fail.
            await run_test_suite({str(failing_test_file)})

            # Verify:
            # 1. Database status table transitions to FAILING
            runner_status = await alert_manager.get_setting_async("test_runner_status")
            assert runner_status == "FAILING"

            # 2. Telegram message sent with test name and traceback
            assert mock_tg.call_count == 1
            tg_message = mock_tg.call_args[0][0]
            assert "test_forced_fail" in tg_message
            assert "EXPECTED_FAILURE_MSG" in tg_message

            # Count lines of traceback in Telegram message (should be <= 8 lines)
            # Find the traceback content inside <pre>...</pre>
            import re

            pre_match = re.search(r"<pre>(.*?)</pre>", tg_message, re.DOTALL)
            assert pre_match is not None
            tb_content = pre_match.group(1)
            tb_lines = tb_content.strip().splitlines()
            assert len(tb_lines) <= 8

            # 3. Logged to test_runs.log
            assert temp_log_file.exists()
            with open(temp_log_file, encoding="utf-8") as lf:
                log_content = lf.read()
                assert "FAILED" in log_content
                assert "test_forced_fail" in log_content
                assert "EXPECTED_FAILURE_MSG" in log_content

    finally:
        # Clean up
        if failing_test_file.exists():
            failing_test_file.unlink()
        # Restore logger configuration and file path
        alert_manager.log_file_path = original_log_file
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        file_handler = logging.FileHandler(original_log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("[%(asctime)s] | %(levelname)s | %(message)s")
        )
        logger.addHandler(file_handler)


@pytest.mark.asyncio
async def test_debounce_verification():
    """
    3. Debounce verification: Trigger multiple rapid writes (e.g., 3 saves within 0.5s)
    on a watched file, and verify that pytest is executed only once.
    """
    queue = asyncio.Queue()

    with patch(
        "scripts.autotest_watcher.run_test_suite", new_callable=AsyncMock
    ) as mock_run_suite:
        # Start debounce consumer as a task
        consumer_task = asyncio.create_task(debounce_consumer(queue))

        # Put 3 rapid writes within 0.5s
        await queue.put("file1.py")
        await asyncio.sleep(0.1)
        await queue.put("file1.py")
        await asyncio.sleep(0.1)
        await queue.put("file1.py")

        # Wait enough time for the sliding window of 1.0s to expire
        # Since the first event is at t=0, and we add events at t=0.1, t=0.2.
        # The last event time is t=0.2. The consumer waits 1.0s after the last event.
        # So at t=1.2s it should trigger. Let's wait 1.5s total.
        await asyncio.sleep(1.5)

        # Clean up consumer task
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        # Verify run_test_suite was executed exactly once
        assert mock_run_suite.call_count == 1

        # The files passed to run_test_suite should contain file1.py
        called_files = mock_run_suite.call_args[0][0]
        assert "file1.py" in called_files


@pytest.mark.asyncio
async def test_liveness():
    """
    4. Liveness: Ensure the daemon continues to run robustly even after a test fails
    or port check errors out.
    """
    # Verify that run_test_suite handles exceptions and doesn't crash the loop
    # We'll mock asyncio.create_subprocess_exec to throw an unexpected exception
    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=RuntimeError("Subprocess failed abnormally"),
    ):
        # run_test_suite should catch the exception and log it, not propagate it
        try:
            await run_test_suite({"test_file.py"})
        except Exception as e:
            pytest.fail(f"run_test_suite propagated an exception: {e}")

    # Verify that health_check_loop catches exceptions and continues
    # We will raise an exception inside database.set_setting
    async def mock_set_setting_fail(key, value):
        raise sqlite3.OperationalError("Database is locked/read-only")

    with (
        patch("database.set_setting", side_effect=mock_set_setting_fail),
        patch("asyncio.sleep", side_effect=asyncio.CancelledError),
    ):
        try:
            await health_check_loop()
        except asyncio.CancelledError:
            # We expect the loop to cancel and exit gracefully on sleep
            pass
        except Exception as e:
            pytest.fail(f"health_check_loop propagated an exception: {e}")
