import asyncio
import shutil
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from capture_client import PythonCaptureClient


@pytest.fixture
def temp_test_dir():
    d = Path(__file__).resolve().parent / "temp_mtf_adversarial"
    d.mkdir(exist_ok=True)
    yield d
    if d.exists():
        shutil.rmtree(d)


@pytest.mark.asyncio
async def test_parent_fetch_failure_causes_total_failure(temp_test_dir):
    """
    CRITICAL EDGE CASE: If the primary timeframe fetch succeeds but the parent timeframe
    fetch fails, does the entire capture_screenshot call fail?
    No, under the new resilient design, parent fetch failure is handled gracefully and
    the request succeeds, rendering the primary chart as a single chart without nested insets.
    """
    client = PythonCaptureClient()
    client._daemon_available = False

    mock_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]

    async def mock_get_ohlcv(symbol, tf, limit):
        if tf == "4H":
            raise RuntimeError(
                "Parent fetch failed (e.g. rate limit, connection issue)"
            )
        return mock_ohlcv

    with (
        patch.object(client, "_get_ohlcv_data", side_effect=mock_get_ohlcv),
        patch("utils.chart_generator_lw.generate_chart_lw") as mock_lw,
    ):
        mock_lw.return_value = temp_test_dir / "lw_mock.png"
        (temp_test_dir / "lw_mock.png").touch()

        res = await client.capture_screenshot(
            symbol="BTCUSDT",
            timeframe="1h",
            method="lightweight-charts",
            save_path=temp_test_dir / "test_failed_parent.png",
        )

        # Assert overall capture call succeeds
        assert res.success

        # Assert that the returned payload has parent_candles=None and parent_timeframe=None
        # (in generate_chart_lw, parent_ohlcv corresponds to parent_candles)
        mock_lw.assert_called_once()
        called_kwargs = mock_lw.call_args[1]
        assert called_kwargs.get("parent_ohlcv") is None
        assert called_kwargs.get("parent_timeframe") is None


@pytest.mark.asyncio
async def test_parent_fetch_timeout_slows_down_primary(temp_test_dir):
    """
    PERFORMANCE / TIMEOUT: If the parent timeframe fetch is extremely slow,
    does it hold up the entire screenshot generation?
    """
    client = PythonCaptureClient()
    client._daemon_available = False

    mock_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]

    async def mock_get_ohlcv(symbol, tf, limit):
        if tf == "4H":
            await asyncio.sleep(1.0)  # simulate slow parent fetch
        return mock_ohlcv

    with (
        patch.object(client, "_get_ohlcv_data", side_effect=mock_get_ohlcv),
        patch("utils.chart_generator_lw.generate_chart_lw") as mock_lw,
    ):
        mock_lw.return_value = temp_test_dir / "lw_mock.png"
        (temp_test_dir / "lw_mock.png").touch()

        start_time = time.monotonic()
        res = await client.capture_screenshot(
            symbol="BTCUSDT",
            timeframe="1h",
            method="lightweight-charts",
            save_path=temp_test_dir / "test_slow_parent.png",
        )
        elapsed = time.monotonic() - start_time

        assert res.success
        # The entire operation is blocked by the slow parent fetch, taking >= 1.0s
        assert elapsed >= 1.0


@pytest.mark.asyncio
async def test_concurrency_load_mocked(temp_test_dir):
    """
    CONCURRENCY: Test concurrent requests to capture_screenshot under local rendering method.
    Verify that multiple requests can be scheduled concurrently.
    """
    client = PythonCaptureClient()
    client._daemon_available = False

    mock_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]

    async def mock_get_ohlcv(symbol, tf, limit):
        return mock_ohlcv

    with (
        patch.object(client, "_get_ohlcv_data", side_effect=mock_get_ohlcv),
        patch("utils.chart_generator_lw.generate_chart_lw") as mock_lw,
    ):
        mock_lw.return_value = temp_test_dir / "lw_mock.png"
        (temp_test_dir / "lw_mock.png").touch()

        # Launch 10 concurrent requests
        tasks = [
            client.capture_screenshot(
                symbol=f"BTCUSDT_{i}",
                timeframe="1h",
                method="lightweight-charts",
                save_path=temp_test_dir / f"test_concurrent_{i}.png",
            )
            for i in range(10)
        ]

        results = await asyncio.gather(*tasks)
        for res in results:
            assert res.success


@pytest.mark.asyncio
async def test_matplotlib_fallback_ignores_parent_data(temp_test_dir):
    """
    FALLBACK RESILIENCE: If Playwright fails, does the fallback to matplotlib succeed,
    and what happens to parent timeframe parameters?
    """
    client = PythonCaptureClient()
    client._daemon_available = False

    mock_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]

    async def mock_get_ohlcv(symbol, tf, limit):
        return mock_ohlcv

    # Mock lightweight-charts to raise an exception, causing fallback to mplfinance
    async def mock_generate_chart_lw(*args, **kwargs):
        raise RuntimeError("Playwright browser launch failed or timed out")

    with (
        patch.object(client, "_get_ohlcv_data", side_effect=mock_get_ohlcv),
        patch(
            "utils.chart_generator_lw.generate_chart_lw",
            side_effect=mock_generate_chart_lw,
        ),
        patch("utils.chart_generator_mpl.generate_chart_mpl") as mock_mpl,
    ):
        mock_mpl.return_value = temp_test_dir / "mpl_fallback.png"
        (temp_test_dir / "mpl_fallback.png").touch()

        res = await client.capture_screenshot(
            symbol="BTCUSDT",
            timeframe="1h",
            method="lightweight-charts",
            save_path=temp_test_dir / "test_fallback.png",
        )

        assert res.success
        assert res.method == "mplfinance"

        # Verify matplotlib was called with parent parameters even if it doesn't render them
        mock_mpl.assert_called_once()
        called_kwargs = mock_mpl.call_args[1]
        assert called_kwargs["parent_timeframe"] == "4H"
        assert called_kwargs["parent_ohlcv"] == mock_ohlcv
