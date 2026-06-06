"""
Integration test: Indicator Signal Pipeline (v6.0 extension).

This test exercises the new end-to-end flow for indicator alerts:
  WebhookGateway -> SignalProcessor -> SignalEnricher -> (TradeEngine OR AIAnalyzer) -> NotificationHub
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.event_bus import EventBus
from core.events import (
    AlertTriggered,
    IndicatorSignalReceived,
    IndicatorSignalRejected,
    IndicatorSignalValidated,
    SignalValidated,
)


@pytest.fixture
def indicator_bus():
    """Create an isolated EventBus and wire up the indicator pipeline components."""
    bus = EventBus()

    from processor.signal_enricher import enrich_indicator_signal
    from processor.signal_enricher import set_bus as se_set_bus
    from processor.signal_processor import (
        _indicator_dedup_cache,
        process_indicator_signal,
    )
    from processor.signal_processor import (
        set_bus as sp_set_bus,
    )

    sp_set_bus(bus)
    se_set_bus(bus)
    _indicator_dedup_cache.clear()

    bus.on(IndicatorSignalReceived)(process_indicator_signal)
    bus.on(IndicatorSignalValidated)(enrich_indicator_signal)

    yield bus

    from core.event_bus import bus as default_bus
    from processor.signal_enricher import set_bus as se_set_bus

    sp_set_bus(default_bus)
    se_set_bus(default_bus)
    _indicator_dedup_cache.clear()


@pytest.mark.asyncio
async def test_indicator_pipeline_entry_signal(indicator_bus):
    """
    Scenario: 'entry' indicator signal should flow through to SignalValidated.
    """
    signal_validated_events = []

    @indicator_bus.on(SignalValidated)
    async def on_validated(event):
        signal_validated_events.append(event)

    with (
        patch("notifier.notify_all", new_callable=AsyncMock),
        patch(
            "mcp_client.MCPClient.capture_screenshot",
            new_callable=AsyncMock,
            return_value=Path("test.png"),
        ),
        patch(
            "vision.analyze_chart_vision",
            new_callable=AsyncMock,
            return_value={"confidence": 8},
        ),
    ):
        await indicator_bus.emit(
            IndicatorSignalReceived(
                signal_id=1001,
                symbol="BTCUSDT",
                indicator_name="SuperTrend",
                signal_type="entry",
                confidence_score=90,
                conditions_met=("price > ST",),
                metadata={"atr_value": "1000"},
                interval="60",
                price=68000.0,
                source_ip="127.0.0.1",
                exchange="binance",
            )
        )
        # Yield control to allow the background task to run
        import asyncio

        await asyncio.sleep(0.1)

    assert len(signal_validated_events) == 1
    event = signal_validated_events[0]
    assert event.symbol == "BTCUSDT"
    assert event.action == "buy"
    assert event.price == 68000.0
    # ATR-based SL/TP: sl = 68000 - (1000*2) = 66000, tp = 68000 + (1000*3) = 71000
    assert float(event.sl) == pytest.approx(66000.0)
    assert float(event.tp) == pytest.approx(71000.0)
    assert event.exchange == "binance"


@pytest.mark.asyncio
async def test_indicator_pipeline_info_signal(indicator_bus):
    """
    Scenario: 'info' indicator signal must NOT emit AlertTriggered.
    It MUST call notifier.notify_all directly (GAP-6 fix, REQ 6.1-6.3).
    """
    alert_events = []

    @indicator_bus.on(AlertTriggered)
    async def on_alert(event):
        alert_events.append(event)

    with patch("notifier.notify_all", new_callable=AsyncMock) as mock_notify:
        await indicator_bus.emit(
            IndicatorSignalReceived(
                signal_id=1002,
                symbol="ETHUSDT",
                indicator_name="RSI Divergence",
                signal_type="info",
                confidence_score=75,
                conditions_met=("RSI < 30",),
                metadata={},
                interval="1h",
                price=3500.0,
                source_ip="127.0.0.1",
                exchange="binance",
            )
        )

    # GAP-6: info must NOT trigger AIAnalyzer via AlertTriggered
    assert len(alert_events) == 0, "Info signal must NOT emit AlertTriggered"
    # Must call Telegram notifier directly
    mock_notify.assert_called_once()
    notification_msg = mock_notify.call_args[0][0]
    assert "RSI Divergence" in notification_msg
    assert "ETHUSDT" in notification_msg
    assert "75%" in notification_msg


@pytest.mark.asyncio
async def test_indicator_pipeline_rejection_low_confidence(indicator_bus):
    """
    Scenario: Signal with confidence < 50 should be rejected by SignalProcessor.
    """
    rejected_events = []
    validated_events = []

    @indicator_bus.on(IndicatorSignalRejected)
    async def on_rejected(event):
        rejected_events.append(event)

    @indicator_bus.on(IndicatorSignalValidated)
    async def on_validated(event):
        validated_events.append(event)

    await indicator_bus.emit(
        IndicatorSignalReceived(
            signal_id=1003,
            symbol="SOLUSDT",
            indicator_name="MACD",
            signal_type="entry",
            confidence_score=40,  # Below 50 threshold
            conditions_met=(),
            metadata={},
            interval="1h",
            price=150.0,
            source_ip="127.0.0.1",
            exchange="binance",
        )
    )

    assert len(rejected_events) == 1
    assert rejected_events[0].reason == "low_confidence"
    assert len(validated_events) == 0


@pytest.mark.asyncio
async def test_indicator_pipeline_dedup(indicator_bus):
    """
    Scenario: Duplicate signals within 60s should be rejected.
    """
    rejected_events = []
    validated_events = []

    @indicator_bus.on(IndicatorSignalRejected)
    async def on_rejected(event):
        rejected_events.append(event)

    @indicator_bus.on(IndicatorSignalValidated)
    async def on_validated(event):
        validated_events.append(event)

    payload = dict(
        symbol="ADAUSDT",
        indicator_name="BollingerBands",
        signal_type="entry",
        confidence_score=85,
        conditions_met=(),
        metadata={},
        interval="1h",
        price=1.2,
        source_ip="127.0.0.1",
        exchange="binance",
    )

    await indicator_bus.emit(IndicatorSignalReceived(signal_id=1004, **payload))
    await indicator_bus.emit(IndicatorSignalReceived(signal_id=1005, **payload))

    assert len(validated_events) == 1
    assert len(rejected_events) == 1
    assert rejected_events[0].reason == "duplicate_signal"
    assert rejected_events[0].signal_id == 1005
