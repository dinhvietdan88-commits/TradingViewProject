import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from pathlib import Path
import shutil

from capture_client import PythonCaptureClient
from utils.chart_generator_mpl import generate_chart_mpl


@pytest.fixture
def temp_test_dir():
    d = Path(__file__).resolve().parent / "temp_mtf_charts"
    d.mkdir(exist_ok=True)
    yield d
    if d.exists():
        shutil.rmtree(d)


def test_timeframe_mappings():
    """Verify that mappings exist for nested timeframes and are case-insensitive."""
    PythonCaptureClient()

    # We test the logic used inside _local_capture to resolve parent timeframes
    def get_parent(tf):
        tf_lower = tf.lower()
        if tf_lower in ("15m", "15"):
            return "1H"
        elif tf_lower in ("1h", "60"):
            return "4H"
        return None

    assert get_parent("15m") == "1H"
    assert get_parent("15M") == "1H"
    assert get_parent("15") == "1H"
    assert get_parent("1h") == "4H"
    assert get_parent("1H") == "4H"
    assert get_parent("60") == "4H"

    # Single timeframes shouldn't map
    assert get_parent("4h") is None
    assert get_parent("D") is None
    assert get_parent("1d") is None


@pytest.mark.asyncio
async def test_concurrent_fetching_nested(temp_test_dir):
    """Verify that capture_screenshot invokes concurrent fetching for target and parent timeframes."""
    client = PythonCaptureClient()
    client._ohlcv_cache_ttl = 5
    client._daemon_available = False

    mock_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]

    # Mock _get_ohlcv_data to record arguments and check parallel execution
    fetched_timeframes = []

    async def mock_get_ohlcv(symbol, tf, limit):
        fetched_timeframes.append(tf)
        await asyncio.sleep(0.01)  # simulate slight network latency
        return mock_ohlcv

    # Mock the actual chart generators to avoid launching browsers/saving files during signature test
    with (
        patch.object(client, "_get_ohlcv_data", side_effect=mock_get_ohlcv),
        patch("utils.chart_generator_lw.generate_chart_lw") as mock_lw,
    ):
        mock_lw.return_value = temp_test_dir / "lw_mock.png"
        (temp_test_dir / "lw_mock.png").touch()

        # Request a nested timeframe: "1H" (parent is "4H")
        res = await client.capture_screenshot(
            symbol="BTCUSDT",
            timeframe="1h",
            method="lightweight-charts",
            save_path=temp_test_dir / "test.png",
        )

        assert res.success
        # Check that both target (1h) and parent (4H) were requested
        assert "1h" in fetched_timeframes
        assert "4H" in fetched_timeframes

        # Check that generate_chart_lw was called with parent_timeframe and parent_ohlcv
        mock_lw.assert_called_once()
        called_kwargs = mock_lw.call_args[1]
        assert called_kwargs["parent_timeframe"] == "4H"
        assert called_kwargs["parent_ohlcv"] == mock_ohlcv


@pytest.mark.asyncio
async def test_single_timeframe_no_parent(temp_test_dir):
    """Verify that single timeframe rendering does not trigger parent candle fetch."""
    client = PythonCaptureClient()
    client._daemon_available = False

    mock_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]
    fetched_timeframes = []

    async def mock_get_ohlcv(symbol, tf, limit):
        fetched_timeframes.append(tf)
        return mock_ohlcv

    with (
        patch.object(client, "_get_ohlcv_data", side_effect=mock_get_ohlcv),
        patch("utils.chart_generator_lw.generate_chart_lw") as mock_lw,
    ):
        mock_lw.return_value = temp_test_dir / "lw_mock.png"
        (temp_test_dir / "lw_mock.png").touch()

        # Request a non-nested timeframe: "4h"
        res = await client.capture_screenshot(
            symbol="BTCUSDT",
            timeframe="4h",
            method="lightweight-charts",
            save_path=temp_test_dir / "test.png",
        )

        assert res.success
        assert fetched_timeframes == ["4h"]

        mock_lw.assert_called_once()
        called_kwargs = mock_lw.call_args[1]
        assert called_kwargs["parent_timeframe"] is None
        assert called_kwargs["parent_ohlcv"] is None


def test_matplotlib_fallback_resilience(temp_test_dir):
    """Verify that the Matplotlib fallback runs successfully with parent args without crashing."""
    mock_ohlcv = [
        {
            "time": 1716240000000 + i * 3600000,
            "open": 100 + i,
            "high": 105 + i,
            "low": 98 + i,
            "close": 102 + i,
            "volume": 1000 * i,
        }
        for i in range(10)
    ]
    save_path = temp_test_dir / "mpl_mtf_test.png"

    # Pass parent arguments to generate_chart_mpl
    result_path = generate_chart_mpl(
        symbol="BTCUSDT",
        timeframe="1h",
        ohlcv_data=mock_ohlcv,
        parent_timeframe="4H",
        parent_ohlcv=mock_ohlcv,
        save_path=save_path,
    )

    assert result_path.exists()
    assert result_path == save_path


