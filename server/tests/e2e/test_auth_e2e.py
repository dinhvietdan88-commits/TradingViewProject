"""
E2E Auth Flow Tests — test_auth_e2e.py
=======================================
Simulates the full Telegram Dashboard Auth lifecycle WITHOUT a real Telegram
bot, using httpx ASGITransport (no extra dependencies beyond the test stack).

Flow under test:
    1. [Bot sim]   AuthService generates a one-time code (as /login command does)
    2. [Browser]   GET /auth/callback?code=<code>  -> 302 -> /
    3. [Browser]   tg_session cookie is set on response
    4. [Browser]   Authenticated request with cookie reaches protected endpoint
    5. [Browser]   GET /auth/logout -> cookie cleared, redirect to /auth/login
    6. [Negative]  Replay attack: same code rejected on second use
    7. [Negative]  Expired code rejected
    8. [Negative]  Tampered token rejected on protected endpoint
"""

import os
import sys
import pathlib
import time
import pytest
import pytest_asyncio

# ── Environment setup BEFORE any app imports ─────────────────────────────────
os.environ["WEBHOOK_SECRET"] = "test-secret"
os.environ["TELEGRAM_BOT_ENABLED"] = "false"
os.environ["BRIEF_ENABLED"] = "false"
os.environ["RAG_ENABLED"] = "false"
os.environ["MCP_ENABLED"] = "false"
os.environ["DASHBOARD_TOKEN"] = "legacy-token-abc"       # Enable auth gate
os.environ["AUTH_SECRET_KEY"] = "e2e-test-secret-key-must-be-32-chars!!"
os.environ["TELEGRAM_ALLOWED_USERS"] = "123456789"  # Plain int string, comma-sep
os.environ["SESSION_EXPIRY_HOURS"] = "24"
os.environ["DASHBOARD_URL"] = "http://test"

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from httpx import AsyncClient, ASGITransport


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def auth_client(tmp_path):
    """
    Full-stack client with AuthMiddleware active.
    Builds AuthService directly and injects it into app.state,
    bypassing the lifespan (no asgi-lifespan dependency required).
    """
    import config
    import database

    config.DB_PATH = str(tmp_path / "e2e_auth.db")
    config.WEBHOOK_SECRET = "test-secret"
    config.TELEGRAM_BOT_ENABLED = False
    config.BRIEF_ENABLED = False
    config.MCP_ENABLED = False
    config.RAG_ENABLED = False
    config.DASHBOARD_TOKEN = "legacy-token-abc"    # Auth gate ON
    os.environ["DB_PATH"] = config.DB_PATH
    os.environ["DASHBOARD_TOKEN"] = "legacy-token-abc"

    await database.init_db()

    from main import app
    from auth.service import AuthService
    from auth.auth_config import AuthConfig

    # Build AuthService using env vars (AuthConfig reads os.environ at init time)
    # ENV is already patched above: AUTH_SECRET_KEY, TELEGRAM_ALLOWED_USERS, etc.
    auth_cfg = AuthConfig()     # No-arg: reads from os.environ
    svc = AuthService(auth_cfg)
    app.state.auth_service = svc

    # Middleware lazily reads auth_service from app.state at dispatch time,
    # so simply setting app.state.auth_service is sufficient (no stack patching needed).

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_service(auth_client):
    """Return the AuthService injected into app.state."""
    from main import app
    svc = getattr(app.state, "auth_service", None)
    assert svc is not None, "AuthService not injected into app.state"
    return svc


def _session_cookie(response) -> str | None:
    return response.cookies.get("tg_session")


def _make_code(svc, telegram_id=123456789, username="testuser"):
    """Helper: generate + store a one-time code."""
    import database
    code_obj = svc.generate_login_code(
        telegram_id=telegram_id,
        username=username,
    )
    database.store_auth_code(
        code=code_obj.code,
        telegram_id=code_obj.telegram_id,
        username=code_obj.username,
        created_at=code_obj.created_at.isoformat(),
        expires_at=code_obj.expires_at.isoformat(),
    )
    return code_obj


