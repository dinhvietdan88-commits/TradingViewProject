"""
Unit tests for SignalProcessor component (v6.0).

Tests verify:
- 'alert' action bypasses dedup/timeframe and emits AlertTriggered.
- Dedup cache rejects identical (symbol, action) within 60s TTL.
- Dedup cache allows after TTL expires.
- Timeframe circuit breaker: valid intervals (60 / 1h / 60m) pass.
- Timeframe circuit breaker: invalid intervals (4h, 15, D) are rejected.
- Unknown actions are rejected with 'unknown_action' reason.
- SignalValidated carries exchange context from original event.
- SignalRejected carries correct reason and interval metadata.
- reset_dedup_cache() fully clears the cache.
"""

import time
import pytest

from core.event_bus import EventBus
from core.events import (
    SignalReceived,
    SignalValidated,
    SignalRejected,
    AlertTriggered,
)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════


def _make_event(**kwargs):
    defaults = dict(
        signal_id=1,
        symbol="BTCUSDT",
        action="buy",
        price=68000.0,
        quote_qty=50.0,
        interval="60",
        sl="",
        tp="",
        exchange="binance",
    )
    defaults.update(kwargs)
    return SignalReceived(**defaults)


# ═══════════════════════════════════════════════════════════════
# ALERT BYPASS
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_alert_action_emits_alert_triggered():
    """Action='alert' must emit AlertTriggered and skip dedup / timeframe checks."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    emitted = []

    @test_bus.on(AlertTriggered)
    async def on_alert(event):
        emitted.append(event)

    try:
        await process_signal(
            _make_event(action="alert", symbol="ETHUSDT", signal_id=10)
        )
        assert len(emitted) == 1
        assert emitted[0].symbol == "ETHUSDT"
        assert emitted[0].signal_id == 10
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


@pytest.mark.asyncio
async def test_alert_carries_exchange_context():
    """AlertTriggered should preserve exchange from original SignalReceived."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    emitted = []

    @test_bus.on(AlertTriggered)
    async def on_alert(event):
        emitted.append(event)

    try:
        await process_signal(
            _make_event(action="alert", exchange="bybit", signal_id=11)
        )
        assert emitted[0].exchange == "bybit"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


# ═══════════════════════════════════════════════════════════════
# DEDUP CACHE
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_dedup_rejects_duplicate_within_ttl():
    """Second identical (symbol, action) within 60s → SignalRejected(reason=duplicate_signal)."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    validated = []
    rejected = []

    @test_bus.on(SignalValidated)
    async def on_valid(event):
        validated.append(event)

    @test_bus.on(SignalRejected)
    async def on_reject(event):
        rejected.append(event)

    try:
        await process_signal(
            _make_event(symbol="BTCUSDT", action="buy", signal_id=20, interval="60")
        )
        await process_signal(
            _make_event(symbol="BTCUSDT", action="buy", signal_id=21, interval="60")
        )

        assert len(validated) == 1
        assert len(rejected) == 1
        assert rejected[0].reason == "duplicate_signal"
        assert rejected[0].signal_id == 21
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


@pytest.mark.asyncio
async def test_dedup_allows_different_actions():
    """buy and sell for the same symbol are different cache keys — both should pass."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    validated = []

    @test_bus.on(SignalValidated)
    async def on_valid(event):
        validated.append(event)

    try:
        await process_signal(
            _make_event(symbol="BTCUSDT", action="buy", signal_id=22, interval="60")
        )
        await process_signal(
            _make_event(symbol="BTCUSDT", action="sell", signal_id=23, interval="60")
        )
        assert len(validated) == 2
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


@pytest.mark.asyncio
async def test_dedup_allows_different_symbols():
    """Same action on different symbols are independent cache keys — both should pass."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    validated = []

    @test_bus.on(SignalValidated)
    async def on_valid(event):
        validated.append(event)

    try:
        await process_signal(
            _make_event(symbol="BTCUSDT", action="buy", signal_id=24, interval="60")
        )
        await process_signal(
            _make_event(symbol="ETHUSDT", action="buy", signal_id=25, interval="60")
        )
        assert len(validated) == 2
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


@pytest.mark.asyncio
async def test_dedup_cache_is_symbol_case_insensitive():
    """Dedup key normalizes symbol to uppercase — 'btcusdt' == 'BTCUSDT'."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    rejected = []

    @test_bus.on(SignalRejected)
    async def on_reject(event):
        rejected.append(event)

    try:
        await process_signal(
            _make_event(symbol="btcusdt", action="buy", signal_id=26, interval="60")
        )
        await process_signal(
            _make_event(symbol="BTCUSDT", action="buy", signal_id=27, interval="60")
        )
        assert len(rejected) == 1
        assert rejected[0].reason == "duplicate_signal"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


