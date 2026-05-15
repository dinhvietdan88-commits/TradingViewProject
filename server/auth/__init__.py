"""
Telegram Dashboard Authentication Package.

Provides secure session-based authentication for the trading dashboard
using Telegram bot integration and optional Login Widget support.
"""

from auth.service import AuthService
from auth.middleware import AuthMiddleware
from auth.routes import auth_router
from auth.models import UserIdentity, SessionData, OneTimeCode

__all__ = [
    "AuthService",
    "AuthMiddleware",
    "auth_router",
    "UserIdentity",
    "SessionData",
    "OneTimeCode",
]
