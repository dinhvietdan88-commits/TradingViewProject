"""
server/workers/ai_circuit_breaker.py — LLM Circuit Breaker (V2 Hardened).

Pattern: CLOSED → OPEN → HALF_OPEN

States:
  CLOSED   : Normal operation — all LLM requests pass through.
  OPEN     : LLM is unhealthy — all requests are short-circuited to Algorithmic Mode.
  HALF_OPEN: Recovery probe — one test request is allowed.
             If it succeeds → CLOSED. If it fails → OPEN again.

Configuration (all tunable via env vars read from config):
  failure_threshold     : Consecutive failures before opening (default 3).
  recovery_timeout_sec  : Seconds before attempting HALF_OPEN probe (default 60).
  call_timeout_sec      : Per-call LLM timeout used by the caller (default 2.0 s).

Usage:
    from workers.ai_circuit_breaker import llm_breaker

    if llm_breaker.is_available():
        try:
            result = await asyncio.wait_for(
                generate_trading_advice(...),
                timeout=llm_breaker.call_timeout_sec,
            )
            llm_breaker.record_success()
        except (asyncio.TimeoutError, Exception) as exc:
            llm_breaker.record_failure(str(exc))
            # → fallback to algorithmic mode
    else:
        # Circuit is OPEN — go straight to algorithmic mode
        ...
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# State enum
# ────────────────────────────────────────────────────────────────────────────


class CircuitState(Enum):
    CLOSED = "closed"  # Normal — LLM traffic flows through
    OPEN = "open"  # Tripped — traffic blocked, fallback active
    HALF_OPEN = "half_open"  # Recovery probe — one request allowed


# ────────────────────────────────────────────────────────────────────────────
# Circuit Breaker
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class LLMCircuitBreaker:
    """Circuit Breaker that guards the pipeline against LLM API downtime.

    Attributes:
        failure_threshold     : Number of consecutive failures before OPEN.
        recovery_timeout_sec  : Seconds to wait in OPEN before probing again.
        call_timeout_sec      : Max seconds to wait for a single LLM call.
                                The *caller* must pass this to asyncio.wait_for().
    """

    # ── Configuration ─────────────────────────────────────────────────────────
    failure_threshold: int = int(os.getenv("LLM_FAILURE_THRESHOLD", "3"))
    recovery_timeout_sec: float = float(os.getenv("LLM_RECOVERY_TIMEOUT_SEC", "60"))
    call_timeout_sec: float = float(os.getenv("LLM_CALL_TIMEOUT_SEC", "2.0"))

    # ── Internal state ────────────────────────────────────────────────────────
    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    failure_count: int = field(default=0, init=False)
    last_failure_time: float = field(default=0.0, init=False)
    total_successes: int = field(default=0, init=False)
    total_failures: int = field(default=0, init=False)
    total_fallbacks: int = field(default=0, init=False)

    # Optional Telegram alert hook — set externally to avoid circular imports
    # Signature: async (message: str) -> None
    alert_hook: Callable[[str], Awaitable[None]] | None = field(
        default=None, init=False, repr=False
    )

    # ── Public API ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True if the LLM should be called, False to short-circuit."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_timeout_sec:
                log.info(
                    "[CircuitBreaker] Recovery timeout elapsed "
                    f"({elapsed:.0f}s ≥ {self.recovery_timeout_sec}s). "
                    "Transitioning OPEN → HALF_OPEN (probe)."
                )
                self.state = CircuitState.HALF_OPEN
                return True
            remaining = self.recovery_timeout_sec - elapsed
            log.debug(f"[CircuitBreaker] OPEN — {remaining:.0f}s until probe.")
            return False

        # HALF_OPEN: allow exactly one probe request
        return True

    def record_success(self):
        """Call this after a successful LLM API call."""
        self.total_successes += 1
        if self.state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
            log.info(
                "[CircuitBreaker] ✅ LLM call succeeded. "
                f"State: {self.state.value} → CLOSED. "
                f"Total fallbacks so far: {self.total_fallbacks}"
            )
            asyncio.create_task(
                self._maybe_send_recovery_alert()
            ) if asyncio.get_event_loop().is_running() else None
        self.state = CircuitState.CLOSED
        self.failure_count = 0

    def record_failure(self, error: str):
        """Call this after a failed or timed-out LLM API call."""
        self.failure_count += 1
        self.total_failures += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            log.warning(
                f"[CircuitBreaker] ❌ Probe failed: {error!r} — "
                "HALF_OPEN → OPEN. Extending recovery window."
            )
            self.state = CircuitState.OPEN
            return

        if self.failure_count >= self.failure_threshold:
            log.critical(
                f"[CircuitBreaker] 🚨 Threshold reached ({self.failure_count} "
                f"consecutive failures). CLOSED → OPEN. "
                f"Algorithmic fallback active for {self.recovery_timeout_sec}s. "
                f"Last error: {error!r}"
            )
            self.state = CircuitState.OPEN
            self.total_fallbacks += 1
            asyncio.create_task(
                self._maybe_send_open_alert(error)
            ) if asyncio.get_event_loop().is_running() else None
        else:
            log.warning(
                f"[CircuitBreaker] ⚠️ Failure {self.failure_count}/"
                f"{self.failure_threshold}: {error!r}"
            )

    @property
    def status_dict(self) -> dict:
        """Structured status — useful for /health endpoints and monitoring."""
        return {
            "circuit_state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "total_fallbacks": self.total_fallbacks,
            "call_timeout_sec": self.call_timeout_sec,
            "recovery_timeout_sec": self.recovery_timeout_sec,
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _maybe_send_open_alert(self, error: str):
        """Telegram alert when circuit trips OPEN."""
        if self.alert_hook is None:
            return
        msg = (
            "🚨 <b>LLM CIRCUIT BREAKER — OPEN</b>\n\n"
            "Hệ thống đã chuyển sang chế độ\n"
            "⚡ <b>ALGORITHMIC MODE</b> (Thuần thuật toán)\n\n"
            f"Lý do: <code>{error[:120]}</code>\n"
            f"Số lỗi liên tiếp: {self.failure_count}\n"
            f"Thời gian phục hồi: {self.recovery_timeout_sec:.0f}s\n\n"
            "✅ Tín hiệu vẫn được xử lý bình thường\n"
            "(chỉ thiếu phân tích AI chi tiết)"
        )
        try:
            await self.alert_hook(msg)
        except Exception as exc:
            log.warning(f"[CircuitBreaker] Failed to send OPEN alert: {exc}")

    async def _maybe_send_recovery_alert(self):
        """Telegram alert when circuit recovers to CLOSED."""
        if self.alert_hook is None:
            return
        msg = (
            "✅ <b>LLM CIRCUIT BREAKER — RECOVERED</b>\n\n"
            "Hệ thống đã trở lại chế độ\n"
            "🧠 <b>AI MODE</b> (RAG + LLM)\n\n"
            f"Tổng fallbacks: {self.total_fallbacks}\n"
            f"Tổng failures: {self.total_failures}"
        )
        try:
            await self.alert_hook(msg)
        except Exception as exc:
            log.warning(f"[CircuitBreaker] Failed to send recovery alert: {exc}")


# ────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# Used by: nerves/workers/trading/workers/vps_analyzer.py
# ────────────────────────────────────────────────────────────────────────────

llm_breaker = LLMCircuitBreaker()
