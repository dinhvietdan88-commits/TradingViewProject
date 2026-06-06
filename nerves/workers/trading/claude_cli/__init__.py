"""
claude_cli — Claude SDK integration package.

Public API:
    SdkClient          — async Anthropic SDK wrapper (core layer)
    ClaudeService      — stateless analysis orchestrator (orchestration layer)
    ContextManager     — per-symbol conversation context (core layer)
    AnalysisRequest    — input dataclass for ClaudeService.analyze()
    AnalysisResponse   — output dataclass from ClaudeService.analyze()

Deprecated (kept for backward compat):
    CliInfrastructure  — subprocess wrapper (superseded by SdkClient)
    CliResult          — subprocess result (superseded by AnalysisResponse)

Entry points (registered from main.py / telegram_bot.py):
    telegram_commands.register_commands(application, claude_service)
    event_handler.register_handler(claude_service)
"""

# Deprecated — kept for backward compatibility
from .infrastructure import CliInfrastructure, CliResult
from .sdk_client import SdkClient
from .service import AnalysisRequest, AnalysisResponse, ClaudeService, ContextManager

__all__ = [
    # New SDK-Headless API
    "SdkClient",
    "ClaudeService",
    "ContextManager",
    "AnalysisRequest",
    "AnalysisResponse",
    # Deprecated
    "CliInfrastructure",
    "CliResult",
]
