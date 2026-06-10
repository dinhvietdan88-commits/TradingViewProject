import sys
import os

sys.path.insert(0, os.path.abspath("nerves/workers/trading"))

import asyncio
import time
import aiosqlite
import config
import database
from capture_client import PythonCaptureClient


async def debug_test():
    # Setup test db
    config.DB_PATH = "test_stress_diag.db"
    await database.init_db()

    client = PythonCaptureClient()
    now_ms = (int(time.time() * 1000) // 1800000) * 1800000

    # Clean the DB first
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m")
        await db.commit()

    # Scenario A: Single-element dataset (with validation bypassed)
    single_candle = [["BTCUSDT", now_ms, 100.0, 105.0, 95.0, 102.0, 10.0]]
    await database.insert_ohlcv_batch("5m", single_candle)

    # Scenario B: Volume = 0
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m")
        await db.commit()
    client._ohlcv_cache.clear()

    ohlcv_zero_vol = []
    for i in range(12):
        ts = now_ms + i * 300000
        ohlcv_zero_vol.append(["BTCUSDT", ts, 100.0, 105.0, 95.0, 102.0, 0.0])
    await database.insert_ohlcv_batch("5m", ohlcv_zero_vol)

    # Scenario C: High volatility kline series
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m")
        await db.commit()
    client._ohlcv_cache.clear()

    ohlcv_volatile = []
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

    # Now let's fetch using capture client
    resampled = await client._get_ohlcv_data("BTCUSDT", "30m", limit=1)
    print("Resampled in test copy:")
    print(resampled)


asyncio.run(debug_test())
