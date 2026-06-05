import time
import json
import hmac
import hashlib
import logging
import aiohttp
import uuid
from typing import Dict, Any, List, Optional

from .base import OrderResult, RiskParams, ExchangeError, ExchangeErrorCategory
import config

log = logging.getLogger(__name__)


class BybitAdapter:
    """Bybit V5 API adapter implementing ExchangeAdapter protocol."""

    TESTNET_URL = "https://api-testnet.bybit.com"
    MAINNET_URL = "https://api.bybit.com"

    def __init__(self, api_key: str, api_secret: str, testnet: bool, dry_run: bool):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.dry_run = dry_run
        self.base_url = self.TESTNET_URL if testnet else self.MAINNET_URL

        mode = []
        if dry_run:
            mode.append("DRY-RUN")
        mode.append("TESTNET" if testnet else "MAINNET")
        log.info(f"BybitAdapter initialized [{', '.join(mode)}] → {self.base_url}")

    @property
    def exchange_name(self) -> str:
        return "bybit"

    @property
    def is_testnet(self) -> bool:
        return self.testnet

    @property
    def is_dry_run(self) -> bool:
        return self.dry_run

    @property
    def supported_order_types(self) -> List[str]:
        return ["MARKET", "LIMIT", "CONDITIONAL"]

    def _sign_request(self, params: Dict[str, Any]) -> Dict[str, str]:
        """Bybit V5 HMAC-SHA256 signing."""
        timestamp = str(int(time.time() * 1000))
        recv_window = "5000"
        param_str = timestamp + self.api_key + recv_window + json.dumps(params)
        signature = hmac.new(
            self.api_secret.encode(), param_str.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window,
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, endpoint: str, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        params = params or {}
        # Simple retry logic for demonstration, a real exponential backoff could be added here
        headers = (
            self._sign_request(params)
            if method in ["POST", "PUT"]
            else self._sign_request({})
        )

        url = f"{self.base_url}{endpoint}"
        async with aiohttp.ClientSession() as session:
            try:
                if method == "GET":
                    # Bybit GET signing needs param string in signing, simplfying here
                    timestamp = str(int(time.time() * 1000))
                    recv_window = "5000"
                    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
                    param_str = timestamp + self.api_key + recv_window + query_string
                    signature = hmac.new(
                        self.api_secret.encode(), param_str.encode(), hashlib.sha256
                    ).hexdigest()
                    headers = {
                        "X-BAPI-API-KEY": self.api_key,
                        "X-BAPI-SIGN": signature,
                        "X-BAPI-TIMESTAMP": timestamp,
                        "X-BAPI-RECV-WINDOW": recv_window,
                    }
                    async with session.get(url, params=params, headers=headers) as resp:
                        data = await resp.json()
                else:
                    async with session.post(url, json=params, headers=headers) as resp:
                        data = await resp.json()

                if data.get("retCode") != 0:
                    retCode = data.get("retCode")
                    msg = data.get("retMsg", "")
                    category = ExchangeErrorCategory.UNKNOWN
                    if retCode in [110007]:
                        category = ExchangeErrorCategory.INSUFFICIENT_BALANCE
                    elif retCode in [110008]:
                        category = ExchangeErrorCategory.INVALID_SYMBOL
                    elif retCode in [10006]:
                        category = ExchangeErrorCategory.RATE_LIMITED
                    elif retCode in [10003, 10004]:
                        category = ExchangeErrorCategory.AUTHENTICATION_ERROR
                    elif retCode in [110001, 110003]:
                        category = ExchangeErrorCategory.ORDER_REJECTED
                    raise ExchangeError(
                        category,
                        f"Bybit Error [{retCode}]: {msg}",
                        str(retCode),
                        self.exchange_name,
                    )

                return data
            except aiohttp.ClientError as e:
                raise ExchangeError(
                    ExchangeErrorCategory.CONNECTION_ERROR,
                    str(e),
                    None,
                    self.exchange_name,
                )

    async def get_account_balance(self, asset: str = "USDT") -> float:
        if self.dry_run:
            return 10000.0

        data = await self._request(
            "GET",
            "/v5/account/wallet-balance",
            {"accountType": "UNIFIED", "coin": asset},
        )
        balances = data.get("result", {}).get("list", [])
        if balances and balances[0].get("coin", []):
            coins = balances[0]["coin"]
            for c in coins:
                if c["coin"] == asset:
                    return float(c.get("walletBalance", 0))
        return 0.0

    async def get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        if self.dry_run:
            return {"symbol": symbol, "status": "Trading"}

        data = await self._request(
            "GET", "/v5/market/instruments-info", {"category": "spot", "symbol": symbol}
        )
        return data.get("result", {}).get("list", [{}])[0]

    async def get_active_symbols(self) -> List[str]:
        if self.dry_run:
            return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]
        try:
            data = await self._request(
                "GET", "/v5/market/instruments-info", {"category": "spot"}
            )
            instruments = data.get("result", {}).get("list", [])
            active_symbols = []
            for inst in instruments:
                sym = inst.get("symbol", "")
                status = inst.get("status", "")
                if sym.endswith("USDT") and status.upper() == "TRADING":
                    active_symbols.append(sym)
            return active_symbols
        except Exception as e:
            log.error(f"Error fetching active symbols from Bybit: {e}")
            return ["BTCUSDT", "ETHUSDT"]

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quote_qty: Optional[float] = None,
        base_qty: Optional[float] = None,
    ) -> Dict[str, Any]:
        params = {
            "category": "spot",
            "symbol": symbol,
            "side": side.capitalize(),
            "orderType": "Market",
        }
        if base_qty:
            params["qty"] = str(round(base_qty, 8))
        elif quote_qty:
            params["qty"] = str(round(quote_qty, 8))
            params["marketUnit"] = "quoteCoin"

        if self.dry_run:
            fill_price = 67500.0  # Mock price
            qty = quote_qty / fill_price if quote_qty else base_qty
            return {
                "orderId": f"DRY-BYB-{uuid.uuid4().hex[:8]}",
                "executedQty": str(round(qty, 8)),
                "cummulativeQuoteQty": str(round(qty * fill_price, 2)),
                "_dry_run": True,
            }

        data = await self._request("POST", "/v5/order/create", params)
        # We need to fetch order details to get executedQty. For now, returning standard format
        res = data.get("result", {})
        return {
            "orderId": res.get("orderId"),
            "executedQty": params.get("qty"),  # Approximate for Market
            "cummulativeQuoteQty": str(quote_qty) if quote_qty else "0",
        }

    async def place_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        take_profit_price: float,
        stop_price: float,
        stop_limit_price: float,
    ) -> Dict[str, Any]:
        # Bybit SPOT OCO is not strictly OCO natively via v5 in the same way, but it supports TP/SL on spot orders using specific categories.
        # For simplicity, we create conditional orders or mock them.
        if self.dry_run:
            return {
                "orderListId": f"DRY-BYB-OCO-{uuid.uuid4().hex[:8]}",
                "orders": [],
                "_dry_run": True,
            }

        # Place TP
        tp_params = {
            "category": "spot",
            "symbol": symbol,
            "side": side.capitalize(),
            "orderType": "Limit",
            "qty": str(round(quantity, 8)),
            "price": str(round(take_profit_price, 2)),
        }
        await self._request("POST", "/v5/order/create", tp_params)

        # Place SL
        sl_params = {
            "category": "spot",
            "symbol": symbol,
            "side": side.capitalize(),
            "orderType": "Limit",
            "qty": str(round(quantity, 8)),
            "price": str(round(stop_limit_price, 2)),
            "triggerPrice": str(round(stop_price, 2)),
            "triggerDirection": 1 if side.upper() == "BUY" else 2,
        }
        res = await self._request("POST", "/v5/order/create", sl_params)

        return {
            "orderListId": res.get("result", {}).get("orderId"),
            "type": "SIMULATED_OCO",
        }

    async def get_ticker_price(self, symbol: str) -> float:
        if self.dry_run:
            return 67500.0
        try:
            symbol_clean = symbol.replace("/", "").upper()
            data = await self._request(
                "GET",
                "/v5/market/tickers",
                {"category": "spot", "symbol": symbol_clean},
            )
            list_data = data.get("result", {}).get("list", [])
            if list_data:
                return float(list_data[0].get("lastPrice", 0.0))
        except Exception as e:
            log.error(f"Error fetching Bybit ticker price: {e}")
        return 67500.0

    async def place_limit_order(
        self, symbol: str, side: str, price: float, quantity: float
    ) -> Dict[str, Any]:
        params = {
            "category": "spot",
            "symbol": symbol.replace("/", "").upper(),
            "side": side.capitalize(),
            "orderType": "Limit",
            "price": str(round(price, 4)),
            "qty": str(round(quantity, 8)),
            "timeInForce": "GTC",
        }
        if self.dry_run:
            return {
                "orderId": f"DRY-BYB-LIM-{uuid.uuid4().hex[:8]}",
                "status": "NEW",
                "price": str(price),
                "qty": str(quantity),
                "_dry_run": True,
            }
        data = await self._request("POST", "/v5/order/create", params)
        res = data.get("result", {})
        return {"orderId": res.get("orderId"), "status": "NEW"}

    async def get_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        if self.dry_run:
            return {"status": "NEW"}
        try:
            data = await self._request(
                "GET",
                "/v5/order/realtime-order",
                {
                    "category": "spot",
                    "symbol": symbol.replace("/", "").upper(),
                    "orderId": order_id,
                },
            )
            res = data.get("result", {}).get("list", [{}])[0]
            status = res.get("orderStatus", "New")
            return {"status": "FILLED" if status.upper() == "FILLED" else "NEW"}
        except Exception:
            return {"status": "NEW"}

    async def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        if self.dry_run:
            return {"status": "CANCELED"}
        await self._request(
            "POST",
            "/v5/order/cancel",
            {
                "category": "spot",
                "symbol": symbol.replace("/", "").upper(),
                "orderId": order_id,
            },
        )
        return {"status": "CANCELED"}

    async def cancel_oco_order(self, symbol: str, order_list_id: str) -> Dict[str, Any]:
        return await self.cancel_order(symbol, order_list_id)

    async def execute_smart_order(
        self,
        symbol: str,
        side: str,
        entry_price: Optional[float] = None,
        quote_qty: Optional[float] = None,
        sl_pct: Optional[float] = None,
        tp_pct: Optional[float] = None,
        risk_pct: Optional[float] = None,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        asset: str = "USDT",
        order_type: str = "MARKET",
    ) -> OrderResult:
        """Simplified smart order for Bybit, mimicking Binance logic."""
        symbol_clean = symbol.replace("/", "").upper()
        side_upper = side.upper()
        sl_pct = sl_pct or config.STOP_LOSS_PCT
        tp_pct = tp_pct or config.TAKE_PROFIT_PCT
        risk_pct = risk_pct or config.RISK_PER_TRADE

        try:
            balance = await self.get_account_balance(asset)

            # SL/TP
            if side_upper == "BUY":
                sl = entry_price * (1 - sl_pct)
                tp = entry_price * (1 + tp_pct)
            else:
                sl = entry_price * (1 + sl_pct)
                tp = entry_price * (1 - tp_pct)

            sl_price = sl_price or sl
            tp_price = tp_price or tp
            rr_ratio = (
                abs(tp_price - entry_price) / abs(sl_price - entry_price)
                if abs(sl_price - entry_price) > 0
                else 0
            )

            # Risk Sizing
            risk_amount = balance * risk_pct
            distance = abs(entry_price - sl_price)
            qty = risk_amount / distance if distance > 0 else 0
            if quote_qty:
                qty = quote_qty / entry_price if entry_price > 0 else qty
            cost = qty * entry_price

            # Cap at 95%
            if cost > balance * 0.95:
                qty = (balance * 0.95) / entry_price
                cost = qty * entry_price

            risk_params = RiskParams(
                entry_price=entry_price,
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
                risk_reward_ratio=rr_ratio,
                quantity=qty,
                cost=cost,
                risk_amount=risk_amount,
                account_balance=balance,
                position_pct=cost / balance if balance > 0 else 0,
            )

            # 4. entry
            if order_type.upper() == "LIMIT":
                entry_result = await self.place_limit_order(
                    symbol_clean, side_upper, price=entry_price, quantity=qty
                )
            elif quote_qty:
                entry_result = await self.place_market_order(
                    symbol_clean, side_upper, quote_qty=quote_qty
                )
            else:
                entry_result = await self.place_market_order(
                    symbol_clean, side_upper, base_qty=qty
                )

            # 5. OCO exit
            exit_side = "SELL" if side_upper == "BUY" else "BUY"
            stop_limit = sl_price * 0.995 if exit_side == "SELL" else sl_price * 1.005

            oco_result = await self.place_oco_order(
                symbol=symbol_clean,
                side=exit_side,
                quantity=qty,
                take_profit_price=tp_price,
                stop_price=sl_price,
                stop_limit_price=stop_limit,
            )

            return OrderResult(
                success=True,
                dry_run=self.dry_run,
                side=side_upper,
                symbol=symbol_clean,
                exchange=self.exchange_name,
                entry_order=entry_result,
                oco_order=oco_result,
                risk=risk_params,
            )

        except ExchangeError as e:
            return OrderResult(
                success=False,
                dry_run=self.dry_run,
                side=side_upper,
                symbol=symbol_clean,
                exchange=self.exchange_name,
                error=str(e),
                error_category=e.category,
            )
        except Exception as e:
            return OrderResult(
                success=False,
                dry_run=self.dry_run,
                side=side_upper,
                symbol=symbol_clean,
                exchange=self.exchange_name,
                error=str(e),
                error_category=ExchangeErrorCategory.UNKNOWN,
            )

    async def health_check(self) -> Dict[str, Any]:
        try:
            start = time.time()
            if not self.dry_run:
                await self.get_symbol_info("BTCUSDT")
            latency = (time.time() - start) * 1000
            return {"healthy": True, "latency_ms": round(latency, 1), "error": None}
        except Exception as e:
            return {"healthy": False, "latency_ms": 0, "error": str(e)}
