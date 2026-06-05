"""
tests/unit/test_capture_studio.py
Unit tests for P11 Stealth Capture Studio (Python layer).

Components tested:
  - PythonCaptureClient: fallback logic, daemon availability caching
  - DaemonLifecycleManager: restart budget, state tracking
  - HookDispatcher: cooldown enforcement, hook registration, event routing
  - CaptureTriggered: event immutability and field integrity
"""

import time
import pytest
import sys
import pathlib
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from core.event_bus import EventBus
from core.events import SignalValidated, CaptureTriggered


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════


def _make_mock_capture_client(daemon_available=True):
    """Create a mock PythonCaptureClient for testing hooks."""
    from capture_client import PythonCaptureClient, CaptureResult

    client = PythonCaptureClient(host="127.0.0.1", port=9333)

    # Mock the HTTP calls
    mock_result = CaptureResult(
        success=True,
        file_path="/tmp/test.png",
        latency_ms=150,
        method="daemon",
        size_bytes=50000,
    )
    client.capture_screenshot = AsyncMock(return_value=mock_result)
    client.set_symbol = AsyncMock(return_value=True)
    client.is_daemon_available = AsyncMock(return_value=daemon_available)
    return client


# ═══════════════════════════════════════════════════════════════
# CaptureTriggered EVENT
# ═══════════════════════════════════════════════════════════════


def test_capture_triggered_frozen():
    """CaptureTriggered events should be immutable (frozen dataclass)."""
    event = CaptureTriggered(symbol="BTCUSDT", trigger="signal")
    with pytest.raises(AttributeError):
        event.symbol = "ETHUSDT"


def test_capture_triggered_fields():
    """CaptureTriggered should have required fields."""
    event = CaptureTriggered(
        symbol="BTCUSDT",
        trigger="signal",
        source_event_id="evt-123",
    )
    assert event.symbol == "BTCUSDT"
    assert event.trigger == "signal"
    assert event.source_event_id == "evt-123"
    assert event.event_id != ""
    assert event.timestamp != ""


def test_capture_triggered_defaults():
    """CaptureTriggered defaults should be empty strings."""
    event = CaptureTriggered()
    assert event.symbol == ""
    assert event.trigger == ""
    assert event.source_event_id == ""


# ═══════════════════════════════════════════════════════════════
# PythonCaptureClient — UNIT TESTS
# ═══════════════════════════════════════════════════════════════


def test_client_base_url():
    """Client should construct base URL from host:port."""
    from capture_client import PythonCaptureClient

    client = PythonCaptureClient(host="10.0.0.1", port=9444)
    assert client._base_url == "http://10.0.0.1:9444"


def test_client_initial_state():
    """Client should start in non-fallback mode."""
    from capture_client import PythonCaptureClient

    client = PythonCaptureClient()
    assert client.fallback_mode is False
    assert client._daemon_available is None


@pytest.mark.asyncio
async def test_client_fallback_on_daemon_down():
    """When daemon is unavailable, client should use local rendering fallback."""
    from capture_client import PythonCaptureClient, CaptureResult

    client = PythonCaptureClient(host="127.0.0.1", port=19999)
    client._daemon_available = False
    client._last_check_time = time.monotonic()

    # Mock local capture fallback to avoid real subprocess/Playwright/mplfinance call
    mock_result = CaptureResult(success=True, method="local-charts", latency_ms=5000)
    client._local_capture = AsyncMock(return_value=mock_result)

    result = await client.capture_screenshot(symbol="BTCUSDT")
    assert result.method == "local-charts"
    client._local_capture.assert_called_once()


@pytest.mark.asyncio
async def test_client_availability_cache_ttl():
    """Availability check should cache result for 5 seconds."""
    from capture_client import PythonCaptureClient

    client = PythonCaptureClient()
    client._daemon_available = True
    client._last_check_time = time.monotonic()

    # Within TTL window — should return cached value without HTTP call
    result = await client.is_daemon_available()
    assert result is True


