"""
Tests for symbol_config.py — Per-symbol risk parameter registry.

Verifies that OPTIMIZED_PARAMETERS_MATRIX.md values are correctly implemented
and that the mode field is properly propagated through the event chain.
"""

import dataclasses

from symbol_config import get_symbol_config, DEFAULT_PARAMS


# ── Symbol Config Value Tests ─────────────────────────────────────────────────


def test_btc_config_values():
    """BTC params must exactly match OPTIMIZED_PARAMETERS_MATRIX (Beta=1.0 baseline)."""
    cfg = get_symbol_config("BTCUSDT")
    assert cfg["stop_loss_pct"] == 0.08, "BTC SL must be 8%"
    assert cfg["risk_pct"] == 0.01, "BTC ATR risk must be 1.0%"
    assert cfg["breakout_size_pct"] == 0.025, "BTC breakout size must be 2.5%"
    assert cfg["atr_sl_mul"] == 2.0, "BTC ATR SL multiplier must be 2.0x"
    assert cfg["atr_tp_mul"] == 8.0, "BTC ATR TP multiplier must be 8.0x"
    assert cfg["trail_atr_mul"] == 3.0, "BTC trail ATR multiplier must be 3.0x"


def test_eth_config_values():
    """ETH params must exactly match OPTIMIZED_PARAMETERS_MATRIX (Beta=1.25 scaled)."""
    cfg = get_symbol_config("ETHUSDT")
    assert cfg["stop_loss_pct"] == 0.10, "ETH SL must be 10% (8% * 1.25)"
    assert cfg["risk_pct"] == 0.008, "ETH ATR risk must be 0.8%"
    assert cfg["breakout_size_pct"] == 0.020, "ETH breakout size must be 2.0%"
    assert cfg["atr_sl_mul"] == 2.5, "ETH ATR SL multiplier must be 2.5x"
    assert cfg["atr_tp_mul"] == 10.0, "ETH ATR TP multiplier must be 10.0x"
    assert cfg["trail_atr_mul"] == 3.75, "ETH trail ATR multiplier must be 3.75x"


def test_sol_config_values():
    """SOL params must exactly match OPTIMIZED_PARAMETERS_MATRIX (Beta=1.6 scaled)."""
    cfg = get_symbol_config("SOLUSDT")
    assert cfg["stop_loss_pct"] == 0.13, "SOL SL must be 13% (8% * 1.625)"
    assert cfg["risk_pct"] == 0.006, "SOL ATR risk must be 0.6%"
    assert cfg["breakout_size_pct"] == 0.015, "SOL breakout size must be 1.5%"
    assert cfg["atr_sl_mul"] == 3.2, "SOL ATR SL multiplier must be 3.2x"
    assert cfg["atr_tp_mul"] == 13.0, "SOL ATR TP multiplier must be 13.0x"
    assert cfg["trail_atr_mul"] == 4.8, "SOL trail ATR multiplier must be 4.8x"


def test_unknown_symbol_fallback():
    """Unknown symbols must return BTC default params (most conservative / lowest beta)."""
    cfg = get_symbol_config("XRPUSDT")
    assert cfg == DEFAULT_PARAMS, "Unknown symbol must return BTC default params"
    assert cfg["stop_loss_pct"] == 0.08, "Fallback SL must be BTC 8%"
    assert cfg["risk_pct"] == 0.01, "Fallback risk must be BTC 1.0%"


def test_case_insensitive_lookup():
    """Symbol lookup must be case-insensitive."""
    assert get_symbol_config("btcusdt") == get_symbol_config("BTCUSDT")
    assert get_symbol_config("ethusdt") == get_symbol_config("ETHUSDT")
    assert get_symbol_config("solusdt") == get_symbol_config("SOLUSDT")


# ── Mode Field Tests ──────────────────────────────────────────────────────────


def test_mode_field_in_signal_received():
    """SignalReceived event must have a 'mode' field with default empty string."""
    from core.events import SignalReceived

    fields = {f.name for f in dataclasses.fields(SignalReceived)}
    assert "mode" in fields, "SignalReceived must have a 'mode' field"
    ev = SignalReceived()
    assert ev.mode == "", "SignalReceived.mode default must be empty string"


def test_mode_field_in_trade_approved():
    """TradeApproved event must have a 'mode' field with default empty string."""
    from core.events import TradeApproved

    fields = {f.name for f in dataclasses.fields(TradeApproved)}
    assert "mode" in fields, "TradeApproved must have a 'mode' field"
    ev = TradeApproved()
    assert ev.mode == "", "TradeApproved.mode default must be empty string"


# ── PERP / Futures Alias Tests ────────────────────────────────────────────────


def test_perp_aliases_resolve_to_spot_params():
    """Perpetual/futures symbol aliases must resolve to the same params as their spot equivalent."""
    btc_spot = get_symbol_config("BTCUSDT")
    eth_spot = get_symbol_config("ETHUSDT")
    sol_spot = get_symbol_config("SOLUSDT")

    # BTC perp variants
    assert get_symbol_config("BTCUSD") == btc_spot, (
        "BTCUSD (Bybit inverse) must match BTCUSDT"
    )
    assert get_symbol_config("BTCPERP") == btc_spot, "BTCPERP must match BTCUSDT"
    assert get_symbol_config("XBTUSDT") == btc_spot, (
        "XBTUSDT (BitMEX) must match BTCUSDT"
    )

    # ETH perp variants
    assert get_symbol_config("ETHUSD") == eth_spot, "ETHUSD must match ETHUSDT"
    assert get_symbol_config("ETHPERP") == eth_spot, "ETHPERP must match ETHUSDT"

    # SOL perp variants
    assert get_symbol_config("SOLUSD") == sol_spot, "SOLUSD must match SOLUSDT"
    assert get_symbol_config("SOLPERP") == sol_spot, "SOLPERP must match SOLUSDT"


def test_perp_aliases_case_insensitive():
    """Perpetual alias lookups must be case-insensitive."""
    assert get_symbol_config("btcperp") == get_symbol_config("BTCPERP")
    assert get_symbol_config("ethusd") == get_symbol_config("ETHUSD")
    assert get_symbol_config("solperp") == get_symbol_config("SOLPERP")
    assert get_symbol_config("xbtusdt") == get_symbol_config("XBTUSDT")
