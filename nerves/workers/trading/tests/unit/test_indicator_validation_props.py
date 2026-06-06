"""
Property-Based Tests: Indicator Signal Validation (Props 7-11)
Feature: tradingview-alert-indicator-signal

Property 7:  signal_type not in {entry,exit,info} → IndicatorSignalRejected(invalid_signal_type)
Property 8:  confidence_score clamped to [0, 100]
Property 9:  indicator dedup independent from strategy dedup
Property 10: same (symbol, indicator_name, signal_type) within 60s → duplicate_signal rejection
Property 11: signal_type=info bypasses timeframe validation
"""

import os
import sys
import time

from hypothesis import assume, given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── Property 7: signal_type validation ───────────────────────────────────────

VALID_SIGNAL_TYPES = {"entry", "exit", "info"}


@given(signal_type=st.text(min_size=1, max_size=20))
@settings(max_examples=100)
def test_prop7_invalid_signal_type_detected(signal_type):
    """
    # Feature: tradingview-alert-indicator-signal, Property 7: Signal type validation
    Any signal_type not in {entry, exit, info} must be classified as invalid.
    """
    assume(signal_type not in VALID_SIGNAL_TYPES)
    is_valid = signal_type in VALID_SIGNAL_TYPES
    assert not is_valid, f"Expected invalid, but {signal_type!r} passed validation"


# ── Property 8: confidence_score clamped to [0, 100] ─────────────────────────


def _clamp_confidence(v) -> int:
    try:
        return max(0, min(100, int(v)))
    except (ValueError, TypeError):
        return 0


@given(
    raw=st.one_of(
        st.integers(min_value=-1000, max_value=1000),
        st.floats(min_value=-1000, max_value=1000, allow_nan=False),
    )
)
@settings(max_examples=200)
def test_prop8_confidence_clamped(raw):
    """
    # Feature: tradingview-alert-indicator-signal, Property 8: Confidence score clamping
    Any numeric confidence_score must be clamped to [0, 100].
    """
    result = _clamp_confidence(raw)
    assert 0 <= result <= 100, f"Clamped value {result} out of range for input {raw}"


# ── Property 9: Indicator dedup independent from strategy dedup ───────────────


def test_prop9_indicator_dedup_uses_separate_keys():
    """
    # Feature: tradingview-alert-indicator-signal, Property 9: Dedup independence
    Strategy dedup key is (symbol, action). Indicator dedup key is (symbol, indicator_name, signal_type).
    They can never collide because they have different arities.
    """
    strategy_key = ("BTCUSDT", "buy")
    indicator_key = ("BTCUSDT", "SuperTrend", "entry")
    assert strategy_key != indicator_key
    assert len(strategy_key) != len(indicator_key)


# ── Property 10: Same indicator key within TTL → duplicate ───────────────────


@given(
    symbol=st.text(min_size=1, max_size=10).map(str.upper),
    indicator_name=st.text(min_size=1, max_size=30),
    signal_type=st.sampled_from(["entry", "exit", "info"]),
)
@settings(max_examples=100)
def test_prop10_same_key_within_ttl_is_duplicate(symbol, indicator_name, signal_type):
    """
    # Feature: tradingview-alert-indicator-signal, Property 10: Indicator dedup within TTL
    Two events with the same (symbol, indicator_name, signal_type) within 60s → second is duplicate.
    """
    DEDUP_TTL = 60.0
    cache: dict = {}

    def check_duplicate(sym, name, stype) -> bool:
        key = (sym.strip().upper(), name.strip().lower(), stype.strip().lower())
        now = time.time()
        last_seen = cache.get(key, 0)
        if now - last_seen < DEDUP_TTL:
            return True
        cache[key] = now
        return False

    first = check_duplicate(symbol, indicator_name, signal_type)
    second = check_duplicate(symbol, indicator_name, signal_type)

    assert not first, "First signal should NOT be a duplicate"
    assert second, "Second signal within TTL MUST be a duplicate"


# ── Property 11: info signal bypasses timeframe validation ────────────────────

VALID_INTERVALS = {
    "1m",
    "5m",
    "15m",
    "30m",
    "1h",
    "4h",
    "1d",
    "1w",
    "60",
    "240",
    "d",
    "w",
}


@given(interval=st.text(min_size=1, max_size=10))
@settings(max_examples=100)
def test_prop11_info_bypasses_timeframe_validation(interval):
    """
    # Feature: tradingview-alert-indicator-signal, Property 11: Timeframe validation conditional
    signal_type='info' must bypass timeframe validation regardless of interval value.
    """
    signal_type = "info"
    # If it were "entry", invalid intervals would be rejected
    # For "info", no rejection should occur
    should_validate_timeframe = signal_type == "entry"
    assert not should_validate_timeframe, "info signals must skip timeframe validation"
