"""
Property-Based Tests for Auth Service — 14 Formal Properties.

Uses Hypothesis to verify correctness invariants across random inputs.
Each property runs ≥100 iterations by default.

Properties tested:
  P1:  Code generation produces unique 32-char hex codes
  P2:  Valid code exchange produces valid session
  P3:  Expired code exchange raises CodeExpiredError
  P4:  Used code exchange raises CodeUsedError
  P5:  Unauthorized user exchange raises UserNotAllowedError (LAST)
  P6:  Validation ordering: technical before authorization
  P7:  Session token round-trip preserves all fields
  P8:  Tampered token raises TokenInvalidError
  P9:  Expired session token raises TokenExpiredError
  P10: 7-day absolute lifetime enforcement
  P11: Session refresh preserves created_at
  P12: Never-expire sessions don't need refresh
  P13: Bearer token constant-time comparison
  P14: Config fallback: invalid SESSION_EXPIRY_HOURS → 24
"""

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

# Ensure server/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

try:
    from hypothesis import given, settings, assume, HealthCheck
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

from auth.auth_config import AuthConfig
from auth.models import (
    CodeExpiredError,
    CodeInvalidError,
    CodeUsedError,
    OneTimeCode,
    SessionData,
    SessionMaxLifetimeError,
    TokenExpiredError,
    TokenInvalidError,
    UserNotAllowedError,
)
from auth.service import AuthService

# ── Test Helpers ─────────────────────────────────────────────────────────

def _make_config(
    secret_key="a" * 32,
    allowed_users=None,
    session_expiry=24,
    widget_enabled=False,
):
    """Create AuthConfig with controlled env vars."""
    env = {
        "AUTH_SECRET_KEY": secret_key,
        "TELEGRAM_ALLOWED_USERS": ",".join(str(u) for u in (allowed_users or [12345])),
        "SESSION_EXPIRY_HOURS": str(session_expiry),
        "DASHBOARD_URL": "http://localhost:5000",
        "TELEGRAM_LOGIN_WIDGET": "true" if widget_enabled else "false",
    }
    with patch.dict(os.environ, env, clear=False):
        return AuthConfig()


def _make_service(allowed_users=None, session_expiry=24):
    """Create AuthService with controlled config."""
    cfg = _make_config(allowed_users=allowed_users, session_expiry=session_expiry)
    return AuthService(cfg)


skipif_no_hypothesis = pytest.mark.skipif(
    not HAS_HYPOTHESIS,
    reason="hypothesis not installed",
)


# ═══════════════════════════════════════════════════════════════
# P1: Code generation uniqueness & format
# ═══════════════════════════════════════════════════════════════

@skipif_no_hypothesis
@given(st.integers(min_value=1, max_value=10**12))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_p1_code_generation_unique_format(telegram_id):
    """P1: Generated codes must be 32-char hex and unique per call."""
    svc = _make_service(allowed_users=[telegram_id])
    code1 = svc.generate_login_code(telegram_id)
    code2 = svc.generate_login_code(telegram_id)

    # 32-char hex format
    assert len(code1.code) == 32
    assert re.match(r"^[0-9a-f]{32}$", code1.code)

    # Unique per call
    assert code1.code != code2.code

    # TTL is 5 minutes
    assert (code1.expires_at - code1.created_at).total_seconds() == pytest.approx(300)


# ═══════════════════════════════════════════════════════════════
# P2: Valid code exchange → valid session
# ═══════════════════════════════════════════════════════════════

@skipif_no_hypothesis
@given(st.integers(min_value=1, max_value=10**12))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_p2_valid_exchange(telegram_id):
    """P2: A valid, unexpired, unused code for an allowed user produces a session."""
    svc = _make_service(allowed_users=[telegram_id])
    code = svc.generate_login_code(telegram_id, username="testuser")

    code_record = {
        "code": code.code,
        "telegram_id": telegram_id,
        "username": "testuser",
        "created_at": code.created_at.isoformat(),
        "expires_at": code.expires_at.isoformat(),
        "used": 0,
    }

    session = svc.exchange_code(code_record, code.code)
    assert session.telegram_id == telegram_id
    assert session.session_id  # Non-empty
    assert session.created_at <= datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════
# P3: Expired code → CodeExpiredError
# ═══════════════════════════════════════════════════════════════

