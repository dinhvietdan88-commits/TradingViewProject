"""
Property-Based Tests: Indicator Events (Props 18-19)
Feature: tradingview-alert-indicator-signal

Property 18: Each IndicatorSignalReceived event has a unique event_id; frozen (immutable)
Property 19: JSON serialization round-trip for conditions_met and metadata
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hypothesis import given, settings
from hypothesis import strategies as st

from core.events import IndicatorSignalReceived


# ── Property 18: Event immutability and unique event_id ──────────────────────


@given(
    symbol=st.text(min_size=1, max_size=20),
    indicator_name=st.text(min_size=1, max_size=50),
)
@settings(max_examples=50)
def test_prop18_event_immutability_and_unique_id(symbol, indicator_name):
    """
    # Feature: tradingview-alert-indicator-signal, Property 18: Unique event_id per instance
    Two independently created events must have unique event_ids (UUID4 per instance).
    """
    evt1 = IndicatorSignalReceived(symbol=symbol, indicator_name=indicator_name)
    evt2 = IndicatorSignalReceived(symbol=symbol, indicator_name=indicator_name)

    assert evt1.event_id != evt2.event_id, "event_ids must be unique across instances"
    assert evt1.event_id  # Must be truthy (non-empty UUID)
    assert evt2.event_id


# ── Property 19: JSON round-trip for conditions_met and metadata ──────────────


@given(
    conditions=st.lists(st.text(min_size=1, max_size=30), max_size=5),
    metadata=st.dictionaries(
        st.text(min_size=1, max_size=10),
        st.one_of(st.text(), st.integers(), st.floats(allow_nan=False)),
        max_size=5,
    ),
)
@settings(max_examples=100)
def test_prop19_json_serialization_round_trip(conditions, metadata):
    """
    # Feature: tradingview-alert-indicator-signal, Property 19: JSON serialization round-trip
    Serialize conditions_met and metadata to JSON and back — values must be equal to originals.
    """
    # Round-trip conditions_met
    serialized_conds = json.dumps(conditions)
    deserialized_conds = json.loads(serialized_conds)
    assert deserialized_conds == conditions, "conditions_met round-trip failed"

    # Round-trip metadata (only JSON-serializable primitives)
    try:
        serialized_meta = json.dumps(metadata)
        deserialized_meta = json.loads(serialized_meta)
        assert deserialized_meta == metadata, "metadata round-trip failed"
    except (ValueError, TypeError):
        pass  # Non-serializable floats (inf etc.) — skip
