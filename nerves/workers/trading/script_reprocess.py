import asyncio
import logging
import sqlite3

# Adjust path so we can import server modules properly
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

import config
from processor.signal_processor import process_signal

logging.basicConfig(level=logging.INFO)


async def main():
    db_path = config.DB_PATH
    print(f"Using DB: {db_path}")

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # Find the latest signal
    c.execute("SELECT id, symbol, action FROM signals ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()

    if not row:
        print("No signal found in DB")
        return

    signal_id, symbol, action = row
    print(f"Reprocessing latest signal #{signal_id} ({symbol} {action})...")

    await process_signal(signal_id)
    print("Done reprocessing.")


if __name__ == "__main__":
    asyncio.run(main())
