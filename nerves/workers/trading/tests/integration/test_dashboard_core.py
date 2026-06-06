"""
Integration tests: test_dashboard_core.py
Tests the specific API endpoints utilized by dashboard-core.js.
"""

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_get_system_status(client):
    """Ensures the dashboard health check returns correct component states."""
    response = await client.get("/api/system/status")
    assert response.status_code == 200
    data = response.json()
    assert "server" in data
    assert "mcp" in data
    assert "telegram_bot" in data
    assert "rag" in data
    assert "database" in data


@pytest.mark.asyncio
async def test_trigger_brief_post(client):
    """Ensures the Morning Brief trigger endpoint is functional."""
    with patch("main.brief_module.generate_morning_brief"):
        response = await client.post("/api/brief/trigger")
        # Endpoint should accept the trigger (200 OK or 202 Accepted)
        assert response.status_code in (200, 202)
        # Verify the response payload confirms background task was enqueued
        assert response.json() == {
            "triggered": True,
            "message": "Morning Brief đang chạy... Kiểm tra Telegram trong 30-60 giây.",
        }
