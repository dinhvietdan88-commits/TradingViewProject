"""
Event Bus — Lightweight in-process Pub-Sub using asyncio.

Design Invariants (from architecture_selection.md):
1. Event ordering guarantee — subscribers execute in registration order.
2. Failure isolation by absence — a failed handler logs the error but does NOT
   prevent other handlers from running, and does NOT crash the bus.
3. Event immutability — enforced by frozen dataclasses in events.py.

Usage:
    from core.event_bus import EventBus
    from core.events import SignalReceived

    bus = EventBus()

    # Register handler
    @bus.on(SignalReceived)
    async def handle_signal(event: SignalReceived):
        print(f"Got signal {event.signal_id}")

    # Emit event
    await bus.emit(SignalReceived(signal_id=42, symbol="BTCUSDT"))
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from core.events import Event

log = logging.getLogger(__name__)

# Type alias for event handler functions
EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """
    In-process async Pub-Sub event bus.

    Features:
    - Type-safe topic registration via Event subclasses.
    - Ordered handler execution per topic.
    - Failure isolation: one handler crash doesn't affect others.
    - Metrics: counts emitted events and handler errors.
    """

    def __init__(self):
        self._handlers: dict[type[Event], list[EventHandler]] = {}
        self._metrics = {
            "events_emitted": 0,
            "handler_errors": 0,
        }
        # BUG-06 fix: Hold strong references to background tasks to prevent
        # CPython GC from collecting them before completion.
        self._background_tasks: set = set()

    def on(self, event_type: type[Event]):
        """
        Decorator to register a handler for a specific event type.

        Example:
            @bus.on(SignalReceived)
            async def handle(event):
                ...
        """

        def decorator(handler: EventHandler) -> EventHandler:
            self.subscribe(event_type, handler)
            return handler

        return decorator

    def subscribe(self, event_type: type[Event], handler: EventHandler) -> None:
        """Register a handler for the given event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        log.debug(f"EventBus: Registered {handler.__name__} for {event_type.__name__}")

    async def emit(self, event: Event) -> None:
        """
        Dispatch an event to all registered handlers.

        Handlers run sequentially in registration order.
        A failing handler is logged but does NOT block subsequent handlers
        (Failure Isolation by Absence).
        """
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])
        self._metrics["events_emitted"] += 1

        if not handlers:
            log.debug(
                f"EventBus: No handlers for {event_type.__name__} ({event.event_id})"
            )
            return

        log.info(
            f"EventBus: Emitting {event_type.__name__} ({event.event_id}) → {len(handlers)} handler(s)"
        )

        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                self._metrics["handler_errors"] += 1
                log.error(
                    f"EventBus: Handler {handler.__name__} failed for "
                    f"{event_type.__name__} ({event.event_id}): {e}",
                    exc_info=True,
                )
                # Failure isolation: continue to next handler

    async def emit_background(self, event: Event) -> None:
        """
        Fire-and-forget: schedule event dispatch as a background asyncio task.
        Useful when the caller should not wait for handlers to complete.

        BUG-06 fix: Task reference is stored in _background_tasks to prevent
        premature garbage collection. The reference is cleaned up on completion.
        """
        task = asyncio.create_task(self.emit(event))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def handler_count(self, event_type: type[Event] = None) -> int:
        """Return number of registered handlers (total or per event type)."""
        if event_type:
            return len(self._handlers.get(event_type, []))
        return sum(len(h) for h in self._handlers.values())

    @property
    def metrics(self) -> dict:
        """Return bus metrics for monitoring."""
        return {
            **self._metrics,
            "registered_topics": len(self._handlers),
            "total_handlers": self.handler_count(),
        }

    def reset(self) -> None:
        """Clear all handlers and metrics. Useful for testing."""
        self._handlers.clear()
        self._metrics = {"events_emitted": 0, "handler_errors": 0}


# ═══════════════════════════════════════════════════════════════
# SINGLETON — Global event bus instance for the application.
# Components import this and register via @bus.on(EventType).
# ═══════════════════════════════════════════════════════════════

bus = EventBus()
