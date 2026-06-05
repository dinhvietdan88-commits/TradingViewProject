import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import shutil
import time

from capture_client import PythonCaptureClient


@pytest.fixture
def temp_test_dir():
    d = Path(__file__).resolve().parent / "temp_routing_charts"
    d.mkdir(exist_ok=True)
    yield d
    if d.exists():
        shutil.rmtree(d)


@pytest.mark.asyncio
async def test_in_memory_cache():
    client = PythonCaptureClient()
    client._ohlcv_cache_ttl = 5  # 5 seconds

    # Pre-populate cache
    cache_key = ("BTCUSDT", "1h")
    mock_data = [[1716240000000, 100, 105, 95, 102, 1000]]
    client._ohlcv_cache[cache_key] = {"timestamp": time.time(), "data": mock_data}

    # Query data
    data = await client._get_ohlcv_data("BTCUSDT", "1h", limit=100)
    assert data == mock_data

    # Test expired cache (simulate timestamp in the past)
    client._ohlcv_cache[cache_key]["timestamp"] = time.time() - 10

    # Mock external fetch so it returns new data
    new_data = [[1716240000000, 200, 205, 195, 202, 2000]]
    with patch.object(
        client, "_fetch_ohlcv_from_exchange", AsyncMock(return_value=new_data)
    ):
        data = await client._get_ohlcv_data("BTCUSDT", "1h", limit=100)
        assert data == new_data


@pytest.mark.asyncio
async def test_hierarchical_resolution(temp_test_dir):
    client = PythonCaptureClient()

    # Mock actual rendering and exchange fetch
    mock_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]

    # 1. Test explicit parameter override (method="mplfinance")
    with (
        patch.object(client, "_get_ohlcv_data", AsyncMock(return_value=mock_ohlcv)),
        patch("utils.chart_generator_mpl.generate_chart_mpl") as mock_mpl,
    ):
        mock_mpl.return_value = temp_test_dir / "mpl_test.png"
        (temp_test_dir / "mpl_test.png").touch()  # create dummy file

        res = await client.capture_screenshot(
            symbol="BTCUSDT",
            timeframe="1h",
            save_path=temp_test_dir / "test.png",
            method="mplfinance",
        )
        assert res.success
        assert res.method == "mplfinance"
        mock_mpl.assert_called_once()

    # 2. Test DB settings override
    with (
        patch.object(client, "_get_ohlcv_data", AsyncMock(return_value=mock_ohlcv)),
        patch("database.get_setting", AsyncMock(return_value="mplfinance")),
        patch("utils.chart_generator_mpl.generate_chart_mpl") as mock_mpl,
    ):
        mock_mpl.return_value = temp_test_dir / "mpl_test2.png"
        (temp_test_dir / "mpl_test2.png").touch()

        res = await client.capture_screenshot(
            symbol="BTCUSDT", timeframe="1h", save_path=temp_test_dir / "test.png"
        )
        assert res.success
        assert res.method == "mplfinance"
        mock_mpl.assert_called_once()


@pytest.mark.asyncio
async def test_playwright_rendering_fallback(temp_test_dir):
    client = PythonCaptureClient()
    mock_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]

    # Force lightweight-charts first, but mock its generator to raise an error
    # It should fallback to mplfinance automatically!
    with (
        patch.object(client, "_get_ohlcv_data", AsyncMock(return_value=mock_ohlcv)),
        patch(
            "utils.chart_generator_lw.generate_chart_lw",
            AsyncMock(side_effect=RuntimeError("Playwright error")),
        ),
        patch("utils.chart_generator_mpl.generate_chart_mpl") as mock_mpl,
    ):
        mock_mpl.return_value = temp_test_dir / "mpl_fallback.png"
        (temp_test_dir / "mpl_fallback.png").touch()

        res = await client.capture_screenshot(
            symbol="BTCUSDT",
            timeframe="1h",
            save_path=temp_test_dir / "test.png",
            method="lightweight-charts",
        )

        assert res.success
        # Should have fallen back to mplfinance
        assert res.method == "mplfinance"
        mock_mpl.assert_called_once()


