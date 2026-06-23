"""
Integration tests: test_forward_sync.py
Tests GET/POST /api/forward/sync-settings, POST /api/forward/sync-now, and live auto-replication hook.
"""

import pytest
import aiosqlite
import config
import json


@pytest.mark.asyncio
async def test_get_sync_settings_default(client):
    # Verify GET returns default empty settings
    response = await client.get("/api/forward/sync-settings")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["settings"] == {
        "position_sizing_mode": "fixed",
        "position_sizing_value": 100.0,
    }


@pytest.mark.asyncio
async def test_post_and_get_sync_settings(client):
    # Verify POST saves settings and subsequent GET retrieves them
    test_settings = {
        "symbols": "BTCUSDT,ETHUSDT",
        "sources": "webhook",
        "start_id": 10,
        "end_id": 100,
        "sync_enabled": True,
    }
    response = await client.post("/api/forward/sync-settings", json=test_settings)
    assert response.status_code == 200
    assert response.json()["success"] is True

    response = await client.get("/api/forward/sync-settings")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["settings"] == {
        **test_settings,
        "position_sizing_mode": "fixed",
        "position_sizing_value": 100.0,
    }


@pytest.mark.asyncio
async def test_sync_now(client):
    # Setup test settings
    test_settings = {
        "symbols": "BTCUSDT",
        "sources": "webhook",
        "start_id": 1,
        "end_id": 10,
        "sync_enabled": True,
    }
    await client.post("/api/forward/sync-settings", json=test_settings)

    # Insert signals directly into trades.db
    async with aiosqlite.connect(config.DB_PATH) as db:
        # Match symbol and source
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                1,
                "BTCUSDT",
                "buy",
                68000.0,
                10.0,
                json.dumps({"source": "webhook"}),
                "LIVE",
            ),
        )
        # Match symbol, mismatch source
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                2,
                "BTCUSDT",
                "buy",
                68000.0,
                10.0,
                json.dumps({"source": "indicator"}),
                "LIVE",
            ),
        )
        # Mismatch symbol, match source
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                3,
                "ETHUSDT",
                "buy",
                3500.0,
                10.0,
                json.dumps({"source": "webhook"}),
                "LIVE",
            ),
        )
        # Match symbol, match source, already in forward DB
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                4,
                "BTCUSDT",
                "buy",
                68000.0,
                10.0,
                json.dumps({"source": "webhook"}),
                "LIVE",
            ),
        )
        await db.commit()

    async with aiosqlite.connect(config.FORWARD_DB_PATH) as f_db:
        await f_db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                4,
                "BTCUSDT",
                "buy",
                68000.0,
                10.0,
                json.dumps({"source": "webhook"}),
                "FORWARD",
            ),
        )
        await f_db.commit()

    # Trigger manual sync
    response = await client.post("/api/forward/sync-now")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    # Only signal ID 1 fits all filters and doesn't exist in forward DB
    assert data["synced_count"] == 1

    # Verify ID 1 exists in forward_trades.db and has mode 'FORWARD'
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as f_db:
        f_db.row_factory = aiosqlite.Row
        async with f_db.execute("SELECT * FROM signals WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row["symbol"] == "BTCUSDT"
            assert row["action"] == "buy"
            assert row["mode"] == "FORWARD"

        # Verify ID 2 was NOT replicated
        async with f_db.execute("SELECT * FROM signals WHERE id = 2") as cursor:
            assert await cursor.fetchone() is None


@pytest.mark.asyncio
async def test_live_auto_replication(client):
    import config

    original_val = config.FORWARD_TEST_ENABLED
    config.FORWARD_TEST_ENABLED = False

    try:
        # Setup test settings
        test_settings = {
            "symbols": "BTCUSDT",
            "sources": "webhook",
            "sync_enabled": True,
        }
        await client.post("/api/forward/sync-settings", json=test_settings)

        # 1. Send matching signal via webhook
        payload_match = {
            "secret": "test-secret",
            "symbol": "BTCUSDT",
            "action": "buy",
            "price": 68000.0,
            "quoteQty": 20.0,
            "source": "webhook",
            "exchange": "binance",
            "interval": "1h",
        }
        response = await client.post("/webhook", json=payload_match)
        assert response.status_code in (200, 202)
        sig_id = response.json()["signal_id"]

        # Verify replicated in forward_trades.db
        async with aiosqlite.connect(config.FORWARD_DB_PATH) as f_db:
            f_db.row_factory = aiosqlite.Row
            async with f_db.execute(
                "SELECT * FROM signals WHERE id = ?", (sig_id,)
            ) as cursor:
                row = await cursor.fetchone()
                assert row is not None
                assert row["symbol"] == "BTCUSDT"
                assert row["mode"] == "FORWARD"

        # 2. Send non-matching signal via webhook (different symbol)
        payload_mismatch = {
            "secret": "test-secret",
            "symbol": "ETHUSDT",
            "action": "buy",
            "price": 3500.0,
            "quoteQty": 20.0,
            "source": "webhook",
            "exchange": "binance",
            "interval": "1h",
        }
        response2 = await client.post("/webhook", json=payload_mismatch)
        assert response2.status_code in (200, 202)
        sig_id2 = response2.json()["signal_id"]

        # Verify NOT replicated in forward_trades.db
        async with aiosqlite.connect(config.FORWARD_DB_PATH) as f_db:
            async with f_db.execute(
                "SELECT * FROM signals WHERE id = ?", (sig_id2,)
            ) as cursor:
                assert await cursor.fetchone() is None
    finally:
        config.FORWARD_TEST_ENABLED = original_val


@pytest.mark.asyncio
async def test_get_production_signals(client):
    # Seed signals in DB
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM signals")
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                10,
                "BTCUSDT",
                "buy",
                68000.0,
                10.0,
                json.dumps({"source": "webhook"}),
                "LIVE",
            ),
        )
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                11,
                "ETHUSDT",
                "sell",
                3500.0,
                5.0,
                json.dumps({"source": "indicator"}),
                "LIVE",
            ),
        )
        await db.commit()

    # Query with symbol
    response = await client.get("/api/forward/production-signals?symbol=BTCUSDT")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["signals"]) == 1
    assert data["signals"][0]["id"] == 10

    # Query with source
    response = await client.get("/api/forward/production-signals?source=indicator")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["signals"]) == 1
    assert data["signals"][0]["id"] == 11

    # Query with range
    response = await client.get("/api/forward/production-signals?start_id=10&end_id=11")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["signals"]) == 2


