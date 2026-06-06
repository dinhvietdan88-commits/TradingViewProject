from unittest.mock import AsyncMock

import pytest

from mcp_client import MCPClient


@pytest.mark.asyncio
async def test_get_study_values_flattening():
    """Verify that get_study_values correctly flattens the 'studies' list format."""
    client = MCPClient()

    # Mock the internal _run method to simulate CLI responses for:
    # 1. symbol config
    # 2. timeframe config
    # 3. values retrieval
    mock_run = AsyncMock()
    mock_run.side_effect = [
        {"success": True},  # symbol
        {"success": True},  # timeframe
        {
            "success": True,
            "studies": [
                {"name": "SMA 50", "values": {"Plot": "65000.1"}},
                {"name": "Moving Average 150", "values": {"MA": "64000.2"}},
                {"name": "ma 200", "values": {"MA": "63000.3"}},
                {"name": "Average True Range", "values": {"ATR": "150.4"}},
            ],
        },
    ]
    client._run = mock_run

    study_vals = await client.get_study_values("BTCUSDT", "1h")

    # Verify exact parsed float values after flattening
    assert study_vals.sma50 == pytest.approx(65000.1)
    assert study_vals.sma150 == pytest.approx(64000.2)
    assert study_vals.sma200 == pytest.approx(63000.3)
    assert study_vals.atr14 == pytest.approx(150.4)
