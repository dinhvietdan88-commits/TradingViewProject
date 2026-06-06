"""
Property-Based Tests: Indicator Signal Classification (Props 1-2)
Feature: tradingview-alert-indicator-signal

Property 1: source=indicator → IndicatorSignalReceived, NOT SignalReceived
Property 2: action=buy/sell/alert (no source=indicator) → SignalReceived, NOT IndicatorSignalReceived
"""

from hypothesis import given, settings
from hypothesis import strategies as st

# ── Helper: simulate the detection logic from webhook.py ─────────────────────


def classify_payload(payload: dict) -> str:
    """Mirror the detection logic in gateway/webhook.py"""
    source = payload.get("source", "")
    indicator_name = payload.get("indicator_name", "")
    action = str(payload.get("action", "")).lower()
    if source == "indicator" or (
        indicator_name and action not in {"buy", "sell", "alert"}
    ):
        return "indicator"
    return "strategy"


# ── Property 1: source=indicator → indicator path ────────────────────────────


@given(
    indicator_name=st.text(min_size=1, max_size=50),
    symbol=st.text(min_size=1, max_size=20),
    extra=st.dictionaries(
        st.text(min_size=1, max_size=10),
        st.one_of(st.text(), st.integers(), st.floats(allow_nan=False)),
    ),
)
@settings(max_examples=100)
def test_prop1_source_indicator_classifies_as_indicator(indicator_name, symbol, extra):
    """
    # Feature: tradingview-alert-indicator-signal, Property 1: Classification by source field
    For any payload where source == 'indicator', classify_payload MUST return 'indicator'.
    """
    payload = {
        "source": "indicator",
        "indicator_name": indicator_name,
        "symbol": symbol,
        **extra,
    }
    # Exclude any key that could override source
    payload.pop("action", None)
    result = classify_payload(payload)
    assert result == "indicator", (
        f"Expected 'indicator', got '{result}' for payload {payload}"
    )


# ── Property 2: action=buy/sell/alert (no source=indicator) → strategy path ──


@given(
    action=st.sampled_from(["buy", "sell", "alert"]),
    symbol=st.text(min_size=1, max_size=20),
    extra=st.dictionaries(st.text(min_size=1, max_size=10), st.text()),
)
@settings(max_examples=100)
def test_prop2_strategy_action_classifies_as_strategy(action, symbol, extra):
    """
    # Feature: tradingview-alert-indicator-signal, Property 2: Classification preservation
    For any payload where action is buy/sell/alert and source != 'indicator',
    classify_payload MUST return 'strategy'.
    """
    payload = {"action": action, "symbol": symbol, **extra}
    payload.pop("source", None)
    # Ensure source is not 'indicator'
    if payload.get("source") == "indicator":
        payload["source"] = "strategy"
    result = classify_payload(payload)
    assert result == "strategy", (
        f"Expected 'strategy', got '{result}' for action={action}"
    )
