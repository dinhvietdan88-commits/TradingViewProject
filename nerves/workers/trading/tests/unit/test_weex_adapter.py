from unittest.mock import AsyncMock, patch

import pytest

from exchanges.base import ExchangeError, ExchangeErrorCategory
from exchanges.weex_adapter import WeexAdapter


@pytest.mark.asyncio
async def test_weex_adapter_properties():
    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",
        passphrase="mock_passphrase",
        testnet=True,
        dry_run=True,
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
        dry_run=True,
    )
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
        dry_run=True,
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
        dry_run=True,
    )
    result = await adapter.execute_smart_order(
        symbol="BTCUSDT",
        side="BUY",
        entry_price=60000.0,
        sl_price=58000.0,
        tp_price=64000.0,
        quote_qty=100.0,
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
        dry_run=True,
    )
    # Entry price is 100.0, but actual fill price is 102.0 (cummulativeQuoteQty=204.0, executedQty=2.0)
    with patch.object(
        adapter,
        "place_market_order",
        AsyncMock(
            return_value={
                "orderId": "DRY-MOCK-WEEX-ENTRY",
                "executedQty": "2.0",
                "cummulativeQuoteQty": "204.0",  # fill price = 204.0 / 2.0 = 102.0
                "status": "FILLED",
                "_dry_run": True,
            }
        ),
    ):
        result = await adapter.execute_smart_order(
            symbol="BTCUSDT",
            side="BUY",
            entry_price=100.0,
            sl_price=90.0,
            tp_price=125.0,
            quote_qty=100.0,
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
        dry_run=True,
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


@pytest.mark.asyncio
async def test_weex_smart_order_micro_volume_limits():
    """Verify Weex adapter enforces micro-volume minimums and cost range clamping."""
    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",
        passphrase="mock_passphrase",
        testnet=True,
        dry_run=True,
    )

    # 1. BTC should clamp to 0.001 BTC minimum
    res_btc = await adapter.execute_smart_order(
        symbol="BTCUSDT",
        side="BUY",
        entry_price=60000.0,
        sl_price=55000.0,
        quote_qty=6.0,  # Unclamped qty = 0.0001 BTC
    )
    assert res_btc.success is True
    assert res_btc.risk.quantity >= 0.001

    # 2. ETH should clamp to 0.01 ETH minimum
    res_eth = await adapter.execute_smart_order(
        symbol="ETHUSDT",
        side="BUY",
        entry_price=3000.0,
        sl_price=2700.0,
        quote_qty=3.0,  # Unclamped qty = 0.001 ETH
    )
    assert res_eth.success is True
    assert res_eth.risk.quantity >= 0.01

    # 3. SOL (other asset) with small value should clamp value to $5.00 minimum
    res_sol_small = await adapter.execute_smart_order(
        symbol="SOLUSDT",
        side="BUY",
        entry_price=100.0,
        sl_price=90.0,
        quote_qty=1.0,  # Unclamped qty = 0.01 SOL (value = $1.00)
    )
    assert res_sol_small.success is True
    assert res_sol_small.risk.cost >= 5.0

    # 4. SOL with large value should clamp value to $10.00 maximum
    res_sol_large = await adapter.execute_smart_order(
        symbol="SOLUSDT",
        side="BUY",
        entry_price=100.0,
        sl_price=90.0,
        quote_qty=20.0,  # Unclamped qty = 0.20 SOL (value = $20.00)
    )
    assert res_sol_large.success is True
    assert res_sol_large.risk.cost <= 10.0 + 0.01


@pytest.mark.asyncio
async def test_weex_http_error_handling():
    """Verify Weex adapter _request raises ExchangeError for status >= 400."""
    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",
        passphrase="mock_passphrase",
        testnet=True,
        dry_run=False,
    )

    mock_resp = AsyncMock()
    mock_resp.__aenter__.return_value.status = 500
    mock_resp.__aenter__.return_value.json = AsyncMock(return_value={})

    # We patch ClientSession's request methods
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        with pytest.raises(ExchangeError) as exc_info:
            await adapter._request("GET", "/api/v2/contract/public/symbols")
        assert exc_info.value.category == ExchangeErrorCategory.CONNECTION_ERROR
        assert "HTTP Error 500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_weex_orphan_position_prevention():
    """Verify that Weex entry order is cancelled if subsequent OCO exit placement fails."""
    adapter = WeexAdapter(
        api_key="mock_key",
        api_secret="mock_secret",
        passphrase="mock_passphrase",
        testnet=True,
        dry_run=False,
    )

    entry_mock_res = {
        "orderId": "MOCK-ENTRY-123",
        "executedQty": "0.01",
        "cummulativeQuoteQty": "30.0",
        "status": "FILLED",
    }

    # Mock place_market_order to succeed, place_oco_order to fail, cancel_order to succeed
    with (
        patch.object(
            adapter, "place_market_order", AsyncMock(return_value=entry_mock_res)
        ),
        patch.object(adapter, "get_account_balance", AsyncMock(return_value=1000.0)),
        patch.object(
            adapter,
            "place_oco_order",
            AsyncMock(side_effect=Exception("OCO API Error")),
        ),
        patch.object(
            adapter, "cancel_order", AsyncMock(return_value={"status": "CANCELED"})
        ) as mock_cancel,
    ):
        result = await adapter.execute_smart_order(
            symbol="ETHUSDT",
            side="BUY",
            entry_price=3000.0,
            sl_price=2700.0,
            tp_price=3600.0,
            quote_qty=30.0,
        )

        # Verify result is a failure and cancel_order was called for the entry order ID
        assert result.success is False
        assert "OCO placement failed" in result.error
        assert result.error_category == ExchangeErrorCategory.ORDER_REJECTED
        mock_cancel.assert_called_once_with("ETHUSDT_UMCBL", "MOCK-ENTRY-123")
