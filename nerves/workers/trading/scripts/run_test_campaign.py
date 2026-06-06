import asyncio
import os
import sys
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# 1. Setup isolated database and config environment BEFORE imports
os.environ["DB_PATH"] = "test_trades.db"
os.environ["WEEX_DRY_RUN"] = "false"  # Force adapter logic path, we mock network calls
os.environ["DISABLE_RATE_LIMIT"] = "true"

# Add project root and server to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import database
from core.event_bus import EventBus
from core.events import TradeApproved, TradeExecuted, TradeFailed
from engine.trade_engine import execute_trade, set_bus
from exchanges.registry import init_registry
from exchanges.weex_adapter import WeexAdapter
from exchanges.base import ExchangeError, ExchangeErrorCategory

# Setup logging to console and file
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("test_campaign")

# Create file handler for logs
file_handler = logging.FileHandler("test_campaign.log", mode="w", encoding="utf-8")
file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
log.addHandler(file_handler)
logging.getLogger("engine.trade_engine").addHandler(file_handler)
logging.getLogger("exchanges.weex_adapter").addHandler(file_handler)

# Test results dict
results = {}


async def cleanup_db():
    if os.path.exists("test_trades.db"):
        try:
            os.remove("test_trades.db")
            log.info("Cleaned up test_trades.db")
        except Exception as e:
            log.warning(f"Could not clean up test_trades.db: {e}")


async def run_case_1():
    log.info("--- TEST CASE 1: Micro-Volume Clamping and Limits ---")
    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",  # noqa: S106
        passphrase="mock_passphrase",  # noqa: S106
        testnet=True,
        dry_run=True,  # Enable dry_run for adapter to avoid real network balance check
    )

    # We will mock place_market_order to see what quantity is calculated.
    mock_place_order = AsyncMock(
        return_value={
            "orderId": "MOCK-ENTRY-WEEX",
            "executedQty": "0.001",
            "cummulativeQuoteQty": "60.0",
            "status": "FILLED",
        }
    )
    mock_place_oco = AsyncMock(return_value={"orderListId": "MOCK-OCO-WEEX"})

    with (
        patch.object(adapter, "place_market_order", mock_place_order),
        patch.object(adapter, "place_oco_order", mock_place_oco),
    ):
        # Scenario 1.1: BTC buy with quote_qty=6.0 (under minimum 0.001 BTC)
        # Price is $60,000, so 0.001 BTC = $60.0. Quote qty of $6 should be clamped to $60.
        res_btc = await adapter.execute_smart_order(
            symbol="BTCUSDT",
            side="BUY",
            entry_price=60000.0,
            sl_price=58000.0,
            quote_qty=6.0,
        )
        assert res_btc.success is True
        assert res_btc.risk.quantity == 0.001
        log.info(
            "[+] Passed 1.1: BTC volume clamped to minimum 0.001 BTC successfully."
        )

        # Scenario 1.2: ETH buy with quote_qty=3.0 (under minimum 0.01 ETH)
        # Price is $3000, so 0.01 ETH = $30.0. Quote qty of $3 should be clamped to $30.
        res_eth = await adapter.execute_smart_order(
            symbol="ETHUSDT",
            side="BUY",
            entry_price=3000.0,
            sl_price=2800.0,
            quote_qty=3.0,
        )
        assert res_eth.success is True
        assert res_eth.risk.quantity == 0.01
        log.info("[+] Passed 1.2: ETH volume clamped to minimum 0.01 ETH successfully.")

        # Scenario 1.3: SOL buy with quote_qty=1.0 (under minimum $5.00 limit for other assets)
        res_sol_small = await adapter.execute_smart_order(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=100.0,
            sl_price=90.0,
            quote_qty=1.0,
        )
        assert res_sol_small.success is True
        assert res_sol_small.risk.cost == 5.0
        log.info(
            "[+] Passed 1.3: Other assets value clamped to minimum $5.00 successfully."
        )

        # Scenario 1.4: SOL buy with quote_qty=20.0 (above maximum $10.00 limit for other assets)
        res_sol_large = await adapter.execute_smart_order(
            symbol="SOLUSDT",
            side="BUY",
            entry_price=100.0,
            sl_price=90.0,
            quote_qty=20.0,
        )
        assert res_sol_large.success is True
        assert res_sol_large.risk.cost == 10.0
        log.info(
            "[+] Passed 1.4: Other assets value clamped to maximum $10.00 successfully."
        )

    results["Case 1: Micro-Volume Limits"] = "PASSED"


