import pytest
from unittest.mock import AsyncMock, patch
from exchanges.weex_adapter import WeexAdapter
from exchanges.base import ExchangeErrorCategory

@pytest.mark.asyncio
async def test_weex_adapter_properties():
    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",
        passphrase="mock_passphrase",
        testnet=True,
        dry_run=True
    )
    assert adapter.exchange_name == "weex"
    assert adapter.exchange_id == "weex"
    assert adapter.is_testnet is True
    assert adapter.is_dry_run is True
    assert "MARKET" in adapter.supported_order_types

def test_weex_signature_generation():
    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",
        passphrase="mock_passphrase",
        testnet=True,
        dry_run=True
    )
    timestamp = "1684812345000"
    method = "POST"
    request_path = "/api/v2/contract/trade/order"
    body = '{"symbol":"BTCUSDT_UMCBL"}'
    
    headers = adapter._sign_request(method, request_path, body)
        
    assert headers["ACCESS-KEY"] == "mock_key"
    assert headers["ACCESS-PASSPHRASE"] == "mock_passphrase"
    assert headers["Content-Type"] == "application/json"
    assert "ACCESS-SIGN" in headers
    assert "ACCESS-TIMESTAMP" in headers

@pytest.mark.asyncio
async def test_weex_dry_run_balance():
    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",
        passphrase="mock_passphrase",
        testnet=True,
        dry_run=True
    )
    balance = await adapter.get_account_balance("USDT")
    assert balance == 10000.0

@pytest.mark.asyncio
async def test_weex_dry_run_smart_order():
    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",
        passphrase="mock_passphrase",
        testnet=True,
        dry_run=True
    )
    result = await adapter.execute_smart_order(
        symbol="BTCUSDT",
        side="BUY",
        entry_price=60000.0,
        sl_price=58000.0,
        tp_price=64000.0,
        quote_qty=100.0
    )
    assert result.success is True
    assert result.dry_run is True
    assert result.symbol == "BTCUSDT_UMCBL"
    assert result.side == "BUY"
    assert result.entry_order["status"] == "FILLED"
    assert result.entry_order["executedQty"] is not None
    assert result.oco_order["type"] == "SIMULATED_OCO"


@pytest.mark.asyncio
async def test_weex_smart_order_slippage_adjustment():
    """Verify Stop-Loss and Take-Profit values are shifted by slippage in Weex adapter."""
    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",
        passphrase="mock_passphrase",
        testnet=True,
        dry_run=True
    )
    # Entry price is 100.0, but actual fill price is 102.0 (cummulativeQuoteQty=204.0, executedQty=2.0)
    with patch.object(adapter, "place_market_order", AsyncMock(return_value={
        "orderId": "DRY-MOCK-WEEX-ENTRY",
        "executedQty": "2.0",
        "cummulativeQuoteQty": "204.0",  # fill price = 204.0 / 2.0 = 102.0
        "status": "FILLED",
        "_dry_run": True
    })) as mock_place_order:
        result = await adapter.execute_smart_order(
            symbol="BTCUSDT",
            side="BUY",
            entry_price=100.0,
            sl_price=90.0,
            tp_price=125.0,
            quote_qty=100.0
        )
        assert result.success is True
        assert result.risk.entry_price == 102.0
        # SL must be shifted: 90.0 + 2.0 = 92.0
        assert result.risk.stop_loss_price == 92.0
        # TP must be shifted: 125.0 + 2.0 = 127.0
        assert result.risk.take_profit_price == 127.0


@pytest.mark.asyncio
async def test_weex_smart_order_position_capped():
    """Verify position size is capped at 95% of available balance in Weex adapter."""
    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",
        passphrase="mock_passphrase",
        testnet=True,
        dry_run=True
    )
    # Account balance is 10,000 USDT in dry-run.
    # Large order with very low entry price and extremely tight stop loss:
    # risk_amount = 10,000 * 0.02 = 200 USDT.
    # Entry = 10.0, SL = 9.999 (distance = 0.001).
    # Uncapped qty = 200 / 0.001 = 200,000. Cost = 2,000,000 USDT.
    # Cap at 95% of balance = 9,500 USDT.
    result = await adapter.execute_smart_order(
        symbol="BTCUSDT",
        side="BUY",
        entry_price=10.0,
        sl_price=9.999,
    )
    assert result.success is True
    assert result.risk.cost <= 10000.0 * 0.95 + 0.01

