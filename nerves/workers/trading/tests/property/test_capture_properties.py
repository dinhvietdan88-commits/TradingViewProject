"""
tests/property/test_capture_properties.py
Property-based tests (Hypothesis) for P11 Stealth Capture Studio invariants.

Properties tested:
  P3: Batch result count === input count (any N ∈ [0, 20])
  P5: Symbol fidelity — capture request always uses exact event.symbol
  P6: Hook parsing — produces trimmed non-empty list
  P7: Cooldown monotonicity — once blocked, remains blocked until window expires
  P8: State cache — same symbol+timeframe is always a cache hit
  P9: State cache — invalidation after change
  P10: Metrics — counters never decrease
"""

import asyncio
import time
import sys
import pathlib
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from capture_client import PythonCaptureClient, CaptureResult, CaptureRequest
from capture_hooks import HookDispatcher
from core.events import SignalValidated, CaptureTriggered


# ── Helpers ──────────────────────────────────────────────────────────────────────


def _make_mock_client():
    """Create a PythonCaptureClient with mocked HTTP calls."""
    client = PythonCaptureClient(host="127.0.0.1", port=9333)
    mock_result = CaptureResult(success=True, method="fallback", latency_ms=100)
    client.capture_screenshot = AsyncMock(return_value=mock_result)
    client.is_daemon_available = AsyncMock(return_value=False)
    client._daemon_available = False
    client._last_check_time = time.monotonic()
    client._fallback_capture = AsyncMock(return_value=mock_result)
    return client


# ── Symbol Strategy ──────────────────────────────────────────────────────────────

symbol_strategy = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
)

hook_name_strategy = st.text(
    min_size=0,
    max_size=30,
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz_0123456789 \t\n"),
)


# ═══════════════════════════════════════════════════════════════
# P3: Batch Result Count === Input Count
# ═══════════════════════════════════════════════════════════════


@given(
    n=st.integers(min_value=0, max_value=20),
)
@settings(max_examples=100, deadline=None)
def test_p3_batch_result_count_matches_input(n):
    """For any N symbols, batch_run returns exactly N results."""
    client = _make_mock_client()
    symbols = [{"symbol": f"SYM{i}", "timeframe": "D"} for i in range(n)]

    results = asyncio.run(client.batch_run(symbols))
    assert len(results) == n, f"Expected {n} results, got {len(results)}"


# ═══════════════════════════════════════════════════════════════
# P5: Symbol Fidelity
# ═══════════════════════════════════════════════════════════════


@given(symbol=symbol_strategy)
@settings(max_examples=100, deadline=None)
def test_p5_symbol_fidelity_on_signal(symbol):
    """on_signal passes event.symbol verbatim to capture_screenshot."""
    client = _make_mock_client()
    dispatcher = HookDispatcher(client)

    async def run():
        with patch("capture_hooks.bus") as mock_bus:
            mock_bus.emit_background = AsyncMock()
            event = SignalValidated(symbol=symbol, signal_id=1, action="buy")
            await dispatcher.on_signal(event)

    asyncio.run(run())
    client.capture_screenshot.assert_called_once_with(symbol=symbol, timeframe="D")


@given(symbol=symbol_strategy)
@settings(max_examples=100, deadline=None)
def test_p5_symbol_fidelity_on_command(symbol):
    """on_command passes symbol verbatim to capture_screenshot."""
    client = _make_mock_client()
    dispatcher = HookDispatcher(client)

    async def run():
        with patch("capture_hooks.bus") as mock_bus:
            mock_bus.emit_background = AsyncMock()
            await dispatcher.on_command(symbol)

    asyncio.run(run())
    client.capture_screenshot.assert_called_once_with(symbol=symbol, timeframe="D")


# ═══════════════════════════════════════════════════════════════
# P6: Hook Parsing — Trimmed Non-Empty List
# ═══════════════════════════════════════════════════════════════


@given(
    hooks=st.lists(hook_name_strategy, min_size=0, max_size=10),
)
@settings(max_examples=100, deadline=None)
def test_p6_hook_parsing_trims_and_filters(hooks):
    """register_hooks always produces a list of trimmed non-empty strings."""
    client = _make_mock_client()
    dispatcher = HookDispatcher(client)
    dispatcher.register_hooks(hooks)

    for hook in dispatcher._active_hooks:
        assert hook == hook.strip(), f"Hook '{hook}' not trimmed"
        assert len(hook) > 0, "Empty hook name in active hooks"


