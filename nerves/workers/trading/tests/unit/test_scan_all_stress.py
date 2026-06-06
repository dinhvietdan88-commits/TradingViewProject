import sys
import pathlib
import asyncio
import gc
import os
import time
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Try to import psutil for memory measurement
try:
    import psutil
except ImportError:
    psutil = None

# Ensure the worker directory is in the sys.path for direct imports
trading_dir = pathlib.Path(__file__).resolve().parent.parent.parent
if str(trading_dir) not in sys.path:
    sys.path.insert(0, str(trading_dir))

from analysis import scan_all_configured_exchanges, ScanResult  # noqa: E402
import analysis as analysis_module  # noqa: E402

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_scan_all_concurrency_and_stress():
    """
    Stress test the 'Scan All' REST pipeline with 200 mock symbols.
    Verifies:
      1. Concurrency limits are strictly managed by the semaphore (<= 15 parallel requests).
      2. No deadlocks or race conditions under load.
      3. Memory/resource usage remains low and doesn't leak.
    """
    # 1. Setup 200 mock symbols
    num_symbols = 200
    mock_symbols = [f"SYM_{i}" for i in range(num_symbols)]

    # 2. Mock exchange registry & adapter
    mock_adapter = MagicMock()
    mock_adapter.exchange_name = "mock_exchange"
    mock_adapter.get_active_symbols = AsyncMock(return_value=mock_symbols)

    mock_registry = MagicMock()
    mock_registry.list_exchange_ids = MagicMock(return_value=["mock_exchange"])
    mock_registry.get_adapter = MagicMock(return_value=mock_adapter)

    # 3. Custom candle fetcher that simulates delay & tracks concurrency
    active_requests = 0
    max_active_requests = 0
    semaphore_violation = False
    request_lock = asyncio.Lock()

    # Generate mock candles to return (365 daily candles)
    mock_candles = []
    now_ms = int(time.time() * 1000)
    day_ms = 24 * 60 * 60 * 1000
    for i in range(365):
        ts = now_ms - (365 - i) * day_ms
        price = 100.0 + i * 0.5
        mock_candles.append(
            [
                ts,
                price,  # open
                price + 2.0,  # high
                price - 2.0,  # low
                price + 0.1,  # close
                1000.0,  # volume
            ]
        )

    async def mock_fetch_candles_with_retry(session, exchange_name, symbol, **kwargs):
        nonlocal active_requests, max_active_requests, semaphore_violation
        semaphore = kwargs.get("semaphore")

        if semaphore:
            await semaphore.acquire()
        try:
            async with request_lock:
                active_requests += 1
                if active_requests > max_active_requests:
                    max_active_requests = active_requests
                if active_requests > 15:
                    # If we exceed the semaphore limit, record it
                    semaphore_violation = True
                    logger.error(
                        f"Semaphore violation! Active requests: {active_requests}"
                    )

            # Simulate network latency of 15ms to make concurrent overlap visible
            await asyncio.sleep(0.015)

            async with request_lock:
                active_requests -= 1
        finally:
            if semaphore:
                semaphore.release()

        return mock_candles

    # Reset scan status
    analysis_module._scan_status = "idle"
    analysis_module._latest_scan_results = []
    analysis_module._scan_start_time = None
    analysis_module._scan_end_time = None
    analysis_module._scan_error = None

    # Measure memory usage before scan
    gc.collect()
    initial_mem = 0
    if psutil:
        initial_mem = psutil.Process(os.getpid()).memory_info().rss / (
            1024 * 1024
        )  # MB

    # Run the scan with mocks patched
    start_time = time.perf_counter()

    with (
        patch("exchanges.registry.get_registry", return_value=mock_registry),
        patch(
            "analysis.fetch_candles_with_retry",
            side_effect=mock_fetch_candles_with_retry,
        ),
    ):
        results = await scan_all_configured_exchanges()

    duration = time.perf_counter() - start_time

    # Measure memory usage after scan
    gc.collect()
    final_mem = 0
    if psutil:
        final_mem = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)  # MB

    # Assertions and Verifications
    print(f"\n--- Concurrency Stress Test Results ({num_symbols} symbols) ---")
    print(f"Total execution time: {duration:.2f} seconds")
    print(f"Max observed concurrent requests: {max_active_requests}")
    print("Semaphore Limit: 15")
    if psutil:
        print(f"Memory before: {initial_mem:.2f} MB")
        print(f"Memory after: {final_mem:.2f} MB")
        print(f"Memory diff: {final_mem - initial_mem:.2f} MB")
    print(f"Total symbols successfully scanned: {len(results)}")

    # 1. Verify semaphore limit is respected (we allow for minor timing tolerances in lock releases if any, but it should be exactly <= 15)
    assert max_active_requests <= 15, (
        f"Concurrency limit exceeded: {max_active_requests} > 15"
    )
    assert not semaphore_violation, "Semaphore violation was flagged during run."

    # 2. Verify all results were scanned and returned correctly
    assert len(results) == num_symbols
    assert all(isinstance(r, ScanResult) for r in results)
    for r in results:
        assert r.error is None
        assert r.trend_template is not None
        assert r.vcp is not None

    # 3. Memory Leak Check: Run scan multiple times and verify memory does not continuously grow
    if psutil:
        mems = []
        for _run_idx in range(4):
            analysis_module._scan_status = "idle"
            analysis_module._latest_scan_results = []

            with (
                patch("exchanges.registry.get_registry", return_value=mock_registry),
                patch(
                    "analysis.fetch_candles_with_retry",
                    side_effect=mock_fetch_candles_with_retry,
                ),
            ):
                await scan_all_configured_exchanges()

            gc.collect()
            mem_now = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
            mems.append(mem_now)

        print(f"Memory across 4 subsequent runs: {mems}")
        growth = mems[-1] - mems[0]
        print(f"Memory growth across runs: {growth:.2f} MB")
        assert growth < 10.0, (
            f"Potential memory leak detected: growth of {growth:.2f} MB"
        )


