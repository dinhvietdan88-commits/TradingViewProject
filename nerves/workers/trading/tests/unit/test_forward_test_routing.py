"""
Unit tests for Forward Test DB Routing verification.
"""

import os
import pytest
import aiosqlite
import config
import database


@pytest.mark.asyncio
async def test_init_db_creates_both_databases(tmp_path):
    """Verify that init_db() successfully initializes both DB files with full schema."""
    db_path = str(tmp_path / "test_init_db.db")
    fwd_db_path = str(tmp_path / "test_init_fwd_db.db")

    # Temporarily patch config paths
    original_db = config.DB_PATH
    original_fwd = config.FORWARD_DB_PATH
    try:
        config.DB_PATH = db_path
        config.FORWARD_DB_PATH = fwd_db_path

        # Verify databases do not exist
        assert not os.path.exists(db_path)
        assert not os.path.exists(fwd_db_path)

        # Run initialization
        await database.init_db()

        # Verify files were created
        assert os.path.exists(db_path)
        assert os.path.exists(fwd_db_path)

        # Verify schema table existence
        for path in [db_path, fwd_db_path]:
            async with aiosqlite.connect(path) as conn:
                async with conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='signals'"
                ) as cursor:
                    assert await cursor.fetchone() is not None

                async with conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
                ) as cursor:
                    assert await cursor.fetchone() is not None

                async with conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='indicator_signals'"
                ) as cursor:
                    assert await cursor.fetchone() is not None
    finally:
        config.DB_PATH = original_db
        config.FORWARD_DB_PATH = original_fwd


@pytest.mark.asyncio
async def test_forward_signal_isolation():
    """Verify signal with mode='FORWARD' saves to forward_trades.db and NOT trades.db."""
    # Insert forward signal
    forward_sig_id = await database.insert_signal(
        symbol="ETHUSDT",
        action="buy",
        price=3500.0,
        quote_qty=100.0,
        source_ip="127.0.0.1",
        mode="FORWARD",
    )

    # Verify present in forward DB and NOT live DB
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        async with db.execute(
            "SELECT symbol, action, mode FROM signals WHERE id = ?", (forward_sig_id,)
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row[0] == "ETHUSDT"
            assert row[1] == "buy"
            assert row[2] == "FORWARD"

    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM signals WHERE id = ?", (forward_sig_id,)
        ) as cur:
            row = await cur.fetchone()
            assert row is None


