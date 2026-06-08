import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from workers.disk_monitor import check_disk_usage, _get_dir_size_mb


@pytest.mark.asyncio
async def test_disk_monitor_ok():
    # Mock disk usage: 100 GB total, 50 GB used, 50 GB free (50%)
    mock_usage = (100 * (1024**3), 50 * (1024**3), 50 * (1024**3))

    with (
        patch("shutil.disk_usage", return_value=mock_usage),
        patch("workers.disk_monitor._get_dir_size_mb", return_value=10.5),
        patch("notifier.notify_all", new_callable=AsyncMock) as mock_notify,
    ):
        result = await check_disk_usage()

        assert result["used_pct"] == 50.0
        assert result["free_gb"] == 50.0
        assert result["total_gb"] == 100.0
        assert result["log_size_mb"] == 10.5
        assert result["status"] == "ok"
        mock_notify.assert_not_called()


@pytest.mark.asyncio
async def test_disk_monitor_warning():
    # Mock disk usage: 100 GB total, 85 GB used, 15 GB free (85%)
    mock_usage = (100 * (1024**3), 85 * (1024**3), 15 * (1024**3))

    with (
        patch("shutil.disk_usage", return_value=mock_usage),
        patch("workers.disk_monitor._get_dir_size_mb", return_value=20.0),
        patch("notifier.notify_all", new_callable=AsyncMock) as mock_notify,
    ):
        result = await check_disk_usage()

        assert result["used_pct"] == 85.0
        assert result["free_gb"] == 15.0
        assert result["status"] == "warning"
        mock_notify.assert_called_once()
        assert "DISK WARNING" in mock_notify.call_args[0][0]


@pytest.mark.asyncio
async def test_disk_monitor_critical():
    # Mock disk usage: 100 GB total, 95 GB used, 5 GB free (95%)
    mock_usage = (100 * (1024**3), 95 * (1024**3), 5 * (1024**3))

    with (
        patch("shutil.disk_usage", return_value=mock_usage),
        patch("workers.disk_monitor._get_dir_size_mb", return_value=30.0),
        patch("notifier.notify_all", new_callable=AsyncMock) as mock_notify,
    ):
        result = await check_disk_usage()

        assert result["used_pct"] == 95.0
        assert result["free_gb"] == 5.0
        assert result["status"] == "critical"
        mock_notify.assert_called_once()
        assert "DISK CRITICAL" in mock_notify.call_args[0][0]


def test_get_dir_size_mb():
    with patch("os.path.exists", return_value=False):
        assert _get_dir_size_mb("nonexistent_dir") == 0.0

    mock_entry1 = MagicMock()
    mock_entry1.is_file.return_value = True
    mock_entry1.stat.return_value.st_size = 1024 * 1024  # 1 MB

    mock_entry2 = MagicMock()
    mock_entry2.is_file.return_value = False  # Directory

    mock_entry3 = MagicMock()
    mock_entry3.is_file.return_value = True
    mock_entry3.stat.side_effect = OSError("Access denied")  # Simulate error

    with (
        patch("os.path.exists", return_value=True),
        patch("os.scandir", return_value=[mock_entry1, mock_entry2, mock_entry3]),
    ):
        size = _get_dir_size_mb("logs")
        assert size == 1.0  # Only mock_entry1 counts
