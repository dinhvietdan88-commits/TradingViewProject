import pathlib
import sys
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
import config
import database
from main import app


@pytest_asyncio.fixture(autouse=True)
async def isolated_db(tmp_path):
    """Create a separate test database file per test run."""
    db_file = str(tmp_path / "test_ledger.db")
    config.DB_PATH = db_file
    await database.init_db()
    yield


@pytest.mark.asyncio
async def test_update_signal_state_with_reason():
    sig_id = await database.insert_signal("BTCUSDT", "buy")
    await database.update_signal_state(sig_id, "REJECTED", "market_regime_chop_block")

    signals_res = await database.get_signals(symbol="BTCUSDT")
    assert signals_res["total"] == 1
    sig = signals_res["signals"][0]
    assert sig["state"] == "REJECTED"
    assert sig["rejection_reason"] == "market_regime_chop_block"


@pytest.mark.asyncio
async def test_get_signals_filtering_and_pagination():
    s1 = await database.insert_signal("BTCUSDT", "buy")
    s2 = await database.insert_signal("ETHUSDT", "sell")
    s3 = await database.insert_signal("SOLUSDT", "buy")

    await database.update_signal_state(s1, "COMPLETED")
    await database.update_signal_state(s2, "REJECTED", "macro_trend_conflict")
    await database.update_signal_state(s3, "INGESTED")

    # Filter by state
    res_rejected = await database.get_signals(state="REJECTED")
    assert res_rejected["total"] == 1
    assert res_rejected["signals"][0]["symbol"] == "ETHUSDT"

    # Filter by symbol
    res_btc = await database.get_signals(symbol="BTCUSDT")
    assert res_btc["total"] == 1
    assert res_btc["signals"][0]["state"] == "COMPLETED"

    # Pagination
    res_page = await database.get_signals(limit=2, offset=0)
    assert len(res_page["signals"]) == 2
    assert res_page["total"] == 3


def test_api_get_signals():
    # We use TestClient from fastapi to test the /api/signals endpoint
    client = TestClient(app)

    # We mock database.get_signals to return static data
    mock_data = {
        "signals": [
            {
                "id": 1,
                "created_at": "2026-06-08 10:00:00",
                "symbol": "BTCUSDT",
                "action": "buy",
                "price": 68000.0,
                "quote_qty": 50.0,
                "source_ip": "127.0.0.1",
                "payload": None,
                "mode": "MTT",
                "processed": 1,
                "vbs_queue_id": None,
                "state": "REJECTED",
                "rejection_reason": "macro_trend_conflict",
            }
        ],
        "total": 1,
        "limit": 50,
        "offset": 0,
    }

    with patch(
        "database.get_signals", new_callable=AsyncMock, return_value=mock_data
    ) as mock_get:
        response = client.get(
            "/api/signals?symbol=BTCUSDT&state=REJECTED&limit=5&offset=0"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["signals"][0]["symbol"] == "BTCUSDT"
        assert data["signals"][0]["rejection_reason"] == "macro_trend_conflict"
        mock_get.assert_called_once_with(
            symbol="BTCUSDT", state="REJECTED", limit=5, offset=0
        )
