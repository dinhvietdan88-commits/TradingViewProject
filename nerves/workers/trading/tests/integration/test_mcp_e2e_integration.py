from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mcp_client import QuoteData, StudyValues


@pytest.mark.asyncio
async def test_mcp_watchlist_scan_flow(client, mocker):
    """Test /api/scan/watchlist with a mocked MCP client."""
    # 1. Enable MCP
    mocker.patch("config.MCP_ENABLED", True)

    # 2. Mock MCPClient batch_run
    mock_mcp = mocker.patch("mcp_client.get_mcp_client")
    mock_client = AsyncMock()
    mock_mcp.return_value = mock_client

    # Create realistic Quote and StudyValues to trigger a high TT score and VCP detection
    mock_quote = QuoteData(
        symbol="BTCUSDT",
        close=100.0,
        open=98.0,
        high=101.0,
        low=99.5,
        volume=4000.0,
        change_pct=2.0,
    )
    mock_studies = StudyValues(
        sma50=95.0,
        sma150=90.0,
        sma200=85.0,
        volume_avg20=10000.0,  # volume 5000 < 50% avg -> vol contracting
        atr14=4.0,  # range 2.0 < 50% ATR -> range contracting
        rs_line=1.2,
        high_52w=105.0,  # within 10% of high -> near_high
        low_52w=70.0,
    )

    mock_client.health_check.return_value = {"connected": True}
    mock_client.batch_run.return_value = [
        {
            "symbol": "BTCUSDT",
            "quote": mock_quote,
            "studies": mock_studies,
            "ohlcv_summary": {},
            "error": None,
        }
    ]

    # 3. Call endpoint
    # Set watchlist to return BTCUSDT
    mocker.patch("watchlist.get_watchlist", return_value=["BTCUSDT"])

    response = await client.get("/api/scan/watchlist")
    assert response.status_code == 200
    data = response.json()
    assert data["scanned"] == 1
    assert len(data["results"]) == 1

    result = data["results"][0]
    assert result["symbol"] == "BTCUSDT"
    assert result["price"] == 100.0
    # MCP path does not pass sma200_slope to score_trend_template, so criteria 3 is None (treated as False)
    # Total score is 7/8.
    assert result["trend_template_score"] == 7
    assert result["vcp_detected"] is True


@pytest.mark.asyncio
async def test_morning_brief_trigger_and_persistence(client, mocker):
    """Test full morning brief generation, notification, and database persistence."""
    # 1. Enable features
    mocker.patch("config.MCP_ENABLED", True)
    mocker.patch("config.BRIEF_ENABLED", True)
    mocker.patch("config.RAG_ENABLED", True)
    mocker.patch(
        "config.GEMINI_API_KEY", "fake-test-key"
    )  # needed to pass has_gemini guard at line 200

    # 2. Mock MCPClient status, batch_run, and screenshot inside brief namespace
    mock_mcp = mocker.patch("brief.get_mcp_client")
    mock_client = AsyncMock()
    mock_mcp.return_value = mock_client

    mock_quote = QuoteData(
        symbol="BTCUSDT",
        close=100.0,
        open=98.0,
        high=101.0,
        low=99.5,
        volume=4000.0,
        change_pct=2.0,
    )
    mock_studies = StudyValues(
        sma50=95.0,
        sma150=90.0,
        sma200=85.0,
        volume_avg20=10000.0,
        atr14=4.0,
        rs_line=1.2,
        high_52w=105.0,
        low_52w=70.0,
    )

    mock_client.health_check.return_value = {"connected": True}
    mock_client.batch_run.return_value = [
        {
            "symbol": "BTCUSDT",
            "quote": mock_quote,
            "studies": mock_studies,
            "ohlcv_summary": {},
            "error": None,
        }
    ]
    mock_client.capture_screenshot.return_value = Path(__file__)

    # 3. Mock RAG advice, search, and vision inside brief namespace
    mocker.patch(
        "brief.query_knowledge",
        return_value=[
            {"content": "mock RAG chunk", "metadata": {}, "relevance_score": 0.95}
        ],
    )
    mocker.patch(
        "brief.generate_trading_advice",
        new_callable=AsyncMock,
        return_value="Minervini AI: Watchlist is showing strong VCP setup.",
    )
    mocker.patch(
        "rag.generate_trading_advice",
        new_callable=AsyncMock,
        return_value="Minervini AI: Watchlist is showing strong VCP setup.",
    )
    mocker.patch(
        "brief.analyze_chart_vision",
        new_callable=AsyncMock,
        return_value={"confidence": 8, "patterns": ["VCP"], "error": None},
    )

    # 4. Mock Telegram sends to avoid network calls inside brief namespace
    mock_send_photo = mocker.patch("brief.send_telegram_photo")
    mocker.patch("brief.send_telegram_message")

    # Mock watchlist inside brief namespace
    mocker.patch("brief.get_watchlist", return_value=["BTCUSDT"])

    # 5. Call trigger API endpoint with generate_morning_brief patched to avoid background double-execution
    with patch("main.brief_module.generate_morning_brief"):
        response = await client.post("/api/brief/trigger")
    assert response.status_code == 200
    assert response.json()["triggered"] is True

    # 6. Execute background generation directly to test end-to-end flow synchronously
    from brief import generate_morning_brief

    brief_data = await generate_morning_brief()

    assert brief_data is not None
    assert brief_data["success"] is True
    assert brief_data["symbols_scanned"] == 1
    assert "BTCUSDT" in brief_data["text"]
    assert (
        "Minervini AI: Watchlist is showing strong VCP setup."
        in brief_data["ai_analysis"]
    )

    # Verify Telegram notification was triggered
    mock_send_photo.assert_called_once()

    # 7. Verify persistence via latest brief endpoint
    latest_resp = await client.get("/api/brief/latest")
    assert latest_resp.status_code == 200
    latest_data = latest_resp.json()
    assert latest_data["available"] is True
    assert latest_data["symbols_scanned"] == 1
