import pytest
from engine.paper_engine import (
    normalize_sl_tp,
    calculate_position_size,
    simulate_trade_outcome,
)
from data.query_service import _build_mode_stats


def test_normalize_sl_tp_extreme_conditions():
    # 1. Missing/Empty Payload
    sig_empty = {}
    sl, tp = normalize_sl_tp(sig_empty, 60000.0, "buy", "BTCUSDT")
    # Percentage fallback (8% SL, 20% TP)
    assert sl == pytest.approx(60000.0 * 0.92)
    assert tp == pytest.approx(60000.0 * 1.20)

    # 2. None / Empty string values in payload keys
    sig_none = {"sl": None, "tp": None, "payload": {"atr": ""}}
    sl, tp = normalize_sl_tp(sig_none, 60000.0, "buy", "BTCUSDT")
    assert sl == pytest.approx(60000.0 * 0.92)
    assert tp == pytest.approx(60000.0 * 1.20)

    # 3. String representation of numbers with commas
    sig_commas = {"sl": "50,000.00", "tp": "70,000.00"}
    sl, tp = normalize_sl_tp(sig_commas, 60000.0, "buy", "BTCUSDT")
    assert sl == 50000.0
    assert tp == 70000.0

    # 4. Invalid string values for stop loss / take profit
    sig_invalid = {"sl": "invalid_sl", "tp": "invalid_tp"}
    sl, tp = normalize_sl_tp(sig_invalid, 60000.0, "buy", "BTCUSDT")
    # Should fall back to percentage
    assert sl == pytest.approx(60000.0 * 0.92)
    assert tp == pytest.approx(60000.0 * 1.20)

    # 5. Weird action / Unknown action (treated as sell by default if not buy)
    sl, tp = normalize_sl_tp(sig_empty, 60000.0, "UNKNOWN_ACTION", "BTCUSDT")
    # Treated as sell: SL is +8%, TP is -20%
    assert sl == pytest.approx(60000.0 * 1.08)
    assert tp == pytest.approx(60000.0 * 0.80)


def test_calculate_position_size_scaling_and_zeros():
    # 1. Zero values / Division by Zero check on entry_price
    assert calculate_position_size("fixed", 100.0, 0.0, 90.0, 10000.0) == (0.0, 0.0)

    # 2. Stop loss price equals entry price (price_dist = 0) in dynamic sizing
    # Under dynamic sizing, if price_dist = 0, it should use fallback: risk_amount / (entry_price * 0.08)
    # Let's test with 2% risk of $10,000 = $200 risk; entry_price = 100.0.
    # Fallback executed_qty = 200.0 / (100.0 * 0.08) = 200.0 / 8.0 = 25.0
    # Fallback quote_qty = 25.0 * 100.0 = 2500.0
    quote_qty, exec_qty = calculate_position_size("dynamic", 2.0, 100.0, 100.0, 10000.0)
    assert exec_qty == 25.0
    assert quote_qty == 2500.0

    # 3. Dynamic Sizing scaling with equity changes
    # $10,000 balance, 2% risk, entry = 100, SL = 90.
    # risk_amount = 200. price_dist = 10. qty = 20. quote_qty = 2000.
    q_10k, e_10k = calculate_position_size("dynamic", 2.0, 100.0, 90.0, 10000.0)
    assert q_10k == 2000.0
    assert e_10k == 20.0

    # $50,000 balance, 2% risk, entry = 100, SL = 90.
    # risk_amount = 1000. price_dist = 10. qty = 100. quote_qty = 10000.
    q_50k, e_50k = calculate_position_size("dynamic", 2.0, 100.0, 90.0, 50000.0)
    assert q_50k == 10000.0
    assert e_50k == 100.0

    # P&L scaling verification
    # For a win (hitting TP at 120.0 from 100.0):
    # With 10k balance: pnl = e_10k * (120 - 100) = 20 * 20 = 400
    pnl_10k, _, _ = simulate_trade_outcome(1, "buy", 100.0, 90.0, 120.0, e_10k)
    # With 50k balance: pnl = e_50k * (120 - 100) = 100 * 20 = 2000
    pnl_50k, _, _ = simulate_trade_outcome(1, "buy", 100.0, 90.0, 120.0, e_50k)
    assert pnl_50k == pytest.approx(pnl_10k * 5.0)

    # 4. Insufficient balance clamping under Fixed sizing
    # Sizing value = 500, balance = 200. Should clamp to 200.
    quote_qty, exec_qty = calculate_position_size("fixed", 500.0, 100.0, 90.0, 200.0)
    assert quote_qty == 200.0
    assert exec_qty == 2.0

    # Zero/negative current balance
    quote_qty, exec_qty = calculate_position_size("fixed", 500.0, 100.0, 90.0, 0.0)
    assert quote_qty == 0.0
    assert exec_qty == 0.0

    quote_qty, exec_qty = calculate_position_size("fixed", 500.0, 100.0, 90.0, -100.0)
    assert quote_qty == 0.0
    assert exec_qty == 0.0

    # 5. Negative sizing value under dynamic sizing
    quote_qty, exec_qty = calculate_position_size("dynamic", -2.0, 100.0, 90.0, 10000.0)
    assert quote_qty == 0.0
    assert exec_qty == 0.0


def test_stats_calculations_correctness():
    # 1. Standard P&L List
    pnl_list = [100.0, -50.0, 150.0, -100.0]
    stats = _build_mode_stats(pnl_list)
    assert stats["total_trades"] == 4
    assert stats["winning_trades"] == 2
    assert stats["losing_trades"] == 2
    assert stats["win_rate"] == 50.0
    assert stats["total_pnl"] == 100.0
    # Profit factor: (100 + 150) / (50 + 100) = 250 / 150 = 1.67
    assert stats["profit_factor"] == 1.67
    assert stats["avg_win"] == 125.0
    assert stats["avg_loss"] == -75.0
    assert stats["best_trade"] == 150.0
    assert stats["worst_trade"] == -100.0

    # 2. Empty P&L List
    stats_empty = _build_mode_stats([])
    assert stats_empty["total_trades"] == 0
    assert stats_empty["winning_trades"] == 0
    assert stats_empty["losing_trades"] == 0
    assert stats_empty["win_rate"] == 0.0
    assert stats_empty["total_pnl"] == 0.0
    assert stats_empty["profit_factor"] == 0.0

    # 3. Only wins
    stats_wins = _build_mode_stats([100.0, 200.0])
    assert stats_wins["profit_factor"] == 99.0  # Fallback for division by zero

    # 4. Only losses
    stats_losses = _build_mode_stats([-100.0, -200.0])
    assert stats_losses["profit_factor"] == 0.0