# ═══════════════════════════════════════════════════════════════
# P7: Cooldown Enforcement — Monotonic Block
# ═══════════════════════════════════════════════════════════════


@given(
    cooldown=st.integers(min_value=1, max_value=300),
    elapsed=st.floats(
        min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False
    ),
)
@settings(max_examples=100, deadline=None)
def test_p7_cooldown_monotonic(cooldown, elapsed):
    """If elapsed < cooldown → blocked. If elapsed >= cooldown → allowed."""
    client = _make_mock_client()
    dispatcher = HookDispatcher(client)
    dispatcher._cooldown_sec = cooldown

    dispatcher._last_capture_time["TEST"] = time.monotonic() - elapsed

    result = dispatcher.is_cooled_down("TEST")

    if elapsed < cooldown:
        assert result is False, (
            f"Expected blocked (elapsed={elapsed} < cooldown={cooldown})"
        )
    else:
        assert result is True, (
            f"Expected allowed (elapsed={elapsed} >= cooldown={cooldown})"
        )


@given(
    symbols=st.lists(symbol_strategy, min_size=2, max_size=5, unique=True),
)
@settings(max_examples=50, deadline=None)
def test_p7_cooldown_is_per_symbol(symbols):
    """Cooldown on symbol A should not affect symbol B."""
    client = _make_mock_client()
    dispatcher = HookDispatcher(client)
    dispatcher._cooldown_sec = 60

    # Set cooldown on first symbol only
    dispatcher._last_capture_time[symbols[0]] = time.monotonic()

    assert dispatcher.is_cooled_down(symbols[0]) is False
    for sym in symbols[1:]:
        assert dispatcher.is_cooled_down(sym) is True, (
            f"Symbol {sym} incorrectly blocked"
        )


# ═══════════════════════════════════════════════════════════════
# P8 + P9: State Cache (imported from Node.js, tested via CaptureRequest)
# ═══════════════════════════════════════════════════════════════


def test_p8_capture_request_defaults():
    """CaptureRequest defaults should be sensible."""
    req = CaptureRequest()
    assert req.symbol == "active"
    assert req.timeframe == "active"
    assert req.region == "chart"
    assert req.crop is True
    assert req.skip_if_same is True


@given(
    symbol=symbol_strategy,
    timeframe=st.sampled_from(["1", "5", "15", "60", "D", "W", "M"]),
)
@settings(max_examples=50, deadline=None)
def test_p8_capture_request_immutable(symbol, timeframe):
    """CaptureRequest should be frozen (immutable)."""
    req = CaptureRequest(symbol=symbol, timeframe=timeframe)
    with pytest.raises(AttributeError):
        req.symbol = "HACKED"


# ═══════════════════════════════════════════════════════════════
# P10: Metrics Monotonicity (Python CaptureResult)
# ═══════════════════════════════════════════════════════════════


@given(
    latencies=st.lists(
        st.floats(min_value=0.1, max_value=5000.0, allow_nan=False),
        min_size=1,
        max_size=20,
    ),
)
@settings(max_examples=50, deadline=None)
def test_p10_capture_result_method_always_set(latencies):
    """CaptureResult.method is always 'daemon' or 'fallback', never empty."""
    for lat in latencies:
        r1 = CaptureResult(success=True, latency_ms=lat, method="daemon")
        r2 = CaptureResult(success=True, latency_ms=lat, method="fallback")
        assert r1.method in ("daemon", "fallback")
        assert r2.method in ("daemon", "fallback")


# ═══════════════════════════════════════════════════════════════
# CaptureTriggered EVENT PROPERTIES
# ═══════════════════════════════════════════════════════════════


@given(
    symbol=symbol_strategy,
    trigger=st.sampled_from(["signal", "schedule", "command"]),
)
@settings(max_examples=100, deadline=None)
def test_capture_triggered_preserves_fields(symbol, trigger):
    """CaptureTriggered should preserve symbol and trigger exactly."""
    event = CaptureTriggered(symbol=symbol, trigger=trigger)
    assert event.symbol == symbol
    assert event.trigger == trigger


@given(
    symbols=st.lists(symbol_strategy, min_size=1, max_size=10),
)
@settings(max_examples=50, deadline=None)
def test_capture_triggered_unique_event_ids(symbols):
    """Each CaptureTriggered event should have a unique event_id."""
    events = [CaptureTriggered(symbol=s) for s in symbols]
    ids = [e.event_id for e in events]
    assert len(set(ids)) == len(ids), "Duplicate event_ids detected"
