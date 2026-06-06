"""
agy-harness: HTTP client wrapper for calling agy-bridge from Docker.

Provides retry, timeout, structured response parsing, and health monitoring.
This is the in-container component that communicates with the agy-bridge
sidecar running on the Server C host.

Harness Pattern: Mini-MDASH Level A adaptation for AI analysis.

Architecture:
  Docker container → AgyHarness (this) → HTTP → agy-bridge (host :9100) → agy CLI

Gates:
  Gate 0: Pre-flight (bridge health check)
  Gate 1: Prompt Construction (RAG context injection)
  Gate 2: Execution (agy --print via bridge HTTP)
  Gate 3: Response Validation (non-empty, UTF-8, length bounds)
  Gate 4: Metric Recording (latency, success/fail for circuit breaker)

SCAR-005: agy --print requires PTY wrapper on host side (handled by bridge).
SCAR-006: ANTIGRAVITY_API_KEY must be Tier 1 (pay-as-you-go) to avoid quota
          exhaustion from agy agent background requests.
"""

import asyncio
import logging
import os
from dataclasses import dataclass

import aiohttp

log = logging.getLogger("agy_harness")


# ════════════════════════════════════════════════════════════════
# Response Model
# ════════════════════════════════════════════════════════════════


@dataclass
class AgyResponse:
    """Structured response from agy CLI via bridge."""

    advice: str
    model: str
    latency_ms: float
    success: bool
    error: str | None = None
    exit_code: int = 0
    stdout_len: int = 0
    provider: str | None = None


# ════════════════════════════════════════════════════════════════
# Harness Client
# ════════════════════════════════════════════════════════════════


class AgyHarness:
    """
    5-Gate Harness for agy CLI integration via HTTP bridge.

    Usage:
        harness = AgyHarness(bridge_url="http://host.docker.internal:9100")
        try:
            result = await harness.analyze("Analyze BTCUSDT buy @ 68000")
            if result.success:
                print(result.advice)
        finally:
            await harness.close()
    """

    def __init__(
        self,
        bridge_url: str = "http://host.docker.internal:9100",
        timeout_sec: int = 25,
        max_retries: int = 1,
        model: str = "gemini-2.5-flash",
        secret: str = "",
    ):
        self.bridge_url = bridge_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.model = model
        self._secret = secret or os.environ.get("AGY_BRIDGE_SECRET", "")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Lazily create aiohttp session with proper timeout."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_sec + 15)
            )
        return self._session

    # ── Gate 0: Pre-flight ──────────────────────────────────────

    async def check_health(self) -> dict:
        """
        Check if agy-bridge is alive and circuit breaker is not OPEN.

        Returns:
            dict with status, circuit_breaker state, pty_mode, etc.
            Empty dict if bridge is unreachable.
        """
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.bridge_url}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data
                return {}
        except Exception as exc:
            log.debug(f"agy-harness health check failed: {exc}")
            return {}

    async def is_available(self) -> bool:
        """Quick check: is the bridge healthy and circuit breaker not OPEN?"""
        health = await self.check_health()
        if not health:
            return False
        cb = health.get("circuit_breaker", {})
        return cb.get("state") != "OPEN"

    # ── Gate 1 + Gate 2: Execute ────────────────────────────────

    async def analyze(
        self,
        prompt: str,
        system_instruction: str = "",
        timeout_sec: int | None = None,
    ) -> AgyResponse:
        """
        Send analysis prompt to agy-bridge and return structured response.

        Args:
            prompt: The analysis prompt (RAG-enriched context expected).
            system_instruction: Optional system-level instruction for the model.
            timeout_sec: Override default timeout for this call.

        Returns:
            AgyResponse with success=True if analysis succeeded.
        """
        effective_timeout = timeout_sec or self.timeout_sec
        session = await self._get_session()

        payload = {
            "prompt": prompt,
            "model": self.model,
            "timeout_sec": effective_timeout,
            "system_instruction": system_instruction,
        }

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                headers = {}
                if self._secret:
                    headers["Authorization"] = f"Bearer {self._secret}"
                async with session.post(
                    f"{self.bridge_url}/analyze",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=effective_timeout + 15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        advice = data.get("advice", "")

                        # ── Gate 3: Response Validation ──
                        if not advice or len(advice.strip()) < 10:
                            log.warning(
                                f"agy-harness: Empty/short response (len={len(advice)})"
                            )
                            return AgyResponse(
                                advice="",
                                model=data.get("model", self.model),
                                latency_ms=data.get("latency_ms", 0),
                                success=False,
                                error="Response too short or empty",
                                exit_code=data.get("exit_code", -1),
                                stdout_len=data.get("stdout_len", 0),
                            )

                        # ── Gate 4: Success metric ──
                        log.info(
                            f"agy-harness: OK "
                            f"({data.get('latency_ms', 0):.0f}ms, "
                            f"len={len(advice)})"
                        )
                        return AgyResponse(
                            advice=advice,
                            model=data.get("model", self.model),
                            latency_ms=data.get("latency_ms", 0),
                            success=True,
                            exit_code=0,
                            stdout_len=data.get("stdout_len", len(advice)),
                            provider=data.get("provider", "agy-bridge"),
                        )

                    elif resp.status == 503:
                        # Circuit breaker OPEN — don't retry
                        body = await resp.text()
                        last_error = f"Bridge CB OPEN: {body[:200]}"
                        log.warning(f"agy-harness: {last_error}")
                        break  # No point retrying when CB is OPEN

                    elif resp.status == 504:
                        # Timeout — may retry
                        body = await resp.text()
                        last_error = f"Timeout: {body[:200]}"
                        log.warning(f"agy-harness attempt {attempt + 1}: {last_error}")

                    else:
                        body = await resp.text()
                        last_error = f"HTTP {resp.status}: {body[:200]}"
                        log.warning(f"agy-harness attempt {attempt + 1}: {last_error}")

            except TimeoutError:
                last_error = f"Client timeout after {effective_timeout}s"
                log.warning(f"agy-harness attempt {attempt + 1}: {last_error}")

            except aiohttp.ClientConnectorError as exc:
                last_error = f"Connection refused: {exc}"
                log.warning(f"agy-harness attempt {attempt + 1}: {last_error}")
                # Bridge is down entirely — no point retrying fast
                break

            except aiohttp.ClientError as exc:
                last_error = str(exc)
                log.warning(f"agy-harness attempt {attempt + 1}: {last_error}")

            # Brief backoff before retry
            if attempt < self.max_retries:
                await asyncio.sleep(1)

        # All attempts exhausted
        return AgyResponse(
            advice="",
            model=self.model,
            latency_ms=0,
            success=False,
            error=last_error,
        )

    # ── Lifecycle ───────────────────────────────────────────────

    async def close(self):
        """Close the underlying HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
