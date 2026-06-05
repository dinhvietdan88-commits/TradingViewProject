from unittest.mock import AsyncMock


def get_mock_binance_client():
    mock_client = AsyncMock()

    # Mock order response
    mock_client.create_order.return_value = {
        "symbol": "BTCUSDT",
        "orderId": 123456789,
        "orderListId": -1,
        "clientOrderId": "testOrder123",
        "transactTime": 1715486400000,
        "price": "65000.00",
        "origQty": "0.00076",
        "executedQty": "0.00076",
        "cummulativeQuoteQty": "49.4",
        "status": "FILLED",
        "timeInForce": "GTC",
        "type": "MARKET",
        "side": "BUY",
    }

    # Mock exchange info (for precision)
    mock_client.get_exchange_info.return_value = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "baseAssetPrecision": 8,
                "quoteAssetPrecision": 8,
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.00001"},
                ],
            }
        ]
    }

    # Mock current price
    mock_client.get_symbol_ticker.return_value = {
        "symbol": "BTCUSDT",
        "price": "65000.00",
    }

    return mock_client
