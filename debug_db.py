import sys
import os

sys.path.insert(0, os.path.abspath("nerves/workers/trading"))

import asyncio
import time
import aiosqlite
import config
import database
from capture_client import PythonCaptureClient


async def debug():
    # Setup test db
    config.DB_PATH = "debug.db"
    await database.init_db()

    client = PythonCaptureClient()
    now_ms = (int(time.time() * 1000) // 1800000) * 1800000

    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM ohlcv_5m")
        await db.commit()

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
    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            "SELECT timestamp, open, high, low, close, volume FROM ohlcv_5m WHERE symbol = 'BTCUSDT'"
        ) as cursor:
            rows = await cursor.fetchall()
            print("DB Rows:")
            for r in rows:
                print(r)

    resampled = await client._get_ohlcv_data("BTCUSDT", "30m", limit=1)
    print("\nResampled returned:")
    print(resampled)


asyncio.run(debug())
