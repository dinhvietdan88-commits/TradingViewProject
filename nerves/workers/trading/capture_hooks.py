"""
P11 — HookDispatcher
Manages event-based capture triggers (on_signal, on_schedule, on_command)
with per-symbol cooldown enforcement.

Design ref: design.md § "HookDispatcher"
"""

import logging
import time
from typing import Dict, Optional

import config
from core.event_bus import bus
from core.events import CaptureTriggered, SignalValidated

logger = logging.getLogger(__name__)


class HookDispatcher:
    """
    Registers EventBus listeners for capture triggers and dispatches
    capture requests to PythonCaptureClient with cooldown enforcement.

    Design invariant (4): Hooks never talk to the daemon directly —
    they always go through PythonCaptureClient.
    """

    def __init__(self, capture_client):
        """
        Args:
            capture_client: PythonCaptureClient instance
        """
        self._client = capture_client
        self._active_hooks: list[str] = []
        self._last_capture_time: dict[str, float] = {}
        self._cooldown_sec = config.CAPTURE_COOLDOWN_SEC

    def register_hooks(self, active_hooks: list[str]) -> None:
        """
        Register enabled capture triggers.

        Property 6: Parsing produces a list of trimmed non-empty hook names.
        """
        self._active_hooks = [h.strip() for h in active_hooks if h.strip()]
        logger.info(f"HookDispatcher: Registering hooks: {self._active_hooks}")

        for hook in self._active_hooks:
            if hook == "on_signal":
                bus.subscribe(SignalValidated, self._on_signal_handler)
                logger.info(
                    "HookDispatcher: ✅ on_signal hook registered (SignalValidated)"
                )
            elif hook == "on_schedule":
                # Placeholder: schedule integration via APScheduler or similar
                logger.info("HookDispatcher: on_schedule hook registered (placeholder)")
            elif hook == "on_command":
                logger.info(
                    "HookDispatcher: on_command hook registered (manual trigger)"
                )
            else:
                logger.warning(f"HookDispatcher: Unknown hook '{hook}', skipping")

    # ── Event Handlers ────────────────────────────────────────────────────────

    async def _on_signal_handler(self, event: SignalValidated) -> None:
        """
        EventBus handler for SignalValidated — triggers capture with cooldown.
        """
        await self.on_signal(event)

    async def on_signal(self, event: SignalValidated) -> None:
        """
        Trigger capture when a trading signal is validated.

        Property 5: Dispatches capture with symbol exactly equal to event.symbol.
        Property 7: Enforces per-symbol cooldown.
        """
        symbol = event.symbol
        if not symbol:
            logger.debug("HookDispatcher: on_signal skipped — empty symbol")
            return

        if not self.is_cooled_down(symbol):
            logger.debug(
                f"HookDispatcher: on_signal skipped for {symbol} — "
                f"cooldown ({self._cooldown_sec}s) not elapsed"
            )
            return

        logger.info(f"HookDispatcher: Triggering capture for {symbol} (signal)")
        self._last_capture_time[symbol] = time.monotonic()

        # Emit tracing event
        await bus.emit_background(
            CaptureTriggered(
                symbol=symbol,
                trigger="signal",
                source_event_id=event.event_id,
            )
        )

        try:
            result = await self._client.capture_screenshot(
                symbol=symbol,
                timeframe="D",  # Default daily for signal captures
            )
            if result.success:
                logger.info(
                    f"HookDispatcher: ✅ Capture complete for {symbol} "
                    f"({result.latency_ms:.0f}ms, method={result.method})"
                )
            else:
                logger.warning(
                    f"HookDispatcher: ❌ Capture failed for {symbol}: {result.error}"
                )
        except Exception as e:
            logger.error(f"HookDispatcher: Capture error for {symbol}: {e}")

    async def on_schedule(self) -> None:
        """
        Trigger scheduled captures (e.g., cron-based batch scan).
        Placeholder — will be wired to APScheduler in future sprint.
        """
        logger.info("HookDispatcher: on_schedule triggered")
        # Future: iterate watchlist and capture each symbol

    async def on_command(self, symbol: str) -> object | None:
        """
        Trigger manual capture from Telegram /capture command.
        Bypasses cooldown — user explicitly requested this.

        Property 5: Dispatches capture with symbol exactly as provided.
        """
        logger.info(f"HookDispatcher: on_command triggered for {symbol}")

        # Emit tracing event
        await bus.emit_background(
            CaptureTriggered(
                symbol=symbol,
                trigger="command",
            )
        )

        try:
            result = await self._client.capture_screenshot(
                symbol=symbol,
                timeframe="D",
            )
            return result
        except Exception as e:
            logger.error(f"HookDispatcher: Command capture error for {symbol}: {e}")
            return None

    # ── Cooldown Logic ────────────────────────────────────────────────────────

    def is_cooled_down(self, symbol: str) -> bool:
        """
        Check if enough time has passed since the last capture for this symbol.

        Property 7: If time since last capture < CAPTURE_COOLDOWN_SEC, return False.
        """
        last_time = self._last_capture_time.get(symbol)
        if last_time is None:
            return True
        elapsed = time.monotonic() - last_time
        return elapsed >= self._cooldown_sec
