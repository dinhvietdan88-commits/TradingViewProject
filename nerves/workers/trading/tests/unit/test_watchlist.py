import pytest
from unittest.mock import MagicMock, patch

import watchlist


@pytest.fixture(autouse=True)
def mock_watchlist_file(tmp_path):
    """Patch the watchlist file path to use a temporary file for tests."""
    temp_file = tmp_path / "watchlist.json"
    with patch.object(watchlist, "_WATCHLIST_FILE", temp_file):
        yield temp_file


def test_get_watchlist_default():
    """Verify that get_watchlist returns default symbols when file doesn't exist."""
    assert watchlist.get_watchlist() == watchlist._DEFAULT_SYMBOLS


def test_get_watchlist_loaded(mock_watchlist_file):
    """Verify loading from JSON file."""
    mock_watchlist_file.write_text(
        '{"symbols": ["BTCUSDT", "ETHUSDT"]}', encoding="utf-8"
    )
    assert watchlist.get_watchlist() == ["BTCUSDT", "ETHUSDT"]


def test_get_watchlist_load_exception(mock_watchlist_file):
    """Verify fallback to defaults on JSON decode error."""
    mock_watchlist_file.write_text("invalid json", encoding="utf-8")
    assert watchlist.get_watchlist() == watchlist._DEFAULT_SYMBOLS


def test_add_symbol_new():
    """Verify adding a new symbol."""
    wl = watchlist.get_watchlist()
    assert "ADAUSDT" not in wl, f"ADAUSDT is already in watchlist: {wl}"
    res = watchlist.add_symbol("adausdt")
    assert res["added"] is True
    assert "ADAUSDT" in res["watchlist"]
    assert watchlist.get_watchlist() == res["watchlist"]


def test_add_symbol_duplicate():
    """Verify duplicate handling."""
    watchlist.set_watchlist(["BTCUSDT"])
    res = watchlist.add_symbol("btcusdt")
    assert res["added"] is False
    assert res["reason"] == "already_exists"


def test_remove_symbol_existing():
    """Verify removing an existing symbol."""
    watchlist.set_watchlist(["BTCUSDT", "ETHUSDT"])
    res = watchlist.remove_symbol("ethusdt")
    assert res["removed"] is True
    assert "ETHUSDT" not in res["watchlist"]


def test_remove_symbol_nonexistent():
    """Verify removing a non-existent symbol."""
    watchlist.set_watchlist(["BTCUSDT"])
    res = watchlist.remove_symbol("solusdt")
    assert res["removed"] is False
    assert res["reason"] == "not_found"


def test_set_watchlist():
    """Verify replacing the entire watchlist."""
    res = watchlist.set_watchlist(["solusdt", "", "btcusdt "])
    assert res == ["SOLUSDT", "BTCUSDT"]
    assert watchlist.get_watchlist() == ["SOLUSDT", "BTCUSDT"]


@pytest.mark.asyncio
async def test_sync_from_tradingview_list():
    """Verify syncing from a list returned by TradingView."""
    watchlist.set_watchlist(["BTCUSDT"])
    mcp_client = MagicMock()

    # Mock return list
    async def mock_run(scope, action):
        return ["ETHUSDT", "SOLUSDT"]

    mcp_client._run = mock_run

    res = await watchlist.sync_from_tradingview(mcp_client)
    assert res["synced"] is True
    assert res["added"] == 2
    assert res["total"] == 3
    assert watchlist.get_watchlist() == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


@pytest.mark.asyncio
async def test_sync_from_tradingview_dict():
    """Verify syncing from a dict returned by TradingView."""
    watchlist.set_watchlist(["BTCUSDT"])
    mcp_client = MagicMock()

    # Mock return dict
    async def mock_run(scope, action):
        return {"symbols": ["ETHUSDT", "BTCUSDT"]}

    mcp_client._run = mock_run

    res = await watchlist.sync_from_tradingview(mcp_client)
    assert res["synced"] is True
    assert res["added"] == 1
    assert watchlist.get_watchlist() == ["BTCUSDT", "ETHUSDT"]


@pytest.mark.asyncio
async def test_sync_from_tradingview_empty():
    """Verify handling of empty TradingView watchlist."""
    mcp_client = MagicMock()

    async def mock_run(scope, action):
        return []

    mcp_client._run = mock_run

    res = await watchlist.sync_from_tradingview(mcp_client)
    assert res["synced"] is False
    assert res["reason"] == "empty_watchlist_from_tv"


@pytest.mark.asyncio
async def test_sync_from_tradingview_error():
    """Verify error handling on exception."""
    mcp_client = MagicMock()

    async def mock_run(scope, action):
        raise RuntimeError("Connection error")

    mcp_client._run = mock_run

    res = await watchlist.sync_from_tradingview(mcp_client)
    assert res["synced"] is False
    assert "Connection error" in res["error"]
