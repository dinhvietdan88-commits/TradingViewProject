"""
sdk_client.py — SdkClient: async Anthropic SDK wrapper.

Single owner of the `anthropic.AsyncAnthropic` instance.
No other component makes direct API calls.

Design invariants (Core Layer):
- Owns rate limiting (sliding 60s window) and concurrency control (asyncio.Semaphore).
- Timeout enforcement via httpx.Timeout passed to the SDK client constructor.
- Returns AnalysisResponse directly — no intermediate CliResult type.
- Never raises exceptions to callers — all errors wrapped in AnalysisResponse.
- check_availability() validates ANTHROPIC_API_KEY presence (no binary check).
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import time
from typing import Optional

import config

log = logging.getLogger(__name__)

ANTHROPIC_AVAILABLE = importlib.util.find_spec("anthropic") is not None


class SdkClient:
    """Async Anthropic SDK wrapper.

    Lifecycle:
        sdk = SdkClient()
        ok = await sdk.check_availability()
        response = await sdk.invoke(prompt, system_prompt)

    Property guarantees:
        Property 1: SDK invocations never block the event loop (async HTTP)
        Property 2: Rate limiting correctness (sliding window)
        Property 9: Timeout enforcement (httpx timeout)
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        timeout: int = 0,
        rate_limit: int = 0,
        max_parallel: int = 0,
    ):
        self._api_key = api_key or getattr(config, "ANTHROPIC_API_KEY", "")
        self._model = (
            model or getattr(config, "CLAUDE_CLI_MODEL", "") or "claude-sonnet-4-5"
        )
        self._timeout = timeout or getattr(config, "CLAUDE_CLI_TIMEOUT", 120)
        self._rate_limit = rate_limit or getattr(config, "CLAUDE_CLI_RATE_LIMIT", 10)
        max_p = max_parallel or getattr(config, "CLAUDE_CLI_MAX_PARALLEL", 2)
        self._semaphore = asyncio.Semaphore(max(1, max_p))
        self._request_timestamps: list[float] = []
        self._client: object | None = None  # anthropic.AsyncAnthropic
        self._available: bool = False

    # ── Lifecycle ───────────────────────────────────────────────────────────────

    async def check_availability(self) -> bool:
        """Validate API key presence and initialize AsyncAnthropic client.

        Called at startup. Sets self._available.
        Returns True if ANTHROPIC_API_KEY is configured and the client
        can be instantiated. Does NOT make a test API call.
        """
        if not ANTHROPIC_AVAILABLE:
            log.warning("SdkClient: anthropic package not installed.")
            self._available = False
            return False

        if not self._api_key:
            log.warning(
                "SdkClient: ANTHROPIC_API_KEY not configured. SDK calls will fail."
            )
            self._available = False
            return False

        try:
            import anthropic
            import httpx

            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key,
                timeout=httpx.Timeout(
                    timeout=float(self._timeout),
                    connect=10.0,
                ),
            )
            self._available = True
            log.info(
                f"SdkClient: ✅ Initialized (model={self._model}, "
                f"timeout={self._timeout}s, rate_limit={self._rate_limit}/min, "
                f"max_parallel={self._semaphore._value})"
            )
            return True
        except Exception as exc:
            log.error(f"SdkClient: Failed to initialize: {exc}")
            self._available = False
            return False

    @property
    def available(self) -> bool:
        """Whether SDK client was detected as available at startup."""
        return self._available

    def get_stats(self) -> dict:
        """Return SDK client stats for status reporting (BUG-004 fix)."""
        self._prune_timestamps()
        return {
            "available": self._available,
            "model": self._model,
            "timeout_seconds": self._timeout,
            "rate_limit": self._rate_limit,
            "max_parallel": self._semaphore._value,
            "requests_in_window": len(self._request_timestamps),
        }

    # ── Public API ──────────────────────────────────────────────────────────────

    async def invoke(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> AnalysisResponse:  # noqa: F821
        """Execute Claude SDK call with the given prompt.

        - Checks rate limit before calling SDK
        - Acquires semaphore (max_parallel bound) before execution
        - Calls AsyncAnthropic.messages.create() with httpx timeout
        - On timeout: returns AnalysisResponse with timed_out=True
        - Returns structured AnalysisResponse — raises no exceptions
        """
        from .service import AnalysisResponse

        if not self._available or self._client is None:
            return AnalysisResponse(
                text="⚠️ Claude SDK không khả dụng (chưa khởi tạo hoặc thiếu API key).",
                confidence=0,
                source="none",
                error="SDK client not available",
            )

        # Rate limit check
        if not self._check_rate_limit():
            log.warning("SdkClient: Rate limit exceeded, rejecting request.")
            return AnalysisResponse(
                text="⚠️ Rate limit — vui lòng thử lại sau.",
                confidence=0,
                source="none",
                error="Rate limit exceeded",
                rate_limited=True,
            )

        # Acquire semaphore and execute
        async with self._semaphore:
            t_start = time.monotonic()
            # BUG-003 fix: record timestamp BEFORE the call so concurrent
            # requests see each other's in-flight slots immediately.
            self._request_timestamps.append(time.monotonic())
            try:
                import anthropic as _anthropic

                messages = [{"role": "user", "content": prompt}]
                kwargs: dict = {
                    "model": self._model,
                    "max_tokens": 1024,
                    "messages": messages,
                }
                if system_prompt:
                    kwargs["system"] = system_prompt

                response = await self._client.messages.create(**kwargs)  # type: ignore[union-attr]
                text = response.content[0].text
                duration = time.monotonic() - t_start

                return AnalysisResponse(
                    text=text,
                    confidence=5,  # caller parses actual confidence
                    source="anthropic_api",
                    duration_seconds=duration,
                )

            except Exception as exc:
                duration = time.monotonic() - t_start
                exc_type = type(exc).__name__

                # Classify error
                timed_out = False
                rate_limited = False

                try:
                    import anthropic as _anthropic
                    import httpx

                    if isinstance(exc, (httpx.TimeoutException,)):
                        timed_out = True
                        log.warning(f"SdkClient: Timeout after {duration:.1f}s")
                    elif isinstance(exc, _anthropic.RateLimitError):
                        rate_limited = True
                        log.warning("SdkClient: Anthropic rate limit hit")
                    elif isinstance(exc, _anthropic.AuthenticationError):
                        log.error("SdkClient: Invalid API key — disabling client")
                        self._available = False
                    else:
                        log.error(f"SdkClient: {exc_type}: {exc}")
                except ImportError:
                    log.error(f"SdkClient: {exc_type}: {exc}")

                error_msg = f"{exc_type}: {str(exc)[:150]}"
                return AnalysisResponse(
                    text=f"⚠️ AI không khả dụng: {str(exc)[:100]}",
                    confidence=0,
                    source="none",
                    duration_seconds=duration,
                    error=error_msg,
                    timed_out=timed_out,
                    rate_limited=rate_limited,
                )

    # ── Rate limiting ───────────────────────────────────────────────────────────

    def _check_rate_limit(self) -> bool:
        """Return True if request is allowed, False if rate limited.
        Uses sliding window: count requests in last 60 seconds.
        """
        self._prune_timestamps()
        return len(self._request_timestamps) < self._rate_limit

    def _prune_timestamps(self) -> None:
        """Remove timestamps older than 60 seconds."""
        cutoff = time.monotonic() - 60.0
        self._request_timestamps = [t for t in self._request_timestamps if t > cutoff]
