"""
Stress and adversarial tests for the dynamic database routing implementation.
Covers:
1. Concurrency: verifying concurrent database access under high load.
2. File Corruption: handling of corrupted database files (e.g. malformed SQLite file).
3. Non-existent routing: routing lookup behavior for non-existent IDs.
4. Invalid inputs/signals.
"""

import asyncio
import pytest
import aiosqlite
import config
import database
from data.routing import get_db_path_by_signal_id, get_db_path_by_trade_id

@pytest.mark.asyncio
async def test_routing_lookup_nonexistent_ids():
    """Verify that routing for nonexistent IDs gracefully defaults to the primary database."""
    nonexistent_sig_id = 999999
    nonexistent_trade_id = 888888

    # Nonexistent IDs must default to DB_PATH
    sig_path = await get_db_path_by_signal_id(nonexistent_sig_id)
    trade_path = await get_db_path_by_trade_id(nonexistent_trade_id)

    assert sig_path == config.DB_PATH
    assert trade_path == config.DB_PATH


@pytest.mark.asyncio
async def test_routing_lookup_invalid_inputs():
    """Verify that routing resolves correctly with invalid inputs like None, string, floats, or negative numbers."""
    # Test None
    assert await get_db_path_by_signal_id(None) == config.DB_PATH
    assert await get_db_path_by_trade_id(None) == config.DB_PATH

    # Test String input
    assert await get_db_path_by_signal_id("invalid_id") == config.DB_PATH
    assert await get_db_path_by_trade_id("invalid_id") == config.DB_PATH

    # Test float input
    assert await get_db_path_by_signal_id(12.34) == config.DB_PATH
    assert await get_db_path_by_trade_id(56.78) == config.DB_PATH

    # Test negative ID
    assert await get_db_path_by_signal_id(-5) == config.DB_PATH
    assert await get_db_path_by_trade_id(-100) == config.DB_PATH


@pytest.mark.asyncio
async def test_routing_lookup_corrupted_forward_db():
    """Verify routing resilience when the forward database file is corrupted."""
    # 1. Insert a forward signal to prove it normal routing first
    forward_sig_id = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=60000.0,
        quote_qty=85.0,
        source_ip="127.0.0.1",
        mode="FORWARD",
    )

    assert await get_db_path_by_signal_id(forward_sig_id) == config.FORWARD_DB_PATH

    # 2. Corrupt the forward DB file by writing random garbage
    with open(config.FORWARD_DB_PATH, "wb") as f:
        f.write(b"CORRUPTED_GARBAGE_DATA_THAT_IS_NOT_SQLITE")

    # 3. Request routing lookup again. It must catch the database connection/read exception,
    # log it, and default back to config.DB_PATH rather than raising a crash.
    fallback_path = await get_db_path_by_signal_id(forward_sig_id)
    assert fallback_path == config.DB_PATH


@pytest.mark.asyncio
async def test_routing_lookup_corrupted_primary_db():
    """Verify routing resilience when the primary database file is corrupted but forward DB is intact."""
    # 1. Insert a forward signal and verify it goes to FORWARD_DB_PATH
    forward_sig_id = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=60000.0,
        quote_qty=85.0,
        source_ip="127.0.0.1",
        mode="FORWARD",
    )
    assert await get_db_path_by_signal_id(forward_sig_id) == config.FORWARD_DB_PATH

    # 2. Corrupt the primary database file
    with open(config.DB_PATH, "wb") as f:
        f.write(b"PRIMARY_DB_IS_CORRUPTED_GARBAGE")

    # 3. Querying for the forward signal should still work and return FORWARD_DB_PATH because it checks forward DB first
    assert await get_db_path_by_signal_id(forward_sig_id) == config.FORWARD_DB_PATH

    # 4. Querying for a non-existent or primary signal will fallback/default to DB_PATH
    assert await get_db_path_by_signal_id(99999) == config.DB_PATH


