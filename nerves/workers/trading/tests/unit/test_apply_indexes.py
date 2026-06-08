"""
Unit tests for apply_indexes.py.
Executes the script to ensure index creation statement syntax is valid and runs successfully.
"""

import config
import sqlite3
import importlib


def test_apply_indexes(tmp_path):
    # Set config.DB_PATH to a temporary database
    db_file = tmp_path / "test_apply_indexes.db"
    orig_db_path = config.DB_PATH
    config.DB_PATH = str(db_file)

    # Create the table indicator_signals since apply_indexes expects it
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE indicator_signals (id INTEGER PRIMARY KEY, symbol TEXT, created_at TEXT, signal_type TEXT)"
    )
    conn.commit()
    conn.close()

    try:
        # Import apply_indexes which executes queries at module level
        import apply_indexes

        # Force a reload to guarantee code execution in this test block
        importlib.reload(apply_indexes)
    finally:
        config.DB_PATH = orig_db_path