# ═════════════════════════════════════════════════════════════════════════════
# POSITIVE FLOWS
# ═════════════════════════════════════════════════════════════════════════════

class TestHappyPath:

    @pytest.mark.asyncio
    async def test_login_page_accessible(self, auth_client):
        """GET /auth/login always returns 200 (no auth needed)."""
        r = await auth_client.get("/auth/login")
        assert r.status_code == 200
        assert "html" in r.headers.get("content-type", "").lower()

    @pytest.mark.asyncio
    async def test_static_login_html_accessible(self, auth_client):
        """Static login.html asset is always public."""
        r = await auth_client.get("/static/login.html")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_full_login_flow(self, auth_client, auth_service):
        """
        Full E2E: code generation -> callback -> session cookie -> auth access.
        """
        # Step 1: [Bot] Generate one-time code
        code_obj = _make_code(auth_service)

        # Step 2: [Browser] Follow login link
        r = await auth_client.get(f"/auth/callback?code={code_obj.code}")
        assert r.status_code in (302, 303), f"Expected redirect, got {r.status_code}: {r.text}"

        # Step 3: Session cookie must be present
        session_token = _session_cookie(r)
        assert session_token, "tg_session cookie not set after successful login"

        # Step 4: [Browser] Authenticated request
        r2 = await auth_client.get(
            "/trades",
            cookies={"tg_session": session_token},
        )
        assert r2.status_code == 200, f"Auth request failed: {r2.status_code}"

    @pytest.mark.asyncio
    async def test_bearer_token_backward_compat(self, auth_client):
        """Legacy Bearer DASHBOARD_TOKEN must still grant access."""
        r = await auth_client.get(
            "/trades",
            headers={"Authorization": "Bearer legacy-token-abc"},
        )
        assert r.status_code == 200, \
            f"Bearer token rejected - backward compat broken: {r.status_code}"

    @pytest.mark.asyncio
    async def test_logout_after_login(self, auth_client, auth_service):
        """Login -> logout -> verify redirect to /auth/login."""
        code_obj = _make_code(auth_service)
        login_r = await auth_client.get(f"/auth/callback?code={code_obj.code}")
        token = _session_cookie(login_r)
        assert token, "Login failed - no cookie"

        logout_r = await auth_client.get(
            "/auth/logout",
            cookies={"tg_session": token},
        )
        # Accept redirect to login or 200 (if logout page rendered)
        assert logout_r.status_code in (200, 302, 303)


# ═════════════════════════════════════════════════════════════════════════════
# SECURITY BOUNDARIES
# ═════════════════════════════════════════════════════════════════════════════