@pytest.mark.asyncio
async def test_sync_now_with_ids(client):
    # Seed signals in trades.db
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM signals")
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                20,
                "BTCUSDT",
                "buy",
                68000.0,
                10.0,
                json.dumps({"source": "webhook"}),
                "LIVE",
            ),
        )
        await db.execute(
            """INSERT INTO signals (id, symbol, action, price, quote_qty, payload, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                21,
                "ETHUSDT",
                "sell",
                3500.0,
                5.0,
                json.dumps({"source": "indicator"}),
                "LIVE",
            ),
        )
        await db.commit()

    # Clear forward DB
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as f_db:
        await f_db.execute("DELETE FROM signals")
        await f_db.commit()

    # Trigger manual sync with explicit ids
    response = await client.post("/api/forward/sync-now", json={"ids": [20, 21]})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["synced_count"] == 2

    # Verify they exist in forward_trades.db
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as f_db:
        f_db.row_factory = aiosqlite.Row
        async with f_db.execute("SELECT * FROM signals ORDER BY id ASC") as cursor:
            rows = await cursor.fetchall()
            assert len(rows) == 2
            assert rows[0]["id"] == 20
            assert rows[0]["mode"] == "FORWARD"
            assert rows[1]["id"] == 21
            assert rows[1]["mode"] == "FORWARD"
