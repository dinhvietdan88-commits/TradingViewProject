import os
from unittest.mock import AsyncMock, patch

import pytest

import alert_manager
from scripts.autotest_watcher import extract_failure_details, parse_pytest_failures


@pytest.mark.asyncio
async def test_log_test_run_creates_file():
    log_path = alert_manager.log_file_path

    # Close and remove existing handlers to release the file handle/descriptor
    handlers = list(alert_manager.test_runs_logger.handlers)
    for h in handlers:
        h.close()
        alert_manager.test_runs_logger.removeHandler(h)

    if os.path.exists(log_path):
        try:
            os.remove(log_path)
        except OSError:
            pass

    # Re-add a new handler so that file gets recreated on disk
    import logging

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    formatter = logging.Formatter(
        "[%(asctime)s] | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    alert_manager.test_runs_logger.addHandler(file_handler)

    alert_manager.log_test_run(True, "15 passed, 0 failed")
    assert os.path.exists(log_path)
    with open(log_path, encoding="utf-8") as f:
        content = f.read()
        assert "PASSED" in content
        assert "15 passed, 0 failed" in content


def test_parse_pytest_failures_helper():
    mock_stdout = """
================================== FAILURES ===================================
________________________ test_cooldown_rejects_duplicate ________________________

    def test_cooldown_rejects_duplicate():
>       assert False
E       assert False

tests/unit/test_ai_analyzer.py:42: AssertionError
=========================== short test summary info ===========================
FAILED tests/unit/test_ai_analyzer.py::test_cooldown_rejects_duplicate - AssertionError: assert False
    """
    failures = parse_pytest_failures(mock_stdout)
    assert len(failures) == 1
    assert failures[0]["test_name"] == "test_cooldown_rejects_duplicate"
    assert "assert False" in failures[0]["traceback_short"]
    assert "AssertionError" in failures[0]["traceback_short"]


def test_extract_failure_details_fallback():
    mock_stdout = """
FAILED tests/unit/test_ai_analyzer.py::test_cooldown_rejects_duplicate - AssertionError: assert False
    """
    test_name, err = extract_failure_details(mock_stdout, "")
    assert (
        test_name == "tests/unit/test_ai_analyzer.py::test_cooldown_rejects_duplicate"
    )
    assert err == "AssertionError: assert False"


@pytest.mark.asyncio
async def test_health_check_transition():
    with (
        patch("alert_manager.get_setting_async", new_callable=AsyncMock) as mock_get,
        patch("alert_manager.set_setting_async", new_callable=AsyncMock) as mock_set,
        patch("notifier.send_telegram_alert", new_callable=AsyncMock) as mock_tg,
    ):
        mock_get.return_value = "OK"
        await alert_manager.handle_health_check_transition(
            "database", "ERROR", "DB locked"
        )
        mock_set.assert_called_with("health_database", "ERROR")
        mock_tg.assert_called_once()

        mock_tg.reset_mock()

        mock_get.return_value = "ERROR"
        await alert_manager.handle_health_check_transition(
            "database", "ERROR", "DB locked again"
        )
        mock_tg.assert_not_called()


@pytest.mark.asyncio
async def test_handle_test_failure_alert():
    with patch("notifier.send_telegram_alert", new_callable=AsyncMock) as mock_tg:
        await alert_manager.handle_test_failure_alert(
            "test_file.py", "AssertionError: test failed"
        )
        mock_tg.assert_called_once()
        called_args = mock_tg.call_args[0][0]
        assert "Test Failure Detected" in called_args
        assert "test_file.py" in called_args
        assert "AssertionError: test failed" in called_args
