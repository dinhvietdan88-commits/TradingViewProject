"""
Integration tests: test_webhook.py
Tests the /webhook endpoint and standard execution logic.
"""

import pytest


@pytest.mark.asyncio
async def test_webhook_buy_order_success(client):
    payload = {
        "secret": "test-secret",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "price": 68000,
        "risk_pct": 2,
    }
    response = await client.post("/webhook", json=payload)
    # Assuming a fully configured mock environment would return 200
    assert response.status_code in (200, 202)


@pytest.mark.asyncio
async def test_webhook_validation_error(client):
    # Empty payload should return 400
    response = await client.post("/webhook", json={"secret": "test-secret"})
    assert response.status_code == 400
    data = response.json()
    assert data["detail"] == "Missing required field: symbol"
