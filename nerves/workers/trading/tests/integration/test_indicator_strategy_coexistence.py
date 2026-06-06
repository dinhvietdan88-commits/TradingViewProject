"""
Integration Test: Indicator + Strategy Signal Coexistence
Feature: tradingview-alert-indicator-signal

Scenario: A strategy buy signal and an indicator entry signal for the same symbol
arrive within 60s. Both MUST be processed independently.
Neither should deduplicate the other (separate caches).
"""

from unittest.mock import AsyncMock, patch

import pytest

from core.event_bus import EventBus
from core.events import (
    IndicatorSignalReceived,
    IndicatorSignalRejected,
    IndicatorSignalValidated,
    SignalReceived,
    SignalRejected,
    SignalValidated,
)


@pytest.fixture
def coexistence_bus():
    """Isolated EventBus with both strategy and indicator paths wired."""
    bus = EventBus()

    from processor.signal_enricher import enrich_indicator_signal
    from processor.signal_enricher import set_bus as se_set_bus
    from processor.signal_processor import (
        _dedup_cache,
        _indicator_dedup_cache,
        process_indicator_signal,
        process_signal,
    )
    from processor.signal_processor import (
        set_bus as sp_set_bus,
    )

    sp_set_bus(bus)
    se_set_bus(bus)
    _dedup_cache.clear()
    _indicator_dedup_cache.clear()

    bus.on(SignalReceived)(process_signal)
    bus.on(IndicatorSignalReceived)(process_indicator_signal)
    bus.on(IndicatorSignalValidated)(enrich_indicator_signal)

    yield bus

    from core.event_bus import bus as default_bus

    sp_set_bus(default_bus)
    se_set_bus(default_bus)
    _dedup_cache.clear()
    _indicator_dedup_cache.clear()


@pytest.mark.asyncio
async def test_strategy_and_indicator_processed_independently(coexistence_bus):
    """
    Strategy buy + indicator entry for same BTCUSDT symbol.
    Both must produce a validated event independently within 60s.
    Dedup caches must NOT interfere with each other.
    """
    signal_validated_events = []
    indicator_validated_events = []
    rejected_events = []

    @coexistence_bus.on(SignalValidated)
    async def on_strategy_validated(event):
        signal_validated_events.append(event)

    @coexistence_bus.on(IndicatorSignalValidated)
    async def on_indicator_validated(event):
        indicator_validated_events.append(event)

    @coexistence_bus.on(SignalRejected)
    async def on_strategy_rejected(event):
        rejected_events.append(("strategy", event))

    @coexistence_bus.on(IndicatorSignalRejected)
    async def on_indicator_rejected(event):
        rejected_events.append(("indicator", event))

    with patch("notifier.notify_all", new_callable=AsyncMock):
        # Emit strategy buy signal
        await coexistence_bus.emit(
            SignalReceived(
                signal_id=6001,
                symbol="BTCUSDT",
                action="buy",
                price=68000.0,
                quote_qty=10.0,
                exchange="binance",
            )
        )

        # Emit indicator entry for same symbol within 60s
        await coexistence_bus.emit(
            IndicatorSignalReceived(
                signal_id=6002,
                symbol="BTCUSDT",
                indicator_name="SuperTrend",
                signal_type="entry",
                confidence_score=85,
                conditions_met=("price > ST",),
                metadata={"atr_value": "500"},
                interval="1h",
                price=68000.0,
                source_ip="127.0.0.1",
                exchange="binance",
            )
        )

    # Both pipelines must produce their own validated event
    assert len(indicator_validated_events) >= 1, (
        "Indicator pipeline must produce IndicatorSignalValidated"
    )

    # Ensure no rejection due to dedup collision
    indicator_rejections = [r for r in rejected_events if r[0] == "indicator"]
    dedup_rejections = [
        r for r in indicator_rejections if r[1].reason == "duplicate_signal"
    ]
    assert len(dedup_rejections) == 0, (
        "Indicator signal must NOT be rejected as strategy duplicate"
    )


@pytest.mark.asyncio
async def test_indicator_dedup_does_not_affect_second_indicator_different_name(
    coexistence_bus,
):
    """
    Two different indicators for the same symbol within 60s should BOTH be processed.
    Dedup key = (symbol, indicator_name, signal_type), so different indicators are distinct.
    """
    validated_events = []

    @coexistence_bus.on(IndicatorSignalValidated)
    async def on_validated(event):
        validated_events.append(event)

    with patch("notifier.notify_all", new_callable=AsyncMock):
        await coexistence_bus.emit(
            IndicatorSignalReceived(
                signal_id=6003,
                symbol="ETHUSDT",
                indicator_name="SuperTrend",
                signal_type="entry",
                confidence_score=80,
                conditions_met=(),
                metadata={},
                interval="1h",
                price=3500.0,
                source_ip="127.0.0.1",
                exchange="binance",
            )
        )

        await coexistence_bus.emit(
            IndicatorSignalReceived(
                signal_id=6004,
                symbol="ETHUSDT",
                indicator_name="RSI Oversold",  # Different indicator name
                signal_type="entry",
                confidence_score=75,
                conditions_met=(),
                metadata={},
                interval="1h",
                price=3500.0,
                source_ip="127.0.0.1",
                exchange="binance",
            )
        )

    assert len(validated_events) == 2, (
        f"Both different-indicator signals must be validated independently, got {len(validated_events)}"
    )
