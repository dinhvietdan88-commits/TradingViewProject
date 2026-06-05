"""
event_handler.py — EventBusInterface for Claude CLI integration.

Subscribes to SignalValidated events and routes them through ClaudeService
when AI_PROVIDER=claude_cli, emitting AnalysisComplete with the same
structural contract as the existing ai_analyzer.py pipeline.

Design invariants (Interface Layer):
- Never mutates context. All state changes go through ClaudeService.
- Only registers when both CLAUDE_CLI_ENABLED=True AND AI_PROVIDER=claude_cli.
- Emitted AnalysisComplete is structurally identical to ai_analyzer output (Property 6).
- Bus reference is overrideable for unit testing via set_bus().

Usage (from main.py lifespan startup):
    from claude_cli import event_handler
    event_handler.register_handler(claude_service)
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

import config
from core.event_bus import bus as _default_bus
from core.events import SignalValidated, AnalysisComplete
from .service import ClaudeService, AnalysisRequest, AnalysisResponse

if TYPE_CHECKING:
    from core.event_bus import EventBus

log = logging.getLogger(__name__)

# ─── Module-level mutable state (safe — modified only at startup) ───────────────
_bus: "EventBus" = _default_bus
_service: Optional[ClaudeService] = None


def set_bus(bus_instance: "EventBus") -> None:
    """Override the event bus instance (for unit testing)."""
    global _bus
    _bus = bus_instance


# ─── Event handler ──────────────────────────────────────────────────────────────


async def handle_signal_validated(event: SignalValidated) -> None:
    """
    Process a SignalValidated event through the Claude CLI pipeline.

    Guards:
    - Silently skips if AI_PROVIDER != "claude_cli".
    - Silently skips if _service not initialized.

    Property 6: emitted AnalysisComplete has all required fields populated with
    same types/value ranges as events from ai_analyzer.py.
    """
    provider = getattr(config, "AI_PROVIDER", "anthropic").lower()
    if provider != "claude_cli":
        log.debug(f"EventHandler: AI_PROVIDER={provider!r}, skipping Claude CLI route")
        return

    if not _service:
        log.warning("EventHandler: ClaudeService not initialized — skipping signal")
        return

    log.info(
        f"EventHandler: Routing SignalValidated({event.symbol} {event.action}) "
        f"→ ClaudeService [claude_cli]"
    )

    request = AnalysisRequest(
        query=(
            f"Phân tích tín hiệu {event.action.upper()} cho {event.symbol} "
            f"tại giá {event.price}. SL: {event.sl}, TP: {event.tp}. "
            f"Đánh giá theo SEPA Minervini và cho biết nên giao dịch không?"
        ),
        symbol=event.symbol,
        action=event.action,
        price=event.price,
        trading_context={
            "signal_id": event.signal_id,
            "quote_qty": event.quote_qty,
            "exchange": event.exchange,
            "sl": event.sl,
            "tp": event.tp,
        },
        include_rag_context=True,
    )

    try:
        response: AnalysisResponse = await _service.analyze(request)
    except Exception as exc:
        log.error(
            f"EventHandler: ClaudeService.analyze raised unexpectedly: {exc}",
            exc_info=True,
        )
        response = AnalysisResponse(
            text=f"⚠️ AI analysis error: {exc}",
            confidence=0,
            source="none",
            error=str(exc),
        )

    analysis_event = _map_to_analysis_complete(event, response)

    try:
        await _bus.emit(analysis_event)
        log.info(
            f"EventHandler: AnalysisComplete emitted for {event.symbol} "
            f"(confidence={analysis_event.confidence}, should_trade={analysis_event.should_trade})"
        )
    except Exception as exc:
        log.error(
            f"EventHandler: Failed to emit AnalysisComplete: {exc}", exc_info=True
        )


def register_handler(claude_service: ClaudeService) -> None:
    """
    Register the SignalValidated handler on the EventBus.

    Must only be called when:
    - CLAUDE_CLI_ENABLED = True
    - AI_PROVIDER = "claude_cli"

    Property 8: calling this when feature flag is False violates the invariant;
    the caller (main.py) is responsible for the guard.
    """
    global _service
    _service = claude_service
    _bus.subscribe(SignalValidated, handle_signal_validated)
    log.info("Claude CLI EventBus handler registered for SignalValidated")


# ─── Mapping helper ─────────────────────────────────────────────────────────────


def _map_to_analysis_complete(
    event: SignalValidated,
    response: AnalysisResponse,
) -> AnalysisComplete:
    """
    Map ClaudeService output → AnalysisComplete event.

    Property 6 guarantee: all required fields populated identically to ai_analyzer.py:
    - signal_id, symbol, action, price: copied from source event
    - quote_qty, sl, tp, exchange: copied from source event
    - confidence: from AnalysisResponse (1–10 scale)
    - analysis_text: full response text
    - should_trade: confidence >= 8  (same threshold as ai_analyzer.py)
    - interactive_required: True when 5 <= confidence < 8 (human review zone)
    - screenshot_path: empty (CLI doesn't capture screenshots)
    - combined_score, vision_result: None (not applicable for text-only CLI)
    """
    confidence = max(0, min(10, response.confidence))
    should_trade = confidence >= 8
    interactive_required = 5 <= confidence < 8

    return AnalysisComplete(
        signal_id=event.signal_id,
        symbol=event.symbol,
        action=event.action,
        price=event.price,
        quote_qty=event.quote_qty,
        sl=event.sl,
        tp=event.tp,
        exchange=event.exchange,
        confidence=confidence,
        analysis_text=response.text,
        screenshot_path="",
        combined_score=f"CLI:{response.source}|conf:{confidence}",
        vision_result=None,
        should_trade=should_trade,
        interactive_required=interactive_required,
    )
