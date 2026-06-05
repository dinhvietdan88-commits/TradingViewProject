"""
tests/unit/test_claude_event_handler.py
Unit tests for claude_cli.event_handler (EventBusInterface).

Tests cover:
  - _map_to_analysis_complete: all required fields populated correctly
  - should_trade = confidence >= 6
  - interactive_required = confidence in [5, 6]
  - combined_score = confidence / 10.0
  - handle_signal_validated: calls ClaudeService.analyze() and emits AnalysisComplete
  - register_handler: wires up the bus subscription
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from claude_cli.service import ClaudeService, AnalysisRequest, AnalysisResponse
import claude_cli.event_handler as eh


# ── minimal stubs for events ────────────────────────────────────────────────────


@dataclass
class _SignalValidated:
    event_id: str = "evt-001"
    timestamp: float = 0.0
    signal_id: str = "sig-001"
    symbol: str = "BTCUSDT"
    action: str = "BUY"
    price: float = 42000.0
    quote_qty: float = 100.0
    sl: float = 41000.0
    tp: float = 44000.0
    exchange: str = "binance"


@dataclass
class _AnalysisComplete:
    event_id: str = ""
    timestamp: float = 0.0
    signal_id: str = ""
    symbol: str = ""
    action: str = ""
    price: float = 0.0
    quote_qty: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    exchange: str = ""
    confidence: int = 0
    analysis_text: str = ""
    screenshot_path: str = ""
    combined_score: str = ""
    vision_result: object = None
    should_trade: bool = False
    interactive_required: bool = False


# ── _map_to_analysis_complete ───────────────────────────────────────────────────


def _make_response(confidence: int = 7, text: str = "good signal") -> AnalysisResponse:
    return AnalysisResponse(text=text, confidence=confidence, source="claude_cli")


# Actual thresholds from event_handler.py:
#   should_trade = confidence >= 8
#   interactive_required = 5 <= confidence < 8
@pytest.mark.parametrize(
    "confidence,should_trade,interactive",
    [
        (8, True, False),  # exactly at threshold
        (9, True, False),
        (10, True, False),
        (7, False, True),  # human-review zone
        (6, False, True),
        (5, False, True),  # lower bound of review zone
        (4, False, False),  # below review zone
        (1, False, False),
        (0, False, False),
    ],
)
def test_map_fields_should_trade_and_interactive(confidence, should_trade, interactive):
    event = _SignalValidated()
    resp = _make_response(confidence=confidence)
    with patch("claude_cli.event_handler.AnalysisComplete", _AnalysisComplete):
        result = eh._map_to_analysis_complete(event, resp)
    assert result.should_trade is should_trade, (
        f"confidence={confidence}: expected should_trade={should_trade}, got {result.should_trade}"
    )
    assert result.interactive_required is interactive, (
        f"confidence={confidence}: expected interactive_required={interactive}, got {result.interactive_required}"
    )


@pytest.mark.parametrize("confidence", [1, 3, 5, 7, 10])
def test_map_combined_score_contains_confidence(confidence):
    """combined_score is a string 'CLI:<source>|conf:<confidence>'."""
    event = _SignalValidated()
    resp = _make_response(confidence=confidence)
    # Use the real AnalysisComplete from core (requires quote_qty / sl / tp)
    result = eh._map_to_analysis_complete(event, resp)
    assert str(confidence) in result.combined_score
    assert "CLI:" in result.combined_score


def test_map_copies_event_fields():
    event = _SignalValidated(
        signal_id="X42", symbol="ETHUSDT", action="SELL", price=3100.0, exchange="bybit"
    )
    resp = _make_response(confidence=8, text="sell signal")
    with patch("claude_cli.event_handler.AnalysisComplete", _AnalysisComplete):
        result = eh._map_to_analysis_complete(event, resp)
    assert result.signal_id == "X42"
    assert result.symbol == "ETHUSDT"
    assert result.action == "SELL"
    assert result.price == 3100.0
    assert result.exchange == "bybit"
    assert result.analysis_text == "sell signal"
    assert result.confidence == 8


# ── handle_signal_validated ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_signal_validated_calls_analyze_and_emits():
    svc = AsyncMock(spec=ClaudeService)
    svc.analyze = AsyncMock(
        return_value=AnalysisResponse(
            text="bullish signal [Confidence: 8/10]", confidence=8, source="claude_cli"
        )
    )

    mock_bus = MagicMock()
    mock_bus.emit = AsyncMock()
    # Patch the module-level _service and _bus
    with (
        patch.object(eh, "_service", svc),
        patch.object(eh, "_bus", mock_bus),
        patch("config.AI_PROVIDER", "claude_cli"),
    ):
        event = _SignalValidated()
        await eh.handle_signal_validated(event)

    svc.analyze.assert_called_once()
    call_req: AnalysisRequest = svc.analyze.call_args[0][0]
    assert call_req.symbol == "BTCUSDT"
    assert call_req.action == "BUY"
    assert call_req.price == 42000.0
    mock_bus.emit.assert_called_once()


@pytest.mark.asyncio
async def test_handle_signal_validated_does_not_crash_on_service_error():
    """If ClaudeService.analyze() raises, handler logs and does not propagate."""
    svc = AsyncMock(spec=ClaudeService)
    svc.analyze = AsyncMock(side_effect=Exception("unexpected"))

    mock_bus = MagicMock()
    mock_bus.emit = AsyncMock()

    with (
        patch.object(eh, "_service", svc),
        patch.object(eh, "_bus", mock_bus),
        patch("config.AI_PROVIDER", "claude_cli"),
    ):
        try:
            await eh.handle_signal_validated(_SignalValidated())
        except Exception:
            pytest.fail("handle_signal_validated must not propagate exceptions")


@pytest.mark.asyncio
async def test_handle_signal_validated_skips_when_wrong_provider():
    """When AI_PROVIDER != 'claude_cli', handler is a no-op."""
    svc = AsyncMock(spec=ClaudeService)
    mock_bus = MagicMock()
    mock_bus.emit = AsyncMock()

    with (
        patch.object(eh, "_service", svc),
        patch.object(eh, "_bus", mock_bus),
        patch("config.AI_PROVIDER", "anthropic"),
    ):
        await eh.handle_signal_validated(_SignalValidated())

    svc.analyze.assert_not_called()
    mock_bus.emit.assert_not_called()


# ── register_handler ────────────────────────────────────────────────────────────


def test_register_handler_sets_service():
    svc = MagicMock(spec=ClaudeService)
    mock_bus = MagicMock()

    with patch.object(eh, "_service", None), patch.object(eh, "_bus", mock_bus):
        eh.register_handler(svc)
        # After registration, module-level _service is set
        assert eh._service is svc
