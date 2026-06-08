import time
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from workers.ntp_monitor import check_clock_drift, _get_server_urls


@pytest.fixture(autouse=True)
def reset_globals():
    import workers.ntp_monitor

    workers.ntp_monitor._SERVER_URLS = {}
    workers.ntp_monitor.last_drift_results = {}


def test_get_server_urls():
    with patch(
        "os.getenv",
        side_effect=lambda key, default="": {
            "SERVER_A_HEALTH_URL": "http://server-a/health",
            "SERVER_B_HEALTH_URL": "",
        }.get(key, default),
    ):
        urls = _get_server_urls()
        assert urls == {"SERVER_A": "http://server-a/health"}


@pytest.mark.asyncio
async def test_ntp_monitor_no_urls():
    with patch("workers.ntp_monitor._get_server_urls", return_value={}):
        res = await check_clock_drift()
        assert res == {}


@pytest.mark.asyncio
async def test_ntp_monitor_success_within_threshold():
    urls = {"SERVER_A": "http://server-a/health"}

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"server_time_epoch": time.time()}

    mock_client_instance = MagicMock()
    # Mock __aenter__ to return the client instance
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_client_instance.get = AsyncMock(return_value=mock_resp)

    with (
        patch("workers.ntp_monitor._get_server_urls", return_value=urls),
        patch("httpx.AsyncClient", return_value=mock_client_instance),
        patch("notifier.notify_all", new_callable=AsyncMock) as mock_notify,
    ):
        res = await check_clock_drift()
        assert "SERVER_A" in res
        assert res["SERVER_A"]["ok"] is True
        assert res["SERVER_A"]["drift_ms"] is not None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_ntp_monitor_drift_alert():
    urls = {"SERVER_A": "http://server-a/health"}

    # 2 seconds behind local time (drift is > 500 ms)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"server_time_epoch": time.time() - 2.0}

    mock_client_instance = MagicMock()
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_client_instance.get = AsyncMock(return_value=mock_resp)

    with (
        patch("workers.ntp_monitor._get_server_urls", return_value=urls),
        patch("httpx.AsyncClient", return_value=mock_client_instance),
        patch("notifier.notify_all", new_callable=AsyncMock) as mock_notify,
    ):
        res = await check_clock_drift()
        assert "SERVER_A" in res
        assert res["SERVER_A"]["ok"] is False
        mock_notify.assert_called_once()
        assert "CLOCK DRIFT ALERT" in mock_notify.call_args[0][0]


@pytest.mark.asyncio
async def test_ntp_monitor_missing_epoch():
    urls = {"SERVER_A": "http://server-a/health"}

    mock_resp = MagicMock()
    mock_resp.json.return_value = {}  # missing server_time_epoch

    mock_client_instance = MagicMock()
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_client_instance.get = AsyncMock(return_value=mock_resp)

    with (
        patch("workers.ntp_monitor._get_server_urls", return_value=urls),
        patch("httpx.AsyncClient", return_value=mock_client_instance),
        patch("notifier.notify_all", new_callable=AsyncMock) as mock_notify,
    ):
        res = await check_clock_drift()
        assert res["SERVER_A"]["drift_ms"] is None
        assert res["SERVER_A"]["ok"] is None
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_ntp_monitor_connection_error():
    urls = {"SERVER_A": "http://server-a/health"}

    mock_client_instance = MagicMock()
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_client_instance.get.side_effect = httpx.ConnectError("Connection failed")

    with (
        patch("workers.ntp_monitor._get_server_urls", return_value=urls),
        patch("httpx.AsyncClient", return_value=mock_client_instance),
        patch("notifier.notify_all", new_callable=AsyncMock) as mock_notify,
    ):
        res = await check_clock_drift()
        assert res["SERVER_A"]["drift_ms"] is None
        assert res["SERVER_A"]["ok"] is False
        mock_notify.assert_not_called()
