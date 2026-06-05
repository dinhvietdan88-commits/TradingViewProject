import pytest
from dataclasses import FrozenInstanceError
from hypothesis import given, strategies as st

from server.core.events import Event, SignalReceived
from server.core.event_bus import EventBus


class DummyEvent(Event):
    value: int = 0


@pytest.fixture
def bus():
    """Fixture to provide a clean EventBus instance for each test."""
    test_bus = EventBus()
    yield test_bus
    test_bus.reset()


@pytest.mark.asyncio
async def test_event_bus_registration(bus):
    """Test that handlers are correctly registered to topics."""

    @bus.on(DummyEvent)
    async def handler(event: DummyEvent):
        pass

    assert bus.handler_count(DummyEvent) == 1
    assert bus.handler_count() == 1
    assert bus.metrics["registered_topics"] == 1


@pytest.mark.asyncio
async def test_event_bus_dispatch_ordering(bus):
    """Test that events are dispatched sequentially in registration order (Design Invariant 1)."""
    execution_order = []

    @bus.on(DummyEvent)
    async def handler1(event: DummyEvent):
        execution_order.append(1)

    @bus.on(DummyEvent)
    async def handler2(event: DummyEvent):
        execution_order.append(2)

    await bus.emit(DummyEvent(value=5))

    assert execution_order == [1, 2]
    assert bus.metrics["events_emitted"] == 1


@pytest.mark.asyncio
async def test_event_bus_failure_isolation(bus):
    """Test failure isolation: a failing handler does not prevent subsequent handlers from running (Design Invariant 2)."""
    execution_order = []

    @bus.on(DummyEvent)
    async def failing_handler(event: DummyEvent):
        execution_order.append("fail")
        raise ValueError("Simulated failure")

    @bus.on(DummyEvent)
    async def successful_handler(event: DummyEvent):
        execution_order.append("success")

    await bus.emit(DummyEvent(value=42))

    # The second handler should still run despite the first one failing
    assert execution_order == ["fail", "success"]
    assert bus.metrics["handler_errors"] == 1
    assert bus.metrics["events_emitted"] == 1


@given(
    signal_id=st.integers(min_value=1, max_value=10000),
    symbol=st.text(min_size=1, max_size=10),
    quote_qty=st.floats(
        min_value=0.1, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
)
def test_event_immutability_property(signal_id, symbol, quote_qty):
    """
    Property-based test: Ensure events are completely immutable after creation (Design Invariant 3).
    """
    event = SignalReceived(signal_id=signal_id, symbol=symbol, quote_qty=quote_qty)

    with pytest.raises(FrozenInstanceError):
        event.signal_id = signal_id + 1
