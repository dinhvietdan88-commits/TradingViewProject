import asyncio
import pytest
from unittest.mock import patch
import logging
from typing import List, Dict

from analysis import scan_single_symbol_rest, ScanResult

logger = logging.getLogger(__name__)

# Track virtual time per asyncio Task
task_clocks: Dict[asyncio.Task, float] = {}
original_sleep = asyncio.sleep


async def mock_sleep(seconds: float):
    current_task = asyncio.current_task()
    if current_task not in task_clocks:
        task_clocks[current_task] = 0.0
    task_clocks[current_task] += seconds
    # Yield control to let other concurrent tasks run via original sleep
    await original_sleep(0.0)


class MockResponse:
    def __init__(self, status: int, headers: dict = None, json_data: list = None):
        self.status = status
        self.headers = headers or {}
        self._json_data = json_data or []

    async def json(self):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_rate_limit_robustness_simulation():
    global task_clocks
    task_clocks.clear()

    # Configuration
    num_symbols = 50
    symbols = [f"SYM_{i}" for i in range(num_symbols)]

    total_attempts = 0
    total_429s = 0
    total_200s = 0

    # Track retries per symbol
    symbol_attempts: Dict[str, int] = {}

    # Mock data for candles
    mock_candles_data = [
        [1684812345000 + i * 86400000, 100.0, 105.0, 95.0, 101.0, 1000.0]
        for i in range(100)
    ]

    def request_handler(url, params):
        nonlocal total_attempts, total_429s, total_200s
        symbol = params.get("symbol", "UNKNOWN")

        # Increment attempts for this symbol
        attempts = symbol_attempts.get(symbol, 0) + 1
        symbol_attempts[symbol] = attempts

        total_attempts += 1

        # Advance current task clock slightly to simulate request latency (e.g. 50ms)
        current_task = asyncio.current_task()
        if current_task not in task_clocks:
            task_clocks[current_task] = 0.0
        task_clocks[current_task] += 0.05

        # If this is the 5th attempt (which means 4 retries), succeed with 200
        # Otherwise return 429
        if attempts >= 5:
            total_200s += 1
            return MockResponse(200, json_data=mock_candles_data)
        else:
            total_429s += 1
            return MockResponse(429, headers={"Retry-After": "2.0"})

    class MockSession:
        def get(self, url, params=None, timeout=None):
            return request_handler(url, params)

    session = MockSession()
    semaphore = asyncio.Semaphore(15)  # matches scan_all concurrency limit

    # We patch asyncio.sleep to use our virtual clock
    with patch("asyncio.sleep", mock_sleep):
        # Run all scans concurrently
        tasks = []
        for sym in symbols:
            tasks.append(
                scan_single_symbol_rest(
                    session=session,
                    exchange_name="binance",
                    symbol=sym,
                    btc_closes={},
                    btc_candles=[],
                    semaphore=semaphore,
                )
            )

        results: List[ScanResult] = await asyncio.gather(*tasks)

    # Calculate metrics
    success_count = sum(1 for r in results if r.error is None)
    failed_count = sum(1 for r in results if r.error is not None)

    # Calculate retries (attempts - 1)
    retries_list = [attempts - 1 for attempts in symbol_attempts.values()]
    avg_retries = sum(retries_list) / len(retries_list) if retries_list else 0
    max_retries_reached = max(retries_list) if retries_list else 0

    # Total scan time is the max virtual clock among all tasks
    total_scan_time = max(task_clocks.values(), default=0.0)

    success_rate = (success_count / num_symbols) * 100

    # Print metrics for verification
    print("\n--- RATE-LIMITING SIMULATION METRICS ---")
    print(f"Total Symbols Scanned: {num_symbols}")
    print(f"Total HTTP Requests Attempted: {total_attempts}")
    print(
        f"Total HTTP 429 Responses: {total_429s} ({total_429s / total_attempts * 100:.1f}%)"
    )
    print(f"Total HTTP 200 Responses: {total_200s}")
    print(f"Scan Success Rate: {success_rate:.1f}%")
    print(f"Average Retries per Symbol: {avg_retries:.2f}")
    print(f"Max Retries for a single Symbol: {max_retries_reached}")
    print(f"Simulated Total Scan Time: {total_scan_time:.2f} seconds")
    print("----------------------------------------")

    # Assertions
    # 1. The rate-limiting handler catches the 429 status correctly
    assert total_429s == 200, f"Expected 200 429s, got {total_429s}"
    assert total_attempts == 250, f"Expected 250 attempts, got {total_attempts}"

    # 2. No requests are lost or silently dropped
    assert success_count == num_symbols, f"Some scans failed: {failed_count} failures"
    assert success_rate == 100.0

    # 3. Verify exponential backoff: sleep times occurred
    # Since each task did 4 retries, the mock_sleep should be called 4 times per task.
    # Total simulated sleep for each task should be 9.625 seconds.
    # Total time for a task should be 9.625 + 5 * 0.05 = 9.875 seconds.
    for _task, clock in task_clocks.items():
        assert clock >= 9.875, f"Task clock {clock} is less than expected 9.875"