async def run_case_2():
    log.info("--- TEST CASE 2: Daily Loss Cap Enforcement ($10.00) ---")

    # 1. Insert a mock signal first to get a real signal_id in signals table
    sig_id_loss = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=65000.0,
        quote_qty=100.0,
        source_ip="127.0.0.1",
        payload={"exchange": "weex"},
    )

    # 2. Insert a mock trade with negative PnL = -$12.50 to exceed the $10 cap
    await database.insert_trade(
        signal_id=sig_id_loss,
        symbol="BTCUSDT",
        side="BUY",
        order_id="MOCK-LOSS-001",
        status="FILLED",
        requested_qty=100.0,
        executed_qty=0.002,
        executed_price=65000.0,
        exchange="weex",
    )
    # Update trade with PnL of -$12.50
    async with database.aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE trades SET pnl = -12.50 WHERE order_id = 'MOCK-LOSS-001'"
        )
        await db.commit()

    # Check that daily loss is computed correctly
    loss = await database.get_daily_loss("weex")
    log.info(f"Daily loss computed in DB for weex: {loss} USDT")
    assert loss == 12.50

    # 3. Insert target signal that should be blocked
    target_sig_id = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=65000.0,
        quote_qty=50.0,
        source_ip="127.0.0.1",
        payload={"exchange": "weex"},
    )

    # Try executing a trade on WEEX
    event = TradeApproved(
        signal_id=target_sig_id,
        symbol="BTCUSDT",
        action="buy",
        price=65000.0,
        quote_qty=50.0,
        exchange="weex",
        approved_by="AI",
        analysis_text="Test case",
    )

    # We will check if execute_trade fails and saves a FAILED trade
    test_bus = EventBus()
    set_bus(test_bus)

    failed_emitted = False

    @test_bus.on(TradeFailed)
    async def on_failed(ev):
        nonlocal failed_emitted
        failed_emitted = True
        log.info(f"Received TradeFailed event: {ev.error}")
        assert "exceeds cap" in ev.error

    # We mock the router to return a mock weex adapter so it doesn't fail on connection,
    # but the safety checks are inside trade_engine.py BEFORE execute_smart_order is called!
    weex_client = AsyncMock()
    weex_client.exchange_name = "weex"
    weex_client.exchange_id = "weex"
    weex_client.execute_smart_order = AsyncMock(return_value=MagicMock(success=True))

    with patch("exchanges.router.get_router") as mock_get_router:
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = weex_client
        mock_get_router.return_value = mock_router

        await execute_trade(event)

    # Read the status of target signal and its trade entry
    async with database.aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = database.aiosqlite.Row
        async with db.execute(
            "SELECT * FROM trades WHERE signal_id = ?", (target_sig_id,)
        ) as cursor:
            trade_row = await cursor.fetchone()
            assert trade_row is not None
            assert trade_row["status"] == "FAILED"
            assert "exceeds cap" in trade_row["error_message"]

        async with db.execute(
            "SELECT processed FROM signals WHERE id = ?", (target_sig_id,)
        ) as cursor:
            sig_row = await cursor.fetchone()
            assert sig_row[0] == 2  # 2 = FAILED

    assert failed_emitted is True
    # Verify execute_smart_order was NOT called (blocked by safety check)
    weex_client.execute_smart_order.assert_not_called()
    log.info(
        "[+] Passed 2.0: Daily Loss Cap blocked trade execution and set status correctly."
    )
    results["Case 2: Daily Loss Cap"] = "PASSED"


