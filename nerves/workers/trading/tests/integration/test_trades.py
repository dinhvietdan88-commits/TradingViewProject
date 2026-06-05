"""
Integration tests: test_trades.py
Tests the /trades endpoint for retrieving trade history and pagination.
"""

import pytest


@pytest.mark.asyncio
async def test_get_trades_empty(client):
    """Should return an empty list when no trades exist."""
    response = await client.get("/trades")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["trades"] == []


@pytest.mark.asyncio
async def test_get_trades_with_data(client_with_trades):
    """Should return all trades correctly."""
    response = await client_with_trades.get("/trades")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert len(data["trades"]) == 5


@pytest.mark.asyncio
async def test_get_trades_pagination(client_with_trades):
    """Should properly paginate results."""
    response = await client_with_trades.get("/trades?limit=2&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert len(data["trades"]) == 2


@pytest.mark.asyncio
async def test_get_trades_filter_by_symbol(client_with_trades):
    """Should properly filter trades by symbol."""
    response = await client_with_trades.get("/trades?symbol=ETHUSDT")
    assert response.status_code == 200
    assert all(t["symbol"] == "ETHUSDT" for t in response.json()["trades"])
