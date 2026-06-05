"""
Integration tests: GET /tv_health_check + Dashboard routes
"""

import pytest


@pytest.mark.asyncio
async def test_health_check_returns_ok(client):
    res = await client.get("/tv_health_check")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "time" in data
    assert "TradingView" in data["service"]


@pytest.mark.asyncio
async def test_health_check_has_correct_content_type(client):
    res = await client.get("/tv_health_check")
    assert "application/json" in res.headers["content-type"]


@pytest.mark.asyncio
async def test_dashboard_route_returns_html(client):
    res = await client.get("/dashboard")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert b"Dashboard" in res.content or b"dashboard" in res.content


@pytest.mark.asyncio
async def test_root_serves_dashboard(client):
    res = await client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