async def run_case_3():
    log.info("--- TEST CASE 3: Drawdown Cap Enforcement (5.0%) ---")

    # Clear previous trades to make drawdown calculation predictable
    async with database.aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM trades")
        await db.commit()

    sig_1 = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=65000.0,
        quote_qty=100.0,
        source_ip="127.0.0.1",
        payload={},
    )
    sig_2 = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=65000.0,
        quote_qty=100.0,
        source_ip="127.0.0.1",
        payload={},
    )

    await database.insert_trade(
        signal_id=sig_1,
        symbol="BTCUSDT",
        side="BUY",
        order_id="DD-1",
        status="FILLED",
        exchange="weex",
    )
    await database.insert_trade(
        signal_id=sig_2,
        symbol="BTCUSDT",
        side="BUY",
        order_id="DD-2",
        status="FILLED",
        exchange="weex",
    )

    # Set created_at to 48 hours ago so they contribute to rolling drawdown but NOT to daily loss!
    async with database.aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE trades SET pnl = 100.0, created_at = datetime('now', '-48 hours') WHERE order_id = 'DD-1'"
        )
        await db.execute(
            "UPDATE trades SET pnl = -60.0, created_at = datetime('now', '-48 hours') WHERE order_id = 'DD-2'"
        )
        await db.commit()

    # Check that daily loss is indeed 0.0 USDT
    daily_loss = await database.get_daily_loss("weex")
    log.info(f"Daily loss check: {daily_loss} USDT (Should be 0.0)")
    assert daily_loss == 0.0

    dd = await database.get_rolling_drawdown(20)
    log.info(f"Rolling drawdown calculated: {dd:.2f}%")
    assert dd > 5.0

    target_sig_id = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=65000.0,
        quote_qty=50.0,
        source_ip="127.0.0.1",
        payload={"exchange": "weex"},
    )

    event = TradeApproved(
        signal_id=target_sig_id,
        symbol="BTCUSDT",
        action="buy",
        price=65000.0,
        quote_qty=50.0,
        exchange="weex",
        approved_by="AI",
        analysis_text="Test case drawdown",
    )

    test_bus = EventBus()
    set_bus(test_bus)
    failed_emitted = False

    @test_bus.on(TradeFailed)
    async def on_failed(ev):
        nonlocal failed_emitted
        failed_emitted = True
        log.info(f"Received TradeFailed event: {ev.error}")
        assert "drawdown" in ev.error.lower()

    weex_client = AsyncMock()
    weex_client.exchange_name = "weex"
    weex_client.exchange_id = "weex"
    weex_client.execute_smart_order = AsyncMock(return_value=MagicMock(success=True))

    with patch("exchanges.router.get_router") as mock_get_router:
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = weex_client
        mock_get_router.return_value = mock_router

        await execute_trade(event)

    async with database.aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = database.aiosqlite.Row
        async with db.execute(
            "SELECT * FROM trades WHERE signal_id = ?", (target_sig_id,)
        ) as cursor:
            trade_row = await cursor.fetchone()
            assert trade_row is not None
            assert trade_row["status"] == "FAILED"
            assert "drawdown" in trade_row["error_message"].lower()

    assert failed_emitted is True
    weex_client.execute_smart_order.assert_not_called()
    log.info("[+] Passed 3.0: Drawdown Cap blocked trade execution correctly.")
    results["Case 3: Drawdown Cap"] = "PASSED"