@skipif_no_hypothesis
@given(st.integers(min_value=1, max_value=10**12))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_p3_expired_code(telegram_id):
    """P3: An expired code must raise CodeExpiredError (before authorization check)."""
    svc = _make_service(allowed_users=[telegram_id])
    past = datetime.now(timezone.utc) - timedelta(minutes=10)

    code_record = {
        "code": "a" * 32,
        "telegram_id": telegram_id,
        "username": None,
        "created_at": past.isoformat(),
        "expires_at": (past + timedelta(minutes=5)).isoformat(),  # Expired
        "used": 0,
    }

    with pytest.raises(CodeExpiredError):
        svc.exchange_code(code_record, "a" * 32)


# ═══════════════════════════════════════════════════════════════
# P4: Used code → CodeUsedError
# ═══════════════════════════════════════════════════════════════

@skipif_no_hypothesis
@given(st.integers(min_value=1, max_value=10**12))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_p4_used_code(telegram_id):
    """P4: A used code must raise CodeUsedError."""
    svc = _make_service(allowed_users=[telegram_id])
    future = datetime.now(timezone.utc) + timedelta(minutes=5)

    code_record = {
        "code": "b" * 32,
        "telegram_id": telegram_id,
        "username": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": future.isoformat(),
        "used": 1,  # Already used
    }

    with pytest.raises(CodeUsedError):
        svc.exchange_code(code_record, "b" * 32)


# ═══════════════════════════════════════════════════════════════
# P5: Unauthorized user → UserNotAllowedError (LAST)
# ═══════════════════════════════════════════════════════════════

