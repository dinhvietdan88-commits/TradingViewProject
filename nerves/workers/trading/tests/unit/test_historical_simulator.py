import pytest
from unittest.mock import AsyncMock, patch
import aiosqlite
import config
from engine.paper_engine import run_paper_trading_simulation
from engine.active_position_monitor import active_position_monitor


@pytest.mark.asyncio
async def test_historical_price_path_tp_hit():
    # Mock fetch_binance_klines to return a TP hit candle
    # Symbol: BTCUSDT, Entry: 60000, TP: 72000 (20%), SL: 55200 (8%)
    # Candle: [open_time, open, high, low, close]
    # Candle 1: High = 73000, Low = 59000 -> TP hit!
    mock_candles = [
        [1718000000000, "60000", "73000", "59000", "71000", "10", 1718000900000]
    ]

    with patch(
        "engine.paper_engine.fetch_binance_klines", AsyncMock(return_value=mock_candles)
    ):
        # Clear forward db signals and trades for testing
        async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
            await db.execute("DELETE FROM trades")
            await db.execute("DELETE FROM signals WHERE mode = 'FORWARD'")
            # Insert a signal
            await db.execute(
                """
                INSERT INTO signals (id, symbol, action, price, mode, created_at, state)
                VALUES (9999, 'BTCUSDT', 'buy', 60000.0, 'FORWARD', '2026-06-22 00:00:00', 'INGESTED')
                """
            )
            await db.commit()

        res = await run_paper_trading_simulation()
        assert res["success"] is True

        async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM trades WHERE signal_id = 9999"
            ) as cursor:
                trade = await cursor.fetchone()

        assert trade is not None
        assert trade["status"] == "FILLED"
        # TP hit! P&L = qty * (72000 - 60000)
        assert trade["pnl"] > 0
        assert "simulation" in trade["error_message"]


@pytest.mark.asyncio
async def test_active_position_monitor_resolve():
    # Test ActivePositionMonitor resolves active trades on ticker updates
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        await db.execute("DELETE FROM trades")
        # Insert an ACTIVE trade
        await db.execute(
            """
            INSERT INTO trades (id, signal_id, symbol, side, status, executed_price, stop_loss_price, take_profit_price, executed_qty)
            VALUES (8888, 9998, 'BTCUSDT', 'buy', 'ACTIVE', 60000.0, 55200.0, 72000.0, 0.00166667)
            """
        )
        await db.commit()

    await active_position_monitor.refresh_active_trades()
    assert len(active_position_monitor.active_trades) == 1

    # Resolve trade manually via live price feed update: trigger Stop Loss
    await active_position_monitor.resolve_trade(8888, 55200.0, "Stop Loss")

    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM trades WHERE id = 8888") as cursor:
            trade = await cursor.fetchone()

    assert trade is not None
    assert trade["status"] == "FILLED"
    assert trade["pnl"] < 0  # Loss!
    assert "Stop Loss" in trade["error_message"]
