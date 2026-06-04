"""
conftest.py — Shared fixtures for entire test suite.
- Uses temp file DB per test (not :memory:) to avoid SQLite isolation issues.
- FastAPI TestClient via ASGITransport — no running server needed.
- WEBHOOK_SECRET overridden to "test-secret" for all tests.
"""

import pytest
import pytest_asyncio
import os
import sys
import pathlib
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

# Override env BEFORE importing any app modules
os.environ["WEBHOOK_SECRET"] = "test-secret"
os.environ["BINANCE_API_KEY"] = ""
os.environ["BINANCE_API_SECRET"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""
os.environ["DISCORD_WEBHOOK_URL"] = ""
os.environ["ENABLE_IP_WHITELIST"] = "false"

@pytest.fixture(autouse=True)
def mock_global_capture_client():
    """Globally mock capture_client to avoid any real network calls to Binance."""
    with patch("capture_client.get_capture_client") as mock_get_capture:
        mock_capture = AsyncMock()
        mock_capture.fetch_ohlcv.return_value = None
        mock_get_capture.return_value = mock_capture
        yield mock_capture

os.environ["LOG_FILE"] = "test_trades.log"
os.environ["TELEGRAM_BOT_ENABLED"] = "false"
os.environ["BRIEF_ENABLED"] = "false"
os.environ["RAG_ENABLED"] = "false"
os.environ["MCP_ENABLED"] = "false"
os.environ["DASHBOARD_TOKEN"] = ""

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from httpx import AsyncClient, ASGITransport

@pytest_asyncio.fixture
async def client(tmp_path):
    """Fixture cung cap httpx.AsyncClient voi mocked environment."""
    import config
    import database

    # Point to per-test temp DB file
    config.DB_PATH = str(tmp_path / "test.db")
    config.WEBHOOK_SECRET = "test-secret"
    config.TELEGRAM_BOT_ENABLED = False
    config.BRIEF_ENABLED = False
    config.MCP_ENABLED = False
    config.RAG_ENABLED = False
    config.DASHBOARD_TOKEN = ""
    os.environ["DB_PATH"] = config.DB_PATH

    await database.init_db()

    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def client_with_trades(client, tmp_path):
    """Client with 5 pre-seeded trades for query endpoint tests."""
    import database

    sig1 = await database.insert_signal("BTCUSDT", "buy", 68000.0, 50.0, "127.0.0.1")
    sig2 = await database.insert_signal("BTCUSDT", "sell", 72000.0, 50.0, "127.0.0.1")
    sig3 = await database.insert_signal("ETHUSDT", "buy", 3500.0, 30.0, "127.0.0.1")
    sig4 = await database.insert_signal("BTCUSDT", "buy", 69000.0, 50.0, "127.0.0.1")
    sig5 = await database.insert_signal("BTCUSDT", "sell", 65000.0, 50.0, "127.0.0.1")

    await database.insert_trade(signal_id=sig1, symbol="BTCUSDT", side="BUY",
        order_id="100001", status="FILLED", requested_qty=50,
        executed_qty=0.000735, executed_price=68000.0, pnl=200.0)
    await database.insert_trade(signal_id=sig2, symbol="BTCUSDT", side="SELL",
        order_id="100002", status="FILLED", requested_qty=50,
        executed_qty=0.000694, executed_price=72000.0, pnl=150.0)
    await database.insert_trade(signal_id=sig3, symbol="ETHUSDT", side="BUY",
        order_id="100003", status="FILLED", requested_qty=30,
        executed_qty=0.00857, executed_price=3500.0, pnl=-80.0)
    await database.insert_trade(signal_id=sig4, symbol="BTCUSDT", side="BUY",
        order_id="100004", status="FAILED", requested_qty=50, error_message="Insufficient balance")
    await database.insert_trade(signal_id=sig5, symbol="BTCUSDT", side="SELL",
        order_id="100005", status="FILLED", requested_qty=50,
        executed_qty=0.000769, executed_price=65000.0, pnl=320.0)

    yield client