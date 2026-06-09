"""
Unit tests for core/event_bus.py and processor/signal_processor.py
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from core.event_bus import EventBus
from core.events import (
    SignalReceived,
    SignalRejected,
    SignalValidated,
    TradeExecuted,
)

# ═══════════════════════════════════════════════════════════════
# EVENT BUS TESTS
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bus_emit_triggers_handler():
    """Handler should be called when its event type is emitted."""
    bus = EventBus()
    received = []

    @bus.on(SignalReceived)
    async def handler(event):
        received.append(event)

    await bus.emit(SignalReceived(signal_id=1, symbol="BTCUSDT", action="buy"))
    assert len(received) == 1
    assert received[0].symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_bus_no_handlers_no_error():
    """Emitting with no handlers should not raise."""
    bus = EventBus()
    await bus.emit(SignalReceived(signal_id=1, symbol="BTCUSDT"))
    assert bus.metrics["events_emitted"] == 1


@pytest.mark.asyncio
async def test_bus_multiple_handlers():
    """Multiple handlers for the same event should all be called."""
    bus = EventBus()
    results = []

    @bus.on(SignalReceived)
    async def h1(event):
        results.append("h1")

    @bus.on(SignalReceived)
    async def h2(event):
        results.append("h2")

    await bus.emit(SignalReceived(signal_id=1))
    assert results == ["h1", "h2"]


@pytest.mark.asyncio
async def test_bus_failure_isolation():
    """A failing handler should NOT prevent subsequent handlers from running."""
    bus = EventBus()
    results = []

    @bus.on(SignalReceived)
    async def bad_handler(event):
        raise RuntimeError("boom")

    @bus.on(SignalReceived)
    async def good_handler(event):
        results.append("ok")

    await bus.emit(SignalReceived(signal_id=1))
    assert results == ["ok"]
    assert bus.metrics["handler_errors"] == 1


@pytest.mark.asyncio
async def test_bus_different_event_types():
    """Handlers should only fire for their registered event type."""
    bus = EventBus()
    signals = []
    trades = []

    @bus.on(SignalReceived)
    async def on_signal(event):
        signals.append(event)

    @bus.on(TradeExecuted)
    async def on_trade(event):
        trades.append(event)

    await bus.emit(SignalReceived(signal_id=1))
    await bus.emit(TradeExecuted(signal_id=2))

    assert len(signals) == 1
    assert len(trades) == 1


@pytest.mark.asyncio
async def test_bus_metrics():
    """Metrics should track emitted events and handler counts."""
    bus = EventBus()

    @bus.on(SignalReceived)
    async def h(event):
        pass

    await bus.emit(SignalReceived())
    await bus.emit(SignalReceived())

    m = bus.metrics
    assert m["events_emitted"] == 2
    assert m["total_handlers"] == 1
    assert m["registered_topics"] == 1


@pytest.mark.asyncio
async def test_bus_reset():
    """Reset should clear all handlers and metrics."""
    bus = EventBus()

    @bus.on(SignalReceived)
    async def h(event):
        pass

    await bus.emit(SignalReceived())
    bus.reset()

    assert bus.handler_count() == 0
    assert bus.metrics["events_emitted"] == 0


@pytest.mark.asyncio
async def test_event_immutability():
    """Events should be frozen (immutable)."""
    event = SignalReceived(signal_id=1, symbol="BTCUSDT")
    with pytest.raises(AttributeError):
        event.symbol = "ETHUSDT"


# ═══════════════════════════════════════════════════════════════
# SIGNAL PROCESSOR TESTS
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_processor_validates_1h_signal():
    """A 1h buy signal should emit SignalValidated."""
    from processor.signal_processor import process_signal, reset_dedup_cache, set_bus

    reset_dedup_cache()

    test_bus = EventBus()
    set_bus(test_bus)
    from core.events import SignalIngested, MacroValidated
    from processor.macro_trend_processor import process_macro_trend
    from processor.minervini_sepa_processor import process_minervini_sepa

    test_bus.subscribe(SignalIngested, process_macro_trend)
    test_bus.subscribe(MacroValidated, process_minervini_sepa)
    validated = []

    @test_bus.on(SignalValidated)
    async def on_validated(event):
        validated.append(event)

    try:
        await process_signal(
            SignalReceived(
                signal_id=10,
                symbol="BTCUSDT",
                action="buy",
                price=68000.0,
                interval="60",
                quote_qty=50.0,
            )
        )
        assert len(validated) == 1
        assert validated[0].symbol == "BTCUSDT"
        assert validated[0].signal_id == 10
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


@pytest.mark.asyncio
async def test_processor_rejects_4h_signal():
    """A 4h buy signal should be rejected by Circuit Breaker."""
    from processor.signal_processor import process_signal, reset_dedup_cache, set_bus

    reset_dedup_cache()

    test_bus = EventBus()
    set_bus(test_bus)
    rejected = []

    @test_bus.on(SignalRejected)
    async def on_rejected(event):
        rejected.append(event)

    try:
        await process_signal(
            SignalReceived(
                signal_id=11,
                symbol="BTCUSDT",
                action="buy",
                price=68000.0,
                interval="4h",
                quote_qty=50.0,
            )
        )
        assert len(rejected) == 1
        assert rejected[0].reason == "invalid_timeframe"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()
