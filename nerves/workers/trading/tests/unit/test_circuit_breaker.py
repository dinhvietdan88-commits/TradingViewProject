import pytest
import pytest_asyncio
import aiosqlite
import json
from unittest.mock import AsyncMock, MagicMock, patch
from core.event_bus import EventBus
from core.events import TradeApproved, TradeFailed, TradeExecuted
import database
import config


@pytest_asyncio.fixture(autouse=True)
async def isolated_db(tmp_path):
    """Tao file DB rieng cho moi test, xoa sau khi xong."""
    db_file = str(tmp_path / "test_cb.db")
    config.DB_PATH = db_file
    await database.init_db()
    yield


@pytest.mark.asyncio
async def test_database_risk_settings_and_logs():
    """Verify database helpers for risk settings and circuit breaker logs."""
    # Get settings for non-existent exchange (should return defaults)
    settings = await database.get_risk_settings("non_existent")
    assert settings["exchange"] == "non_existent"
    assert settings["state"] == "CLOSED"
    assert settings["daily_loss_cap"] == 10.0
    assert settings["drawdown_cap"] == 5.0

    # Save settings
    await database.save_risk_settings(
        exchange="test_ex",
        daily_loss_cap=15.0,
        drawdown_cap=7.5,
        max_quote_qty=200.0,
        slippage_limit=0.01,
        safe_mode=0,
        state="CLOSED",
    )

    settings = await database.get_risk_settings("test_ex")
    assert settings["exchange"] == "test_ex"
    assert settings["daily_loss_cap"] == 15.0
    assert settings["drawdown_cap"] == 7.5
    assert settings["state"] == "CLOSED"

    # Update circuit breaker state
    await database.update_circuit_breaker_state("test_ex", "OPEN")
    settings = await database.get_risk_settings("test_ex")
    assert settings["state"] == "OPEN"

    # Log circuit breaker transition
    await database.log_circuit_breaker(
        exchange="test_ex",
        symbol="BTCUSDT",
        prev_state="CLOSED",
        new_state="OPEN",
        trigger_reason="Daily loss test",
        current_metrics={"dailyLoss": 20.0},
    )

    # Fetch logs to verify insertion
    async with aiosqlite.connect(config.DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM circuit_breaker_logs WHERE exchange = 'test_ex'"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert row["exchange"] == "test_ex"
            assert row["new_state"] == "OPEN"
            metrics = json.loads(row["current_metrics"])
            assert metrics["dailyLoss"] == 20.0

    # Test get_all_risk_statuses
    statuses = await database.get_all_risk_statuses()
    weex_status = next(s for s in statuses if s["exchange"] == "weex")
    assert weex_status["dailyLossCap"] == 10.0


@pytest.mark.asyncio
async def test_trade_engine_blocked_by_open_circuit_breaker():
    """Verify that TradeEngine blocks execution when circuit breaker is OPEN."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    failed_events = []

    @test_bus.on(TradeFailed)
    async def on_failed(event):
        failed_events.append(event)

    # Mock dynamic settings to return OPEN state
    mock_settings = {
        "exchange": "weex",
        "state": "OPEN",
        "daily_loss_cap": 10.0,
        "drawdown_cap": 5.0,
    }

    mock_client = AsyncMock()
    mock_client.exchange_id = "weex"

    event = TradeApproved(
        signal_id=100,
        symbol="BTCUSDT_UMCBL",
        action="BUY",
        price="68000.0",
        quote_qty="50.0",
        sl="66000.0",
        tp="72000.0",
        exchange="weex",
    )

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
    ):
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = mock_client
        mock_get_router.return_value = mock_router

        mock_db.get_risk_settings = AsyncMock(return_value=mock_settings)
        mock_db.insert_trade = AsyncMock(return_value=1)
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        # Assert trade failed and adapter order was never called
        assert len(failed_events) == 1
        assert "Circuit Breaker is OPEN" in failed_events[0].error
        mock_client.execute_smart_order.assert_not_called()


@pytest.mark.asyncio
async def test_trade_engine_auto_trips_circuit_breaker():
    """Verify that TradeEngine trips to OPEN when daily loss limits are exceeded."""
    from engine.trade_engine import execute_trade, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    failed_events = []

    @test_bus.on(TradeFailed)
    async def on_failed(event):
        failed_events.append(event)

    mock_settings = {
        "exchange": "weex",
        "state": "CLOSED",
        "daily_loss_cap": 10.0,
        "drawdown_cap": 5.0,
    }

    mock_client = AsyncMock()
    mock_client.exchange_id = "weex"

    event = TradeApproved(
        signal_id=101,
        symbol="BTCUSDT_UMCBL",
        action="BUY",
        price="68000.0",
        quote_qty="50.0",
        sl="66000.0",
        tp="72000.0",
        exchange="weex",
    )

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
    ):
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = mock_client
        mock_get_router.return_value = mock_router

        mock_db.get_risk_settings = AsyncMock(return_value=mock_settings)
        # Exceed daily loss: $12.50 > $10.00
        mock_db.get_daily_loss = AsyncMock(return_value=12.50)
        mock_db.get_rolling_drawdown = AsyncMock(return_value=2.0)
        mock_db.update_circuit_breaker_state = AsyncMock()
        mock_db.log_circuit_breaker = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=1)
        mock_db.update_signal_status = AsyncMock()

        await execute_trade(event)

        # Assert circuit breaker was tripped
        mock_db.update_circuit_breaker_state.assert_called_with("weex", "OPEN")
        mock_db.log_circuit_breaker.assert_called_once()
        assert len(failed_events) == 1
        assert "Circuit Breaker tripped to OPEN" in failed_events[0].error
        mock_client.execute_smart_order.assert_not_called()


@pytest.mark.asyncio
async def test_trade_engine_half_open_halves_position_size():
    """Verify that position size is halved in HALF-OPEN state."""
    from engine.trade_engine import execute_trade, set_bus
    from tests.unit.test_trade_engine import MockOrderResult

    test_bus = EventBus()
    set_bus(test_bus)
    executed_events = []

    @test_bus.on(TradeExecuted)
    async def on_executed(event):
        executed_events.append(event)

    mock_settings = {
        "exchange": "weex",
        "state": "HALF-OPEN",
        "daily_loss_cap": 10.0,
        "drawdown_cap": 5.0,
    }

    mock_client = AsyncMock()
    mock_client.exchange_id = "weex"
    mock_client.execute_smart_order.return_value = MockOrderResult()

    event = TradeApproved(
        signal_id=102,
        symbol="BTCUSDT_UMCBL",
        action="BUY",
        price="68000.0",
        quote_qty="50.0",
        sl="66000.0",
        tp="72000.0",
        exchange="weex",
    )

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
    ):
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = mock_client
        mock_get_router.return_value = mock_router

        mock_db.get_risk_settings = AsyncMock(return_value=mock_settings)
        mock_db.get_daily_loss = AsyncMock(return_value=0.0)
        mock_db.get_rolling_drawdown = AsyncMock(return_value=0.0)
        mock_db.insert_trade = AsyncMock(return_value=1)
        mock_db.update_signal_status = AsyncMock()
        mock_db.update_trade_oco = AsyncMock()

        await execute_trade(event)

        # Assert trade succeeded
        assert len(executed_events) == 1
        # Verify the position size was reduced by 50%
        # The original was 50.0. Under HALF-OPEN state, it should be passed to the adapter as 25.0
        args, kwargs = mock_client.execute_smart_order.call_args
        assert kwargs.get("quote_qty") == 25.0


@pytest.mark.asyncio
async def test_trade_engine_tripping_event_emitted():
    """Verify that TradeEngine emits CircuitBreakerTripped when circuit breaker is tripped."""
    from engine.trade_engine import execute_trade, set_bus
    from core.events import CircuitBreakerTripped

    test_bus = EventBus()
    set_bus(test_bus)
    tripped_events = []

    @test_bus.on(CircuitBreakerTripped)
    async def on_tripped(event):
        tripped_events.append(event)

    mock_settings = {
        "exchange": "weex",
        "state": "CLOSED",
        "daily_loss_cap": 10.0,
        "drawdown_cap": 5.0,
    }

    mock_client = AsyncMock()
    mock_client.exchange_id = "weex"

    event = TradeApproved(
        signal_id=103,
        symbol="BTCUSDT_UMCBL",
        action="BUY",
        price="68000.0",
        quote_qty="50.0",
        sl="66000.0",
        tp="72000.0",
        exchange="weex",
    )

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
    ):
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = mock_client
        mock_get_router.return_value = mock_router

        mock_db.get_risk_settings = AsyncMock(return_value=mock_settings)
        mock_db.get_daily_loss = AsyncMock(return_value=12.50)  # Exceeds cap
        mock_db.get_rolling_drawdown = AsyncMock(return_value=1.0)
        mock_db.update_circuit_breaker_state = AsyncMock()
        mock_db.log_circuit_breaker = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=1)
        mock_db.update_signal_status = AsyncMock()
        mock_db.get_setting = AsyncMock(return_value=None)  # No bypass

        await execute_trade(event)

        # Assert CircuitBreakerTripped was emitted
        assert len(tripped_events) == 1
        assert tripped_events[0].exchange == "weex"
        assert tripped_events[0].prev_state == "CLOSED"
        assert tripped_events[0].new_state == "OPEN"
        assert "Daily loss 12.50" in tripped_events[0].reason


@pytest.mark.asyncio
async def test_trade_engine_respects_bypass_setting():
    """Verify that TradeEngine does NOT trip if a valid bypass timestamp is active."""
    from engine.trade_engine import execute_trade, set_bus
    from datetime import datetime, timezone, timedelta
    from tests.unit.test_trade_engine import MockOrderResult

    test_bus = EventBus()
    set_bus(test_bus)
    executed_events = []

    @test_bus.on(TradeExecuted)
    async def on_executed(event):
        executed_events.append(event)

    mock_settings = {
        "exchange": "weex",
        "state": "CLOSED",
        "daily_loss_cap": 10.0,
        "drawdown_cap": 5.0,
    }

    mock_client = AsyncMock()
    mock_client.exchange_id = "weex"
    mock_client.execute_smart_order.return_value = MockOrderResult()

    event = TradeApproved(
        signal_id=104,
        symbol="BTCUSDT_UMCBL",
        action="BUY",
        price="68000.0",
        quote_qty="50.0",
        sl="66000.0",
        tp="72000.0",
        exchange="weex",
    )

    # Active bypass until 30 minutes in the future
    future_bypass = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()

    with (
        patch("exchanges.router.get_router") as mock_get_router,
        patch("engine.trade_engine.database") as mock_db,
    ):
        mock_router = MagicMock()
        mock_router.resolve_exchange.return_value = mock_client
        mock_get_router.return_value = mock_router

        mock_db.get_risk_settings = AsyncMock(return_value=mock_settings)
        mock_db.get_daily_loss = AsyncMock(
            return_value=12.50
        )  # Exceeds cap but bypassed
        mock_db.get_rolling_drawdown = AsyncMock(return_value=1.0)
        mock_db.update_circuit_breaker_state = AsyncMock()
        mock_db.log_circuit_breaker = AsyncMock()
        mock_db.insert_trade = AsyncMock(return_value=1)
        mock_db.update_signal_status = AsyncMock()
        mock_db.update_trade_oco = AsyncMock()
        mock_db.get_setting = AsyncMock(return_value=future_bypass)

        await execute_trade(event)

        # Assert circuit breaker was NOT tripped
        mock_db.update_circuit_breaker_state.assert_not_called()
        # Assert trade successfully executed
        assert len(executed_events) == 1
        mock_client.execute_smart_order.assert_called_once()