@pytest.mark.asyncio
async def test_forward_subsequent_trades_and_oco_routing():
    """Verify that subsequent trades and OCO updates for forward signal are written to forward_trades.db."""
    # 1. Insert a forward signal
    forward_sig_id = await database.insert_signal(
        symbol="SOLUSDT",
        action="buy",
        price=150.0,
        quote_qty=50.0,
        source_ip="127.0.0.1",
        mode="FORWARD",
    )

    # 2. Insert trade associated with forward signal
    trade_id = await database.insert_trade(
        signal_id=forward_sig_id,
        symbol="SOLUSDT",
        side="BUY",
        order_id="SOL-FWD-001",
        status="FILLED",
        requested_qty=10.0,
        executed_qty=10.0,
        executed_price=150.0,
        exchange="binance",
    )

    # Verify trade is in forward DB
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        async with db.execute(
            "SELECT signal_id, symbol, order_id FROM trades WHERE id = ?", (trade_id,)
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row[0] == forward_sig_id
            assert row[1] == "SOLUSDT"
            assert row[2] == "SOL-FWD-001"

    # Verify trade is NOT in live DB
    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute("SELECT id FROM trades WHERE id = ?", (trade_id,)) as cur:
            row = await cur.fetchone()
            assert row is None

    # 3. Update OCO details for the trade
    await database.update_trade_oco(
        trade_id=trade_id,
        stop_loss_price=145.0,
        take_profit_price=165.0,
        oco_order_id="SOL-OCO-001",
        order_type="OCO",
    )

    # Verify updated in forward DB
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        async with db.execute(
            "SELECT stop_loss_price, take_profit_price, oco_order_id, order_type FROM trades WHERE id = ?",
            (trade_id,),
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row[0] == 145.0
            assert row[1] == 165.0
            assert row[2] == "SOL-OCO-001"
            assert row[3] == "OCO"

    # Verify not modified in live DB
    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute("SELECT id FROM trades WHERE id = ?", (trade_id,)) as cur:
            row = await cur.fetchone()
            assert row is None


@pytest.mark.asyncio
async def test_ohlcv_and_indicators_route_to_live_db():
    """Verify that OHLCV and indicator data continue to be saved to trades.db even when mode='FORWARD'."""
    forward_sig_id = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=60000.0,
        quote_qty=100.0,
        source_ip="127.0.0.1",
        mode="FORWARD",
    )

    # 1. Insert indicator signal referencing the forward signal id
    ind_sig_id = await database.insert_indicator_signal(
        signal_id=forward_sig_id,
        symbol="BTCUSDT",
        indicator_name="RSI",
        signal_type="BUY",
        confidence_score=75,
        conditions_met="RSI < 30",
        metadata="{}",
        interval="1h",
        price=60000.0,
        source_ip="127.0.0.1",
        exchange="binance",
    )

    # Verify indicator signal in forward DB
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        async with db.execute(
            "SELECT signal_id, indicator_name, signal_type FROM indicator_signals WHERE id = ?",
            (ind_sig_id,),
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row[0] == forward_sig_id
            assert row[1] == "RSI"
            assert row[2] == "BUY"

    # Verify indicator signal NOT in live DB
    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM indicator_signals WHERE id = ?", (ind_sig_id,)
        ) as cur:
            row = await cur.fetchone()
            assert row is None

    # 2. Insert OHLCV batch
    candles = [("BTCUSDT", 1700000000, 60000.0, 60100.0, 59900.0, 60050.0, 15.5)]
    await database.insert_ohlcv_batch(timeframe="5m", candles=candles)

    # Verify OHLCV in live DB
    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            "SELECT open, close, volume FROM ohlcv_5m WHERE symbol = ? AND timestamp = ?",
            ("BTCUSDT", 1700000000),
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row[0] == 60000.0
            assert row[1] == 60050.0
            assert row[2] == 15.5

    # Verify OHLCV NOT in forward DB
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        async with db.execute(
            "SELECT open FROM ohlcv_5m WHERE symbol = ? AND timestamp = ?",
            ("BTCUSDT", 1700000000),
        ) as cur:
            row = await cur.fetchone()
            assert row is None


@pytest.mark.asyncio
async def test_forward_test_enabled_routing_isolation():
    """Verify that when FORWARD_TEST_ENABLED=true, signals with any mode (e.g. MTT/MIS) save to forward_trades.db."""
    original_enabled = config.FORWARD_TEST_ENABLED
    config.FORWARD_TEST_ENABLED = True
    try:
        sig_id = await database.insert_signal(
            symbol="BTCUSDT",
            action="buy",
            price=60000.0,
            quote_qty=100.0,
            source_ip="127.0.0.1",
            mode="MTT",
        )

        # Verify present in forward DB and NOT live DB
        async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
            async with db.execute(
                "SELECT symbol, action, mode FROM signals WHERE id = ?", (sig_id,)
            ) as cur:
                row = await cur.fetchone()
                assert row is not None
                assert row[0] == "BTCUSDT"
                assert row[1] == "buy"
                assert row[2] == "MTT"

        async with aiosqlite.connect(config.DB_PATH) as db:
            async with db.execute(
                "SELECT id FROM signals WHERE id = ?", (sig_id,)
            ) as cur:
                row = await cur.fetchone()
                assert row is None
    finally:
        config.FORWARD_TEST_ENABLED = original_enabled
