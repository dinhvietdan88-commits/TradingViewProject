"""
Symbol Configuration Registry — Per-asset beta-scaled risk parameters.

Derived from: docs/knowledge/trading_wizard/OPTIMIZED_PARAMETERS_MATRIX.md
Base asset: BTC (Beta=1.0). ETH (Beta=1.25) and SOL (Beta=1.6) are scaled linearly.

Design Decision:
    These are mathematical constants derived from backtesting, NOT environment variables.
    Keep this module separate from config.py (which is 100% os.getenv()-driven).
    config.STOP_LOSS_PCT remains as the global sentinel/fallback for unknown symbols.
"""

import config

SYMBOL_PARAMS: dict = {
    "BTCUSDT": {
        "stop_loss_pct": 0.08,  # Hard SL cap: 8% (Beta=1.0 baseline)
        "risk_pct": 0.010,  # ATR risk-based sizing: 1.0% of account per trade
        "breakout_size_pct": 0.025,  # Tactical breakout position: 2.5% of account
        "atr_sl_mul": config.ATR_SL_MULTIPLIER,  # ATR multiplier for stop-loss placement
        "atr_tp_mul": config.ATR_TP_MULTIPLIER,  # ATR multiplier for take-profit target
        "trail_atr_mul": config.CHANDELIER_TRAILING_MULTIPLIER,  # Chandelier trailing stop ATR multiplier
    },
    "ETHUSDT": {
        "stop_loss_pct": 0.10,  # 8% * 1.25 = 10% (Beta=1.25)
        "risk_pct": 0.008,  # Lower risk for higher-beta asset
        "breakout_size_pct": 0.020,  # 2.5% * 0.8 = 2.0% (beta-scaled allocation)
        "atr_sl_mul": config.ATR_SL_MULTIPLIER
        * 1.25,  # Wider stop to avoid premature whipsaws
        "atr_tp_mul": config.ATR_TP_MULTIPLIER * 1.25,  # Proportionally wider target
        "trail_atr_mul": config.CHANDELIER_TRAILING_MULTIPLIER * 1.25,
    },
    "SOLUSDT": {
        "stop_loss_pct": 0.13,  # 8% * 1.625 ≈ 13% (Beta=1.6)
        "risk_pct": 0.006,  # Lowest risk for highest-beta asset
        "breakout_size_pct": 0.015,  # 2.5% * 0.6 = 1.5% (beta-scaled allocation)
        "atr_sl_mul": config.ATR_SL_MULTIPLIER
        * 1.6,  # Much wider stop for SOL volatility
        "atr_tp_mul": config.ATR_TP_MULTIPLIER * 1.6,  # Captures larger SOL swings
        "trail_atr_mul": config.CHANDELIER_TRAILING_MULTIPLIER * 1.6,
    },
}

# Safe fallback: BTC parameters for any symbol not in the registry.
# This ensures unknown symbols get the most conservative (lowest-beta) treatment.
DEFAULT_PARAMS: dict = SYMBOL_PARAMS["BTCUSDT"]

# ── Perpetual / Futures Aliases ───────────────────────────────────────────────
# TradingView and Bybit send different symbol strings for the same underlying asset.
# All aliases share the same parameter dict as their spot equivalent.
#
#  Format origins:
#    BTCUSD    — Bybit inverse perpetual / BitMEX style
#    BTCPERP   — Generic perpetual label (some TradingView feeds)
#    BTCUSDT.P — TradingView perpetual notation (dot-P suffix) handled via upper()
#    BTC/USDT:USDT — ccxt unified format; '/' and ':' stripped by get_symbol_config
#    XBTUSDT   — BitMEX canonical BTC symbol
#
# NOTE: Risk parameters are IDENTICAL to spot. The exchange adapter (bybit_adapter.py)
# handles the category=linear routing independently. symbol_config is risk-params only.
SYMBOL_PARAMS["BTCUSD"] = SYMBOL_PARAMS["BTCUSDT"]  # Bybit inverse / BitMEX
SYMBOL_PARAMS["BTCPERP"] = SYMBOL_PARAMS["BTCUSDT"]  # Generic perpetual label
SYMBOL_PARAMS["XBTUSDT"] = SYMBOL_PARAMS["BTCUSDT"]  # BitMEX canonical BTC
SYMBOL_PARAMS["ETHUSD"] = SYMBOL_PARAMS["ETHUSDT"]  # Bybit inverse ETH
SYMBOL_PARAMS["ETHPERP"] = SYMBOL_PARAMS["ETHUSDT"]  # Generic perpetual label
SYMBOL_PARAMS["SOLUSD"] = SYMBOL_PARAMS["SOLUSDT"]  # Bybit inverse SOL
SYMBOL_PARAMS["SOLPERP"] = SYMBOL_PARAMS["SOLUSDT"]  # Generic perpetual label


def get_symbol_config(symbol: str) -> dict:
    """Return per-symbol risk config for a given trading pair.

    Args:
        symbol: Trading pair (e.g. 'BTCUSDT', 'ETHUSDT', 'SOLUSDT').
                Case-insensitive. Unknown symbols fall back to BTC defaults.

    Returns:
        Dict with keys: stop_loss_pct, risk_pct, breakout_size_pct,
                        atr_sl_mul, atr_tp_mul, trail_atr_mul.

    Example:
        >>> get_symbol_config("ETHUSDT")
        {'stop_loss_pct': 0.1, 'risk_pct': 0.008, ...}
        >>> get_symbol_config("XRPUSDT")  # Unknown → BTC defaults
        {'stop_loss_pct': 0.08, 'risk_pct': 0.01, ...}
    """
    return SYMBOL_PARAMS.get(symbol.upper(), DEFAULT_PARAMS)
