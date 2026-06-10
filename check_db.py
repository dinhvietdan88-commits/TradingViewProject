import sqlite3
import os

db_paths = ["trades.db", "nerves/workers/trading/trades.db"]
for path in db_paths:
    if os.path.exists(path):
        print(f"=== {path} ===")
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            schema = cur.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='signals'"
            ).fetchone()
            print("Schema:", schema[0])
            row = cur.execute("SELECT * FROM signals LIMIT 1").fetchone()
            if row:
                print("Columns in signals:", list(row.keys()))
            else:
                print("No rows in signals")
        except Exception as e:
            print("Error:", e)
        conn.close()
