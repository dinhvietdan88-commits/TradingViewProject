import pytest
from gateway.webhook import (
    _matches_id_range,
    _matches_symbol_filter,
    _matches_source_filter,
    _matches_sync_filters,
)


def test_matches_id_range():
    # Test valid numeric values
    assert _matches_id_range({"start_id": 10, "end_id": 20}, 15) is True
    assert _matches_id_range({"start_id": "10", "end_id": "20"}, 15) is True
    assert _matches_id_range({"start_id": 10, "end_id": 20}, 9) is False
    assert _matches_id_range({"start_id": 10, "end_id": 20}, 21) is False

    # Test empty or missing values
    assert _matches_id_range({}, 15) is True
    assert _matches_id_range({"start_id": "", "end_id": " "}, 15) is True
    assert _matches_id_range({"start_id": None, "end_id": None}, 15) is True

    # Test partially set range
    assert _matches_id_range({"start_id": 10}, 15) is True
    assert _matches_id_range({"start_id": 10}, 9) is False
    assert _matches_id_range({"end_id": 20}, 15) is True
    assert _matches_id_range({"end_id": 20}, 21) is False

    # Test invalid values that might raise ValueError
    with pytest.raises(ValueError):
        _matches_id_range({"start_id": "abc"}, 15)


def test_matches_symbol_filter():
    # Normal usage
    assert _matches_symbol_filter({"symbols": "BTCUSDT,ETHUSDT"}, "BTCUSDT") is True
    assert _matches_symbol_filter({"symbols": "BTCUSDT, ETHUSDT"}, "btc_usdt") is False
    assert _matches_symbol_filter({"symbols": "BTCUSDT, ETHUSDT"}, "ethusdt") is True
    assert _matches_symbol_filter({"symbols": "BTCUSDT, ETHUSDT"}, "SOLUSDT") is False

    # Empty or missing
    assert _matches_symbol_filter({}, "BTCUSDT") is True
    assert _matches_symbol_filter({"symbols": ""}, "BTCUSDT") is True
    assert _matches_symbol_filter({"symbols": "  "}, "BTCUSDT") is True

    # Vulnerability: symbols is None
    with pytest.raises(AttributeError):
        _matches_symbol_filter({"symbols": None}, "BTCUSDT")


def test_matches_source_filter():
    # Normal usage
    assert (
        _matches_source_filter({"sources": "webhook,indicator"}, {"source": "webhook"})
        is True
    )
    assert (
        _matches_source_filter(
            {"sources": "webhook, indicator"}, {"source": "INDICATOR"}
        )
        is True
    )
    assert (
        _matches_source_filter({"sources": "webhook"}, {"source": "indicator"}) is False
    )

    # Empty or missing
    assert _matches_source_filter({}, {"source": "webhook"}) is True
    assert _matches_source_filter({"sources": ""}, {"source": "webhook"}) is True
    assert _matches_source_filter({"sources": "  "}, {"source": "webhook"}) is True
    assert _matches_source_filter({"sources": "webhook"}, None) is False

    # Vulnerability: sources is None
    with pytest.raises(AttributeError):
        _matches_source_filter({"sources": None}, {"source": "webhook"})


def test_matches_sync_filters():
    settings = {
        "start_id": 10,
        "end_id": 20,
        "symbols": "BTCUSDT",
        "sources": "webhook",
    }

    # Match all
    assert _matches_sync_filters(settings, 15, "BTCUSDT", {"source": "webhook"}) is True

    # Mismatches
    assert _matches_sync_filters(settings, 9, "BTCUSDT", {"source": "webhook"}) is False
    assert (
        _matches_sync_filters(settings, 15, "ETHUSDT", {"source": "webhook"}) is False
    )
    assert (
        _matches_sync_filters(settings, 15, "BTCUSDT", {"source": "indicator"}) is False
    )
