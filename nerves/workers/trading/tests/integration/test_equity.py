"""
Integration tests: test_equity.py
Tests the /trades/equity endpoint to ensure the equity curve generates properly.
"""

import pytest


@pytest.mark.asyncio
async def test_get_equity_empty(client):
    response = await client.get("/trades/equity")
    assert response.status_code == 200
    data = response.json()
    assert data["labels"] == []
    assert data["cumulative_pnl"] == []


@pytest.mark.asyncio
async def test_get_equity_with_data(client_with_trades):
    response = await client_with_trades.get("/trades/equity")
    assert response.status_code == 200
    data = response.json()

    assert len(data["labels"]) > 0
    assert len(data["cumulative_pnl"]) > 0
