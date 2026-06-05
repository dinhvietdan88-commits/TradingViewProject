"""
E2E test suite for the Indicator Signal Feed feature.
Covers:
1. Webhook Ingress (accepts "source": "indicator", validates fields, parses ATR values).
2. Indicator signals persistence (DI-1 EventBus listener stores to DB).
3. Query API endpoints (GET /api/indicator-signals and GET /api/indicator-signals/stats).
4. Watchlist management API (GET, POST, DELETE /api/watchlist, PUT /api/watchlist/sync).
"""

import sys
from pathlib import Path

# Add project root to sys.path so 'nerves' can be imported in all contexts
project_root = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Also add the nerves/workers/trading folder to path
trading_dir = Path(__file__).resolve().parent.parent.parent
if str(trading_dir) not in sys.path:
    sys.path.insert(0, str(trading_dir))

import pytest  # noqa: E402
import asyncio  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402

# Explicitly import persistence module to register the EventBus handler in tests
import data.indicator_persistence  # noqa: F401, E402


@pytest.mark.asyncio
async def test_indicator_signal_feed_full_e2e(client, mocker):
    # Mock EventBus notify/telegram calls if they do background calls
    mocker.patch("main.notifier.notify_all", return_value=True)

    # 1. Post a valid indicator signal with ATR risk metadata
    payload = {
        "secret": "test-secret",
        "source": "indicator",
        "symbol": "BTCUSDT",
        "indicator_name": "SuperTrend",
        "signal_type": "entry",
        "confidence_score": 85,
        "conditions_met": ["price > ST"],
        "metadata": {"atr_value": "1000.0"},
        "interval": "60",
        "price": 68000.0,
        "exchange": "binance",
    }

    response = await client.post("/webhook", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
    assert data["status"] == "dispatched"
    signal_id = data["signal_id"]
    assert signal_id > 0

    # Await all background tasks on the bus to ensure persistence is complete
    from core.event_bus import bus as _event_bus

    if _event_bus._background_tasks:
        await asyncio.gather(*list(_event_bus._background_tasks))

    # 2. Query /api/indicator-signals to verify it's persisted in DB
    query_resp = await client.get("/api/indicator-signals?limit=10")
    assert query_resp.status_code == 200
    query_data = query_resp.json()
    assert query_data["total"] >= 1

    # Verify properties of the received signal
    signal = query_data["signals"][0]
    assert signal["symbol"] == "BTCUSDT"
    assert signal["indicator_name"] == "SuperTrend"
    assert signal["signal_type"] == "entry"
    assert signal["confidence_score"] == 85
    assert "price > ST" in signal["conditions_met"]
    assert signal["metadata"]["atr_value"] == "1000.0"
    assert signal["interval"] == "60"
    assert signal["price"] == 68000.0
    assert signal["exchange"] == "binance"

    # 3. Query /api/indicator-signals/stats to verify KPIs are generated correctly
    stats_resp = await client.get("/api/indicator-signals/stats")
    assert stats_resp.status_code == 200
    stats_data = stats_resp.json()
    assert stats_data["total"] >= 1
    assert stats_data["by_type"]["entry"]["count"] == 1
    assert stats_data["avg_confidence"] == 85.0
    assert any(ind["name"] == "SuperTrend" for ind in stats_data["top_indicators"])
    assert any(sym["symbol"] == "BTCUSDT" for sym in stats_data["top_symbols"])
    assert "direction_mix" in stats_data
    assert "market_regime" in stats_data

    # Test filtering stats by symbol
    stats_btc = await client.get("/api/indicator-signals/stats?symbol=BTCUSDT")
    assert stats_btc.status_code == 200
    stats_btc_data = stats_btc.json()
    assert stats_btc_data["total"] >= 1
    assert stats_btc_data["by_type"]["entry"]["count"] == 1
    assert "long" in stats_btc_data["direction_mix"]

    # Test filtering stats by a symbol with no signals
    stats_eth = await client.get("/api/indicator-signals/stats?symbol=ETHUSDT")
    assert stats_eth.status_code == 200
    assert stats_eth.json()["total"] == 0

    # Test filtering stats by indicator_name
    stats_ind = await client.get(
        "/api/indicator-signals/stats?indicator_name=SuperTrend"
    )
    assert stats_ind.status_code == 200
    assert stats_ind.json()["total"] >= 1

    stats_ind_none = await client.get(
        "/api/indicator-signals/stats?indicator_name=NonExistent"
    )
    assert stats_ind_none.status_code == 200
    assert stats_ind_none.json()["total"] == 0


@pytest.mark.asyncio
async def test_indicator_signal_validation_e2e(client):
    # Missing required field: symbol
    payload_no_sym = {
        "secret": "test-secret",
        "source": "indicator",
        "indicator_name": "SuperTrend",
        "signal_type": "entry",
    }
    resp = await client.post("/webhook", json=payload_no_sym)
    assert resp.status_code == 400
    assert "symbol" in resp.json()["detail"].lower()

    # Missing required field: indicator_name
    payload_no_ind = {
        "secret": "test-secret",
        "source": "indicator",
        "symbol": "BTCUSDT",
        "signal_type": "entry",
    }
    resp = await client.post("/webhook", json=payload_no_ind)
    assert resp.status_code == 400
    assert "indicator_name" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_watchlist_crud_e2e(client, mocker, tmp_path):
    # Set path of watchlist to a temp path to isolate test
    import watchlist

    mocker.patch.object(watchlist, "_WATCHLIST_FILE", tmp_path / "watchlist.json")

    # 1. Fetch initial watchlist (should be default)
    get_resp = await client.get("/api/watchlist")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert "BTCUSDT" in data["symbols"]

    # 2. Add non-default symbol to watchlist (SOLUSDT is default, so use DOGEUSDT)
    post_resp = await client.post("/api/watchlist", json={"symbol": "DOGEUSDT"})
    assert post_resp.status_code == 200
    post_data = post_resp.json()
    assert post_data["added"] is True
    assert "DOGEUSDT" in post_data["watchlist"]

    # 3. Delete symbol from watchlist
    del_resp = await client.delete("/api/watchlist/DOGEUSDT")
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    assert del_data["removed"] is True
    assert "DOGEUSDT" not in del_data["watchlist"]

    # 4. Sync from TradingView (mock MCP response)
    mock_mcp = mocker.patch("mcp_client.get_mcp_client")
    mock_client = AsyncMock()
    mock_client._run.return_value = ["ETHUSDT", "ADAUSDT"]
    mock_mcp.return_value = mock_client

    # Set MCP_ENABLED temporarily to True for the endpoint to allow sync
    import config

    original_mcp_enabled = config.MCP_ENABLED
    try:
        config.MCP_ENABLED = True
        sync_resp = await client.put("/api/watchlist/sync")
        assert sync_resp.status_code == 200
        sync_data = sync_resp.json()
        assert sync_data["synced"] is True
        assert "ETHUSDT" in sync_data["watchlist"]
        assert "ADAUSDT" in sync_data["watchlist"]
    finally:
        config.MCP_ENABLED = original_mcp_enabled
