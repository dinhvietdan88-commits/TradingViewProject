"""
Auth Configuration — startup validation and environment loading.

Handles secret key generation, allowed user parsing, and session
expiry configuration with graceful degradation.
"""

import os
import secrets
import logging

log = logging.getLogger(__name__)


class AuthConfig:
    """Auth-specific configuration with startup validation.

    Design Decisions (from design.md):
    - AUTH_SECRET_KEY auto-generated if missing (with warning)
    - TELEGRAM_ALLOWED_USERS falls back to TELEGRAM_CHAT_IDS
    - SESSION_EXPIRY_HOURS: 0=never-expire, 1-720=hours, invalid→24
    - Warning log failure during key generation = critical startup halt (REQ-9.2)
    """

    def __init__(self):
        self.secret_key: str = self._load_secret_key()
        self.allowed_users: list[int] = self._load_allowed_users()
        self.session_expiry_hours: int | None = self._load_session_expiry()
        self.dashboard_url: str = os.getenv("DASHBOARD_URL", "http://localhost:5000")
        self.widget_enabled: bool = os.getenv("TELEGRAM_LOGIN_WIDGET", "false").lower() == "true"
        self.code_ttl_minutes: int = 5  # One-time code TTL
        self.max_session_lifetime_days: int = 7  # Absolute max session lifetime

    def _load_secret_key(self) -> str:
        """Load AUTH_SECRET_KEY or generate random key (REQ-9.2).

        If AUTH_SECRET_KEY is not set:
        1. Generate random key (≥32 bytes)
        2. If generation succeeds but warning log fails → critical error, halt
        3. If generation succeeds and warning logs → use generated key
        """
        key = os.getenv("AUTH_SECRET_KEY", "")
        if key and len(key) >= 32:
            return key

        if key and len(key) < 32:
            log.error(
                f"AUTH_SECRET_KEY too short ({len(key)} chars, need ≥32). "
                "Generating random key instead."
            )

        # Attempt to generate random key
        try:
            generated_key = secrets.token_hex(32)  # 64-char hex = 32 bytes
        except Exception as gen_err:
            # Generation failed — try to log
            try:
                log.warning(
                    f"AUTH_SECRET_KEY generation failed: {gen_err}. "
                    "Auth system will operate in partial compliance mode."
                )
            except Exception:
                pass  # Both failed — allow startup with partial compliance
            return secrets.token_hex(16)  # Minimal fallback

        # Generation succeeded — must log warning
        try:
            log.warning(
                "AUTH_SECRET_KEY not set — generated random key. "
                "Sessions will NOT persist across server restarts. "
                "Set AUTH_SECRET_KEY in .env for persistent sessions."
            )
        except Exception as log_err:
            # WARNING LOG FAILURE IS CRITICAL (REQ-9.2)
            raise RuntimeError(
                f"CRITICAL: AUTH_SECRET_KEY not set and warning log failed: {log_err}. "
                "Cannot start server without proper key configuration logging."
            ) from log_err

        return generated_key

    def _load_allowed_users(self) -> list[int]:
        """Load allowed users (REQ-7.3).

        Priority: TELEGRAM_ALLOWED_USERS > TELEGRAM_CHAT_IDS
        If both empty: log warning, allow startup (reject all auth at runtime).
        """
        raw = os.getenv("TELEGRAM_ALLOWED_USERS", "")
        if not raw.strip():
            # Fallback to TELEGRAM_CHAT_IDS
            raw = os.getenv("TELEGRAM_CHAT_ID", "")

        users = self._parse_user_ids(raw)

        if not users:
            log.warning(
                "No authorized users configured (TELEGRAM_ALLOWED_USERS and "
                "TELEGRAM_CHAT_ID both empty). All dashboard auth attempts will "
                "be rejected. Set TELEGRAM_ALLOWED_USERS in .env."
            )

        return users

    @staticmethod
    def _parse_user_ids(raw: str) -> list[int]:
        """Parse comma-separated numeric IDs, ignoring whitespace/empty entries."""
        result = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                result.append(int(part))
            except ValueError:
                log.warning(f"Ignoring non-numeric user ID: {part!r}")
        return result

    def _load_session_expiry(self) -> int | None:
        """Load SESSION_EXPIRY_HOURS (REQ-9.4).

        - 0: never expire (returns None)
        - 1-720: hours
        - Invalid/out-of-range: log error, fallback to 24
        """
        raw = os.getenv("SESSION_EXPIRY_HOURS", "24")
        try:
            value = int(raw)
        except (ValueError, TypeError):
            log.error(
                f"Invalid SESSION_EXPIRY_HOURS value: {raw!r}. "
                "Using default 24 hours."
            )
            return 24

        if value == 0:
            log.info("SESSION_EXPIRY_HOURS=0: sessions will never expire "
                     "(still subject to 7-day absolute lifetime).")
            return None  # None signals "never expire"

        if 1 <= value <= 720:
            return value

        log.error(
            f"SESSION_EXPIRY_HOURS={value} out of valid range [0-720]. "
            "Using default 24 hours."
        )
        return 24

    def is_user_allowed(self, telegram_id: int) -> bool:
        """Check if user is in the allowed list."""
        return telegram_id in self.allowed_users
