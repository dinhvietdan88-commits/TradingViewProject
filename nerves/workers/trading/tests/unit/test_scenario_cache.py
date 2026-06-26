import pathlib
import sys
import json
import pytest
import pytest_asyncio
import aiosqlite
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
import config
import database
from main import app


@pytest_asyncio.fixture(autouse=True)
async def isolated_db(tmp_path):
    """Create a separate test database file per test run."""
    db_file = str(tmp_path / "test_cache.db")
    config.DB_PATH = db_file
    config.FORWARD_DB_PATH = db_file
    await database.init_db()
    yield


@pytest.mark.asyncio
async def test_signals_scenarios_cache_table_exists():
    async with aiosqlite.connect(config.DB_PATH) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='signals_scenarios_cache'"
        )
        row = await cursor.fetchone()
        assert row is not None


@pytest.mark.asyncio
async def test_insert_and_select_simulation_cache():
    sig_id = 1000005
    result_mock = {
        "signal_info": {"vbs_id": sig_id, "symbol": "BTCUSDT"},
        "market_context": {"daily_close": 65000.0},
        "scenarios": {"S1": {"executed": True, "pnl_pct": 0.02}},
        "candles": [],
        "daily_candles": [],
    }

    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT OR REPLACE INTO signals (id, symbol, action, price, processed) VALUES (?, ?, ?, ?, ?)",
            (sig_id, "BTCUSDT", "buy", 65000.0, 1),
        )
        await db.execute(
            "INSERT OR REPLACE INTO signals_scenarios_cache (signal_id, result_json, updated_at) VALUES (?, ?, datetime('now'))",
            (sig_id, json.dumps(result_mock)),
        )
        await db.commit()

        async with db.execute(
            "SELECT * FROM signals_scenarios_cache WHERE signal_id = ?", (sig_id,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            row_dict = dict(row)
            loaded = json.loads(row_dict["result_json"])
            assert loaded["signal_info"]["symbol"] == "BTCUSDT"
            assert loaded["scenarios"]["S1"]["pnl_pct"] == 0.02


def test_api_signals_simulations_endpoint():
    client = TestClient(app)
    response = client.get("/api/forward/signals-simulations")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert isinstance(data["simulations"], dict)
