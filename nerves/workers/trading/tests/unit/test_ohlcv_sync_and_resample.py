"""
Unit tests for OHLCV Candlestick Sync, Indicator helpers, RAM Resampling, and Feature Crystallization.
Milestone 2, Milestone 3, Milestone 4.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiosqlite

import config
import database
from capture_client import PythonCaptureClient
from workers.ohlcv_sync import (
    sync_ohlcv_all_symbols,
    get_sma,
    get_rsi,
    get_atr,
    calculate_crystallized_features,
)


# ── Indicator Helpers Tests ──────────────────────────────────────────────────


def test_get_sma():
    # Test insufficient data
    assert get_sma([10.0] * 4, 5) is None

    # Test correct calculation
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert get_sma(closes, 5) == 3.0
    assert get_sma(closes, 3) == 4.0  # (3 + 4 + 5) / 3 = 4.0


def test_get_rsi():
    # Test insufficient data
    assert get_rsi([10.0] * 14, 14) is None

    # Test flat data (no changes)
    closes = [100.0] * 16
    assert get_rsi(closes, 14) == 50.0

    # Test steadily rising prices (highly positive RSI)
    closes = [float(i) for i in range(100, 116)]
    rsi = get_rsi(closes, 14)
    assert rsi is not None
    assert rsi > 90.0


def test_get_atr():
    # Test insufficient data
    assert get_atr([10.0] * 14, [5.0] * 14, [8.0] * 14, 14) is None

    # Test stable true ranges
    highs = [10.0] * 16
    lows = [5.0] * 16
    closes = [8.0] * 16  # TR is max(10-5, 10-8, 8-5) = 5
    atr = get_atr(highs, lows, closes, 14)
    assert atr is not None
    assert abs(atr - 5.0) < 1e-6


# ── Sync Daemon Integration Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_ohlcv_all_symbols():
    """Verify that sync_ohlcv_all_symbols fetches watchlist and stores candles in DB."""
    # Mock watchlist to return a single symbol
    mock_watchlist = ["BTCUSDT"]

    # Generate 200 candles for 5m, 250 for 1d
    now_ms = int(time.time() * 1000)
    mock_5m_candles = [
        [now_ms - i * 300000, 100.0, 105.0, 95.0, 102.0, 1000.0] for i in range(200)
    ]
    mock_5m_candles.reverse()

    mock_1d_candles = [
        [now_ms - i * 86400000, 100.0, 105.0, 95.0, 102.0, 1000.0] for i in range(250)
    ]
    mock_1d_candles.reverse()

    # Create mock capture client
    mock_client = MagicMock(spec=PythonCaptureClient)

    async def mock_fetch(symbol, timeframe, limit, force_exchange=False):
        if timeframe == "5m":
            return mock_5m_candles[:limit]
        elif timeframe == "1d":
            return mock_1d_candles[:limit]
        return []

    mock_client.fetch_ohlcv = AsyncMock(side_effect=mock_fetch)

    with (
        patch("workers.ohlcv_sync.get_watchlist", return_value=mock_watchlist),
        patch("workers.ohlcv_sync.get_capture_client", return_value=mock_client),
    ):
        await sync_ohlcv_all_symbols()

    # Query the SQLite DB to ensure data was written
    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            "SELECT count(*) FROM ohlcv_5m WHERE symbol = 'BTCUSDT'"
        ) as cursor:
            count_5m = (await cursor.fetchone())[0]
            assert count_5m == 200

        async with db.execute(
            "SELECT count(*) FROM ohlcv_1d WHERE symbol = 'BTCUSDT'"
        ) as cursor:
            count_1d = (await cursor.fetchone())[0]
            assert count_1d == 250


# ── RAM Resampling Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_client_resampling():
    """Test PythonCaptureClient resampling 5m to 30m, 1h, and 4h using pandas."""
    # Bypass the global autouse mock_global_capture_client for this test
    client = PythonCaptureClient()

    # Prepopulate database with 250 valid 5m candles (no gaps, not stale)
    # 5m interval is 300,000 ms. We use millisecond timestamps.
    now_ms = int(time.time() * 1000)
    # We populate 250 candles ending at now
    ohlcv_5m = []
    for i in range(250):
        # 5m interval
        ts = now_ms - (249 - i) * 300000
        # open, high, low, close, volume
        ohlcv_5m.append(
            ["BTCUSDT", ts, 100.0 + i, 105.0 + i, 95.0 + i, 102.0 + i, 10.0]
        )

    await database.insert_ohlcv_batch("5m", ohlcv_5m)

    # Let's verify _get_ohlcv_data correctly resamples 5m to 30m
    # 30m limit = 10. We expect 10 resampled candles.
    resampled = await client._get_ohlcv_data("BTCUSDT", "30m", limit=10)
    assert len(resampled) == 10

    # Verify values logic (e.g. open should be from the first 5m of the 30m, close from the last)
    # A 30m candle combines 6 x 5m candles.
    # Check volume sum: each 5m candle had volume 10.0. So 30m candle must have volume 60.0.
    assert resampled[0][5] == 60.0


# ── Feature Crystallization Tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calculate_crystallized_features():
    """Verify calculate_crystallized_features retrieves candles and calculates indicators."""
    PythonCaptureClient()

    # Populate database with 250 valid 5m candles and 250 valid 1d candles
    now_ms = int(time.time() * 1000)

    # 5m candles
    ohlcv_5m = []
    for i in range(250):
        ts = now_ms - (249 - i) * 300000
        ohlcv_5m.append(["BTCUSDT", ts, 100.0, 102.0, 98.0, 101.0, 10.0])
    await database.insert_ohlcv_batch("5m", ohlcv_5m)

    # 1d candles
    ohlcv_1d = []
    for i in range(250):
        ts = now_ms - (249 - i) * 86400000
        ohlcv_1d.append(["BTCUSDT", ts, 100.0, 102.0, 98.0, 101.0, 10.0])
    await database.insert_ohlcv_batch("1d", ohlcv_1d)

    # We need to un-mock capture client fetch_ohlcv or let calculate_crystallized_features use a custom patched client
    mock_client = PythonCaptureClient()
    with (
        patch.object(
            PythonCaptureClient, "fetch_ohlcv", side_effect=mock_client._get_ohlcv_data
        ),
        patch("workers.ohlcv_sync.get_capture_client", return_value=mock_client),
    ):
        features = await calculate_crystallized_features("BTCUSDT")

    # Verify structure
    assert "5m" in features
    assert "1d" in features
    for tf in ("5m", "1d"):
        for indicator in ("sma50", "sma150", "sma200", "rsi14", "atr14"):
            assert indicator in features[tf]
            assert features[tf][indicator] is not None
            assert isinstance(features[tf][indicator], float)


# ── Signal Feature Integration Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_insert_signal_with_dynamic_features():
    """Verify that inserting a signal triggers dynamic feature crystallization if analysis_features is None."""
    # Pre-populate DB with enough candles so crystallization works
    now_ms = int(time.time() * 1000)
    ohlcv_5m = [
        ["BTCUSDT", now_ms - (249 - i) * 300000, 100.0, 102.0, 98.0, 101.0, 10.0]
        for i in range(250)
    ]
    ohlcv_1d = [
        ["BTCUSDT", now_ms - (249 - i) * 86400000, 100.0, 102.0, 98.0, 101.0, 10.0]
        for i in range(250)
    ]

    await database.insert_ohlcv_batch("5m", ohlcv_5m)
    await database.insert_ohlcv_batch("1d", ohlcv_1d)

    # Insert a signal with analysis_features=None (default)
    client = PythonCaptureClient()
    with patch.object(
        PythonCaptureClient, "fetch_ohlcv", side_effect=client._get_ohlcv_data
    ):
        sig_id = await database.insert_signal("BTCUSDT", "buy", 100.0)

    # Retrieve the signal and verify that analysis_features is populated
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM signals WHERE id = ?", (sig_id,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row["analysis_features"] is not None

            import json

            features = json.loads(row["analysis_features"])
            assert "5m" in features
            assert "1d" in features
            assert features["5m"]["sma50"] is not None
            assert features["1d"]["sma50"] is not None


# ── Adversarial / Stress Tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_gap_detection_triggers_exchange_fallback():
    """Assert that gaps and stale candles are correctly identified and trigger exchange fallbacks."""
    client = PythonCaptureClient()

    # Clean DB first
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m")
        await db.commit()
    client._ohlcv_cache.clear()

    now_ms = int(time.time() * 1000)

    # Scenario A: Extremely large gap (e.g. 30 minutes instead of 5 minutes between two candles)
    ohlcv_with_gap = []
    for i in range(250):
        # 5m interval is 300,000 ms. We introduce a gap of 1,800,000 ms (30m) at index 100
        if i > 100:
            ts = now_ms - (249 - i) * 300000 + 1500000
        else:
            ts = now_ms - (249 - i) * 300000
        ohlcv_with_gap.append(["BTCUSDT", ts, 100.0, 105.0, 95.0, 102.0, 10.0])

    await database.insert_ohlcv_batch("5m", ohlcv_with_gap)

    # Mock fallback exchange method
    mock_exchange_data = [[now_ms, 100.0, 105.0, 95.0, 102.0, 10.0]]
    with patch.object(
        PythonCaptureClient, "_fetch_ohlcv_from_exchange", new_callable=AsyncMock
    ) as mock_fetch:
        mock_fetch.return_value = mock_exchange_data

        # This should fail validation due to the gap, triggering the fallback
        result = await client._get_ohlcv_data("BTCUSDT", "5m", limit=250)

        mock_fetch.assert_called_once_with("BTCUSDT", "5m", 250)
        assert result == mock_exchange_data

    # Clear DB for next scenario
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m")
        await db.commit()
    client._ohlcv_cache.clear()

    # Scenario B: Stale last candle (e.g. last candle is 2 hours old)
    ohlcv_stale = []
    stale_now_ms = now_ms - 2 * 3600 * 1000  # 2 hours ago
    for i in range(250):
        ts = stale_now_ms - (249 - i) * 300000
        ohlcv_stale.append(["BTCUSDT", ts, 100.0, 105.0, 95.0, 102.0, 10.0])

    await database.insert_ohlcv_batch("5m", ohlcv_stale)

    with patch.object(
        PythonCaptureClient, "_fetch_ohlcv_from_exchange", new_callable=AsyncMock
    ) as mock_fetch:
        mock_fetch.return_value = mock_exchange_data
        result = await client._get_ohlcv_data("BTCUSDT", "5m", limit=250)
        mock_fetch.assert_called_once_with("BTCUSDT", "5m", 250)
        assert result == mock_exchange_data


@pytest.mark.asyncio
async def test_resampler_robustness_extreme_inputs():
    """Assert that the resampler handles single-element datasets, volume=0, and high volatility without crashing."""
    client = PythonCaptureClient()
    # Align now_ms to a 30-minute boundary to guarantee all candles fall neatly inside bins and do not randomly split across UTC boundaries.
    now_ms = (int(time.time() * 1000) // 1800000) * 1800000

    # Clean the DB first
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m")
        await db.commit()
    client._ohlcv_cache.clear()

    # Scenario A: Single-element dataset (with validation bypassed)
    # We populate exactly 1 candle and force validation to pass
    single_candle = [["BTCUSDT", now_ms, 100.0, 105.0, 95.0, 102.0, 10.0]]
    await database.insert_ohlcv_batch("5m", single_candle)

    with patch.object(PythonCaptureClient, "_validate_candles", return_value=True):
        # resample to 30m with limit 1
        resampled = await client._get_ohlcv_data("BTCUSDT", "30m", limit=1)
        assert len(resampled) == 1
        assert resampled[0][1] == 100.0  # open
        assert resampled[0][2] == 105.0  # high
        assert resampled[0][3] == 95.0  # low
        assert resampled[0][4] == 102.0  # close
        assert resampled[0][5] == 10.0  # volume

    # Scenario B: Volume = 0
    # Clean DB and populate with zero volume
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m")
        await db.commit()
    client._ohlcv_cache.clear()

    ohlcv_zero_vol = []
    for i in range(12):
        ts = now_ms + i * 300000
        ohlcv_zero_vol.append(
            ["BTCUSDT", ts, 100.0, 105.0, 95.0, 102.0, 0.0]
        )  # volume = 0
    await database.insert_ohlcv_batch("5m", ohlcv_zero_vol)

    with patch.object(PythonCaptureClient, "_validate_candles", return_value=True):
        # resample to 30m (combines 6 candles). 12 candles resample to 2 candles of 30m.
        resampled = await client._get_ohlcv_data("BTCUSDT", "30m", limit=2)
        assert len(resampled) == 2
        assert resampled[0][5] == 0.0  # volume sum is 0.0
        assert resampled[1][5] == 0.0  # volume sum is 0.0

    # Scenario C: High volatility kline series
    # Clean DB and populate with highly volatile prices
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m")
        await db.commit()
    client._ohlcv_cache.clear()

    ohlcv_volatile = []
    # 6 candles of 5m (resamples to 1 candle of 30m)
    # Volatility range from 0.0001 to 1000000.0
    prices = [
        (100.0, 1000.0, 50.0, 500.0),
        (500.0, 10000.0, 400.0, 8000.0),
        (8000.0, 1000000.0, 7000.0, 50000.0),
        (50000.0, 60000.0, 0.0001, 10.0),
        (10.0, 100.0, 5.0, 90.0),
        (90.0, 150.0, 80.0, 120.0),
    ]
    for i in range(6):
        ts = now_ms + i * 300000
        open_p, high_p, low_p, close_p = prices[i]
        ohlcv_volatile.append(["BTCUSDT", ts, open_p, high_p, low_p, close_p, 15.0])
    await database.insert_ohlcv_batch("5m", ohlcv_volatile)

    with patch.object(PythonCaptureClient, "_validate_candles", return_value=True):
        resampled = await client._get_ohlcv_data("BTCUSDT", "30m", limit=1)
        assert len(resampled) == 1
        # Open of the first 5m candle
        assert resampled[0][1] == 100.0
        # Max high across all 6 candles
        assert resampled[0][2] == 1000000.0
        # Min low across all 6 candles
        assert resampled[0][3] == 0.0001
        # Close of the last 5m candle
        assert resampled[0][4] == 120.0
        # Sum of volumes
        assert resampled[0][5] == 15.0 * 6


@pytest.mark.asyncio
async def test_signal_features_zero_candles_in_db():
    """Assert that signal features calculations return None instead of crashing when DB has zero candles."""
    # Ensure database is empty of candles
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m")
        await db.execute("DELETE FROM ohlcv_1d")
        await db.commit()

    # Mock python capture client to return empty lists from exchange as well
    PythonCaptureClient()
    with patch.object(PythonCaptureClient, "fetch_ohlcv", return_value=[]):
        # Call calculate_crystallized_features directly
        features = await calculate_crystallized_features("BTCUSDT")

        # Verify all indicators are None
        for tf in ("5m", "1d"):
            for indicator in ("sma50", "sma150", "sma200", "rsi14", "atr14"):
                assert features[tf][indicator] is None

        # Verify insert_signal does not crash and populates analysis_features with JSON containing None values
        sig_id = await database.insert_signal("BTCUSDT", "buy", 100.0)

        async with aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT analysis_features FROM signals WHERE id = ?", (sig_id,)
            ) as cursor:
                row = await cursor.fetchone()
                assert row is not None
                assert row["analysis_features"] is not None

                import json

                saved_features = json.loads(row["analysis_features"])
                for tf in ("5m", "1d"):
                    for indicator in ("sma50", "sma150", "sma200", "rsi14", "atr14"):
                        assert saved_features[tf][indicator] is None


# ── Robustness & Stress Tests (Empirical Challenger) ──────────────────────────


@pytest.mark.asyncio
async def test_resampling_performance_and_accuracy_stress():
    """Stress test resampling performance and mathematical accuracy under high load."""
    import asyncio

    client = PythonCaptureClient()
    symbol = "STRESSUSDT"

    # Clean the DB first to prevent pollution from previous runs
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m WHERE symbol = ?", (symbol,))
        await db.commit()

    # Ensure aligned start time ending near now to pass the staleness check
    now_ms = int(time.time() * 1000)
    # Align start time to a 4-hour boundary (14400000 ms) so that all resampled intervals (30m, 1h, 4h) align perfectly
    start_time_ms = ((now_ms - 5000 * 300000) // 14400000) * 14400000

    # 5,000 candles of 5m
    ohlcv_5m = []
    for i in range(5000):
        ts = start_time_ms + i * 300000
        ohlcv_5m.append(
            [
                symbol,
                ts,
                float(i + 100),  # open
                float(i + 105),  # high
                float(i + 97),  # low
                float(i + 101),  # close
                10.0,  # volume
            ]
        )

    # Insert batch into DB
    await database.insert_ohlcv_batch("5m", ohlcv_5m)

    # Let's run a stress loop: resample 30m, 1h, 4h concurrently in 50 tasks (total 150 resamples)
    import time as time_mod

    start_perf = time_mod.perf_counter()

    async def run_resample(tf, limit):
        return await client._get_ohlcv_data(symbol, tf, limit=limit)

    tasks = []
    # 50 tasks for 30m
    tasks.extend([run_resample("30m", 100) for _ in range(50)])
    # 50 tasks for 1h
    tasks.extend([run_resample("1h", 100) for _ in range(50)])
    # 50 tasks for 4h
    tasks.extend([run_resample("4h", 100) for _ in range(50)])

    # Mock _validate_candles to return True to prevent staleness/gap checks and fallbacks to exchange
    with patch.object(PythonCaptureClient, "_validate_candles", return_value=True):
        results = await asyncio.gather(*tasks)
        duration = time_mod.perf_counter() - start_perf
        avg_ms = (duration / 150) * 1000
        print(
            f"\nResampling stress test: 150 operations completed in {duration:.4f}s (avg: {avg_ms:.2f}ms/op)"
        )

        # Verify we got correct lists
        assert len(results) == 150
        for res in results:
            assert len(res) == 100

        # Cache contamination prevention: clear cache before fetching with larger limits
        client._ohlcv_cache.clear()

        # Mathematically verify resampling accuracy
        # 5000 / 6 = 833.33 -> resampler produces 834 candles.
        # Request limit=834 to avoid slicing that would discard initial candles.
        all_res_30m = await client._get_ohlcv_data(symbol, "30m", limit=834)
        assert len(all_res_30m) >= 834

        for g in range(833):
            # resampled candle index g (chronological order)
            # corresponds to ohlcv_5m from index 6*g to 6*g + 5
            candle = all_res_30m[g]
            expected_ts = start_time_ms + (6 * g) * 300000
            assert candle[0] == expected_ts
            assert candle[1] == 6 * g + 100.0  # open
            assert (
                candle[2] == 6 * g + 110.0
            )  # high (max of 6*g+j+105 is 6*g+5+105 = 6*g+110)
            assert candle[3] == 6 * g + 97.0  # low (min of 6*g+j+97 is 6*g+97)
            assert (
                candle[4] == 6 * g + 106.0
            )  # close (last close is 6*g+5+101 = 6*g+106)
            assert candle[5] == 60.0  # volume (6 * 10.0)

        # Also check 1h resampled candles
        # 5000 / 12 = 416.66 -> resampler produces 417 candles.
        # Request limit=417 to get the full series starting from index 0.
        all_res_1h = await client._get_ohlcv_data(symbol, "1h", limit=417)
        for g in range(416):
            candle = all_res_1h[g]
            expected_ts = start_time_ms + (12 * g) * 300000
            assert candle[0] == expected_ts
            assert candle[1] == 12 * g + 100.0  # open
            assert (
                candle[2] == 12 * g + 116.0
            )  # high (max of 12*g+j+105 is 12*g+11+105 = 12*g+116)
            assert candle[3] == 12 * g + 97.0  # low (min of 12*g+j+97 is 12*g+97)
            assert (
                candle[4] == 12 * g + 112.0
            )  # close (last close is 12*g+11+101 = 12*g+112)
            assert candle[5] == 120.0  # volume

        # Also check 4h resampled candles
        # 5000 / 48 = 104.16 -> resampler produces 105 candles.
        # Request limit=105 to get the full series starting from index 0.
        all_res_4h = await client._get_ohlcv_data(symbol, "4h", limit=105)
        for g in range(104):
            candle = all_res_4h[g]
            expected_ts = start_time_ms + (48 * g) * 300000
            assert candle[0] == expected_ts
            assert candle[1] == 48 * g + 100.0  # open
            assert (
                candle[2] == 48 * g + 152.0
            )  # high (max of 48*g+j+105 is 48*g+47+105 = 48*g+152)
            assert candle[3] == 48 * g + 97.0  # low (min of 48*g+j+97 is 48*g+97)
            assert (
                candle[4] == 48 * g + 148.0
            )  # close (last close is 48*g+47+101 = 48*g+148)
            assert candle[5] == 480.0  # volume

    assert duration < 60.0  # Resampling should be reasonably fast


@pytest.mark.asyncio
async def test_sync_daemon_resilience():
    """Verify that sync_ohlcv_all_symbols correctly retries/skips and doesn't crash on various exchange errors."""
    import asyncio

    mock_watchlist = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    # Generate basic mock candles
    now_ms = int(time.time() * 1000)
    mock_candles_5m = [
        [now_ms - i * 300000, 100.0, 105.0, 95.0, 102.0, 1000.0] for i in range(200)
    ]
    mock_candles_5m.reverse()
    mock_candles_1d = [
        [now_ms - i * 86400000, 100.0, 105.0, 95.0, 102.0, 1000.0] for i in range(250)
    ]
    mock_candles_1d.reverse()

    mock_client = MagicMock(spec=PythonCaptureClient)

    # Setup the side effect raising timeouts, connection errors, and rate limits
    async def mock_fetch_ohlcv(symbol, timeframe, limit, force_exchange=False):
        if symbol == "BTCUSDT":
            if timeframe == "5m":
                raise asyncio.TimeoutError("Connection timed out to mock exchange API")
            elif timeframe == "1d":
                return mock_candles_1d[:limit]
        elif symbol == "ETHUSDT":
            if timeframe == "5m":
                return mock_candles_5m[:limit]
            elif timeframe == "1d":
                raise ConnectionResetError("Connection reset by peer")
        elif symbol == "SOLUSDT":
            if timeframe == "5m":
                return mock_candles_5m[:limit]
            elif timeframe == "1d":
                # Rate limit exceeded error
                raise Exception("Rate limit exceeded (429 Too Many Requests)")
        return []

    mock_client.fetch_ohlcv = AsyncMock(side_effect=mock_fetch_ohlcv)

    with (
        patch("workers.ohlcv_sync.get_watchlist", return_value=mock_watchlist),
        patch("workers.ohlcv_sync.get_capture_client", return_value=mock_client),
        patch("asyncio.sleep", return_value=None),  # instant sleeps
    ):
        # This call should succeed and NOT crash
        await sync_ohlcv_all_symbols()

    # Query the database to verify the correct batches were written
    async with aiosqlite.connect(config.DB_PATH) as db:
        # BTCUSDT: 5m failed (timeout), 1d succeeded
        async with db.execute(
            "SELECT count(*) FROM ohlcv_5m WHERE symbol = 'BTCUSDT'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 0
        async with db.execute(
            "SELECT count(*) FROM ohlcv_1d WHERE symbol = 'BTCUSDT'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 250

        # ETHUSDT: 5m succeeded, 1d failed (connection reset)
        async with db.execute(
            "SELECT count(*) FROM ohlcv_5m WHERE symbol = 'ETHUSDT'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 200
        async with db.execute(
            "SELECT count(*) FROM ohlcv_1d WHERE symbol = 'ETHUSDT'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 0

        # SOLUSDT: 5m succeeded, 1d failed (rate limit)
        async with db.execute(
            "SELECT count(*) FROM ohlcv_5m WHERE symbol = 'SOLUSDT'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 200
        async with db.execute(
            "SELECT count(*) FROM ohlcv_1d WHERE symbol = 'SOLUSDT'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_database_concurrency_stress():
    """Test concurrent insertions of signals and klines in separate connections under high load, ensuring no conflicts."""
    import asyncio
    import random

    # Build typical kline batch
    now_ms = int(time.time() * 1000)
    ohlcv_5m = [
        ["CONCURRENCYUSDT", now_ms - i * 300000, 100.0, 105.0, 95.0, 102.0, 1000.0]
        for i in range(100)
    ]

    # Mock crystallized features to avoid expensive/slow logic during concurrency test
    mock_features = {"5m": {"sma50": 100.0}, "1d": {"sma50": 100.0}}

    async def insert_signal_task(i):
        # Slightly offset start to stagger writes
        await asyncio.sleep(random.random() * 0.1)  # noqa: S311
        # Use mock features so we don't fetch or calculate features which makes db queries
        await database.insert_signal(
            symbol="CONCURRENCYUSDT",
            action="buy" if i % 2 == 0 else "sell",
            price=60000.0 + i,
            quote_qty=10.0,
            analysis_features=mock_features,
        )

    async def insert_ohlcv_task():
        await asyncio.sleep(random.random() * 0.1)  # noqa: S311
        await database.insert_ohlcv_batch("5m", ohlcv_5m)

    # Stagger 50 signal insertions and 50 ohlcv batch insertions in parallel
    tasks = []
    for i in range(50):
        tasks.append(insert_signal_task(i))
        tasks.append(insert_ohlcv_task())

    # This should run concurrently and NOT raise sqlite3.OperationalError (database is locked)
    await asyncio.gather(*tasks)

    # Verify all 50 signals were saved
    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            "SELECT count(*) FROM signals WHERE symbol = 'CONCURRENCYUSDT'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 50

        # Verify klines are present
        async with db.execute(
            "SELECT count(*) FROM ohlcv_5m WHERE symbol = 'CONCURRENCYUSDT'"
        ) as cursor:
            assert (await cursor.fetchone())[0] == 100


@pytest.mark.asyncio
async def test_capture_client_fallback_writes_to_db():
    """Verify that PythonCaptureClient writes fallback candles to the database when fetching from exchange."""
    client = PythonCaptureClient()
    symbol = "FALLBACK_TEST_USDT"

    # 1. Clear database for that symbol
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m WHERE symbol = ?", (symbol,))
        await db.commit()
    client._ohlcv_cache.clear()

    # 2. Mock exchange fetch
    # Make sure we use a timestamp within the last 2 hours to pass the staleness check!
    # A 5m interval is 300,000 ms.
    now_ms = int(time.time() * 1000)
    # Generate 5 valid candles
    dummy_candles = []
    for i in range(5):
        # timestamps in ms, e.g. 5 minutes apart, ending now
        ts = now_ms - (4 - i) * 300000
        dummy_candles.append([ts, 100.0 + i, 105.0 + i, 95.0 + i, 102.0 + i, 10.0])

    with patch.object(
        client, "_fetch_ohlcv_from_exchange", new_callable=AsyncMock
    ) as mock_fetch:
        mock_fetch.return_value = dummy_candles

        # 3. Call _get_ohlcv_data
        res = await client._get_ohlcv_data(symbol, "5m", limit=5, force_exchange=False)

        # 4. Assert fallback to exchange
        mock_fetch.assert_called_once_with(symbol, "5m", 5)
        assert res == dummy_candles

    # 5. Verify database contains the candles
    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv_5m WHERE symbol = ? ORDER BY timestamp ASC",
            (symbol,),
        ) as cursor:
            rows = await cursor.fetchall()

    assert len(rows) == 5
    for idx, row in enumerate(rows):
        assert row[0] == dummy_candles[idx][0]
        assert row[1] == dummy_candles[idx][1]
        assert row[2] == dummy_candles[idx][2]
        assert row[3] == dummy_candles[idx][3]
        assert row[4] == dummy_candles[idx][4]
        assert row[5] == dummy_candles[idx][5]