@pytest.mark.asyncio
async def test_client_batch_result_count():
    """Property 3: batch_run returns exactly len(symbols) results."""
    from capture_client import PythonCaptureClient, CaptureResult

    client = PythonCaptureClient()
    client._daemon_available = False
    client._last_check_time = time.monotonic()

    mock_result = CaptureResult(success=True, method="local-charts", latency_ms=100)
    client._local_capture = AsyncMock(return_value=mock_result)

    symbols = [
        {"symbol": "BTCUSDT", "timeframe": "D"},
        {"symbol": "ETHUSDT", "timeframe": "1h"},
        {"symbol": "SOLUSDT", "timeframe": "4h"},
    ]
    results = await client.batch_run(symbols)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_client_singleton():
    """get_capture_client should return the same instance."""
    from capture_client import get_capture_client
    import capture_client as mod

    mod._capture_client = None  # Reset singleton

    c1 = get_capture_client()
    c2 = get_capture_client()
    assert c1 is c2

    mod._capture_client = None  # Cleanup


# ═══════════════════════════════════════════════════════════════
# DaemonLifecycleManager — UNIT TESTS
# ═══════════════════════════════════════════════════════════════


def test_lifecycle_manager_initial_state():
    """Manager should start with no process and not stopping."""
    from capture_daemon import DaemonLifecycleManager

    mgr = DaemonLifecycleManager()
    assert mgr.is_running is False
    assert mgr._stopping is False
    assert mgr._restart_times == []


@pytest.mark.asyncio
async def test_lifecycle_restart_budget():
    """Manager should refuse restart after exhausting budget (3 per 5min)."""
    from capture_daemon import DaemonLifecycleManager

    mgr = DaemonLifecycleManager(max_restarts=3, restart_window_sec=300)

    # Simulate 3 recent restarts
    now = time.monotonic()
    mgr._restart_times = [now - 10, now - 5, now - 1]

    # The stop/start won't actually run (no process), but budget should block
    with patch.object(mgr, "stop", new_callable=AsyncMock):
        with patch.object(mgr, "start", new_callable=AsyncMock) as mock_start:
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await mgr.restart()
                # start should NOT be called — budget exhausted
                mock_start.assert_not_called()
                # verify sleep was called with 300 seconds
                mock_sleep.assert_called_once_with(300)


@pytest.mark.asyncio
async def test_lifecycle_restart_budget_window_expiry():
    """Restarts outside the window should not count toward the budget."""
    from capture_daemon import DaemonLifecycleManager

    mgr = DaemonLifecycleManager(max_restarts=3, restart_window_sec=300)

    # Simulate old restarts (>300s ago) — should be pruned
    old_time = time.monotonic() - 600
    mgr._restart_times = [old_time, old_time, old_time]

    with patch.object(mgr, "stop", new_callable=AsyncMock):
        with patch.object(mgr, "start", new_callable=AsyncMock) as mock_start:
            await mgr.restart()
            # Old restarts pruned, budget available → start should be called
            mock_start.assert_called_once()


@pytest.mark.asyncio
async def test_lifecycle_stop_no_process():
    """Stopping when no process is running should not error."""
    from capture_daemon import DaemonLifecycleManager

    mgr = DaemonLifecycleManager()
    await mgr.stop()  # Should not raise


# ═══════════════════════════════════════════════════════════════
# HookDispatcher — UNIT TESTS
# ═══════════════════════════════════════════════════════════════


def test_hook_dispatcher_register():
    """Registering hooks should parse the hook list correctly."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)

    dispatcher.register_hooks(["on_signal", "on_command", ""])
    assert dispatcher._active_hooks == ["on_signal", "on_command"]


def test_hook_dispatcher_register_with_whitespace():
    """Property 6: Parsing produces trimmed non-empty hook names."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)

    dispatcher.register_hooks(["  on_signal  ", "", "  on_command  ", "  "])
    assert dispatcher._active_hooks == ["on_signal", "on_command"]


def test_hook_cooldown_fresh_symbol():
    """A never-seen symbol should always pass cooldown check."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)
    assert dispatcher.is_cooled_down("BTCUSDT") is True


def test_hook_cooldown_enforced():
    """Property 7: Recent capture should block subsequent captures."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)
    dispatcher._cooldown_sec = 60

    # Simulate a recent capture
    dispatcher._last_capture_time["BTCUSDT"] = time.monotonic()
    assert dispatcher.is_cooled_down("BTCUSDT") is False


