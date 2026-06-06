"""
Tests for trail_atr_mul values in symbol_config.py.

Verifies that the Chandelier trailing stop multiplier is:
  - Present in all registered symbols
  - Always strictly greater than the initial ATR SL multiplier (trail is wider)
  - Correctly scaled between BTC, ETH, and SOL
"""

from symbol_config import SYMBOL_PARAMS, get_symbol_config


def test_trail_atr_mul_present_in_all_symbols():
    """Every registered symbol must have a 'trail_atr_mul' key."""
    for symbol, params in SYMBOL_PARAMS.items():
        assert "trail_atr_mul" in params, (
            f"{symbol} is missing 'trail_atr_mul' — "
            "required for Chandelier trailing stop reference"
        )
        assert params["trail_atr_mul"] > 0, (
            f"{symbol} trail_atr_mul must be positive, got {params['trail_atr_mul']}"
        )


def test_trail_atr_mul_wider_than_initial_sl():
    """Chandelier trail multiplier must be strictly wider than the initial ATR SL multiplier.

    Rationale: The trailing stop is placed further away from entry than the initial stop.
    As the trade moves in our favour, the trail tightens toward the initial SL level.
    If trail_atr_mul <= atr_sl_mul, the trailing stop would never be triggered first.
    """
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        cfg = get_symbol_config(symbol)
        assert cfg["trail_atr_mul"] > cfg["atr_sl_mul"], (
            f"{symbol}: trail_atr_mul ({cfg['trail_atr_mul']}) must be > "
            f"atr_sl_mul ({cfg['atr_sl_mul']})"
        )


def test_trail_atr_mul_scales_with_beta():
    """Higher-beta assets must have larger trail multipliers (more room to breathe)."""
    btc = get_symbol_config("BTCUSDT")["trail_atr_mul"]
    eth = get_symbol_config("ETHUSDT")["trail_atr_mul"]
    sol = get_symbol_config("SOLUSDT")["trail_atr_mul"]

    assert eth > btc, f"ETH trail ({eth}) must be > BTC trail ({btc}) (Beta 1.25 > 1.0)"
    assert sol > eth, f"SOL trail ({sol}) must be > ETH trail ({eth}) (Beta 1.6 > 1.25)"
