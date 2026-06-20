"""
Integration tests for Forward Test DB Routing.
"""

import pytest
import aiosqlite
import config
import database
from data.routing import get_db_path_by_signal_id, get_db_path_by_trade_id


@pytest.mark.asyncio
async def test_db_routing_signals_and_trades_isolation():
    """Verify that signals and trades are correctly routed based on mode."""
    # 1. Insert a forward signal
    forward_sig_id = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=60000.0,
        quote_qty=85.0,
        source_ip="127.0.0.1",
        mode="FORWARD",
    )

    # 2. Insert a standard (live/backtest) signal
    live_sig_id = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=60000.0,
        quote_qty=85.0,
        source_ip="127.0.0.1",
        mode="LIVE",
    )

    # Verify routing functions resolve correctly
    assert await get_db_path_by_signal_id(forward_sig_id) == config.FORWARD_DB_PATH
    assert await get_db_path_by_signal_id(live_sig_id) == config.DB_PATH

    # Verify presence in respective SQLite files
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM signals WHERE id = ?", (forward_sig_id,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
        async with db.execute(
            "SELECT id FROM signals WHERE id = ?", (live_sig_id,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is None

    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM signals WHERE id = ?", (forward_sig_id,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is None
        async with db.execute(
            "SELECT id FROM signals WHERE id = ?", (live_sig_id,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None

    # 3. Insert trades associated with the signals
    forward_trade_id = await database.insert_trade(
        signal_id=forward_sig_id,
        symbol="BTCUSDT",
        side="BUY",
        order_id="FWD-001",
        status="FILLED",
        requested_qty=0.1,
    )

    live_trade_id = await database.insert_trade(
        signal_id=live_sig_id,
        symbol="BTCUSDT",
        side="BUY",
        order_id="LIVE-001",
        status="FILLED",
        requested_qty=0.1,
    )

    # Verify routing functions resolve correctly
    assert await get_db_path_by_trade_id(forward_trade_id) == config.FORWARD_DB_PATH
    assert await get_db_path_by_trade_id(live_trade_id) == config.DB_PATH

    # Verify presence in respective SQLite files
    async with aiosqlite.connect(config.FORWARD_DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM trades WHERE id = ?", (forward_trade_id,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
        async with db.execute(
            "SELECT id FROM trades WHERE id = ?", (live_trade_id,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is None

    async with aiosqlite.connect(config.DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM trades WHERE id = ?", (forward_trade_id,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is None
        async with db.execute(
            "SELECT id FROM trades WHERE id = ?", (live_trade_id,)
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None


@pytest.mark.asyncio
async def test_risk_calculations_isolation():
    """Verify that risk calculations are isolated when mode is passed."""
    # Seed trades in standard DB
    sig_live = await database.insert_signal(
        "BTCUSDT", "buy", 60000.0, 85.0, "127.0.0.1", mode="LIVE"
    )
    await database.insert_trade(
        signal_id=sig_live,
        symbol="BTCUSDT",
        side="BUY",
        order_id="LIVE-T1",
        status="FILLED",
        requested_qty=1.0,
        executed_qty=1.0,
        executed_price=60000.0,
        pnl=-200.0,  # Negative PnL (loss)
        exchange="binance",
    )

    # Seed trades in forward DB
    sig_forward = await database.insert_signal(
        "BTCUSDT", "buy", 60000.0, 85.0, "127.0.0.1", mode="FORWARD"
    )
    await database.insert_trade(
        signal_id=sig_forward,
        symbol="BTCUSDT",
        side="BUY",
        order_id="FWD-T1",
        status="FILLED",
        requested_qty=1.0,
        executed_qty=1.0,
        executed_price=60000.0,
        pnl=-50.0,  # Negative PnL (loss)
        exchange="binance",
    )

    # Test daily loss separation
    daily_loss_live = await database.get_daily_loss("binance", mode="LIVE")
    daily_loss_forward = await database.get_daily_loss("binance", mode="FORWARD")
    assert daily_loss_live == 200.0
    assert daily_loss_forward == 50.0

    # Test rolling drawdown separation
    dd_live = await database.get_rolling_drawdown(20, mode="LIVE")
    dd_forward = await database.get_rolling_drawdown(20, mode="FORWARD")
    assert dd_live > 0
    assert dd_forward > 0
    assert dd_live != dd_forward


@pytest.mark.asyncio
async def test_api_endpoints_mode_filtering(client):
    """Verify that REST API endpoints filter correctly by mode."""
    # Seed standard DB
    sig_live = await database.insert_signal(
        "BTCUSDT", "buy", 60000.0, 85.0, "127.0.0.1", mode="LIVE"
    )
    await database.insert_trade(
        signal_id=sig_live,
        symbol="BTCUSDT",
        side="BUY",
        order_id="LIVE-T1",
        status="FILLED",
        requested_qty=1.0,
        executed_qty=1.0,
        executed_price=60000.0,
        pnl=100.0,
    )

    # Seed forward DB
    sig_forward = await database.insert_signal(
        "BTCUSDT", "buy", 60000.0, 85.0, "127.0.0.1", mode="FORWARD"
    )
    await database.insert_trade(
        signal_id=sig_forward,
        symbol="BTCUSDT",
        side="BUY",
        order_id="FWD-T1",
        status="FILLED",
        requested_qty=1.0,
        executed_qty=1.0,
        executed_price=60000.0,
        pnl=300.0,
    )

    # 1. Test /api/signals with mode
    res_sig_live = await client.get("/api/signals?mode=LIVE")
    assert res_sig_live.status_code == 200
    assert res_sig_live.json()["total"] == 1
    assert res_sig_live.json()["signals"][0]["id"] == sig_live

    res_sig_fwd = await client.get("/api/signals?mode=FORWARD")
    assert res_sig_fwd.status_code == 200
    assert res_sig_fwd.json()["total"] == 1
    assert res_sig_fwd.json()["signals"][0]["id"] == sig_forward

    # 2. Test /trades with mode
    res_trades_live = await client.get("/trades?mode=LIVE")
    assert res_trades_live.status_code == 200
    assert res_trades_live.json()["total"] == 1
    assert res_trades_live.json()["trades"][0]["order_id"] == "LIVE-T1"

    res_trades_fwd = await client.get("/trades?mode=FORWARD")
    assert res_trades_fwd.status_code == 200
    assert res_trades_fwd.json()["total"] == 1
    assert res_trades_fwd.json()["trades"][0]["order_id"] == "FWD-T1"

    # 3. Test /trades/stats with mode
    res_stats_live = await client.get("/trades/stats?mode=LIVE")
    assert res_stats_live.status_code == 200
    assert res_stats_live.json()["total_trades"] == 1
    assert res_stats_live.json()["total_pnl"] == 100.0

    res_stats_fwd = await client.get("/trades/stats?mode=FORWARD")
    assert res_stats_fwd.status_code == 200
    assert res_stats_fwd.json()["total_trades"] == 1
    assert res_stats_fwd.json()["total_pnl"] == 300.0

    # 4. Test /trades/equity with mode
    res_eq_live = await client.get("/trades/equity?mode=LIVE")
    assert res_eq_live.status_code == 200
    assert res_eq_live.json()["cumulative_pnl"][-1] == 100.0

    res_eq_fwd = await client.get("/trades/equity?mode=FORWARD")
    assert res_eq_fwd.status_code == 200
    assert res_eq_fwd.json()["cumulative_pnl"][-1] == 300.0

    # 5. Test /trades/analysis with mode
    res_an_live = await client.get("/trades/analysis?mode=LIVE")
    assert res_an_live.status_code == 200
    assert res_an_live.json()["total"] == 1
    assert res_an_live.json()["trades"][0]["order_id"] == "LIVE-T1"

    res_an_fwd = await client.get("/trades/analysis?mode=FORWARD")
    assert res_an_fwd.status_code == 200
    assert res_an_fwd.json()["total"] == 1
    assert res_an_fwd.json()["trades"][0]["order_id"] == "FWD-T1"
