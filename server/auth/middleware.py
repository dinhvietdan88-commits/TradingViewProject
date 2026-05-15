"""
AuthMiddleware — Path-aware request authentication.

Classifies requests as protected or public, then applies
Bearer token → Session cookie → Redirect authentication cascade.
"""

import logging
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# PATH CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

# Paths that NEVER require authentication
PUBLIC_PATHS = (
    "/webhook",       # TradingView webhook
    "/health",        # Health check
    "/auth/",         # Auth flow itself
    "/static/",       # Static assets (CSS/JS/images)
    "/favicon.ico",
    "/docs",          # FastAPI Swagger
    "/openapi.json",
    "/redoc",
)

# Paths that require authentication
PROTECTED_PREFIXES = (
    "/api/",          # All API endpoints
    "/dashboard",     # Dashboard page
    "/trades",        # Trade endpoints
    "/signals",       # Signal endpoints
    "/screenshots/",  # Screenshot endpoints
)


def _is_public_path(path: str) -> bool:
    """Check if a request path is public (no auth needed)."""
    for prefix in PUBLIC_PATHS:
        if path.startswith(prefix):
            return True
    # Root "/" (dashboard HTML) is protected
    return False


def _is_api_request(request: Request) -> bool:
    """Determine if a request is an API call (expects JSON) vs browser (expects HTML)."""
    accept = request.headers.get("accept", "")
    # Explicit JSON preference or API path
    if "application/json" in accept:
        return True
    # Fetch API requests
    if request.headers.get("x-requested-with", "").lower() == "xmlhttprequest":
        return True
    # Bearer token present → treat as API
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Multi-tier authentication middleware.

    Auth Priority:
    1. Bearer token (header) — legacy DASHBOARD_TOKEN or API clients
    2. Session cookie (tg_session) — Telegram-authenticated sessions
    3. No auth → 302 redirect (browser) or 401 JSON (API)

    Selective Refresh:
    Only refreshes session cookie when within 1hr of expiry.
    """

    def __init__(self, app, auth_service=None):
        super().__init__(app)
        self.auth_service = auth_service

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process each request through auth pipeline."""
        path = request.url.path

        # ── Public paths: pass through ─────────────────────────────
        if _is_public_path(path):
            return await call_next(request)

        # ── Lazy-resolve AuthService (supports test injection after startup) ──
        # add_middleware() runs at import time before lifespan, so app.state
        # may not be populated yet. Always prefer the live app.state value.
        auth_service = getattr(request.app.state, "auth_service", None) or self.auth_service

        # ── No auth service configured: open access mode ──────────
        if auth_service is None:
            return await call_next(request)

        # ── Check if DASHBOARD_TOKEN is empty → open access ───────
        import config as app_config
        dashboard_token = getattr(app_config, "DASHBOARD_TOKEN", "")
        if not dashboard_token:
            # No token configured = open access (backward compatible)
            return await call_next(request)

        # ── Auth cascade ──────────────────────────────────────────
        # 1. Try Bearer token
        user = self._check_bearer(request, auth_service)
        if user is not None:
            request.state.user = user
            request.state.auth_method = "bearer"
            return await call_next(request)

        # 2. Try session cookie
        session_result = self._check_session(request, auth_service)
        if session_result is not None:
            session, needs_refresh = session_result
            request.state.user = {
                "telegram_id": session.telegram_id,
                "username": session.username,
                "session_id": session.session_id,
            }
            request.state.auth_method = "session"

            response = await call_next(request)

            # Selective refresh (only within 1hr of expiry)
            if needs_refresh:
                response = self._refresh_cookie(response, session, auth_service)

            return response

        # 3. Unauthenticated
        return self._unauthenticated_response(request, path)

    def _check_bearer(self, request: Request, auth_service=None) -> Optional[dict]:
        """Check Authorization: Bearer header."""
        svc = auth_service or self.auth_service
        if svc is None:
            return None
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]  # Strip "Bearer "
        if not token:
            return None

        if svc.verify_bearer_token(token):
            return {"auth_type": "bearer", "token_verified": True}

        return None

    def _check_session(self, request: Request, auth_service=None):
        """Check tg_session cookie.

        Returns:
            (SessionData, needs_refresh: bool) if valid.
            None if invalid/missing.
        """
        svc = auth_service or self.auth_service
        if svc is None:
            return None
        from auth.models import (
            TokenExpiredError,
            TokenInvalidError,
            SessionMaxLifetimeError,
        )

        token = request.cookies.get("tg_session")
        if not token:
            return None

        try:
            session = svc.verify_session_token(token)
            needs_refresh = svc.should_refresh(session)
            return (session, needs_refresh)
        except (TokenInvalidError, TokenExpiredError, SessionMaxLifetimeError) as e:
            log.debug(f"Session cookie invalid: {e}")
            return None

    def _refresh_cookie(self, response: Response, session, auth_service=None) -> Response:
        """Attach refreshed session cookie to response."""
        from auth.models import SessionMaxLifetimeError
        svc = auth_service or self.auth_service
        if svc is None:
            return response

        try:
            refreshed = svc.refresh_session(session)
            new_token = svc.create_session_token(refreshed)

            # Set cookie with security flags
            response.set_cookie(
                key="tg_session",
                value=new_token,
                httponly=True,
                secure=False,  # Set True in production with HTTPS
                samesite="lax",
                max_age=self._cookie_max_age(),
                path="/",
            )
            log.debug(f"Session refreshed for user {session.telegram_id}")
        except SessionMaxLifetimeError:
            log.info(
                f"Session refresh blocked (7-day max) for user {session.telegram_id}"
            )
        except Exception as e:
            log.warning(f"Session refresh failed: {e}")

        return response

    def _cookie_max_age(self, auth_service=None) -> Optional[int]:
        """Calculate cookie max-age from config."""
        svc = auth_service or self.auth_service
        if svc is None:
            return None
        if svc.config.session_expiry_hours is None:
            return 7 * 24 * 3600
        return svc.config.session_expiry_hours * 3600

    def _unauthenticated_response(self, request: Request, path: str) -> Response:
        """Return appropriate response for unauthenticated requests."""
        if _is_api_request(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )

        # Browser request → redirect to login
        return RedirectResponse(
            url=f"/auth/login?next={path}",
            status_code=302,
        )