def test_hook_cooldown_expired():
    """After cooldown period, symbol should be allowed again."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)
    dispatcher._cooldown_sec = 1  # 1 second cooldown

    # Simulate a capture 2 seconds ago
    dispatcher._last_capture_time["BTCUSDT"] = time.monotonic() - 2
    assert dispatcher.is_cooled_down("BTCUSDT") is True


def test_hook_cooldown_per_symbol():
    """Cooldown should be enforced per-symbol, not globally."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)
    dispatcher._cooldown_sec = 60

    dispatcher._last_capture_time["BTCUSDT"] = time.monotonic()
    assert dispatcher.is_cooled_down("BTCUSDT") is False
    assert dispatcher.is_cooled_down("ETHUSDT") is True  # Different symbol


@pytest.mark.asyncio
async def test_hook_on_signal_dispatches_capture():
    """Property 5: on_signal should dispatch capture with event.symbol."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)

    # Patch bus to avoid emitting to real bus
    with patch("capture_hooks.bus") as mock_bus:
        mock_bus.emit_background = AsyncMock()

        event = SignalValidated(
            signal_id=1,
            symbol="BTCUSDT",
            action="buy",
            price=68000.0,
            quote_qty=50.0,
        )
        await dispatcher.on_signal(event)

    client.capture_screenshot.assert_called_once_with(symbol="BTCUSDT", timeframe="D")


@pytest.mark.asyncio
async def test_hook_on_signal_respects_cooldown():
    """on_signal should skip capture when cooldown is active."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)
    dispatcher._cooldown_sec = 60

    # Simulate recent capture
    dispatcher._last_capture_time["BTCUSDT"] = time.monotonic()

    event = SignalValidated(signal_id=1, symbol="BTCUSDT", action="buy")
    await dispatcher.on_signal(event)

    client.capture_screenshot.assert_not_called()


@pytest.mark.asyncio
async def test_hook_on_signal_empty_symbol_skipped():
    """on_signal should skip if symbol is empty."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)

    event = SignalValidated(signal_id=1, symbol="", action="buy")
    await dispatcher.on_signal(event)

    client.capture_screenshot.assert_not_called()


@pytest.mark.asyncio
async def test_hook_on_command_bypasses_cooldown():
    """on_command should capture even if cooldown is active."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)
    dispatcher._cooldown_sec = 60
    dispatcher._last_capture_time["BTCUSDT"] = time.monotonic()

    with patch("capture_hooks.bus") as mock_bus:
        mock_bus.emit_background = AsyncMock()
        result = await dispatcher.on_command("BTCUSDT")

    assert result is not None
    assert result.success is True
    client.capture_screenshot.assert_called_once()


@pytest.mark.asyncio
async def test_hook_on_signal_emits_capture_triggered():
    """on_signal should emit CaptureTriggered event to the bus."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)

    emitted = []
    with patch("capture_hooks.bus") as mock_bus:
        mock_bus.emit_background = AsyncMock(side_effect=lambda e: emitted.append(e))

        event = SignalValidated(signal_id=42, symbol="ETHUSDT", action="buy")
        await dispatcher.on_signal(event)

    assert len(emitted) == 1
    assert isinstance(emitted[0], CaptureTriggered)
    assert emitted[0].symbol == "ETHUSDT"
    assert emitted[0].trigger == "signal"
    assert emitted[0].source_event_id == event.event_id


# ═══════════════════════════════════════════════════════════════
# INTEGRATION: EventBus → HookDispatcher wiring
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_eventbus_wiring_on_signal():
    """Subscribing on_signal hook to EventBus should fire on SignalValidated."""
    from capture_hooks import HookDispatcher

    client = _make_mock_capture_client()
    dispatcher = HookDispatcher(client)

    test_bus = EventBus()

    # Manually subscribe to simulate register_hooks behavior
    test_bus.subscribe(SignalValidated, dispatcher._on_signal_handler)

    with patch("capture_hooks.bus") as mock_bus:
        mock_bus.emit_background = AsyncMock()

        await test_bus.emit(
            SignalValidated(
                signal_id=1,
                symbol="SOLUSDT",
                action="buy",
                price=100.0,
            )
        )

    client.capture_screenshot.assert_called_once_with(symbol="SOLUSDT", timeframe="D")
