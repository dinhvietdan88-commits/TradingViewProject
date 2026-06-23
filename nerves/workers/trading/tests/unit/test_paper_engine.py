import pytest
import aiosqlite
import config
from engine.paper_engine import (
    normalize_sl_tp,
    calculate_position_size,
    simulate_trade_outcome,
)


def test_paper_engine_sizing_and_extraction():
    # 1. Test normalize_sl_tp
    # Explicit values
    sig = {"sl": "50000.0", "tp": "75000.0"}
    sl, tp = normalize_sl_tp(sig, 60000.0, "buy", "BTCUSDT")
    assert sl == 50000.0
    assert tp == 75000.0

    # ATR fallback (ATR = 1000.0)
    sig_atr = {"payload": {"atr": "1000.0"}}
    sl, tp = normalize_sl_tp(sig_atr, 60000.0, "buy", "BTCUSDT")
    assert sl == 60000.0 - (config.ATR_SL_MULTIPLIER * 1000.0)
    assert tp == 60000.0 + (config.ATR_TP_MULTIPLIER * 1000.0)

    # Percentage fallback (SL = 8%, TP = 20%)
    sig_empty = {}
    sl, tp = normalize_sl_tp(sig_empty, 60000.0, "buy", "BTCUSDT")
    assert sl == 60000.0 * 0.92
    assert tp == 60000.0 * 1.20

    # 2. Test calculate_position_size
    # Input validation
    assert calculate_position_size("fixed", 200.0, 0.0, 92.0, 10000.0) == (0.0, 0.0)
    assert calculate_position_size("fixed", 200.0, -50.0, 92.0, 10000.0) == (0.0, 0.0)
    assert calculate_position_size("fixed", 200.0, 100.0, 92.0, 0.0) == (0.0, 0.0)
    assert calculate_position_size("fixed", 200.0, 100.0, 92.0, -100.0) == (0.0, 0.0)
    assert calculate_position_size("fixed", 0.0, 100.0, 92.0, 10000.0) == (0.0, 0.0)
    assert calculate_position_size("fixed", -10.0, 100.0, 92.0, 10000.0) == (0.0, 0.0)

    # Dynamic sizing edge cases
    assert calculate_position_size("dynamic", 0.02, 0.0, 90.0, 10000.0) == (0.0, 0.0)
    assert calculate_position_size("dynamic", 0.02, -50.0, 90.0, 10000.0) == (0.0, 0.0)
    assert calculate_position_size("dynamic", 0.02, 100.0, 90.0, 0.0) == (0.0, 0.0)
    assert calculate_position_size("dynamic", 0.02, 100.0, 90.0, -100.0) == (0.0, 0.0)
    assert calculate_position_size("dynamic", 0.0, 100.0, 90.0, 10000.0) == (0.0, 0.0)
    assert calculate_position_size("dynamic", -0.02, 100.0, 90.0, 10000.0) == (0.0, 0.0)

    # Fixed sizing
    quote_qty, exec_qty = calculate_position_size("fixed", 200.0, 100.0, 92.0, 10000.0)
    assert quote_qty == 200.0
    assert exec_qty == 2.0

    # Fixed sizing with insufficient balance
    quote_qty, exec_qty = calculate_position_size("fixed", 5000.0, 100.0, 92.0, 2000.0)
    assert quote_qty == 2000.0
    assert exec_qty == 20.0

    # Dynamic sizing (2% risk of $10,000 = $200 risk; stop loss distance = $10; qty = 20, quote = $2000)
    quote_qty, exec_qty = calculate_position_size("dynamic", 0.02, 100.0, 90.0, 10000.0)
    assert quote_qty == 2000.0
    assert exec_qty == 20.0


def test_simulate_trade_outcome():
    # Verify deterministic behavior using signal_id as seed
    pnl1, comm1, stat1 = simulate_trade_outcome(42, "buy", 100.0, 90.0, 120.0, 2.0)
    pnl2, comm2, stat2 = simulate_trade_outcome(42, "buy", 100.0, 90.0, 120.0, 2.0)

    # Must be identical for the same seed
    assert stat1 == stat2
    assert pnl1 == pnl2
    assert comm1 == comm2
    assert stat1 == "FILLED"
    assert comm1 > 0.0


@pytest.mark.asyncio
async def test_paper_engine_api_integration(client):
    # Test POST and GET settings
    settings_payload = {
        "position_sizing_mode": "dynamic",
        "position_sizing_value": 0.03,
        "sync_enabled": True,
    }
    res = await client.post("/api/forward/sync-settings", json=settings_payload)
    assert res.status_code == 200
    assert res.json()["success"] is True

    res = await client.get("/api/forward/sync-settings")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["settings"]["position_sizing_mode"] == "dynamic"
    assert data["settings"]["position_sizing_value"] == 0.03

    # Add mock FORWARD signals to forward DB (inserting 50 to satisfy minimum stats count)
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
        actions = ["buy", "sell"]
        prices = {
            "BTCUSDT": 60000.0,
            "ETHUSDT": 3000.0,
            "SOLUSDT": 140.0,
            "XRPUSDT": 0.50,
            "ADAUSDT": 0.45,
        }
        for i in range(50):
            sym = symbols[i % len(symbols)]
            act = actions[i % len(actions)]
            price = prices[sym]
            await db.execute(
                """
                INSERT INTO signals (id, symbol, action, price, quote_qty, mode, state)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (1000001 + i, sym, act, price, 100.0, "FORWARD", "INGESTED"),
            )
        await db.commit()

    # Trigger run-paper-engine
    res = await client.post("/api/forward/run-paper-engine")
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["success"] is True
    assert res_data["sizing_mode"] == "dynamic"
    # Wait, it generates 50 mock signals on top of existing ones to ensure min signals >= 50
    assert res_data["trades_simulated"] >= 50

    # Check stats endpoint
    res_stats = await client.get("/trades/stats?mode=FORWARD")
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["total_trades"] >= 50
    assert stats["win_rate"] > 0
