"""
Adversarial and stress tests for dynamic database routing.
"""

import pytest
import asyncio
import aiosqlite
import time
import logging
import config
import database
from data.routing import get_db_path_by_signal_id, get_db_path_by_trade_id

log = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_concurrent_writes_and_reads():
    """
    Stress test: simulate concurrent database writes and routing lookups.
    Verifies lock handling, WAL configuration, and correct routing under pressure.
    """
    concurrency_limit = 30
    tasks = []

    async def simulate_live_flow(index: int):
        # 1. Insert live signal
        sig_id = await database.insert_signal(
            symbol=f"BTCUSDT_{index}",
            action="buy",
            price=60000.0 + index,
            quote_qty=10.0,
            mode="LIVE",
        )
        assert isinstance(sig_id, int)

        # 2. Check routing resolves to live DB immediately
        path = await get_db_path_by_signal_id(sig_id)
        assert path == config.DB_PATH

        # 3. Insert trade for live signal
        trade_id = await database.insert_trade(
            signal_id=sig_id,
            symbol=f"BTCUSDT_{index}",
            side="BUY",
            order_id=f"LIVE-STRESS-{index}",
            status="FILLED",
            requested_qty=1.0,
        )
        assert isinstance(trade_id, int)

        # 4. Check trade routing resolves to live DB
        trade_path = await get_db_path_by_trade_id(trade_id)
        assert trade_path == config.DB_PATH

        # 5. Concurrent updates
        await database.update_signal_status(sig_id, 1)
        await database.update_trade_oco(
            trade_id=trade_id,
            stop_loss_price=59000.0,
            take_profit_price=65000.0,
            oco_order_id=f"LIVE-STRESS-OCO-{index}",
        )

    async def simulate_forward_flow(index: int):
        # 1. Insert forward signal
        sig_id = await database.insert_signal(
            symbol=f"ETHUSDT_{index}",
            action="buy",
            price=3000.0 + index,
            quote_qty=5.0,
            mode="FORWARD",
        )
        assert isinstance(sig_id, int)

        # 2. Check routing resolves to forward DB immediately
        path = await get_db_path_by_signal_id(sig_id)
        assert path == config.FORWARD_DB_PATH

        # 3. Insert trade for forward signal
        trade_id = await database.insert_trade(
            signal_id=sig_id,
            symbol=f"ETHUSDT_{index}",
            side="BUY",
            order_id=f"FWD-STRESS-{index}",
            status="FILLED",
            requested_qty=2.0,
        )
        assert isinstance(trade_id, int)

        # 4. Check trade routing resolves to forward DB
        trade_path = await get_db_path_by_trade_id(trade_id)
        assert trade_path == config.FORWARD_DB_PATH

        # 5. Concurrent updates
        await database.update_signal_status(sig_id, 1)
        await database.update_trade_oco(
            trade_id=trade_id,
            stop_loss_price=29000.0,
            take_profit_price=35000.0,
            oco_order_id=f"FWD-STRESS-OCO-{index}",
        )

    # Launch a mix of live and forward signal flows concurrently
    for i in range(concurrency_limit):
        if i % 2 == 0:
            tasks.append(simulate_live_flow(i))
        else:
            tasks.append(simulate_forward_flow(i))

    # Gather all tasks to execute concurrently
    await asyncio.gather(*tasks)

    # Verify final counts in each database
    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM signals") as cur:
            live_signals_count = (await cur.fetchone())[0]
            assert live_signals_count == concurrency_limit // 2

    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM signals") as cur:
            fwd_signals_count = (await cur.fetchone())[0]
            assert fwd_signals_count == concurrency_limit // 2


