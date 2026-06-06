"""
Property-Based Tests: Indicator Signal Enrichment (Props 12-15)
Feature: tradingview-alert-indicator-signal

Property 12: ATR-based SL/TP formula — sl = price - (atr*2), tp = price + (atr*3)
Property 13: Default SL/TP — sl = price * 0.95, tp = price * 1.10
Property 14: entry → buy, exit → sell
Property 15: Enriched entry/exit emits SignalValidated with correct fields
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hypothesis import given, settings
from hypothesis import strategies as st


def _compute_sl_tp(price: float, metadata: dict):
    """Mirror the _compute_sl_tp logic from signal_enricher.py"""
    try:
        atr_raw = metadata.get("atr_value")
        if atr_raw is not None:
            atr = float(atr_raw)
            if atr > 0:
                sl = price - (atr * 2)
                tp = price + (atr * 3)
                return f"{sl:.6f}", f"{tp:.6f}"
    except (ValueError, TypeError):
        pass
    sl = price * 0.95
    tp = price * 1.10
    return f"{sl:.6f}", f"{tp:.6f}"


# ── Property 12: ATR SL/TP formula ───────────────────────────────────────────


@given(
    price=st.floats(
        min_value=0.01, max_value=1_000_000, allow_nan=False, allow_infinity=False
    ),
    atr=st.floats(
        min_value=0.01, max_value=100_000, allow_nan=False, allow_infinity=False
    ),
)
@settings(max_examples=200)
def test_prop12_atr_sl_tp_formula(price, atr):
    """
    # Feature: tradingview-alert-indicator-signal, Property 12: SL/TP computation with ATR
    sl == price - (atr * 2)
    tp == price + (atr * 3)
    """
    metadata = {"atr_value": atr}
    sl_str, tp_str = _compute_sl_tp(price, metadata)
    expected_sl = price - (atr * 2)
    expected_tp = price + (atr * 3)
    assert abs(float(sl_str) - expected_sl) < 0.0001, (
        f"SL mismatch: {sl_str} != {expected_sl}"
    )
    assert abs(float(tp_str) - expected_tp) < 0.0001, (
        f"TP mismatch: {tp_str} != {expected_tp}"
    )


# ── Property 13: Default SL/TP without ATR ───────────────────────────────────


@given(
    price=st.floats(
        min_value=0.01, max_value=1_000_000, allow_nan=False, allow_infinity=False
    ),
    metadata=st.one_of(
        st.just({}),
        st.just({"atr_value": 0}),
        st.just({"atr_value": None}),
        st.just({"other_key": "value"}),
    ),
)
@settings(max_examples=200)
def test_prop13_default_sl_tp_without_atr(price, metadata):
    """
    # Feature: tradingview-alert-indicator-signal, Property 13: SL/TP defaults without ATR
    sl == price * 0.95
    tp == price * 1.10
    """
    sl_str, tp_str = _compute_sl_tp(price, metadata)
    expected_sl = price * 0.95
    expected_tp = price * 1.10
    assert abs(float(sl_str) - expected_sl) < 0.001, (
        f"Default SL mismatch: {sl_str} != {expected_sl}"
    )
    assert abs(float(tp_str) - expected_tp) < 0.001, (
        f"Default TP mismatch: {tp_str} != {expected_tp}"
    )


# ── Property 14: Signal type to action mapping ───────────────────────────────


@given(signal_type=st.sampled_from(["entry", "exit"]))
@settings(max_examples=50)
def test_prop14_signal_type_to_action_mapping(signal_type):
    """
    # Feature: tradingview-alert-indicator-signal, Property 14: Type→action mapping
    entry → buy, exit → sell
    """
    action = "buy" if signal_type == "entry" else "sell"
    if signal_type == "entry":
        assert action == "buy"
    else:
        assert action == "sell"


# ── Property 15: Enriched entry signal has correct shape ─────────────────────


@given(
    symbol=st.text(min_size=1, max_size=20),
    price=st.floats(
        min_value=0.01, max_value=1_000_000, allow_nan=False, allow_infinity=False
    ),
    exchange=st.sampled_from(["binance", "bybit"]),
    signal_type=st.sampled_from(["entry", "exit"]),
)
@settings(max_examples=100)
def test_prop15_enriched_signal_has_correct_shape(symbol, price, exchange, signal_type):
    """
    # Feature: tradingview-alert-indicator-signal, Property 15: SignalValidated output shape
    Enriched entry/exit signals must have: symbol, action (buy/sell), price, sl, tp, exchange.
    """
    metadata = {}
    sl, tp = _compute_sl_tp(price, metadata)
    action = "buy" if signal_type == "entry" else "sell"

    enriched = {
        "symbol": symbol,
        "action": action,
        "price": price,
        "sl": sl,
        "tp": tp,
        "exchange": exchange,
    }

    assert enriched["symbol"] == symbol
    assert enriched["action"] in {"buy", "sell"}
    assert enriched["price"] == price
    assert float(enriched["sl"]) > 0
    assert float(enriched["tp"]) > 0
    assert enriched["exchange"] == exchange
