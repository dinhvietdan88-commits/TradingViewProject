import pytest
from httpx import ASGITransport, AsyncClient
from server.main import app

import config


@pytest.fixture
async def async_client():
    """Fixture to provide an AsyncClient for testing the FastAPI app with isolated dependencies."""
    # Reset rate limiting state before each test
    from gateway.webhook import _WEBHOOK_RATE_LIMITS

    _WEBHOOK_RATE_LIMITS.clear()

    # Disable external daemons and DB/RAG for test isolation
    config.TELEGRAM_BOT_ENABLED = False
    config.BRIEF_ENABLED = False
    config.MCP_ENABLED = False
    config.RAG_ENABLED = False
    config.WEBHOOK_SECRET = "test-secret"  # noqa: S105 # pragma: allowlist secret

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_webhook_auth_failure(async_client):
    """Test that webhook rejects requests with missing or invalid secret."""
    payload = {"action": "buy", "symbol": "BTCUSDT"}

    # Missing secret completely
    response = await async_client.post("/webhook", json=payload)
    assert response.status_code == 401

    # Invalid secret passed via headers
    response = await async_client.post(
        "/webhook",
        json=payload,
        headers={"X-TV-Secret": "wrong-secret"},  # pragma: allowlist secret
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_webhook_auth_success(async_client, mocker):
    """Test that a webhook with a valid secret is accepted."""
    # Mock out database insertions to test purely the auth logic
    mocker.patch("server.database.insert_signal", return_value=1)
    mocker.patch("server.database.update_signal_status", return_value=True)

    payload = {
        "action": "alert",
        "symbol": "BTCUSDT",
        "secret": "test-secret",  # pragma: allowlist secret
    }

    response = await async_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["received"] is True


@pytest.mark.asyncio
async def test_webhook_rate_limiting(async_client, mocker):
    """Test that webhook accurately limits requests from the same IP to 15 req/min."""
    mocker.patch("server.database.insert_signal", return_value=1)
    mocker.patch("server.database.update_signal_status", return_value=True)

    payload = {
        "action": "buy",
        "symbol": "BTCUSDT",
        "secret": "test-secret",  # pragma: allowlist secret
    }

    # Send 15 allowed requests rapidly
    for _ in range(15):
        response = await async_client.post("/webhook", json=payload)
        assert response.status_code == 200

    # The 16th request should hit the rate limiter
    response = await async_client.post("/webhook", json=payload)
    assert response.status_code == 429
    assert response.json() == {"detail": "Too Many Requests"}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_price", ["not-a-number", None, {}, [], "1,000,000.50"])
@pytest.mark.parametrize("bad_qty", ["infinity", -500, "NaN", None])
async def test_webhook_safe_parsing(async_client, mocker, bad_price, bad_qty):
    """Test safe fallbacks on payload fields (fixing TVP-001/CWE-20 & TVP-002/CWE-770)."""
    mocker.patch("server.database.insert_signal", return_value=1)
    mocker.patch("server.database.update_signal_status", return_value=True)

    payload = {
        "action": "buy",
        "symbol": "BTCUSDT",
        "secret": "test-secret",  # pragma: allowlist secret
        "price": bad_price,
        "quoteQty": bad_qty,
    }

    # Asserts that the endpoint gracefully catches type/value errors instead of throwing a 500 error
    response = await async_client.post("/webhook", json=payload)
    assert response.status_code == 200