async def run_case_4():
    log.info("--- TEST CASE 4: Weex Failure Fallover to Bybit ---")

    # Reset DB so drawdown / daily loss don't block Weex execution
    async with database.aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("DELETE FROM trades")
        await db.commit()

    target_sig_id = await database.insert_signal(
        symbol="BTCUSDT",
        action="buy",
        price=65000.0,
        quote_qty=50.0,
        source_ip="127.0.0.1",
        payload={"exchange": "weex"},
    )

    # We will mock the registry to return Weex and Bybit adapters.
    # Weex adapter will throw a ConnectionError on execute_smart_order.
    # Bybit adapter will succeed.
    weex_client = AsyncMock()
    weex_client.exchange_name = "weex"
    weex_client.exchange_id = "weex"
    weex_client.execute_smart_order = AsyncMock(
        side_effect=ExchangeError(
            ExchangeErrorCategory.CONNECTION_ERROR, "Weex API connection refused"
        )
    )

    bybit_client = AsyncMock()
    bybit_client.exchange_name = "bybit"
    bybit_client.exchange_id = "bybit"
    bybit_client.execute_smart_order = AsyncMock(
        return_value=MagicMock(
            success=True,
            dry_run=False,
            side="BUY",
            symbol="BTCUSDT",
            entry_order={
                "orderId": "FALLBACK-BYBIT-001",
                "status": "FILLED",
                "executedQty": "0.001",
                "cummulativeQuoteQty": "65.0",
            },
            oco_order={"orderListId": "FALLBACK-BYBIT-OCO-001"},
            risk=MagicMock(stop_loss_price=63000.0, take_profit_price=70000.0),
        )
    )

    test_bus = EventBus()
    set_bus(test_bus)

    executed_emitted = False

    @test_bus.on(TradeExecuted)
    async def on_exec(ev):
        nonlocal executed_emitted
        executed_emitted = True
        log.info(
            f"Received TradeExecuted event: order_id={ev.order_id}, exchange={ev.exchange}"
        )
        assert ev.exchange == "bybit"
        assert ev.order_id == "FALLBACK-BYBIT-001"

    event = TradeApproved(
        signal_id=target_sig_id,
        symbol="BTCUSDT",
        action="buy",
        price=65000.0,
        quote_qty=50.0,
        exchange="weex",
        approved_by="AI",
        analysis_text="Test fallback",
    )

    # We mock get_router to return a router with these mocked adapters
    with patch("exchanges.router.get_router") as mock_get_router:
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = weex_client
        mock_router._get_fallback.return_value = "bybit"

        mock_registry = MagicMock()
        mock_registry.is_available.side_effect = lambda name: name in ["bybit", "weex"]
        mock_registry.get_adapter.side_effect = lambda name: (
            bybit_client if name == "bybit" else weex_client
        )
        mock_router._registry = mock_registry

        mock_get_router.return_value = mock_router

        await execute_trade(event)

    # Check that Bybit was called and trade is saved with exchange='bybit'
    weex_client.execute_smart_order.assert_awaited_once()
    bybit_client.execute_smart_order.assert_awaited_once()

    async with database.aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = database.aiosqlite.Row
        async with db.execute(
            "SELECT * FROM trades WHERE signal_id = ?", (target_sig_id,)
        ) as cursor:
            trade_row = await cursor.fetchone()
            assert trade_row is not None
            assert trade_row["exchange"] == "bybit"
            assert trade_row["status"] == "FILLED"
            assert trade_row["order_id"] == "FALLBACK-BYBIT-001"

    assert executed_emitted is True
    log.info(
        "[+] Passed 4.0: Weex connection failure triggered fallback to Bybit successfully."
    )
    results["Case 4: Fallback Routing"] = "PASSED"


async def run_case_5():
    log.info(
        "--- TEST CASE 5: Orphan Position Prevention (Entry Success, OCO Exit Failure) ---"
    )

    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",  # noqa: S106
        passphrase="mock_passphrase",  # noqa: S106
        testnet=True,
        dry_run=False,  # Disable dry run to trigger real OCO placement try-catch block
    )

    entry_mock_res = {
        "orderId": "ENTRY-SUCCESS-999",
        "executedQty": "0.01",
        "cummulativeQuoteQty": "30.0",
        "status": "FILLED",
    }

    mock_place_order = AsyncMock(return_value=entry_mock_res)
    mock_place_oco = AsyncMock(
        side_effect=Exception("OCO Order Rejected by exchange API")
    )
    mock_cancel = AsyncMock(return_value={"status": "CANCELED"})

    with (
        patch.object(adapter, "place_market_order", mock_place_order),
        patch.object(adapter, "get_account_balance", AsyncMock(return_value=1000.0)),
        patch.object(adapter, "place_oco_order", mock_place_oco),
        patch.object(adapter, "cancel_order", mock_cancel),
    ):
        res = await adapter.execute_smart_order(
            symbol="ETHUSDT",
            side="BUY",
            entry_price=3000.0,
            sl_price=2800.0,
            tp_price=3500.0,
            quote_qty=30.0,
        )

        # Verify execution fails, and cancel_order is called for the entry order
        assert res.success is False
        assert "OCO placement failed" in res.error
        mock_cancel.assert_called_once_with("ETHUSDT_UMCBL", "ENTRY-SUCCESS-999")
        log.info(
            "[+] Passed 5.0: Entry order successfully cancelled after OCO exit failure."
        )

    results["Case 5: Orphan Position Prevention"] = "PASSED"


async def run_campaign():
    log.info("======================================================================")
    log.info("STARTING WEEX SAFETY AND RESILIENCE INTEGRATION TEST CAMPAIGN")
    log.info("======================================================================")

    # Initialize clean test db
    await cleanup_db()
    await database.init_db()
    init_registry()

    try:
        await run_case_1()
        await run_case_2()
        await run_case_3()
        await run_case_4()
        await run_case_5()

        log.info(
            "======================================================================"
        )
        log.info("TEST CAMPAIGN SUMMARY:")
        for name, status in results.items():
            log.info(f"  {name}: {status}")
        log.info(
            "======================================================================"
        )
    finally:
        await cleanup_db()


if __name__ == "__main__":
    asyncio.run(run_campaign())
