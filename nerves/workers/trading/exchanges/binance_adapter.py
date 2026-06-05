import time
from typing import Dict, Any, List, Optional

from .base import OrderResult
from binance_client import BinanceClient


class BinanceAdapter:
    """Adapter wrapping existing BinanceClient to conform to ExchangeAdapter protocol."""

    def __init__(self, api_key: str, api_secret: str, testnet: bool, dry_run: bool):
        self._client = BinanceClient(api_key, api_secret, testnet, dry_run)

    @property
    def exchange_name(self) -> str:
        return "binance"

    @property
    def is_testnet(self) -> bool:
        return self._client.testnet

    @property
    def is_dry_run(self) -> bool:
        return self._client.dry_run

    @property
    def supported_order_types(self) -> List[str]:
        return ["MARKET", "LIMIT", "OCO"]

    async def get_account_balance(self, asset: str = "USDT") -> float:
        return await self._client.get_account_balance(asset)

    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        return await self._client.get_symbol_info(symbol)

    async def get_active_symbols(self) -> List[str]:
        return await self._client.get_active_symbols()

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quote_qty: Optional[float] = None,
        base_qty: Optional[float] = None,
    ) -> Dict[str, Any]:
        return await self._client.place_market_order(symbol, side, quote_qty, base_qty)

    async def place_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        take_profit_price: float,
        stop_price: float,
        stop_limit_price: float,
    ) -> Dict[str, Any]:
        return await self._client.place_oco_order(
            symbol, side, quantity, take_profit_price, stop_price, stop_limit_price
        )

    async def get_ticker_price(self, symbol: str) -> float:
        return await self._client.get_ticker_price(symbol)

    async def place_limit_order(
        self, symbol: str, side: str, price: float, quantity: float
    ) -> Dict[str, Any]:
        return await self._client.place_limit_order(symbol, side, price, quantity)

    async def get_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        return await self._client.get_order(symbol, order_id)

    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        return await self._client.cancel_order(symbol, order_id)

    async def cancel_oco_order(self, symbol: str, order_list_id: str) -> Dict[str, Any]:
        return await self._client.cancel_oco_order(symbol, order_list_id)

    async def execute_smart_order(
        self, symbol: str, side: str, **kwargs
    ) -> OrderResult:
        result = await self._client.execute_smart_order(symbol, side, **kwargs)
        result.exchange = self.exchange_name
        return result

    async def health_check(self) -> Dict[str, Any]:
        try:
            start = time.time()
            await self._client.get_symbol_info("BTCUSDT")
            latency = (time.time() - start) * 1000
            return {"healthy": True, "latency_ms": round(latency, 1), "error": None}
        except Exception as e:
            return {"healthy": False, "latency_ms": 0, "error": str(e)}
