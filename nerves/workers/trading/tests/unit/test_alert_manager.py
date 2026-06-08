"""
Unit tests for alert_manager.py.
Covers synchronous/asynchronous settings get/set, test run logging, telegram alerts, and health check transitions.
"""

import sqlite3
import pytest
from unittest.mock import AsyncMock, patch

import config
from alert_manager import (
    log_test_run,
    get_setting_sync,
    set_setting_sync,
    set_setting_async,
    get_setting_async,
    handle_test_failure_alert,
    handle_health_check_transition,
)


@pytest.fixture
def temp_db(tmp_path):
    """Fixture to set up a temporary SQLite database with a settings table."""
    db_file = tmp_path / "test_alert_manager.db"
    orig_db_path = config.DB_PATH
    config.DB_PATH = str(db_file)

    # Create the settings table
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    conn.close()

    yield str(db_file)

    config.DB_PATH = orig_db_path


def test_log_test_run_success():
    """Verify log_test_run logs success information correctly."""
    with patch("alert_manager.test_runs_logger") as mock_logger:
        log_test_run(True, "All tests passed")
        mock_logger.log.assert_called_once()
        args, kwargs = mock_logger.log.call_args
        assert "PASSED: All tests passed" in args[1]


def test_log_test_run_failure():
    """Verify log_test_run logs failure details correctly."""
    with patch("alert_manager.test_runs_logger") as mock_logger:
        log_test_run(False, "Some tests failed", "Traceback details here")
        mock_logger.log.assert_called_once()
        args, kwargs = mock_logger.log.call_args
        assert "FAILED: Some tests failed" in args[1]
        assert "Traceback details here" in args[1]


def test_get_set_setting_sync(temp_db):
    """Verify synchronous get and set setting operations."""
    # Try getting a non-existent key
    val = get_setting_sync("test_key", default="default_val")
    assert val == "default_val"

    # Set key
    set_setting_sync("test_key", "real_val")

    # Get key again
    val = get_setting_sync("test_key")
    assert val == "real_val"


def test_get_setting_sync_exception():
    """Verify get_setting_sync exception fallback behavior."""
    with patch("sqlite3.connect", side_effect=sqlite3.Error("DB connection error")):
        val = get_setting_sync("any_key", default="fallback")
        assert val == "fallback"


def test_set_setting_sync_exception():
    """Verify set_setting_sync exception handling does not raise."""
    with patch("sqlite3.connect", side_effect=sqlite3.Error("DB connection error")):
        # Should catch and log error, not raise
        set_setting_sync("any_key", "any_val")


@pytest.mark.asyncio
async def test_get_set_setting_async(temp_db):
    """Verify asynchronous get and set setting operations."""
    # Try getting a non-existent key
    val = await get_setting_async("async_key", default="default_async")
    assert val == "default_async"

    # Set key
    await set_setting_async("async_key", "real_async_val")

    # Get key again
    val = await get_setting_async("async_key")
    assert val == "real_async_val"


@pytest.mark.asyncio
async def test_get_setting_async_exception():
    """Verify get_setting_async exception fallback behavior."""
    import aiosqlite

    with patch("aiosqlite.connect", side_effect=aiosqlite.Error("Async DB error")):
        val = await get_setting_async("any_key", default="async_fallback")
        assert val == "async_fallback"


@pytest.mark.asyncio
async def test_set_setting_async_exception():
    """Verify set_setting_async exception handling does not raise."""
    import aiosqlite

    with patch("aiosqlite.connect", side_effect=aiosqlite.Error("Async DB error")):
        # Should catch and log error, not raise
        await set_setting_async("any_key", "any_val")


@pytest.mark.asyncio
async def test_handle_test_failure_alert():
    """Verify handle_test_failure_alert invokes send_telegram_alert with message."""
    with patch("notifier.send_telegram_alert", new_callable=AsyncMock) as mock_alert:
        await handle_test_failure_alert("test_file.py", "Traceback info")
        mock_alert.assert_called_once()
        call_msg = mock_alert.call_args[0][0]
        assert "Test Failure Detected!" in call_msg
        assert "test_file.py" in call_msg
        assert "Traceback info" in call_msg


@pytest.mark.asyncio
async def test_handle_test_failure_alert_exception():
    """Verify handle_test_failure_alert handles notifier exceptions gracefully."""
    with patch(
        "notifier.send_telegram_alert",
        side_effect=Exception("Telegram connection failed"),
    ):
        # Should not raise exception
        await handle_test_failure_alert("test_file.py", "Traceback info")


@pytest.mark.asyncio
async def test_handle_health_check_transition_ok_to_error(temp_db):
    """Verify transition from OK (or None) to ERROR triggers a telegram alert."""
    # Set previous status to OK
    await set_setting_async("health_db_check", "OK")

    with patch("notifier.send_telegram_alert", new_callable=AsyncMock) as mock_alert:
        await handle_health_check_transition("db_check", "ERROR", "Connection refused")
        mock_alert.assert_called_once()
        call_msg = mock_alert.call_args[0][0]
        assert "System Health Check Failed!" in call_msg
        assert "db_check" in call_msg
        assert "ERROR" in call_msg
        assert "Connection refused" in call_msg

    # Verify status in DB updated to ERROR
    status = await get_setting_async("health_db_check")
    assert status == "ERROR"


@pytest.mark.asyncio
async def test_handle_health_check_transition_no_alert_on_same_status(temp_db):
    """Verify no telegram alert is sent if status remains ERROR."""
    # Set previous status to ERROR
    await set_setting_async("health_db_check", "ERROR")

    with patch("notifier.send_telegram_alert", new_callable=AsyncMock) as mock_alert:
        await handle_health_check_transition(
            "db_check", "ERROR", "Still connection refused"
        )
        mock_alert.assert_not_called()


@pytest.mark.asyncio
async def test_handle_health_check_transition_exception(temp_db):
    """Verify handle_health_check_transition handles notifier exceptions gracefully."""
    await set_setting_async("health_db_check", "OK")

    with patch(
        "notifier.send_telegram_alert",
        side_effect=Exception("Telegram connection failed"),
    ):
        # Should not raise exception
        await handle_health_check_transition("db_check", "ERROR", "Error message")
