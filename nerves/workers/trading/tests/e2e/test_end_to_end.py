"""
E2E tests: test_end_to_end.py
Tests full webhook lifecycle from signal receipt through trade execution.

BUG-02 fixes:
  1. config.DB_NAME -> config.DB_PATH: ensures in-memory override actually works.
  2. Global PAYLOADS removed: fixture now returns payloads as a value to
     prevent race conditions if tests ever run in parallel (pytest-xdist).
"""

import pytest
import json
import sys
import os
from httpx import AsyncClient, ASGITransport

# Add server to path so we can import main
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from main import app
from database import init_db


def load_payloads():
    import config

    payloads_path = os.path.join(
        os.path.dirname(__file__), "../mock_data/payloads.json"
    )
    with open(payloads_path, "r") as f:
        payloads = json.load(f)

    # Inject config.WEBHOOK_SECRET into payloads
    for key, payload in payloads.items():
        if key != "invalid_secret" and "secret" in payload:
            payload["secret"] = config.WEBHOOK_SECRET
    return payloads


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path):
    """
    BUG-02 fix #1: Use config.DB_PATH (not config.DB_NAME) to match what
    the app actually reads. Using :memory: via the wrong key had no effect
    and tests silently ran against a real DB file.
    BUG-02 fix #2: Return payloads as fixture value instead of a global
    to avoid mutation/race conditions with parallel test execution.
    """
    import config

    config.DB_PATH = str(tmp_path / "e2e_test.db")
    await init_db()
    return load_payloads()


@pytest.mark.asyncio
async def test_valid_1h_buy_webhook(setup_test_db, mocker):
    """A valid 1H BUY signal with correct secret should be accepted for processing."""
    payloads = setup_test_db
    mocker.patch("main.notifier.notify_all", return_value=True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/webhook", json=payloads["valid_1h_buy"])

    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
    assert data["status"] == "dispatched"
    assert "signal_id" in data


@pytest.mark.asyncio
async def test_invalid_4h_buy_webhook(setup_test_db, mocker):
    """A 4H interval signal should be rejected by the Circuit Breaker timeframe filter."""
    payloads = setup_test_db
    mocker.patch("main.notifier.notify_all", return_value=True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/webhook", json=payloads["invalid_4h_buy"])

    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
    assert (
        data["status"] == "dispatched"
    )  # Phase 5: rejection is now async (SignalProcessor → NotificationHub)


@pytest.mark.asyncio
async def test_invalid_secret_webhook(setup_test_db):
    """A payload with a wrong secret should receive a 401 Unauthorized."""
    payloads = setup_test_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/webhook", json=payloads["invalid_secret"])

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


@pytest.mark.asyncio
async def test_missing_interval_webhook(setup_test_db, mocker):
    """A payload with a missing interval should be rejected by the Circuit Breaker."""
    payloads = setup_test_db
    mocker.patch("main.notifier.notify_all", return_value=True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/webhook", json=payloads["missing_interval"])

    assert response.status_code == 200
    data = response.json()
    assert data["received"] is True
    assert (
        data["status"] == "dispatched"
    )  # Phase 5: rejection is now async (SignalProcessor → NotificationHub)
