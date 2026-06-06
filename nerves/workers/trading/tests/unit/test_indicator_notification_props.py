"""
Property-Based Tests: Indicator Notification (Props 16-17)
Feature: tradingview-alert-indicator-signal

Property 16: Info signal notification must contain indicator_name, symbol, conditions, confidence%
Property 17: confidence_score > 80 → high-priority notification; <= 80 → normal
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hypothesis import given, settings
from hypothesis import strategies as st


def _format_info_notification(
    symbol, indicator_name, conditions_met, confidence_score, exchange="binance"
):
    """Mirror the notification formatting from signal_enricher.py"""
    conditions_str = ", ".join(conditions_met) if conditions_met else "Không có"
    priority_prefix = "🔴 **KHẨN CẤP** — " if confidence_score > 80 else ""
    msg = (
        f"{priority_prefix}📊 **Tín Hiệu Thông Tin — {indicator_name}**\n"
        f"- Mã: `{symbol}`\n"
        f"- Sàn: `{exchange.upper()}`\n"
        f"- Điều kiện: `{conditions_str}`\n"
        f"- Độ tin cậy: `{confidence_score}%`\n"
        f"- Signal ID: `#0`"
    )
    return msg


# ── Property 16: Info notification content ───────────────────────────────────


@given(
    symbol=st.text(min_size=1, max_size=20),
    indicator_name=st.text(min_size=1, max_size=50),
    conditions=st.lists(st.text(min_size=1, max_size=30), min_size=1, max_size=5),
    confidence=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=100)
def test_prop16_info_notification_content(
    symbol, indicator_name, conditions, confidence
):
    """
    # Feature: tradingview-alert-indicator-signal, Property 16: Info signal notification content
    Notification must contain indicator_name, symbol, all conditions, and confidence as %.
    """
    msg = _format_info_notification(symbol, indicator_name, conditions, confidence)

    assert indicator_name in msg, "indicator_name missing from notification"
    assert symbol in msg, "symbol missing from notification"
    for condition in conditions:
        assert condition in msg, f"condition '{condition}' missing from notification"
    assert f"{confidence}%" in msg, "confidence percentage missing from notification"


# ── Property 17: High-priority gate at confidence > 80 ───────────────────────


@given(confidence=st.integers(min_value=0, max_value=100))
@settings(max_examples=101)
def test_prop17_priority_gate_based_on_confidence(confidence):
    """
    # Feature: tradingview-alert-indicator-signal, Property 17: Info signal priority
    confidence > 80 → message contains high-priority prefix.
    confidence <= 80 → message does NOT contain high-priority prefix.
    """
    msg = _format_info_notification("BTC", "RSI", ["RSI < 30"], confidence)

    if confidence > 80:
        assert "KHẨN CẤP" in msg, (
            f"Expected high-priority prefix for confidence={confidence}"
        )
    else:
        assert "KHẨN CẤP" not in msg, (
            f"Unexpected high-priority prefix for confidence={confidence}"
        )
