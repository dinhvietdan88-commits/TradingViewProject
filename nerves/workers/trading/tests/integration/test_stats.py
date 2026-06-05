"""
Integration tests: test_stats.py
Tests the KPI stats endpoint to verify correct win rate and total P&L.
"""

import pytest


@pytest.mark.asyncio
async def test_get_stats_empty(client):
    response = await client.get("/trades/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_trades"] == 0
    assert data["win_rate"] == 0.0


@pytest.mark.asyncio
async def test_get_stats_with_data(client_with_trades):
    response = await client_with_trades.get("/trades/stats")
    assert response.status_code == 200
    data = response.json()
    # We seeded 5 trades: 4 filled, 1 failed. Of the 4 filled: 3 winners, 1 loser
    assert data["total_trades"] == 4
    assert data["winning_trades"] == 3
    assert data["losing_trades"] == 1
    assert data["win_rate"] == 75.0
