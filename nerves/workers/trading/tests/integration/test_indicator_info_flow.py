"""
Integration Test: Indicator Info Signal Flow
Feature: tradingview-alert-indicator-signal

Scenario: info signal must:
  1. Be persisted to DB
  2. Pass validation
  3. Emit notification to Telegram
  4. NOT emit AlertTriggered (no screenshot / AIAnalyzer)
  5. NOT emit SignalValidated (no trade execution)
"""

import pytest
from unittest.mock import AsyncMock, patch

from core.event_bus import EventBus
from core.events import (
    IndicatorSignalReceived,
    IndicatorSignalValidated,
    IndicatorSignalRejected,
    SignalValidated,
    AlertTriggered,
)


@pytest.fixture
def info_bus():
    """Isolated EventBus wired for the info signal test."""
    bus = EventBus()

    from processor.signal_processor import (
        process_indicator_signal,
        set_bus as sp_set_bus,
        _indicator_dedup_cache,
    )
    from processor.signal_enricher import enrich_indicator_signal, set_bus as se_set_bus

    sp_set_bus(bus)
    se_set_bus(bus)
    _indicator_dedup_cache.clear()

    bus.on(IndicatorSignalReceived)(process_indicator_signal)
    bus.on(IndicatorSignalValidated)(enrich_indicator_signal)

    yield bus

    from core.event_bus import bus as default_bus

    sp_set_bus(default_bus)
    se_set_bus(default_bus)
    _indicator_dedup_cache.clear()


@pytest.mark.asyncio
async def test_info_signal_no_trade_execution(info_bus):
    """
    Info signals MUST NOT emit SignalValidated (no TradeEngine interaction).
    Info signals MUST NOT emit AlertTriggered (no AIAnalyzer / screenshot).
    """
    trade_events = []
    alert_events = []
    info_validated_events = []

    @info_bus.on(SignalValidated)
    async def on_trade(event):
        trade_events.append(event)

    @info_bus.on(AlertTriggered)
    async def on_alert(event):
        alert_events.append(event)

    @info_bus.on(IndicatorSignalValidated)
    async def on_validated(event):
        info_validated_events.append(event)

    with patch("notifier.notify_all", new_callable=AsyncMock) as mock_notify:
        await info_bus.emit(
            IndicatorSignalReceived(
                signal_id=5001,
                symbol="ETHUSDT",
                indicator_name="RSI Oversold",
                signal_type="info",
                confidence_score=70,
                conditions_met=("RSI < 30", "Price below MA50"),
                metadata={"rsi": "28", "ma50": "3200"},
                interval="4h",
                price=3150.0,
                source_ip="127.0.0.1",
                exchange="binance",
            )
        )

    # Must propagate through: Received → Validated
    assert len(info_validated_events) == 1
    # Must NOT trigger trade execution
    assert len(trade_events) == 0, "Info signal must NOT produce SignalValidated"
    # Must NOT trigger AIAnalyzer
    assert len(alert_events) == 0, "Info signal must NOT emit AlertTriggered"
    # Must send notification
    mock_notify.assert_called_once()
    notification_msg = mock_notify.call_args[0][0]
    assert "RSI Oversold" in notification_msg
    assert "ETHUSDT" in notification_msg
    assert "70%" in notification_msg


@pytest.mark.asyncio
async def test_info_signal_high_priority_notification(info_bus):
    """
    Info signals with confidence > 80 must trigger high-priority (KHẨN CẤP) notification.
    """
    with patch("notifier.notify_all", new_callable=AsyncMock) as mock_notify:
        await info_bus.emit(
            IndicatorSignalReceived(
                signal_id=5002,
                symbol="BTCUSDT",
                indicator_name="SuperTrend Reversal",
                signal_type="info",
                confidence_score=92,  # > 80 → high priority
                conditions_met=("Price below ST", "Volume spike"),
                metadata={},
                interval="1h",
                price=68000.0,
                source_ip="127.0.0.1",
                exchange="binance",
            )
        )

    mock_notify.assert_called_once()
    msg = mock_notify.call_args[0][0]
    assert "KHẨN CẤP" in msg, "Expected high-priority prefix for confidence=92"


@pytest.mark.asyncio
async def test_info_signal_low_confidence_rejected(info_bus):
    """
    Info signals with confidence < 50 MUST be rejected, not enriched.
    """
    rejected = []
    validated = []

    @info_bus.on(IndicatorSignalRejected)
    async def on_rejected(event):
        rejected.append(event)

    @info_bus.on(IndicatorSignalValidated)
    async def on_validated(event):
        validated.append(event)

    await info_bus.emit(
        IndicatorSignalReceived(
            signal_id=5003,
            symbol="SOLUSDT",
            indicator_name="MACD Cross",
            signal_type="info",
            confidence_score=30,  # < 50
            conditions_met=(),
            metadata={},
            interval="1d",
            price=160.0,
            source_ip="127.0.0.1",
            exchange="binance",
        )
    )

    assert len(rejected) == 1
    assert rejected[0].reason == "low_confidence"
    assert len(validated) == 0