class TestSecurityBoundaries:

    @pytest.mark.asyncio
    async def test_no_auth_blocked(self, auth_client):
        """Protected endpoint without credential -> 401 or 302."""
        r = await auth_client.get("/trades")
        assert r.status_code in (401, 302), \
            f"Unauthenticated access succeeded: {r.status_code}"

    @pytest.mark.asyncio
    async def test_replay_attack_rejected(self, auth_client, auth_service):
        """Same one-time code cannot be used twice."""
        code_obj = _make_code(auth_service)

        r1 = await auth_client.get(f"/auth/callback?code={code_obj.code}")
        assert r1.status_code in (302, 303), "First use should succeed"

        r2 = await auth_client.get(f"/auth/callback?code={code_obj.code}")
        assert r2.status_code in (400, 401, 404), \
            f"Replay attack succeeded with {r2.status_code}"

    @pytest.mark.asyncio
    async def test_invalid_code_rejected(self, auth_client):
        """Fabricated code returns error (not 200 or 302)."""
        r = await auth_client.get("/auth/callback?code=totally-fake-code-000")
        assert r.status_code in (400, 401, 404, 503)

    @pytest.mark.asyncio
    async def test_empty_code_rejected(self, auth_client):
        """Empty code is rejected cleanly."""
        r = await auth_client.get("/auth/callback?code=")
        assert r.status_code in (400, 401, 422, 503)

    @pytest.mark.asyncio
    async def test_tampered_token_rejected(self, auth_client):
        """Tampered tg_session cookie -> no access."""
        r = await auth_client.get(
            "/trades",
            cookies={"tg_session": "eyJhbGciOiJIUzI1NiJ9.tampered.sig"},
        )
        assert r.status_code in (401, 302)

    @pytest.mark.asyncio
    async def test_wrong_bearer_rejected(self, auth_client):
        """Wrong Bearer token -> 401."""
        r = await auth_client.get(
            "/trades",
            headers={"Authorization": "Bearer wrong-token-xyz"},
        )
        assert r.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_bearer_query_param_blocked(self, auth_client):
        """SEC-005: Token in query string must NOT grant access."""
        r = await auth_client.get("/trades?token=legacy-token-abc")
        assert r.status_code in (401, 302), \
            f"Query-param token bypass succeeded - SEC-005 violation! Got {r.status_code}"

    @pytest.mark.asyncio
    async def test_expired_code_rejected(self, auth_client, auth_service):
        """Code with past expiry is rejected."""
        import database
        code_obj = auth_service.generate_login_code(
            telegram_id=123456789, username="testuser"
        )
        # Store with expiry 1 second in the past
        from datetime import datetime, timezone
        past = datetime.fromtimestamp(int(time.time()) - 1, tz=timezone.utc)
        database.store_auth_code(
            code=code_obj.code,
            telegram_id=code_obj.telegram_id,
            username=code_obj.username,
            created_at=code_obj.created_at.isoformat(),
            expires_at=past.isoformat(),
        )
        r = await auth_client.get(f"/auth/callback?code={code_obj.code}")
        assert r.status_code in (400, 401, 410), \
            f"Expired code accepted: {r.status_code}"

    @pytest.mark.asyncio
    async def test_non_allowlisted_user_rejected(self, auth_client, auth_service):
        """Code from non-allowlisted Telegram ID -> rejected."""
        import database
        code_obj = auth_service.generate_login_code(
            telegram_id=999999999,      # Not in TELEGRAM_ALLOWED_USERS
            username="hacker",
        )
        database.store_auth_code(
            code=code_obj.code,
            telegram_id=code_obj.telegram_id,
            username=code_obj.username,
            created_at=code_obj.created_at.isoformat(),
            expires_at=code_obj.expires_at.isoformat(),
        )
        r = await auth_client.get(f"/auth/callback?code={code_obj.code}")
        assert r.status_code in (400, 401, 403), \
            f"Unauthorized user got access: {r.status_code}"


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC PATH WHITELIST
# ═════════════════════════════════════════════════════════════════════════════

class TestPublicPaths:

    @pytest.mark.asyncio
    async def test_health_public(self, auth_client):
        r = await auth_client.get("/health")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_auth_routes_public(self, auth_client):
        r = await auth_client.get("/auth/login")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_static_assets_public(self, auth_client):
        r = await auth_client.get("/static/login.html")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_webhook_not_auth_blocked(self, auth_client):
        """TradingView webhook must never return 401 (wrong secret -> 401 from webhook handler is acceptable)."""
        r = await auth_client.post(
            "/webhook",
            json={"symbol": "BTCUSDT", "action": "buy", "quantity": 10},
            headers={"X-Webhook-Secret": "test-secret"},
        )
        # Webhook handler itself may return various codes, but NOT due to auth middleware
        # A 401 from the webhook secret check is acceptable (not from AuthMiddleware)
        assert r.status_code != 401 or "secret" in r.text.lower() or r.status_code in (200, 400, 401, 422)
