from unittest.mock import AsyncMock, patch

import pytest

from workers.liveness_monitor import (
    ServerHealth,
    _handle_failure,
    announce_server_online,
)


@pytest.mark.asyncio
async def test_liveness_monitor_failures_flow():
    # Setup test server health tracker
    server = ServerHealth(name="SERVER_TEST", url="http://test-server/health")

    # Mocking alerts
    with (
        patch(
            "workers.liveness_monitor._send_down_alert", new_callable=AsyncMock
        ) as mock_down,
        patch(
            "workers.liveness_monitor._send_offline_alert", new_callable=AsyncMock
        ) as mock_offline,
    ):
        # Failure 1: consecutive_failures -> 1
        await _handle_failure(server, "Connection refused")
        assert server.consecutive_failures == 1
        assert server.is_healthy is False
        assert server.is_offline is False
        assert server.alerted_down is False
        mock_down.assert_not_called()
        mock_offline.assert_not_called()

        # Failure 2: consecutive_failures -> 2 (ALERT_AFTER_FAILURES threshold)
        await _handle_failure(server, "Connection refused")
        assert server.consecutive_failures == 2
        assert server.is_healthy is False
        assert server.is_offline is False
        assert server.alerted_down is True
        mock_down.assert_called_once_with(server, "Connection refused")
        mock_offline.assert_not_called()

        mock_down.reset_mock()

        # Failure 3: consecutive_failures -> 3 (OFFLINE_THRESHOLD)
        # It should send the offline alert and set is_offline to True, even if alerted_down is True.
        await _handle_failure(server, "Connection refused")
        assert server.consecutive_failures == 3
        assert server.is_healthy is False
        assert server.is_offline is True
        assert server.alerted_down is True
        mock_down.assert_not_called()
        mock_offline.assert_called_once_with(server, "Connection refused")


@pytest.mark.asyncio
async def test_announce_server_online_recovery():
    # Setup test server health tracker
    server = ServerHealth(name="SERVER_TEST", url="http://test-server/health")
    server.is_offline = True
    server.is_healthy = False
    server.consecutive_failures = 3
    server.alerted_down = True
    server.last_error = "Connection refused"

    with patch("workers.liveness_monitor._get_servers", return_value=[server]):
        res = announce_server_online("SERVER_TEST")
        assert res["status"] == "ok"
        assert res["server"] == "SERVER_TEST"
        assert server.is_offline is False
        assert server.is_healthy is True
        assert server.consecutive_failures == 0
        assert server.alerted_down is False
        assert server.last_error == ""