@pytest.mark.asyncio
async def test_concurrent_database_reads_writes():
    """Stress test dynamic routing with concurrent database access under high load.
    Spawns 50 concurrent tasks inserting and updating signals/trades in both forward and live modes.
    """
    import random

    async def worker(worker_id: int):
        mode = "FORWARD" if worker_id % 2 == 0 else "LIVE"

        # 1. Insert signal
        sig_id = await database.insert_signal(
            symbol="BTCUSDT",
            action="buy" if random.random() > 0.5 else "sell",  # noqa: S311
            price=60000.0 + random.randint(-1000, 1000),  # noqa: S311
            quote_qty=10.0 + random.randint(1, 100),  # noqa: S311
            source_ip="127.0.0.1",
            mode=mode,
        )

        # 2. Perform quick lookup to verify routing
        expected_path = config.FORWARD_DB_PATH if mode == "FORWARD" else config.DB_PATH
        resolved_path = await get_db_path_by_signal_id(sig_id)
        assert resolved_path == expected_path

        # 3. Insert trade
        trade_id = await database.insert_trade(
            signal_id=sig_id,
            symbol="BTCUSDT",
            side="BUY",
            order_id=f"T-{mode}-{worker_id}",
            status="FILLED",
            requested_qty=0.5,
        )

        # 4. Verify trade routing
        resolved_trade_path = await get_db_path_by_trade_id(trade_id)
        assert resolved_trade_path == expected_path

        # 5. Update signal state
        await database.update_signal_state(sig_id, "COMPLETED")

        # 6. Update signal status
        await database.update_signal_status(sig_id, 1)

        # 7. Update trade OCO
        await database.update_trade_oco(
            trade_id=trade_id,
            stop_loss_price=59000.0,
            take_profit_price=65000.0,
            oco_order_id=f"OCO-{mode}-{worker_id}",
            order_type="OCO",
        )

    # Spawn 50 concurrent operations
    tasks = [worker(i) for i in range(50)]
    await asyncio.gather(*tasks)

    # Verify counts in both DBs
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM signals") as cursor:
            row = await cursor.fetchone()
            assert row[0] == 25

    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM signals") as cursor:
            row = await cursor.fetchone()
            assert row[0] == 25


@pytest.mark.asyncio
async def test_routing_collision_duplicate_ids():
    """Verify how the system behaves when the same ID exists in both the primary and forward databases.
    This reveals a core design limitation where routing by ID alone can cause collisions.
    """
    # Set the primary DB sqlite_sequence to 1000000 so it also starts generating IDs from 1000001
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO sqlite_sequence (name, seq) VALUES ('signals', 1000000)")
        await db.commit()

    # 1. Insert a forward signal first (gets ID 1000001 in forward DB)
    fwd_sig_id = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=60000.0,
        quote_qty=85.0,
        source_ip="127.0.0.1",
        mode="FORWARD",
    )

    # 2. Insert a live/main signal (gets ID 1000001 in primary DB)
    live_sig_id = await database.insert_signal(
        symbol="BTCUSDT",
        action="sell",
        price=65000.0,
        quote_qty=50.0,
        source_ip="127.0.0.1",
        mode="LIVE",
    )

    # Both IDs should be equal (1000001)
    assert fwd_sig_id == 1000001
    assert live_sig_id == 1000001

    # 3. Call get_db_path_by_signal_id with signal_id = 1000001 (live_sig_id)
    # It will connect to forward_trades.db, find that ID 1000001 exists, and return config.FORWARD_DB_PATH!
    resolved_path = await get_db_path_by_signal_id(live_sig_id)
    assert resolved_path == config.FORWARD_DB_PATH  # Collision! Returns FORWARD_DB_PATH instead of DB_PATH

    # 4. Attempt to update the live signal state to "COMPLETED"
    # Because of the collision, it routes to forward_trades.db, updating the forward signal instead of the live signal.
    await database.update_signal_state(live_sig_id, "COMPLETED")

    # 5. Check the state of signal ID 1000001 in BOTH databases:
    # - In FORWARD DB, it should be updated to "COMPLETED" (even though we targeted live_sig_id)
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT state FROM signals WHERE id = 1000001") as cursor:
            row = await cursor.fetchone()
            assert row["state"] == "COMPLETED"

    # - In PRIMARY DB, the live signal is still at its default "INGESTED" state!
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT state FROM signals WHERE id = 1000001") as cursor:
            row = await cursor.fetchone()
            assert row["state"] == "INGESTED"  # Did not get updated due to collision!