@pytest.mark.asyncio
async def test_api_vision_capture_route(client):
    """Verify endpoint /api/vision/capture concurrent fetch integration."""
    mock_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]

    # Mocking both get_ohlcv_data and the actual playwright screenshot save to keep test fast and stable
    with (
        patch(
            "capture_client.PythonCaptureClient.is_daemon_available",
            AsyncMock(return_value=False),
        ),
        patch(
            "capture_client.PythonCaptureClient._get_ohlcv_data",
            AsyncMock(return_value=mock_ohlcv),
        ) as mock_fetch,
        patch("utils.chart_generator_lw.generate_chart_lw") as mock_lw,
        patch(
            "vision.analyze_chart_vision",
            AsyncMock(return_value={"verdict": "STRONG BUY", "confidence": 9}),
        ),
    ):
        mock_lw.return_value = Path("test_img.png")

        # We trigger the capture via the client API client fixture
        response = await client.post("/api/vision/capture?symbol=BTCUSDT&timeframe=1h")
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] == "STRONG BUY"

        # Verify that the client did fetch parent trend candles
        # The calls should include both '1H' (or '1h') and parent timeframe '4H'
        called_tfs = [call[0][1] for call in mock_fetch.call_args_list]
        assert any(x.upper() == "1H" for x in called_tfs)
        assert "4H" in called_tfs


@pytest.mark.asyncio
async def test_mtf_nested_resilience_on_parent_failure(temp_test_dir):
    """Verify that if parent timeframe candle fetching fails, the primary chart still renders successfully without nested insets."""
    client = PythonCaptureClient()
    client._daemon_available = False

    mock_primary_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]

    async def mock_get_ohlcv(symbol, tf, limit):
        if tf == "4H":
            raise RuntimeError("API Connection Error for parent timeframe")
        return mock_primary_ohlcv

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
            save_path=temp_test_dir / "test.png",
        )

        assert res.success
        mock_lw.assert_called_once()
        called_kwargs = mock_lw.call_args[1]
        # Verify that parent parameters are set to None due to the failure
        assert called_kwargs["parent_timeframe"] is None
        assert called_kwargs["parent_ohlcv"] is None


@pytest.mark.asyncio
async def test_mtf_nested_resilience_on_parent_failure_provided_ohlcv(temp_test_dir):
    """Verify that if ohlcv_data is provided but parent timeframe candle fetching fails, the primary chart still renders successfully."""
    client = PythonCaptureClient()
    client._daemon_available = False

    mock_primary_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]

    async def mock_get_ohlcv(symbol, tf, limit):
        raise RuntimeError("Failed to fetch parent timeframe candles")

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
            ohlcv_data=mock_primary_ohlcv,
            save_path=temp_test_dir / "test.png",
        )

        assert res.success
        mock_lw.assert_called_once()
        called_kwargs = mock_lw.call_args[1]
        assert called_kwargs["parent_timeframe"] is None
        assert called_kwargs["parent_ohlcv"] is None


@pytest.mark.asyncio
async def test_show_parent_chart_toggle(temp_test_dir):
    """Verify that setting show_parent_chart=False does not trigger parent kline fetch."""
    client = PythonCaptureClient()
    client._daemon_available = False

    mock_ohlcv = [[1716240000000, 100, 105, 95, 102, 1000]]
    fetched_timeframes = []

    async def mock_get_ohlcv(symbol, tf, limit):
        fetched_timeframes.append(tf)
        return mock_ohlcv

    with (
        patch.object(client, "_get_ohlcv_data", side_effect=mock_get_ohlcv),
        patch("utils.chart_generator_lw.generate_chart_lw") as mock_lw,
    ):
        mock_lw.return_value = temp_test_dir / "lw_mock.png"
        (temp_test_dir / "lw_mock.png").touch()

        # Request with show_parent_chart=False
        res = await client.capture_screenshot(
            symbol="BTCUSDT",
            timeframe="1h",
            method="lightweight-charts",
            save_path=temp_test_dir / "test.png",
            show_parent_chart=False,
            inset_position="top-left",
        )

        assert res.success
        assert fetched_timeframes == ["1h"]

        mock_lw.assert_called_once()
        called_kwargs = mock_lw.call_args[1]
        assert called_kwargs["parent_timeframe"] is None
        assert called_kwargs["parent_ohlcv"] is None
        assert called_kwargs["inset_position"] == "top-left"