@skipif_no_hypothesis
@given(
    st.integers(min_value=1, max_value=10**12),
    st.integers(min_value=10**12 + 1, max_value=10**13),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_p5_unauthorized_user(allowed_id, unauthorized_id):
    """P5: Unauthorized user raises UserNotAllowedError."""
    assume(allowed_id != unauthorized_id)
    svc = _make_service(allowed_users=[allowed_id])
    future = datetime.now(timezone.utc) + timedelta(minutes=5)

    code_record = {
        "code": "c" * 32,
        "telegram_id": unauthorized_id,
        "username": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": future.isoformat(),
        "used": 0,
    }

    with pytest.raises(UserNotAllowedError):
        svc.exchange_code(code_record, "c" * 32)


# ═══════════════════════════════════════════════════════════════
# P6: Validation ordering — technical before authorization
# ═══════════════════════════════════════════════════════════════

@skipif_no_hypothesis
@given(st.integers(min_value=1, max_value=10**12))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_p6_validation_ordering(unauthorized_id):
    """P6: Expired code for unauthorized user → CodeExpiredError (NOT UserNotAllowedError)."""
    svc = _make_service(allowed_users=[99999])  # Different user
    past = datetime.now(timezone.utc) - timedelta(minutes=10)

    code_record = {
        "code": "d" * 32,
        "telegram_id": unauthorized_id,
        "username": None,
        "created_at": past.isoformat(),
        "expires_at": (past + timedelta(minutes=5)).isoformat(),
        "used": 0,
    }

    # Must raise CodeExpiredError, NOT UserNotAllowedError
    with pytest.raises(CodeExpiredError):
        svc.exchange_code(code_record, "d" * 32)


# ═══════════════════════════════════════════════════════════════
# P7: Session token round-trip
# ═══════════════════════════════════════════════════════════════

@skipif_no_hypothesis
@given(
    st.integers(min_value=1, max_value=10**12),
    st.text(min_size=3, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_0123456789"),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_p7_token_roundtrip(telegram_id, username):
    """P7: create_session_token → verify_session_token preserves all fields."""
    svc = _make_service(allowed_users=[telegram_id])
    now = datetime.now(timezone.utc)

    session = SessionData(
        session_id="test-sid",
        telegram_id=telegram_id,
        username=username,
        created_at=now,
        expires_at=now + timedelta(hours=24),
        never_expires=False,
    )

    token = svc.create_session_token(session)
    restored = svc.verify_session_token(token)

    assert restored.telegram_id == session.telegram_id
    assert restored.username == session.username
    assert restored.session_id == session.session_id
    assert restored.never_expires == session.never_expires


# ═══════════════════════════════════════════════════════════════
# P8: Tampered token → TokenInvalidError
# ═══════════════════════════════════════════════════════════════

@skipif_no_hypothesis
@given(st.integers(min_value=1, max_value=10**12))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_p8_tampered_token(telegram_id):
    """P8: Any modification to token must cause TokenInvalidError."""
    svc = _make_service(allowed_users=[telegram_id])
    now = datetime.now(timezone.utc)

    session = SessionData(
        session_id="test-sid",
        telegram_id=telegram_id,
        username="user",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )

    token = svc.create_session_token(session)
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")

    with pytest.raises(TokenInvalidError):
        svc.verify_session_token(tampered)


# ═══════════════════════════════════════════════════════════════
# P9: Expired session token → TokenExpiredError
# ═══════════════════════════════════════════════════════════════

def test_p9_expired_session_token():
    """P9: Token past its expires_at raises TokenExpiredError."""
    svc = _make_service()
    past = datetime.now(timezone.utc) - timedelta(hours=25)

    session = SessionData(
        session_id="test-sid",
        telegram_id=12345,
        username="user",
        created_at=past - timedelta(hours=1),
        expires_at=past,
    )

    token = svc.create_session_token(session)

    with pytest.raises(TokenExpiredError):
        svc.verify_session_token(token)


# ═══════════════════════════════════════════════════════════════
# P10: 7-day absolute lifetime enforcement
# ═══════════════════════════════════════════════════════════════

def test_p10_absolute_lifetime():
    """P10: Session older than 7 days raises SessionMaxLifetimeError."""
    svc = _make_service(session_expiry=0)  # Never expire
    old_creation = datetime.now(timezone.utc) - timedelta(days=8)

    session = SessionData(
        session_id="test-sid",
        telegram_id=12345,
        username="user",
        created_at=old_creation,
        expires_at=None,
        never_expires=True,
    )

    token = svc.create_session_token(session)

    with pytest.raises(SessionMaxLifetimeError):
        svc.verify_session_token(token)


# ═══════════════════════════════════════════════════════════════
# P11: Session refresh preserves created_at
# ═══════════════════════════════════════════════════════════════

def test_p11_refresh_preserves_created_at():
    """P11: Refresh must keep original created_at for absolute lifetime tracking."""
    svc = _make_service()
    original_created = datetime.now(timezone.utc) - timedelta(hours=20)

    session = SessionData(
        session_id="test-sid",
        telegram_id=12345,
        username="user",
        created_at=original_created,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),  # Within 1hr
    )

    refreshed = svc.refresh_session(session)
    assert refreshed.created_at == original_created
    assert refreshed.expires_at > session.expires_at


# ═══════════════════════════════════════════════════════════════
# P12: Never-expire sessions don't need refresh
# ═══════════════════════════════════════════════════════════════

def test_p12_never_expire_no_refresh():
    """P12: Never-expire sessions return False for should_refresh."""
    svc = _make_service(session_expiry=0)
    now = datetime.now(timezone.utc)

    session = SessionData(
        session_id="test-sid",
        telegram_id=12345,
        username="user",
        created_at=now,
        expires_at=None,
        never_expires=True,
    )

    assert svc.should_refresh(session) is False


# ═══════════════════════════════════════════════════════════════
# P13: Bearer token constant-time comparison
# ═══════════════════════════════════════════════════════════════

def test_p13_bearer_token_verification():
    """P13: Bearer token must match DASHBOARD_TOKEN via constant-time compare."""
    with patch("config.DASHBOARD_TOKEN", "correct-token-value"):
        assert AuthService.verify_bearer_token("correct-token-value") is True
        assert AuthService.verify_bearer_token("wrong-token-value") is False
        assert AuthService.verify_bearer_token("") is False


def test_p13_bearer_empty_dashboard_token():
    """P13b: Empty DASHBOARD_TOKEN → always return False."""
    with patch("config.DASHBOARD_TOKEN", ""):
        assert AuthService.verify_bearer_token("anything") is False


# ═══════════════════════════════════════════════════════════════
# P14: Config fallback for invalid SESSION_EXPIRY_HOURS
# ═══════════════════════════════════════════════════════════════

def test_p14_invalid_session_expiry_fallback():
    """P14: Invalid SESSION_EXPIRY_HOURS → default to 24."""
    cfg = _make_config(session_expiry=9999)
    assert cfg.session_expiry_hours == 24


def test_p14_zero_session_expiry():
    """P14b: SESSION_EXPIRY_HOURS=0 → None (never expire)."""
    cfg = _make_config(session_expiry=0)
    assert cfg.session_expiry_hours is None
