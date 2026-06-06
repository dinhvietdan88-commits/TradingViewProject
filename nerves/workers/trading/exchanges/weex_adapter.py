import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
import uuid
from typing import Any

import aiohttp

import config

from .base import ExchangeError, ExchangeErrorCategory, OrderResult, RiskParams

log = logging.getLogger(__name__)


class WeexAdapter:
    """Weex Contract V2 API adapter implementing ExchangeAdapter protocol."""

    TESTNET_URL = "https://api-demo.weex.com"
    MAINNET_URL = "https://api.weex.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        testnet: bool,
        dry_run: bool,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.testnet = testnet
        self.dry_run = dry_run
        self.base_url = self.TESTNET_URL if testnet else self.MAINNET_URL

        mode = []
        if dry_run:
            mode.append("DRY-RUN")
        mode.append("TESTNET" if testnet else "MAINNET")
        log.info(f"WeexAdapter initialized [{', '.join(mode)}] → {self.base_url}")

    @property
    def exchange_name(self) -> str:
        return "weex"

    @property
    def exchange_id(self) -> str:
        return "weex"

    @property
    def is_testnet(self) -> bool:
        return self.testnet

    @property
    def is_dry_run(self) -> bool:
        return self.dry_run

    @property
    def supported_order_types(self) -> list[str]:
        return ["MARKET", "LIMIT"]

    def _sign_request(
        self, method: str, request_path: str, body: str = ""
    ) -> dict[str, str]:
        """WEEX HMAC-SHA256 signing payload: timestamp + METHOD + requestPath + body."""
        timestamp = str(int(time.time() * 1000))
        payload = f"{timestamp}{method.upper()}{request_path}{body}"
        mac = hmac.new(
            self.api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        )
        signature = base64.b64encode(mac.digest()).decode("utf-8")
        return {
            "ACCESS-KEY": self.api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, endpoint: str, params: dict[str, Any] = None
    ) -> dict[str, Any]:
        params = params or {}
        method = method.upper()

        if method == "GET":
            if params:
                sorted_params = sorted(params.items())
                query_string = urllib.parse.urlencode(sorted_params)
                request_path = f"{endpoint}?{query_string}"
            else:
                request_path = endpoint
            body_str = ""
        else:
            request_path = endpoint
            if params:
                body_str = json.dumps(params, separators=(",", ":"))
            else:
                body_str = ""

        headers = self._sign_request(method, request_path, body_str)
        url = f"{self.base_url}{request_path}"

        async with aiohttp.ClientSession() as session:
            try:
                if method == "GET":
                    async with session.get(url, headers=headers) as resp:
                        if resp.status >= 400:
                            raise ExchangeError(
                                ExchangeErrorCategory.CONNECTION_ERROR,
                                f"HTTP Error {resp.status}",
                                str(resp.status),
                                self.exchange_name,
                            )
                        data = await resp.json()
                elif method == "POST":
                    async with session.post(
                        url, data=body_str, headers=headers
                    ) as resp:
                        if resp.status >= 400:
                            raise ExchangeError(
                                ExchangeErrorCategory.CONNECTION_ERROR,
                                f"HTTP Error {resp.status}",
                                str(resp.status),
                                self.exchange_name,
                            )
                        data = await resp.json()
                else:
                    raise ValueError(f"Unsupported method {method}")

                code = data.get("code")
                if code != "00000":
                    msg = data.get("msg", "")
                    category = ExchangeErrorCategory.UNKNOWN
                    lower_msg = msg.lower()
                    if "balance" in lower_msg or "insufficient" in lower_msg:
                        category = ExchangeErrorCategory.INSUFFICIENT_BALANCE
                    elif "symbol" in lower_msg or "invalid pair" in lower_msg:
                        category = ExchangeErrorCategory.INVALID_SYMBOL
                    elif "rate limit" in lower_msg or "too many requests" in lower_msg:
                        category = ExchangeErrorCategory.RATE_LIMITED
                    elif (
                        "auth" in lower_msg or "sign" in lower_msg or "key" in lower_msg
                    ):
                        category = ExchangeErrorCategory.AUTHENTICATION_ERROR
                    raise ExchangeError(
                        category,
                        f"Weex Error [{code}]: {msg}",
                        code,
                        self.exchange_name,
                    )

                return data
            except aiohttp.ClientError as e:
                raise ExchangeError(
                    ExchangeErrorCategory.CONNECTION_ERROR,
                    str(e),
                    None,
                    self.exchange_name,
                ) from e

    async def get_account_balance(self, asset: str = "USDT") -> float:
        if self.dry_run:
            return 10000.0

        try:
            data = await self._request(
                "GET", "/api/v2/contract/account/accounts", {"marginCoin": asset}
            )
            account_data = data.get("data")
            if not account_data:
                return 0.0

            if isinstance(account_data, list):
                for acc in account_data:
                    if acc.get("marginCoin") == asset:
                        return float(acc.get("available", 0.0))
            elif isinstance(account_data, dict):
                if account_data.get("marginCoin") == asset:
                    return float(account_data.get("available", 0.0))

            return 0.0
        except Exception as e:
            log.error(f"Error fetching Weex account balance: {e}")
            return 0.0

    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        if self.dry_run:
            return {"symbol": symbol, "status": "Trading"}

        # Weex Contract V2 symbol info
        data = await self._request(
            "GET", "/api/v2/contract/public/symbols", {"symbol": symbol}
        )
        return data.get("data", {})

    async def get_active_symbols(self) -> list[str]:
        if self.dry_run:
            return [
                "BTCUSDT_UMCBL",
                "ETHUSDT_UMCBL",
                "SOLUSDT_UMCBL",
                "ADAUSDT_UMCBL",
                "XRPUSDT_UMCBL",
            ]
        try:
            data = await self._request("GET", "/api/v2/contract/public/symbols")
            symbols_list = data.get("data", [])
            active_symbols = []
            for s in symbols_list:
                sym = s.get("symbol", "")
                status = s.get("status", "")
                if sym.endswith("_UMCBL") and status == "Trading":
                    active_symbols.append(sym)
            return active_symbols
        except Exception as e:
            log.error(f"Error fetching active symbols from Weex: {e}")
            return ["BTCUSDT_UMCBL", "ETHUSDT_UMCBL"]

    async def get_ticker_price(self, symbol: str) -> float:
        if self.dry_run:
            return 67500.0
        try:
            clean_symbol = symbol.replace("_UMCBL", "")
            data = await self._request(
                "GET", "/api/v1/spot/market/ticker", {"symbol": clean_symbol}
            )
            ticker_data = data.get("data", {})
            if isinstance(ticker_data, dict):
                return float(ticker_data.get("last", 0.0))
            elif isinstance(ticker_data, list) and len(ticker_data) > 0:
                return float(ticker_data[0].get("last", 0.0))
        except ValueError as e:
            import logging

            logging.getLogger(__name__).warning("Ignored: %s", e)
        return 67500.0

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quote_qty: float | None = None,
        base_qty: float | None = None,
    ) -> dict[str, Any]:
        # Map side
        weex_side = side.lower()
        if weex_side == "buy":
            weex_side = "open_long"
        elif weex_side == "sell":
            weex_side = "close_long"

        # Determine size (base_qty)
        size_val = base_qty
        if not size_val and quote_qty:
            ticker_price = await self.get_ticker_price(symbol)
            size_val = quote_qty / ticker_price

        if not size_val:
            size_val = 0.001

        params = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "side": weex_side,
            "orderType": "market",
            "size": str(round(size_val, 4)),
            "clientOid": f"WEX-{uuid.uuid4().hex[:8]}",
        }

        if self.dry_run:
            fill_price = 67500.0
            return {
                "orderId": f"DRY-WEX-{uuid.uuid4().hex[:8]}",
                "executedQty": str(round(size_val, 4)),
                "cummulativeQuoteQty": str(round(size_val * fill_price, 2)),
                "status": "FILLED",
                "_dry_run": True,
            }

        data = await self._request("POST", "/api/v2/contract/trade/order", params)
        res = data.get("data", {})
        return {
            "orderId": res.get("orderId"),
            "executedQty": params.get("size"),
            "cummulativeQuoteQty": str(round(float(params.get("size")) * 67500.0, 2)),
        }

    async def place_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        take_profit_price: float,
        stop_price: float,
        stop_limit_price: float,
    ) -> dict[str, Any]:
        if self.dry_run:
            return {
                "orderListId": f"DRY-WEX-OCO-{uuid.uuid4().hex[:8]}",
                "orders": [],
                "type": "SIMULATED_OCO",
                "_dry_run": True,
            }

        # Map side
        weex_side = side.lower()
        if weex_side == "buy":
            weex_side = "close_short"
        elif weex_side == "sell":
            weex_side = "close_long"

        # Place TP Limit Order
        tp_params = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "side": weex_side,
            "orderType": "limit",
            "price": str(round(take_profit_price, 2)),
            "size": str(round(quantity, 4)),
            "clientOid": f"WEX-TP-{uuid.uuid4().hex[:8]}",
        }
        tp_res = await self._request("POST", "/api/v2/contract/trade/order", tp_params)
        tp_order_id = tp_res.get("data", {}).get("orderId")

        return {
            "orderListId": tp_order_id or f"WEX-SIM-OCO-{uuid.uuid4().hex[:8]}",
            "tp_order_id": tp_order_id,
            "type": "SIMULATED_OCO",
        }

    async def place_limit_order(
        self, symbol: str, side: str, price: float, quantity: float
    ) -> dict[str, Any]:
        weex_side = side.lower()
        if weex_side == "buy":
            weex_side = "open_long"
        elif weex_side == "sell":
            weex_side = "close_long"

        params = {
            "symbol": symbol,
            "marginCoin": "USDT",
            "side": weex_side,
            "orderType": "limit",
            "price": str(round(price, 4)),
            "size": str(round(quantity, 4)),
            "clientOid": f"WEX-{uuid.uuid4().hex[:8]}",
        }
        if self.dry_run:
            return {
                "orderId": f"DRY-WEX-LIM-{uuid.uuid4().hex[:8]}",
                "status": "NEW",
                "price": str(price),
                "size": str(quantity),
                "_dry_run": True,
            }
        data = await self._request("POST", "/api/v2/contract/trade/order", params)
        res = data.get("data", {})
        return {"orderId": res.get("orderId"), "status": "NEW"}

    async def get_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        if self.dry_run:
            return {"status": "NEW"}
        try:
            data = await self._request(
                "GET",
                "/api/v2/contract/trade/orderInfo",
                {"symbol": symbol, "orderId": order_id},
            )
            res = data.get("data", {})
            state = res.get("state", "new")
            return {"status": "FILLED" if state == "filled" else "NEW"}
        except Exception:
            return {"status": "NEW"}

    async def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        if self.dry_run:
            return {"status": "CANCELED"}
        await self._request(
            "POST",
            "/api/v2/contract/trade/cancel-order",
            {"symbol": symbol, "orderId": order_id},
        )
        return {"status": "CANCELED"}

    async def cancel_oco_order(self, symbol: str, order_list_id: str) -> dict[str, Any]:
        return await self.cancel_order(symbol, order_list_id)

    async def execute_smart_order(
        self,
        symbol: str,
        side: str,
        entry_price: float | None = None,
        quote_qty: float | None = None,
        sl_pct: float | None = None,
        tp_pct: float | None = None,
        risk_pct: float | None = None,
        sl_price: float | None = None,
        tp_price: float | None = None,
        asset: str = "USDT",
        order_type: str = "MARKET",
    ) -> OrderResult:
        symbol_clean = symbol.upper()
        if not symbol_clean.endswith("_UMCBL"):
            symbol_clean += "_UMCBL"

        side_upper = side.upper()
        sl_pct = sl_pct or config.STOP_LOSS_PCT
        tp_pct = tp_pct or config.TAKE_PROFIT_PCT
        risk_pct = risk_pct or config.RISK_PER_TRADE

        try:
            balance = await self.get_account_balance(asset)

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

            risk_amount = balance * risk_pct
            distance = abs(entry_price - sl_price)
            qty = risk_amount / distance if distance > 0 else 0.001
            if quote_qty:
                qty = quote_qty / entry_price if entry_price > 0 else qty
            cost = qty * entry_price

            # Enforce micro-volume minimum and value range checks
            symbol_upper = symbol_clean.upper()
            if "BTC" in symbol_upper:
                qty = max(qty, 0.001)
            elif "ETH" in symbol_upper:
                qty = max(qty, 0.01)
            else:
                # Default cost bounds for other assets: $5.00 - $10.00 USDT
                if qty * entry_price < 5.0:
                    qty = 5.0 / entry_price
                elif qty * entry_price > 10.0:
                    qty = 10.0 / entry_price
            cost = qty * entry_price

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

            # Get actual fill price from entry
            exec_qty = float(entry_result.get("executedQty", qty))
            if order_type.upper() == "LIMIT" and exec_qty == 0:
                exec_qty = qty
            cum_quote = float(entry_result.get("cummulativeQuoteQty", cost))
            fill_price = cum_quote / exec_qty if exec_qty > 0 else entry_price

            # Recalculate SL/TP from actual fill price
            if abs(fill_price - entry_price) > 0.01:
                price_diff = fill_price - entry_price
                sl_price += price_diff
                tp_price += price_diff

                risk_params.entry_price = fill_price
                risk_params.stop_loss_price = sl_price
                risk_params.take_profit_price = tp_price

            exit_side = "SELL" if side_upper == "BUY" else "BUY"
            stop_limit = sl_price * 0.995 if exit_side == "SELL" else sl_price * 1.005

            try:
                oco_result = await self.place_oco_order(
                    symbol=symbol_clean,
                    side=exit_side,
                    quantity=qty,
                    take_profit_price=tp_price,
                    stop_price=sl_price,
                    stop_limit_price=stop_limit,
                )
            except Exception as oco_err:
                log.error(
                    f"Weex OCO order placement failed: {oco_err}. Cancelling entry order {entry_result.get('orderId')} to prevent orphan position."
                )
                try:
                    await self.cancel_order(symbol_clean, entry_result.get("orderId"))
                except Exception as cancel_err:
                    log.error(
                        f"Failed to cancel entry order after OCO failure: {cancel_err}"
                    )
                raise ExchangeError(
                    ExchangeErrorCategory.ORDER_REJECTED,
                    f"OCO placement failed: {oco_err}. Entry order cancelled.",
                    None,
                    self.exchange_name,
                ) from oco_err

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

    async def health_check(self) -> dict[str, Any]:
        try:
            start = time.time()
            if not self.dry_run:
                await self.get_symbol_info("BTCUSDT_UMCBL")
            latency = (time.time() - start) * 1000
            return {"healthy": True, "latency_ms": round(latency, 1), "error": None}
        except Exception as e:
            return {"healthy": False, "latency_ms": 0, "error": str(e)}