@pytest.mark.asyncio
async def test_dedup_allows_signal_after_ttl_expires():
    """After the 60s TTL, the same (symbol, action) should be accepted."""
    from processor.signal_processor import (
        process_signal,
        set_bus,
        reset_dedup_cache,
        _dedup_cache,
        DEDUP_TTL_SEC,
    )

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    validated = []

    @test_bus.on(SignalValidated)
    async def on_valid(event):
        validated.append(event)

    try:
        # Pre-seed cache with an expired timestamp
        _dedup_cache[("BTCUSDT", "buy")] = time.time() - DEDUP_TTL_SEC - 1

        await process_signal(
            _make_event(symbol="BTCUSDT", action="buy", signal_id=28, interval="60")
        )
        assert len(validated) == 1
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


# ═══════════════════════════════════════════════════════════════
# TIMEFRAME CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════════════


@pytest.mark.parametrize("valid_interval", ["60", "1h", "60m"])
@pytest.mark.asyncio
async def test_valid_timeframes_pass(valid_interval):
    """Intervals '60', '1h', '60m' should all produce SignalValidated."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    validated = []

    @test_bus.on(SignalValidated)
    async def on_valid(event):
        validated.append(event)

    try:
        await process_signal(_make_event(interval=valid_interval, signal_id=30))
        assert len(validated) == 1
        assert validated[0].action == "buy"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


@pytest.mark.parametrize("bad_interval", ["4h", "15", "240", ""])
@pytest.mark.asyncio
async def test_invalid_timeframes_rejected(bad_interval):
    """Intervals that are not 1h/60/60m should produce SignalRejected(invalid_timeframe)."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    rejected = []

    @test_bus.on(SignalRejected)
    async def on_reject(event):
        rejected.append(event)

    try:
        await process_signal(_make_event(interval=bad_interval, signal_id=31))
        assert len(rejected) == 1
        assert rejected[0].reason == "invalid_timeframe"
        assert rejected[0].interval == bad_interval
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


# ═══════════════════════════════════════════════════════════════
# UNKNOWN ACTIONS
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unknown_action_rejected():
    """An unrecognized action (not buy/sell/alert) should be rejected."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    rejected = []

    @test_bus.on(SignalRejected)
    async def on_reject(event):
        rejected.append(event)

    try:
        await process_signal(_make_event(action="close", signal_id=40))
        assert len(rejected) == 1
        assert rejected[0].reason == "unknown_action"
        assert rejected[0].action == "close"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


# ═══════════════════════════════════════════════════════════════
# EXCHANGE PROPAGATION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_signal_validated_preserves_exchange():
    """SignalValidated must carry the exchange field from the original SignalReceived."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    validated = []

    @test_bus.on(SignalValidated)
    async def on_valid(event):
        validated.append(event)

    try:
        await process_signal(_make_event(exchange="bybit", interval="1h", signal_id=50))
        assert len(validated) == 1
        assert validated[0].exchange == "bybit"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


@pytest.mark.asyncio
async def test_signal_rejected_preserves_exchange():
    """SignalRejected must carry the exchange field (for logging/notifications)."""
    from processor.signal_processor import process_signal, set_bus, reset_dedup_cache

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()
    rejected = []

    @test_bus.on(SignalRejected)
    async def on_reject(event):
        rejected.append(event)

    try:
        await process_signal(
            _make_event(action="buy", exchange="okx", interval="4h", signal_id=51)
        )
        assert len(rejected) == 1
        assert rejected[0].exchange == "okx"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


# ═══════════════════════════════════════════════════════════════
# CACHE RESET
# ═══════════════════════════════════════════════════════════════


def test_reset_dedup_cache_clears_state():
    """reset_dedup_cache() should empty the in-memory dedup store."""
    from processor.signal_processor import reset_dedup_cache, _dedup_cache

    _dedup_cache[("BTCUSDT", "buy")] = time.time()
    assert len(_dedup_cache) > 0
    reset_dedup_cache()
    assert len(_dedup_cache) == 0