@pytest.mark.asyncio
async def test_corrupted_database_files(caplog):
    """
    Adversarial test: corrupt the forward database file and verify resilience.
    The router must fall back to DB_PATH and log warnings, without raising uncaught errors.
    """
    # 1. Insert a forward signal first while DB is healthy
    sig_id = await database.insert_signal(
        symbol="SOLUSDT",
        action="buy",
        price=150.0,
        quote_qty=5.0,
        mode="FORWARD",
    )
    # Check that healthy routing returns forward path
    path = await get_db_path_by_signal_id(sig_id)
    assert path == config.FORWARD_DB_PATH

    # 2. Corrupt the forward database file
    with open(config.FORWARD_DB_PATH, "wb") as f:
        f.write(b"CORRUPTED_GARBAGE_DATA_THAT_IS_NOT_SQLITE")

    # 3. Try to resolve routing for the forward signal
    # It should fail to query the corrupted DB, catch the exception, log warning, and return DB_PATH
    with caplog.at_level(logging.WARNING):
        routed_path = await get_db_path_by_signal_id(sig_id)
        assert routed_path == config.DB_PATH
        assert any(
            "Error checking signal_id" in record.message for record in caplog.records
        )

    # 4. Try to resolve routing for a trade ID
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        routed_trade_path = await get_db_path_by_trade_id(1)
        assert routed_trade_path == config.DB_PATH
        assert any(
            "Error checking trade_id" in record.message for record in caplog.records
        )


@pytest.mark.asyncio
async def test_routing_non_existent_and_invalid_ids():
    """
    Adversarial test: query routing with non-existent or invalid ID types.
    """
    # 1. Non-existent IDs (positive, negative, zero)
    assert await get_db_path_by_signal_id(999999) == config.DB_PATH
    assert await get_db_path_by_signal_id(-5) == config.DB_PATH
    assert await get_db_path_by_signal_id(0) == config.DB_PATH

    assert await get_db_path_by_trade_id(999999) == config.DB_PATH
    assert await get_db_path_by_trade_id(-10) == config.DB_PATH
    assert await get_db_path_by_trade_id(0) == config.DB_PATH

    # 2. Invalid inputs/types
    # None value checks
    assert await get_db_path_by_signal_id(None) == config.DB_PATH
    assert await get_db_path_by_trade_id(None) == config.DB_PATH

    # Float values
    assert await get_db_path_by_signal_id(12.5) == config.DB_PATH
    assert await get_db_path_by_trade_id(99.9) == config.DB_PATH

    # String values (e.g. invalid type input)
    assert await get_db_path_by_signal_id("invalid_id") == config.DB_PATH
    assert await get_db_path_by_trade_id("some_trade_id") == config.DB_PATH

    # Empty array/dict
    assert await get_db_path_by_signal_id([]) == config.DB_PATH
    assert await get_db_path_by_trade_id({}) == config.DB_PATH


@pytest.mark.asyncio
async def test_performance_routing_overhead():
    """
    Performance test: measure and compare latency with routing checks.
    Ensures the additional connection check to the forward database does not cause excessive latency.
    """
    iterations = 100

    # Insert a forward signal to ensure there is a record to check in forwarding DB
    await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=60000.0,
        quote_qty=10.0,
        mode="FORWARD",
    )

    # 1. Time lookup for a non-existent ID (worst case: full attempt to query forward DB, then return default)
    start_time = time.perf_counter()
    for i in range(iterations):
        await get_db_path_by_signal_id(999999 + i)
    duration_non_existent = time.perf_counter() - start_time
    avg_non_existent = (duration_non_existent / iterations) * 1000

    # 2. Time lookup for None or empty ID (best case: early exit)
    start_time = time.perf_counter()
    for _ in range(iterations):
        await get_db_path_by_signal_id(None)
    duration_empty = time.perf_counter() - start_time
    avg_empty = (duration_empty / iterations) * 1000

    log.info(f"Avg Routing Latency (Non-existent ID): {avg_non_existent:.4f} ms")
    log.info(f"Avg Routing Latency (Early Exit): {avg_empty:.4f} ms")

    # Assert that early exit is extremely fast (< 0.1ms typically, we check < 5ms for runner noise tolerance)
    assert avg_empty < 5.0

    # Assert that querying forward DB does not take excessive time (< 15ms per lookup in ordinary environment)
    # We set a generous upper threshold of 30ms to account for slow CI runner I/O
    assert avg_non_existent < 30.0
