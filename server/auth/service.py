"""
AuthService — Core authentication logic.

Handles:
- One-time code generation & exchange
- Session token creation & verification (HMAC-SHA256)
- Session refresh & invalidation
- Telegram Login Widget verification
- 7-day absolute session lifetime enforcement

STRICT VALIDATION ORDERING:
All validation flows follow: technical checks FIRST → authorization LAST.
This prevents data leakage (e.g., confirming user existence via error type).
"""

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

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
    UserIdentity,
    UserNotAllowedError,
    WidgetExpiredError,
    WidgetHashInvalidError,
)

log = logging.getLogger(__name__)


class AuthService:
    """Stateless auth operations — all persistence delegates to database module.

    Design Principle: AuthService does NOT hold DB connections.
    All DB operations are performed through the `database` module functions.
    """

    def __init__(self, config: AuthConfig):
        self.config = config
        self._signing_key = config.secret_key.encode("utf-8")

    # ═══════════════════════════════════════════════════════════════
    # ONE-TIME CODE — Generate & Exchange
    # ═══════════════════════════════════════════════════════════════

    def generate_login_code(
        self, telegram_id: int, username: Optional[str] = None
    ) -> OneTimeCode:
        """Generate a one-time login code for a Telegram user.

        Authorization check is done BEFORE calling this method (by the caller).
        Code is 32-char hex with 5-minute TTL.

        Returns:
            OneTimeCode to be stored in DB and sent to user.
        """
        now = datetime.now(timezone.utc)
        code = secrets.token_hex(16)  # 32-char hex
        expires_at = now + timedelta(minutes=self.config.code_ttl_minutes)

        otp = OneTimeCode(
            code=code,
            telegram_id=telegram_id,
            username=username,
            created_at=now,
            expires_at=expires_at,
            used=False,
        )

        log.info(
            f"Generated login code for user {telegram_id} "
            f"(expires: {expires_at.isoformat()})"
        )
        return otp

    def exchange_code(self, code_record: Optional[dict], code: str) -> SessionData:
        """Exchange a one-time code for a session token.

        STRICT VALIDATION ORDER (from design.md):
        1. Code exists? → CodeInvalidError
        2. Code expired? → CodeExpiredError
        3. Code already used? → CodeUsedError
        4. User authorized? → UserNotAllowedError

        Args:
            code_record: Dict from DB (or None if not found).
                Keys: code, telegram_id, username, created_at, expires_at, used
            code: The raw code string submitted by the user.

        Returns:
            SessionData with newly created session.

        Raises:
            CodeInvalidError, CodeExpiredError, CodeUsedError, UserNotAllowedError
        """
        now = datetime.now(timezone.utc)

        # Step 1: Code exists?
        if code_record is None:
            raise CodeInvalidError("Invalid login code")

        # Step 2: Code expired? (TECHNICAL — before authorization)
        expires_at = code_record.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now > expires_at:
            raise CodeExpiredError("Login code has expired")

        # Step 3: Code already used? (TECHNICAL — before authorization)
        if code_record.get("used"):
            raise CodeUsedError("Login code has already been used")

        # Step 4: User authorized? (AUTHORIZATION — always last)
        telegram_id = code_record["telegram_id"]
        if not self.config.is_user_allowed(telegram_id):
            raise UserNotAllowedError(
                f"User {telegram_id} is not authorized for dashboard access"
            )

        # All checks passed — create session
        username = code_record.get("username")
        return self._create_session(telegram_id, username)

    # ═══════════════════════════════════════════════════════════════
    # SESSION TOKEN — Create, Verify, Refresh, Invalidate
    # ═══════════════════════════════════════════════════════════════

    def _create_session(
        self, telegram_id: int, username: Optional[str] = None
    ) -> SessionData:
        """Create a new session for an authenticated user."""
        now = datetime.now(timezone.utc)
        session_id = str(uuid.uuid4())

        if self.config.session_expiry_hours is None:
            # Never expire (SESSION_EXPIRY_HOURS=0)
            expires_at = None
            never_expires = True
        else:
            expires_at = now + timedelta(hours=self.config.session_expiry_hours)
            never_expires = False

        return SessionData(
            session_id=session_id,
            telegram_id=telegram_id,
            username=username,
            created_at=now,
            expires_at=expires_at,
            never_expires=never_expires,
        )

    def create_session_token(self, session: SessionData) -> str:
        """Sign session data into a compact token string.

        Format: base64url(json_payload) + "." + hex(hmac_sha256)

        No external JWT library needed — simple HMAC signing.
        """
        import base64

        payload = {
            "sid": session.session_id,
            "tid": session.telegram_id,
            "usr": session.username,
            "cat": session.created_at.isoformat(),
            "eat": session.expires_at.isoformat() if session.expires_at else None,
            "nex": session.never_expires,
        }

        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii")

        sig = hmac.new(self._signing_key, payload_bytes, hashlib.sha256).hexdigest()

        return f"{payload_b64}.{sig}"

    def verify_session_token(self, token: str) -> SessionData:
        """Verify and decode a session token.

        STRICT VALIDATION ORDER:
        1. Token format valid? → TokenInvalidError
        2. Signature valid? → TokenInvalidError
        3. Token expired? → TokenExpiredError
        4. Absolute lifetime exceeded? → SessionMaxLifetimeError

        Returns:
            SessionData if valid.

        Raises:
            TokenInvalidError, TokenExpiredError, SessionMaxLifetimeError
        """
        import base64

        now = datetime.now(timezone.utc)

        # Step 1: Format check
        parts = token.split(".", 1)
        if len(parts) != 2:
            raise TokenInvalidError("Malformed token")

        payload_b64, received_sig = parts

        # Step 2: Signature check (TECHNICAL — before any data interpretation)
        try:
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
        except Exception:
            raise TokenInvalidError("Invalid token encoding")

        expected_sig = hmac.new(
            self._signing_key, payload_bytes, hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, received_sig):
            raise TokenInvalidError("Invalid token signature")

        # Step 3: Parse payload (signature validated, safe to decode)
        try:
            payload = json.loads(payload_bytes)
        except json.JSONDecodeError:
            raise TokenInvalidError("Corrupted token payload")

        created_at = datetime.fromisoformat(payload["cat"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        never_expires = payload.get("nex", False)

        if payload.get("eat") is not None:
            expires_at = datetime.fromisoformat(payload["eat"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        else:
            expires_at = None

        # Step 4: Expiry check (TECHNICAL)
        if not never_expires and expires_at is not None and now > expires_at:
            raise TokenExpiredError("Session has expired")

        # Step 5: Absolute lifetime check (7-day max)
        max_lifetime = created_at + timedelta(
            days=self.config.max_session_lifetime_days
        )
        if now > max_lifetime:
            raise SessionMaxLifetimeError(
                "Session has exceeded 7-day maximum lifetime"
            )

        return SessionData(
            session_id=payload["sid"],
            telegram_id=payload["tid"],
            username=payload.get("usr"),
            created_at=created_at,
            expires_at=expires_at,
            never_expires=never_expires,
        )

    def should_refresh(self, session: SessionData) -> bool:
        """Check if session is within 1 hour of expiry (eligible for refresh).

        Never-expire sessions return False (no refresh needed).
        """
        if session.never_expires or session.expires_at is None:
            return False

        now = datetime.now(timezone.utc)
        time_left = session.expires_at - now
        return timedelta(0) < time_left <= timedelta(hours=1)

    def refresh_session(self, session: SessionData) -> SessionData:
        """Create a refreshed session with extended expiry.

        Keeps original created_at (for 7-day max lifetime enforcement).
        Only extends expires_at by session_expiry_hours from now.

        Args:
            session: Current valid session.

        Returns:
            New SessionData with extended expiry.

        Raises:
            SessionMaxLifetimeError: If refresh would exceed 7-day max.
        """
        now = datetime.now(timezone.utc)
        max_lifetime = session.created_at + timedelta(
            days=self.config.max_session_lifetime_days
        )

        if now > max_lifetime:
            raise SessionMaxLifetimeError(
                "Cannot refresh: session has exceeded 7-day maximum lifetime"
            )

        if self.config.session_expiry_hours is None:
            new_expires = None
        else:
            new_expires = now + timedelta(hours=self.config.session_expiry_hours)
            # Cap at max lifetime
            if new_expires > max_lifetime:
                new_expires = max_lifetime

        return SessionData(
            session_id=session.session_id,
            telegram_id=session.telegram_id,
            username=session.username,
            created_at=session.created_at,  # PRESERVE original
            expires_at=new_expires,
            never_expires=session.never_expires,
        )

    # ═══════════════════════════════════════════════════════════════
    # INVALIDATION
    # ═══════════════════════════════════════════════════════════════

    def invalidate_session(self, session_id: str) -> None:
        """Mark a single session as invalidated.

        Actual DB deletion is handled by the caller (route handler).
        This method exists for logging/auditing.
        """
        log.info(f"Session invalidated: {session_id[:8]}...")

    def invalidate_all_user_sessions(self, telegram_id: int) -> None:
        """Mark all sessions for a user as invalidated.

        Actual DB deletion is handled by the caller.
        """
        log.info(f"All sessions invalidated for user {telegram_id}")

    # ═══════════════════════════════════════════════════════════════
    # TELEGRAM LOGIN WIDGET
    # ═══════════════════════════════════════════════════════════════

    def verify_widget_data(self, data: dict) -> UserIdentity:
        """Verify Telegram Login Widget data.

        STRICT VALIDATION ORDER:
        1. HMAC hash valid? → WidgetHashInvalidError
        2. auth_date fresh? (≤5min) → WidgetExpiredError
        3. User authorized? → UserNotAllowedError

        Uses SHA256(bot_token) as key, HMAC-SHA256 for signature.

        Args:
            data: Dict containing Telegram widget fields
                  (id, first_name, auth_date, hash, etc.)

        Returns:
            UserIdentity if valid.
        """
        import config as app_config

        # Build data-check-string (alphabetical, excluding hash)
        check_data = "\n".join(
            f"{k}={data[k]}"
            for k in sorted(data.keys())
            if k != "hash"
        )

        # Step 1: HMAC verification (TECHNICAL)
        bot_token = app_config.TELEGRAM_BOT_TOKEN
        secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
        computed_hash = hmac.new(
            secret_key,
            check_data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, data.get("hash", "")):
            raise WidgetHashInvalidError("Invalid widget authentication data")

        # Step 2: Freshness check (TECHNICAL)
        now = datetime.now(timezone.utc)
        auth_date = datetime.fromtimestamp(int(data["auth_date"]), tz=timezone.utc)
        if (now - auth_date) > timedelta(minutes=5):
            raise WidgetExpiredError("Widget authentication has expired")

        # Step 3: Authorization check (AUTHORIZATION — always last)
        telegram_id = int(data["id"])
        if not self.config.is_user_allowed(telegram_id):
            raise UserNotAllowedError(
                f"User {telegram_id} is not authorized for dashboard access"
            )

        return UserIdentity(
            telegram_id=telegram_id,
            username=data.get("username"),
            display_name=data.get("first_name"),
        )

    # ═══════════════════════════════════════════════════════════════
    # BEARER TOKEN VERIFICATION (backward compatibility)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def verify_bearer_token(token: str) -> bool:
        """Verify a legacy Bearer token against DASHBOARD_TOKEN.

        Uses constant-time comparison to prevent timing attacks.

        Returns:
            True if token matches DASHBOARD_TOKEN.
        """
        import config as app_config

        dashboard_token = getattr(app_config, "DASHBOARD_TOKEN", "")
        if not dashboard_token:
            return False
        return hmac.compare_digest(token, dashboard_token)
