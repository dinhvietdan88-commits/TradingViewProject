"""
Auth Data Models & Exception Hierarchy.

Frozen dataclasses for immutable auth data passing.
Custom exceptions for precise error handling in the auth flow.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class UserIdentity:
    """Authenticated user info extracted from session token or bearer context."""
    telegram_id: int
    username: Optional[str] = None
    display_name: Optional[str] = None


@dataclass(frozen=True)
class OneTimeCode:
    """One-time authentication code payload."""
    code: str                    # 32+ char hex string
    telegram_id: int
    username: Optional[str]
    created_at: datetime
    expires_at: datetime
    used: bool = False


@dataclass(frozen=True)
class SessionData:
    """Session token payload (stored in signed cookie).

    Attributes:
        session_id: UUID for server-side tracking
        telegram_id: Telegram user ID
        username: Telegram username (optional)
        created_at: Original session creation timestamp (for 7-day max)
        expires_at: Current expiration (refreshable); None if never-expire
        never_expires: True when SESSION_EXPIRY_HOURS=0
    """
    session_id: str
    telegram_id: int
    username: Optional[str]
    created_at: datetime
    expires_at: Optional[datetime]
    never_expires: bool = False


# ═══════════════════════════════════════════════════════════════
# EXCEPTIONS — ordered by validation priority
# ═══════════════════════════════════════════════════════════════

class AuthError(Exception):
    """Base class for all auth exceptions."""
    pass


# --- One-Time Code Errors (validation order: 1→2→3→4) ---

class CodeInvalidError(AuthError):
    """Code does not exist or has an invalid signature (Step 1)."""
    pass


class CodeExpiredError(AuthError):
    """Code has expired past its 5-minute TTL (Step 2)."""
    pass


class CodeUsedError(AuthError):
    """Code has already been consumed (Step 3)."""
    pass


# --- Authorization Error (Step 4 — always last) ---

class UserNotAllowedError(AuthError):
    """User is not in the Allowed_Users list (Step 4)."""
    pass


# --- Session Token Errors ---

class TokenInvalidError(AuthError):
    """Token signature is invalid or token is malformed."""
    pass


class TokenExpiredError(AuthError):
    """Token has passed its expiration time."""
    pass


class SessionMaxLifetimeError(AuthError):
    """Session has exceeded the absolute 7-day maximum lifetime."""
    pass


# --- Widget Errors ---

class WidgetHashInvalidError(AuthError):
    """Telegram Login Widget HMAC-SHA256 hash does not match."""
    pass


class WidgetExpiredError(AuthError):
    """Telegram Login Widget auth_date is older than 5 minutes."""
    pass