@pytest.mark.asyncio
async def test_weex_ohlcv_fetch():
    client = PythonCaptureClient()

    mock_weex_response = [
        [
            "1779807600000",
            "76873.5",
            "76983.4",
            "76234.6",
            "76478.0",
            "6547.6317",
            "501180307.18849",
        ],
        [
            "1779804000000",
            "77198.8",
            "78056.3",
            "76683.0",
            "76873.5",
            "10387.0830",
            "803463776.92746",
        ],
    ]

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=mock_weex_response)

    # Configure mock session context manager
    mock_session_instance = MagicMock()
    mock_session_instance.get = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_resp))
    )

    # We must mock context manager `async with aiohttp.ClientSession() as session`
    # Python `__aenter__` on mock context manager returns the session instance.
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session_instance)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        # We pass BTCUSDT_UMCBL and it should fetch using 'weex' logic
        ohlcv = await client._fetch_ohlcv_from_exchange("BTCUSDT_UMCBL", "1h", limit=2)

        # Verify call URL matches expected format
        mock_session_instance.get.assert_called_once()
        call_url = mock_session_instance.get.call_args[0][0]
        assert "symbol=cmt_btcusdt" in call_url
        assert "granularity=1h" in call_url
        assert "limit=2" in call_url

        # Verify reversing and float conversion
        assert len(ohlcv) == 2
        assert ohlcv[0][0] == 1779804000000
        assert ohlcv[0][1] == 77198.8
        assert ohlcv[1][0] == 1779807600000
        assert ohlcv[1][1] == 76873.5


@pytest.mark.asyncio
async def test_weekly_ohlcv_fetch_and_resample():
    client = PythonCaptureClient()

    daily_candles = [
        [1716163200000, 100, 110, 90, 105, 1000],  # Monday May 20, 2026
        [1716249600000, 105, 115, 95, 110, 1000],  # Tuesday May 21, 2026
    ]

    async def mock_fetch_raw(symbol, interval, limit, exchange=None):
        if interval == "1w":
            raise RuntimeError("Direct weekly fetch failed")
        return daily_candles

    with patch.object(client, "_fetch_raw_ohlcv", side_effect=mock_fetch_raw):
        ohlcv = await client._fetch_ohlcv_from_exchange("BTCUSDT", "W", limit=1)
        assert len(ohlcv) == 1
        assert ohlcv[0][0] == 1716163200000
        assert ohlcv[0][1] == 100
        assert ohlcv[0][2] == 115
        assert ohlcv[0][3] == 90
        assert ohlcv[0][4] == 110
        assert ohlcv[0][5] == 2000


def test_weekly_ohlcv_resample_logic():
    client = PythonCaptureClient()

    daily_candles = [
        [1779062400000, 100, 105, 95, 101, 100],  # Mon May 18, 2026
        [1779148800000, 101, 110, 100, 108, 150],  # Tue May 19, 2026
        [1779235200000, 108, 109, 90, 95, 200],  # Wed May 20, 2026
        [1779667200000, 95, 105, 92, 103, 300],  # Mon May 25, 2026
        [1779753600000, 103, 104, 100, 102, 250],  # Tue May 26, 2026
    ]

    resampled = client._resample_daily_to_weekly(daily_candles)

    assert len(resampled) == 2
    assert resampled[0][0] == 1779062400000  # Mon May 18, 2026
    assert resampled[0][1] == 100  # open
    assert resampled[0][2] == 110  # high
    assert resampled[0][3] == 90  # low
    assert resampled[0][4] == 95  # close
    assert resampled[0][5] == 450  # volume

    assert resampled[1][0] == 1779667200000  # Mon May 25, 2026
    assert resampled[1][1] == 95  # open
    assert resampled[1][2] == 105  # high
    assert resampled[1][3] == 92  # low
    assert resampled[1][4] == 102  # close
    assert resampled[1][5] == 550  # volume