@pytest.mark.asyncio
async def test_scan_all_endpoint_stress(client):
    """
    Stress test `/api/scan/all?force=true` with 200 mock symbols.
    Verifies that triggering the endpoint runs the background task safely under the lock,
    respecting concurrency without deadlock.
    """
    num_symbols = 200
    mock_symbols = [f"SYM_{i}" for i in range(num_symbols)]

    # Mock exchange registry & adapter
    mock_adapter = MagicMock()
    mock_adapter.exchange_name = "mock_exchange"
    mock_adapter.get_active_symbols = AsyncMock(return_value=mock_symbols)

    mock_registry = MagicMock()
    mock_registry.list_exchange_ids = MagicMock(return_value=["mock_exchange"])
    mock_registry.get_adapter = MagicMock(return_value=mock_adapter)

    # Mock candles
    mock_candles = []
    now_ms = int(time.time() * 1000)
    day_ms = 24 * 60 * 60 * 1000
    for i in range(250):
        ts = now_ms - (250 - i) * day_ms
        price = 100.0 + i * 0.5
        mock_candles.append([ts, price, price + 2.0, price - 2.0, price + 0.1, 1000.0])

    async def mock_fetch_candles(session, exchange_name, symbol, **kwargs):
        await asyncio.sleep(0.005)
        return mock_candles

    # Set scan status to idle
    analysis_module._scan_status = "idle"
    analysis_module._latest_scan_results = []
    analysis_module._scan_start_time = None
    analysis_module._scan_end_time = None
    analysis_module._scan_error = None

    with (
        patch("exchanges.registry.get_registry", return_value=mock_registry),
        patch("analysis.fetch_candles_with_retry", side_effect=mock_fetch_candles),
    ):
        # Trigger the scan via endpoint
        response = await client.get("/api/scan/all?force=true")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("idle", "running", "completed")

        # Wait for it to complete
        max_wait = 20.0
        start_wait = time.perf_counter()
        while time.perf_counter() - start_wait < max_wait:
            response = await client.get("/api/scan/all")
            data = response.json()
            if data["status"] == "completed":
                break
            elif data["status"] == "failed":
                pytest.fail(f"Scan failed with error: {data.get('error')}")
            await asyncio.sleep(0.1)

        assert data["status"] == "completed", (
            f"Scan did not complete, current status: {data['status']}"
        )
        assert data["scanned"] == num_symbols
        assert len(data["results"]) == num_symbols
        print(f"REST API scan all stress verified. Scanned symbols: {data['scanned']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Starting manual concurrency stress test...")
    asyncio.run(test_scan_all_concurrency_and_stress())
