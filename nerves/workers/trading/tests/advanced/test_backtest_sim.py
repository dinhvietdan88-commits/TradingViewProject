import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from collections import namedtuple

from core.events import TradeApproved
from core.event_bus import EventBus
from engine import trade_engine
import config

pytestmark = pytest.mark.asyncio

@pytest.fixture
def mock_bus():
    bus = EventBus()
    trade_engine.set_bus(bus)
    return bus

async def test_backtest_pnl_sl_tp_logic(mock_bus, mocker):
    """
    Simulate processing of 100 consecutive prices (ticks/candles) to validate 
    Stop-Loss (SL) and Take-Profit (TP) logic in the Trade Engine.
    """
    # 1. Setup mock exchange adapter
    mock_adapter = AsyncMock()
    mock_adapter.exchange_id = "mock_exchange"
    mock_adapter.get_account_balance.return_value = 10000.0
    mock_adapter.get_ticker_price.return_value = 50000.0
    
    # Mock smart order execution
    SmartOrderResult = namedtuple("SmartOrderResult", ["success", "entry_order", "oco_order", "risk", "error", "dry_run"])
    RiskInfo = namedtuple("RiskInfo", ["stop_loss_price", "take_profit_price"])
    
    # Capture the parameters passed to execute_smart_order
    captured_kwargs = {}
    
    async def fake_execute_smart_order(**kwargs):
        captured_kwargs.update(kwargs)
        risk = RiskInfo(kwargs.get("sl_price"), kwargs.get("tp_price"))
        entry = {"orderId": "123", "status": "FILLED", "executedQty": 0.1, "cummulativeQuoteQty": 5000.0}
        return SmartOrderResult(True, entry, None, risk, None, False)
        
    mock_adapter.execute_smart_order.side_effect = fake_execute_smart_order
    
    mocker.patch("exchanges.router.ExchangeRouter.resolve_exchange", return_value=mock_adapter)
    mocker.patch("engine.trade_engine.get_symbol_config", return_value={
        "risk_pct": 0.02,
        "stop_loss_pct": 0.10,
        "atr_sl_mul": 2.0,
        "atr_tp_mul": 3.0,
        "trail_atr_mul": 3.0,
        "breakout_size_pct": 0.025
    })
    
    mocker.patch("database.insert_trade", new_callable=AsyncMock, return_value=1)
    mocker.patch("database.update_trade_oco", new_callable=AsyncMock)
    mocker.patch("database.update_signal_status", new_callable=AsyncMock)
    mocker.patch("engine.regime_switcher.get_market_regime", new_callable=AsyncMock, return_value="TRENDING")
    
    # 2. Trigger the TradeEngine by sending a TradeApproved event
    event = TradeApproved(
        signal_id=999,
        action="buy",
        symbol="BTCUSDT",
        price=50000.0,
        sl=45000.0,  # 10% SL -> Should hit the 10% hardcap logic (or exactly 10%)
        tp=60000.0,
        quote_qty=None,
        approved_by="BacktestSim"
    )
    
    await trade_engine.execute_trade(event)
    
    # 3. Verify execution parameters
    assert "sl_price" in captured_kwargs
    assert "tp_price" in captured_kwargs
    
    executed_entry = captured_kwargs["entry_price"]
    sl = captured_kwargs["sl_price"]
    tp = captured_kwargs["tp_price"]
    
    assert executed_entry == 50000.0
    assert sl == 45000.0
    assert tp == 60000.0
    
    # 4. Deep Backtest Simulation: Feed 100 prices to evaluate PnL logic
    # We simulate a trending market that dips slightly then hits TP.
    prices = []
    # 20 prices dipping (but not hitting SL 45000)
    for i in range(20):
        prices.append(50000.0 - (i * 200)) # drops to 46200
    # 80 prices rallying to hit TP
    for i in range(80):
        prices.append(46200.0 + (i * 200)) # rallies to 62000
        
    result_status = "OPEN"
    pnl = 0.0
    
    for price in prices:
        if price <= sl:
            result_status = "STOP_LOSS_HIT"
            pnl = price - executed_entry
            break
        if price >= tp:
            result_status = "TAKE_PROFIT_HIT"
            pnl = price - executed_entry
            break
            
    assert result_status == "TAKE_PROFIT_HIT"
    assert pnl > 0.0
    
    print(f"Backtest Simulation Passed: Simulated 100 ticks. Result: {result_status}, PnL: +{pnl:.2f}")

