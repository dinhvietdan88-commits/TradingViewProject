"""
Unit Tests — Auth edge cases and integration points.

Example-based tests for scenarios that are hard to express as properties.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from auth.auth_config import AuthConfig
from auth.models import (
    CodeInvalidError,
    TokenInvalidError,
    SessionData,
)
from auth.service import AuthService


# ── Helpers ──────────────────────────────────────────────────────────────

def _env(**kwargs):
    """Build env dict for AuthConfig."""
    defaults = {
        "AUTH_SECRET_KEY": "x" * 32,
        "TELEGRAM_ALLOWED_USERS": "12345",
        "SESSION_EXPIRY_HOURS": "24",
        "DASHBOARD_URL": "http://localhost:5000",
        "TELEGRAM_LOGIN_WIDGET": "false",
    }
    defaults.update(kwargs)
    return defaults


def _svc(**env_overrides):
    """Create AuthService with env."""
    with patch.dict(os.environ, _env(**env_overrides), clear=False):
        return AuthService(AuthConfig())


# ═══════════════════════════════════════════════════════════════
# Config Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestAuthConfig:
    """Configuration loading edge cases."""

    def test_short_secret_key_generates_new(self):
        """Keys shorter than 32 chars trigger auto-generation."""
        with patch.dict(os.environ, {"AUTH_SECRET_KEY": "short"}, clear=False):
            cfg = AuthConfig()
            assert len(cfg.secret_key) >= 32

    def test_allowed_users_fallback_to_chat_id(self):
        """TELEGRAM_ALLOWED_USERS empty → falls back to TELEGRAM_CHAT_ID."""
        env = {
            "AUTH_SECRET_KEY": "a" * 32,
            "TELEGRAM_ALLOWED_USERS": "",
            "TELEGRAM_CHAT_ID": "111,222",
            "SESSION_EXPIRY_HOURS": "24",
            "DASHBOARD_URL": "http://localhost:5000",
            "TELEGRAM_LOGIN_WIDGET": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = AuthConfig()
            assert 111 in cfg.allowed_users
            assert 222 in cfg.allowed_users

    def test_non_numeric_user_ids_ignored(self):
        """Non-numeric entries in user list are silently ignored."""
        with patch.dict(os.environ, _env(TELEGRAM_ALLOWED_USERS="123,abc,456"), clear=False):
            cfg = AuthConfig()
            assert cfg.allowed_users == [123, 456]

    def test_session_expiry_string_fallback(self):
        """Non-integer SESSION_EXPIRY_HOURS → fallback 24."""
        with patch.dict(os.environ, _env(SESSION_EXPIRY_HOURS="not_a_number"), clear=False):
            cfg = AuthConfig()
            assert cfg.session_expiry_hours == 24


# ═══════════════════════════════════════════════════════════════
# Service Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestAuthService:
    """AuthService edge case tests."""

    def test_exchange_code_none_record(self):
        """None code_record → CodeInvalidError."""
        svc = _svc()
        with pytest.raises(CodeInvalidError):
            svc.exchange_code(None, "anything")

    def test_token_no_dot(self):
        """Token without dot separator → TokenInvalidError."""
        svc = _svc()
        with pytest.raises(TokenInvalidError):
            svc.verify_session_token("no-dot-here")

    def test_token_empty_string(self):
        """Empty token → TokenInvalidError."""
        svc = _svc()
        with pytest.raises(TokenInvalidError):
            svc.verify_session_token("")

    def test_token_bad_base64(self):
        """Invalid base64 payload → TokenInvalidError."""
        svc = _svc()
        with pytest.raises(TokenInvalidError):
            svc.verify_session_token("!!!invalid!!!.abcdef")

    def test_different_signing_keys_reject(self):
        """Token signed with key A fails verification with key B."""
        svc_a = _svc(AUTH_SECRET_KEY="a" * 32)
        svc_b = _svc(AUTH_SECRET_KEY="b" * 32)

        session = SessionData(
            session_id="sid", telegram_id=12345, username="u",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )

        token = svc_a.create_session_token(session)

        with pytest.raises(TokenInvalidError):
            svc_b.verify_session_token(token)

    def test_should_refresh_within_1hr(self):
        """Session expiring in 30 min → should_refresh returns True."""
        svc = _svc()
        session = SessionData(
            session_id="sid", telegram_id=12345, username="u",
            created_at=datetime.now(timezone.utc) - timedelta(hours=23),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        assert svc.should_refresh(session) is True

    def test_should_refresh_beyond_1hr(self):
        """Session expiring in 2hr → should_refresh returns False."""
        svc = _svc()
        session = SessionData(
            session_id="sid", telegram_id=12345, username="u",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        assert svc.should_refresh(session) is False

    def test_refresh_caps_at_max_lifetime(self):
        """Refreshed expiry cannot exceed 7-day absolute max."""
        svc = _svc()
        created = datetime.now(timezone.utc) - timedelta(days=6, hours=23)
        session = SessionData(
            session_id="sid", telegram_id=12345, username="u",
            created_at=created,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        refreshed = svc.refresh_session(session)
        max_allowed = created + timedelta(days=7)
        assert refreshed.expires_at <= max_allowed
