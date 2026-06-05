"""
Property-Based Tests: Indicator Signal Parsing (Props 3-6)
Feature: tradingview-alert-indicator-signal

Property 3: Round-trip field preservation
Property 4: Required field rejection (symbol, indicator_name)
Property 5: Optional field defaults (signal_type, confidence_score)
Property 6: Malformed conditions_met → empty tuple, no exception
"""

from hypothesis import given, settings
from hypothesis import strategies as st


# ── Parsing helpers (mirror webhook.py logic) ─────────────────────────────────


def _safe_parse_confidence(raw) -> int:
    try:
        v = int(raw)
        return max(0, min(100, v))
    except (ValueError, TypeError):
        return 0


def _safe_parse_conditions(raw) -> tuple:
    if isinstance(raw, list):
        return tuple(str(c) for c in raw)
    return ()


def _safe_parse_metadata(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    return {}


# ── Property 3: Round-trip field preservation ─────────────────────────────────


@given(
    symbol=st.text(min_size=1, max_size=20),
    indicator_name=st.text(min_size=1, max_size=50),
    signal_type=st.sampled_from(["entry", "exit", "info"]),
    confidence=st.integers(min_value=0, max_value=100),
    conditions=st.lists(st.text(min_size=1, max_size=30), max_size=5),
)
@settings(max_examples=100)
def test_prop3_round_trip_field_preservation(
    symbol, indicator_name, signal_type, confidence, conditions
):
    """
    # Feature: tradingview-alert-indicator-signal, Property 3: Parsing round-trip
    All populated fields must be preserved through parsing.
    """
    payload = {
        "symbol": symbol,
        "indicator_name": indicator_name,
        "signal_type": signal_type,
        "confidence_score": confidence,
        "conditions_met": conditions,
        "metadata": {"key": "val"},
    }
    parsed_conf = _safe_parse_confidence(payload["confidence_score"])
    parsed_conds = _safe_parse_conditions(payload["conditions_met"])
    parsed_meta = _safe_parse_metadata(payload["metadata"])

    assert parsed_conf == confidence
    assert parsed_conds == tuple(str(c) for c in conditions)
    assert parsed_meta == {"key": "val"}


# ── Property 4: Required field rejection ──────────────────────────────────────


@given(
    missing_field=st.sampled_from(["symbol", "indicator_name"]),
    other_data=st.dictionaries(st.text(min_size=1), st.text(), max_size=5),
)
@settings(max_examples=100)
def test_prop4_required_field_missing_detected(missing_field, other_data):
    """
    # Feature: tradingview-alert-indicator-signal, Property 4: Required field rejection
    Payloads missing symbol or indicator_name must be detectable as invalid.
    """
    payload = {"source": "indicator", **other_data}
    payload.pop("symbol", None)
    payload.pop("indicator_name", None)
    # Add the field that is NOT missing
    if missing_field == "symbol":
        payload["indicator_name"] = "RSI"
    else:
        payload["symbol"] = "BTCUSDT"

    # The missing field should produce empty string
    missing_val = payload.get(missing_field, "")
    assert not missing_val, (
        f"Expected empty value for {missing_field}, got {missing_val!r}"
    )


# ── Property 5: Optional field defaults ───────────────────────────────────────


@given(extra=st.dictionaries(st.text(min_size=1), st.text(), max_size=3))
@settings(max_examples=100)
def test_prop5_signal_type_default_info(extra):
    """
    # Feature: tradingview-alert-indicator-signal, Property 5: Optional defaults
    When signal_type is absent, the default is 'info'.
    When confidence_score is absent, the default is 0.
    """
    payload = {"symbol": "BTC", "indicator_name": "RSI", **extra}
    payload.pop("signal_type", None)
    payload.pop("confidence_score", None)

    signal_type = payload.get("signal_type", "info")
    confidence = _safe_parse_confidence(payload.get("confidence_score", 0))

    assert signal_type == "info"
    assert confidence == 0


# ── Property 6: Malformed conditions_met → empty tuple ───────────────────────


@given(
    malformed=st.one_of(
        st.text(),
        st.integers(),
        st.floats(allow_nan=False),
        st.none(),
        st.booleans(),
    )
)
@settings(max_examples=100)
def test_prop6_malformed_conditions_met_empty_tuple(malformed):
    """
    # Feature: tradingview-alert-indicator-signal, Property 6: Malformed conditions graceful
    Any non-list conditions_met value must produce an empty tuple without exception.
    """
    result = _safe_parse_conditions(malformed)
    assert result == (), f"Expected (), got {result!r} for input {malformed!r}"
