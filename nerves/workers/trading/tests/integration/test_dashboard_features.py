"""
Integration tests: test_dashboard_features.py
Tests the specialized analytical endpoints utilized by dashboard-features.js
(Scanner, Vision AI, Watchlist, RAG, and Watchlist Sync)

BUG-07 fix: Added missing Scanner endpoint test and Watchlist mutation tests.
"""

import pytest


@pytest.mark.asyncio
async def test_get_vision_history(client):
    """Dashboard should be able to fetch historical AI Vision captures."""
    response = await client.get("/api/vision/history?limit=20")
    assert response.status_code == 200
    assert "items" in response.json()


@pytest.mark.asyncio
async def test_get_vision_stats(client):
    """Dashboard should be able to retrieve KPI stats for Vision captures."""
    response = await client.get("/api/vision/stats")
    assert response.status_code == 200
    assert "total_captures" in response.json()


@pytest.mark.asyncio
async def test_get_briefs(client):
    """Dashboard should be able to retrieve Morning Brief lists."""
    response = await client.get("/api/briefs?limit=5")
    assert response.status_code == 200
    assert "briefs" in response.json()


@pytest.mark.asyncio
async def test_get_watchlist(client):
    """Dashboard should correctly load tracked symbols."""
    response = await client.get("/api/watchlist")
    assert response.status_code == 200
    assert "symbols" in response.json()
    assert isinstance(response.json()["symbols"], list)


@pytest.mark.asyncio
async def test_rag_query_endpoint(client):
    """Dashboard RAG querying functionality test."""
    response = await client.get("/api/rag/query?q=SEPA&n=3")
    # Depending on RAG init state, may return 200 or 503 if vector DB isn't loaded
    # We just ensure it's mapped correctly.
    assert response.status_code in (200, 503)


# ── BUG-07: Scanner and Watchlist mutation coverage ───────────────────────────


@pytest.mark.asyncio
async def test_watchlist_add_symbol(client):
    """
    BUG-07 fix: Dashboard should be able to add a symbol to the watchlist.
    POST /api/watchlist adds a new ticker symbol.
    API response shape: {added: bool, symbol: str, watchlist: list}
    """
    response = await client.post("/api/watchlist", json={"symbol": "NVDA"})
    assert response.status_code == 200
    data = response.json()
    assert data.get("added") is True or data.get("reason") == "already_exists"
    assert "NVDA" in data.get("watchlist", [])


@pytest.mark.asyncio
async def test_watchlist_remove_symbol(client):
    """
    BUG-07 fix: Dashboard should be able to remove a symbol from the watchlist.
    DELETE /api/watchlist removes a ticker symbol.
    Note: httpx.AsyncClient.delete() does not support a json body;
    symbol is passed as a query param to match the API contract.
    """
    # First add the symbol
    await client.post("/api/watchlist", json={"symbol": "TSLA"})
    # Then remove it via path param
    response = await client.delete("/api/watchlist/TSLA")
    assert response.status_code == 200
    data = response.json()
    assert data.get("removed") is True or data.get("reason") == "not_found"
    assert "TSLA" not in data.get("watchlist", [])


@pytest.mark.asyncio
async def test_scanner_watchlist_endpoint(client):
    """
    BUG-07 fix: The scanner endpoint (/api/scan/watchlist) used by
    dashboard-features.js must be reachable and return a valid structure.
    MCP is disabled in tests — scanner returns an empty or mock result.
    """
    response = await client.get("/api/scan/watchlist")
    # Scanner may return 200 (empty results) or 503 (MCP not connected in test env)
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        data = response.json()
        assert "results" in data or "error" in data


@pytest.mark.asyncio
async def test_vision_capture_endpoint(client):
    """
    Tests the /api/vision/capture endpoint which is called by the dashboard's
    "Capture + Analyze" button.
    Mocks the internal `capture_chart_and_analyze` function to prevent actual
    external calls (e.g., CDP, AI API).
    """
    from pathlib import Path
    from unittest.mock import AsyncMock, patch

    mock_vision_result = {
        "status": "ok",
        "symbol": "BTCUSDT",
        "screenshot_url": "/screenshots/test.png",
        "verdict": "STRONG BUY SETUP",
        "confidence": 8,
        "ai_analysis": "Mock AI analysis text.",
        "patterns": ["VCP"],
    }

    with (
        patch("config.MCP_ENABLED", True),
        patch("main._mcp_module.get_mcp_client") as mock_get_mcp,
        patch("main.vision_module.analyze_chart_vision") as mock_vision,
    ):
        mock_mcp = mock_get_mcp.return_value
        mock_mcp.health_check = AsyncMock(return_value={"connected": True})
        mock_mcp.capture_screenshot = AsyncMock(return_value=Path(__file__))
        mock_vision.side_effect = AsyncMock(return_value=mock_vision_result)

        response = await client.post("/api/vision/capture?symbol=BTCUSDT")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ok"
        assert data["symbol"] == "BTCUSDT"
        assert data["has_screenshot"] is True
        assert "brief_id" in data
        mock_vision.assert_called_once()
        mock_mcp.capture_screenshot.assert_called_once_with(
            symbol="BTCUSDT", timeframe="1H"
        )


@pytest.mark.asyncio
async def test_scanner_trigger_endpoint(client):
    """
    Tests the /api/scan/trigger endpoint which initiates a full scan.
    Mocks the internal `run_scanner_full` function to prevent actual
    scanner execution against MCP.
    """
    from unittest.mock import AsyncMock, patch

    with (
        patch("config.MCP_ENABLED", True),
        patch("main.wl_module.get_watchlist", return_value=["BTCUSDT"]),
        patch("main._mcp_module.get_mcp_client"),
        patch("main.analysis_module.scan_symbols") as mock_scan,
    ):
        mock_scan.side_effect = AsyncMock(return_value=[])

        response = await client.post("/api/scan/trigger")
        assert response.status_code == 200
        assert "results" in response.json()
        mock_scan.assert_called_once()


@pytest.mark.asyncio
async def test_watchlist_sync_endpoint(client):
    """
    Tests the /api/watchlist/sync endpoint, simulating the TradingView
    watchlist synchronization feature.
    Mocks the internal `sync_watchlist_with_tradingview` function.
    """
    from unittest.mock import AsyncMock, patch

    mock_sync_result = {
        "synced": True,
        "added": 2,
        "removed": 0,
        "watchlist": ["AAPL", "GOOG", "MSFT"],
    }
    with (
        patch("config.MCP_ENABLED", True),
        patch("main.wl_module.sync_from_tradingview") as mock_sync,
        patch("main._mcp_module.get_mcp_client"),
    ):
        mock_sync.side_effect = AsyncMock(return_value=mock_sync_result)

        response = await client.put("/api/watchlist/sync")
        assert response.status_code == 200
        assert response.json() == mock_sync_result
        mock_sync.assert_called_once()
