import pytest
import aiosqlite
from httpx import AsyncClient, ASGITransport

import sys
from pathlib import Path

# All module names that overlap between server/ and vbs/
_VBS_MODULE_NAMES = [
    "config",
    "database",
    "main",
    "router",
    "models",
    "notifier",
    "scheduler",
]

# Save original modules if they exist
_originals = {name: sys.modules.pop(name, None) for name in _VBS_MODULE_NAMES}

# Add vbs folder to front of sys.path
vbs_path = str(Path(__file__).resolve().parents[4] / "vbs")
if vbs_path not in sys.path:
    sys.path.insert(0, vbs_path)

import config
import database as vbs_db
from main import app as vbs_app

# Restore the original modules to sys.modules to prevent test pollution
for name in _VBS_MODULE_NAMES:
    if _originals[name] is not None:
        sys.modules[name] = _originals[name]
    else:
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path):
    """Setup an isolated test database for VBS."""
    original_db = vbs_db.config.DB_PATH
    test_db = str(tmp_path / "test_vbs.db")
    vbs_db.config.DB_PATH = test_db

    # Initialize schema
    await vbs_db.init_db()

    yield

    vbs_db.config.DB_PATH = original_db


@pytest.mark.asyncio
async def test_vbs_filtering_database_level():
    # Insert test signals
    # 1. Indicator signal
    await vbs_db.insert_signal(
        {
            "symbol": "BTCUSDT",
            "action": "rsi_cross",
            "price": 60000.0,
            "source": "indicator",
            "exchange": "binance",
        }
    )

    # 2. Trading signal with source="strategy"
    await vbs_db.insert_signal(
        {
            "symbol": "ETHUSDT",
            "action": "buy",
            "price": 3000.0,
            "source": "strategy",
            "exchange": "binance",
        }
    )

    # 3. Trading signal with empty source
    await vbs_db.insert_signal(
        {
            "symbol": "SOLUSDT",
            "action": "sell",
            "price": 100.0,
            "source": "",
            "exchange": "bybit",
        }
    )

    # Test 1: Consume only "indicator"
    signals_ind = await vbs_db.consume_signals(
        "test-consumer-1", limit=10, source="indicator"
    )
    assert len(signals_ind) == 1
    assert signals_ind[0]["symbol"] == "BTCUSDT"

    # Reset status of BTCUSDT to PENDING for subsequent tests
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("UPDATE signal_queue SET status = 'PENDING'")
        await db.commit()

    # Test 2: Consume with exclude_source="indicator"
    signals_ex_ind = await vbs_db.consume_signals(
        "test-consumer-2", limit=10, exclude_source="indicator"
    )
    assert len(signals_ex_ind) == 2
    symbols = {s["symbol"] for s in signals_ex_ind}
    assert "ETHUSDT" in symbols
    assert "SOLUSDT" in symbols

    # Reset status
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("UPDATE signal_queue SET status = 'PENDING'")
        await db.commit()

    # Test 3: Consume everything (no filters)
    signals_all = await vbs_db.consume_signals("test-consumer-3", limit=10)
    assert len(signals_all) == 3


@pytest.mark.asyncio
async def test_vbs_filtering_router_level():
    # Insert test signals
    await vbs_db.insert_signal(
        {
            "symbol": "BTCUSDT",
            "action": "rsi_cross",
            "price": 60000.0,
            "source": "indicator",
        }
    )
    await vbs_db.insert_signal(
        {
            "symbol": "ETHUSDT",
            "action": "buy",
            "price": 3000.0,
            "source": "strategy",
        }
    )

    # Use httpx.AsyncClient with ASGITransport to hit VBS routes
    headers = {"X-Buffer-Secret": getattr(config, "BUFFER_SECRET", "")}
    async with AsyncClient(
        transport=ASGITransport(app=vbs_app), base_url="http://test"
    ) as client:
        # Test 1: GET /consume with source=indicator
        resp = await client.get(
            "/consume",
            params={"consumer_id": "c1", "source": "indicator"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["signals"][0]["symbol"] == "BTCUSDT"

        # Reset DB status
        async with aiosqlite.connect(config.DB_PATH) as db:
            await db.execute("UPDATE signal_queue SET status = 'PENDING'")
            await db.commit()

        # Test 2: GET /consume-long with exclude_source=indicator
        resp = await client.get(
            "/consume-long",
            params={"consumer_id": "c2", "exclude_source": "indicator", "timeout": 5},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["signals"][0]["symbol"] == "ETHUSDT"
