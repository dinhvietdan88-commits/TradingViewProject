"""
Binance Client — Sprint 7.2
Async MARKET + OCO order execution with position sizing and dry-run mode.
Supports both BUY entry → OCO SELL exit AND SELL entry → OCO BUY exit.
"""

import hashlib
import hmac
import logging
import time
import uuid
from typing import Any, Dict, Optional

import aiohttp

import config

log = logging.getLogger(__name__)


from exchanges.base import OrderResult, RiskParams  # noqa: E402

# ═══════════════════════════════════════════════════════════════
# BINANCE CLIENT
# ═══════════════════════════════════════════════════════════════


class BinanceClient:
    """Async Binance client — MARKET + OCO orders with risk management."""

    TESTNET_URL = "https://testnet.binance.vision"
    MAINNET_URL = "https://api.binance.com"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
        dry_run: bool = True,
    ):
        self.api_key = api_key or config.BINANCE_API_KEY
        self.api_secret = api_secret or config.BINANCE_API_SECRET
        self.testnet = testnet
        self.dry_run = dry_run
        self.base_url = self.TESTNET_URL if testnet else self.MAINNET_URL

        mode = []
        if dry_run:
            mode.append("DRY-RUN")
        mode.append("TESTNET" if testnet else "MAINNET")
        log.info(f"BinanceClient initialized [{', '.join(mode)}] → {self.base_url}")

    # ═══ SIGNING ═══════════════════════════════════════════════

    def _sign_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Add timestamp + HMAC-SHA256 signature to params."""
        params["timestamp"] = int(time.time() * 1000)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        sig = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = sig
        return params

    # ═══ HTTP ══════════════════════════════════════════════════

    async def _request(
        self, method: str, endpoint: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Send signed request to Binance API."""
        signed = self._sign_params(params)
        headers = {"X-MBX-APIKEY": self.api_key}
        url = f"{self.base_url}{endpoint}"

        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(url, params=signed, headers=headers) as resp:
                    data = await resp.json()
            else:
                async with session.post(url, params=signed, headers=headers) as resp:
                    data = await resp.json()

            if isinstance(data, dict) and data.get("code"):
                raise Exception(
                    f"Binance API Error [{data.get('code')}]: {data.get('msg', data)}"
                )

            return data

    # ═══ ACCOUNT ═══════════════════════════════════════════════

    async def get_account_balance(self, asset: str = "USDT") -> float:
        """Get free balance for a specific asset."""
        if self.dry_run:
            log.info(f"[DRY-RUN] get_account_balance({asset}) → $10,000.00")  # codeql[py/log-injection]
            return 10000.0

        data = await self._request("GET", "/api/v3/account", {})
        for b in data.get("balances", []):
            if b["asset"] == asset.upper():
                return float(b["free"])
        return 0.0

    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        """Get exchange info for symbol (LOT_SIZE, PRICE_FILTER, etc.)."""
        if self.dry_run:
            return {
                "symbol": symbol,
                "status": "TRADING",
                "baseAssetPrecision": 8,
                "quoteAssetPrecision": 8,
                "filters": [],
            }

        async with aiohttp.ClientSession() as session:
            url = f"{self.base_url}/api/v3/exchangeInfo"
            async with session.get(url, params={"symbol": symbol}) as resp:
                data = await resp.json()
                symbols = data.get("symbols", [])
                if symbols:
                    return symbols[0]
                raise Exception(f"Symbol {symbol} not found on Binance")

    async def get_active_symbols(self) -> list[str]:
        """Get active trading symbols ending with USDT."""
        if self.dry_run:
            return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"]

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/api/v3/exchangeInfo"
                async with session.get(url) as resp:
                    data = await resp.json()
                    symbols = data.get("symbols", [])
                    active_symbols = []
                    for s in symbols:
                        sym = s.get("symbol", "")
                        status = s.get("status", "")
                        if sym.endswith("USDT") and status.upper() == "TRADING":
                            active_symbols.append(sym)
                    return active_symbols
        except Exception as e:
            log.error(f"Error fetching active symbols from Binance: {e}")
            return ["BTCUSDT", "ETHUSDT"]

    # ═══ POSITION SIZING ═══════════════════════════════════════

    @staticmethod
    def calculate_sl_tp(
        entry_price: float,
        side: str,
        sl_pct: float = None,
        tp_pct: float = None,
    ) -> dict[str, float]:
        """Calculate Stop-Loss and Take-Profit prices.

        BUY side:  SL = entry × (1 - sl_pct), TP = entry × (1 + tp_pct)
        SELL side: SL = entry × (1 + sl_pct), TP = entry × (1 - tp_pct)
        """
        sl_pct = sl_pct if sl_pct is not None else config.STOP_LOSS_PCT
        tp_pct = tp_pct if tp_pct is not None else config.TAKE_PROFIT_PCT

        if side.upper() == "BUY":
            sl = entry_price * (1 - sl_pct)
            tp = entry_price * (1 + tp_pct)
        else:  # SELL
            sl = entry_price * (1 + sl_pct)
            tp = entry_price * (1 - tp_pct)

        rr = tp_pct / sl_pct if sl_pct > 0 else 0

        return {
            "stop_loss": round(sl, 8),
            "take_profit": round(tp, 8),
            "risk_reward": round(rr, 2),
        }

    @staticmethod
    def calculate_position_size(
        balance: float,
        entry_price: float,
        stop_price: float,
        risk_pct: float = None,
    ) -> float:
        """Calculate position size (base qty) based on risk %.

        Formula: qty = (balance × risk_pct) / |entry - stop|
        """
        risk_pct = risk_pct or config.RISK_PER_TRADE
        risk_amount = balance * risk_pct
        distance = abs(entry_price - stop_price)
        if distance == 0:
            return 0.0
        return risk_amount / distance

    # ═══ ORDERS ════════════════════════════════════════════════

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quote_qty: float = None,
        base_qty: float = None,
    ) -> dict[str, Any]:
        """Place a MARKET order. Use quote_qty (USDT) OR base_qty (BTC)."""
        symbol_clean = symbol.replace("/", "").upper()
        side_upper = side.upper()

        params = {
            "symbol": symbol_clean,
            "side": side_upper,
            "type": "MARKET",
        }
        if quote_qty:
            params["quoteOrderQty"] = quote_qty
        elif base_qty:
            params["quantity"] = base_qty
        else:
            raise ValueError("Must provide either quote_qty or base_qty")

        if self.dry_run:
            fill_price = 67500.0  # Mock price
            qty = quote_qty / fill_price if quote_qty else base_qty
            mock = {
                "orderId": f"DRY-{uuid.uuid4().hex[:8].upper()}",
                "symbol": symbol_clean,
                "side": side_upper,
                "type": "MARKET",
                "status": "FILLED",
                "executedQty": str(round(qty, 8)),
                "cummulativeQuoteQty": str(round(qty * fill_price, 2)),
                "fills": [
                    {
                        "price": str(fill_price),
                        "qty": str(round(qty, 8)),
                        "commission": "0",
                    }
                ],
                "_dry_run": True,
            }
            log.info(
                f"[DRY-RUN] MARKET {side_upper} {symbol_clean} "
                f"qty={round(qty, 8)} cost=${round(qty * fill_price, 2)}"
            )
            return mock

        return await self._request("POST", "/api/v3/order", params)

    async def get_ticker_price(self, symbol: str) -> float:
        """Get current market price for a symbol."""
        if self.dry_run:
            return 67500.0
        symbol_clean = symbol.replace("/", "").upper()
        # Non-signed request for ticker price is best, but _request enforces signing.
        # Since it is public, we can use unsigned session request, or signed since Binance allows it.
        # Let's do a simple unsigned request to avoid auth issues if key doesn't have permissions or is empty.
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/api/v3/ticker/price"
                async with session.get(url, params={"symbol": symbol_clean}) as resp:
                    data = await resp.json()
                    if isinstance(data, dict) and "price" in data:
                        return float(data["price"])
        except Exception as e:
            log.error(f"Error fetching Binance ticker price: {e}")
        return 67500.0

    async def place_limit_order(
        self, symbol: str, side: str, price: float, quantity: float
    ) -> dict[str, Any]:
        """Place a LIMIT order."""
        symbol_clean = symbol.replace("/", "").upper()
        side_upper = side.upper()
        params = {
            "symbol": symbol_clean,
            "side": side_upper,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": round(quantity, 8),
            "price": round(price, 2),
        }
        if self.dry_run:
            mock = {
                "orderId": f"DRY-LIM-{uuid.uuid4().hex[:8].upper()}",
                "symbol": symbol_clean,
                "side": side_upper,
                "type": "LIMIT",
                "status": "NEW",
                "price": str(price),
                "origQty": str(quantity),
                "executedQty": "0.0",
                "_dry_run": True,
            }
            log.info(
                f"[DRY-RUN] LIMIT {side_upper} {symbol_clean} at {price} qty={quantity}"
            )
            return mock
        return await self._request("POST", "/api/v3/order", params)

    async def get_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        """Get order status."""
        if self.dry_run:
            return {"status": "NEW", "executedQty": "0.0", "origQty": "1.0"}
        symbol_clean = symbol.replace("/", "").upper()
        params = {"symbol": symbol_clean, "orderId": order_id}
        data = await self._request("GET", "/api/v3/order", params)
        # Normalize status to uppercase FILLED or NEW
        status = data.get("status", "NEW").upper()
        return {"status": "FILLED" if status == "FILLED" else "NEW"}

    async def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        """Cancel an active order."""
        if self.dry_run:
            return {"status": "CANCELED"}
        symbol_clean = symbol.replace("/", "").upper()
        params = {"symbol": symbol_clean, "orderId": order_id}
        return await self._request("DELETE", "/api/v3/order", params)

    async def cancel_oco_order(self, symbol: str, order_list_id: str) -> dict[str, Any]:
        """Cancel an active OCO order list."""
        if self.dry_run:
            return {"status": "CANCELED"}
        symbol_clean = symbol.replace("/", "").upper()
        params = {"symbol": symbol_clean, "orderListId": order_list_id}
        return await self._request("DELETE", "/api/v3/orderList", params)

    async def place_oco_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        take_profit_price: float,
        stop_price: float,
        stop_limit_price: float,
    ) -> dict[str, Any]:
        """Place an OCO order (one-cancels-other) for SL + TP exit."""
        symbol_clean = symbol.replace("/", "").upper()
        side_upper = side.upper()

        params = {
            "symbol": symbol_clean,
            "side": side_upper,
            "quantity": round(quantity, 8),
            "price": round(take_profit_price, 2),  # LIMIT (TP)
            "stopPrice": round(stop_price, 2),  # STOP trigger
            "stopLimitPrice": round(stop_limit_price, 2),  # STOP_LIMIT fill
            "stopLimitTimeInForce": "GTC",
        }

        if self.dry_run:
            mock = {
                "orderListId": f"DRY-OCO-{uuid.uuid4().hex[:8].upper()}",
                "listStatusType": "EXEC_STARTED",
                "listOrderStatus": "EXECUTING",
                "symbol": symbol_clean,
                "orders": [
                    {
                        "orderId": f"DRY-TP-{uuid.uuid4().hex[:6].upper()}",
                        "type": "LIMIT_MAKER",
                    },
                    {
                        "orderId": f"DRY-SL-{uuid.uuid4().hex[:6].upper()}",
                        "type": "STOP_LOSS_LIMIT",
                    },
                ],
                "take_profit_price": take_profit_price,
                "stop_loss_price": stop_price,
                "_dry_run": True,
            }
            log.info(
                f"[DRY-RUN] OCO {side_upper} {symbol_clean} "
                f"qty={round(quantity, 8)} TP=${take_profit_price} SL=${stop_price}"
            )
            return mock

        return await self._request("POST", "/api/v3/order/oco", params)

    # ═══ SMART ORDER ═══════════════════════════════════════════

    async def execute_smart_order(
        self,
        symbol: str,
        side: str,
        entry_price: float = None,
        quote_qty: float = None,
        sl_pct: float = None,
        tp_pct: float = None,
        risk_pct: float = None,
        sl_price: float = None,
        tp_price: float = None,
        asset: str = "USDT",
        order_type: str = "MARKET",
    ) -> OrderResult:
        """Full workflow: MARKET/LIMIT entry → OCO exit with position sizing.

        Steps:
        1. Get account balance
        2. Calculate SL/TP levels
        3. Calculate position size (risk-based)
        4. Place MARKET or LIMIT order
        5. Place OCO exit order
        6. Return unified result
        """
        symbol_clean = symbol.replace("/", "").upper()
        side_upper = side.upper()
        sl_pct = sl_pct or config.STOP_LOSS_PCT
        tp_pct = tp_pct or config.TAKE_PROFIT_PCT
        risk_pct = risk_pct or config.RISK_PER_TRADE

        try:
            # 1. Account balance
            balance = await self.get_account_balance(asset)
            log.info(f"Account balance: ${balance:,.2f} {asset}")

            # 2. SL/TP levels
            if sl_price is not None and tp_price is not None:
                # Use explicitly provided prices
                rr_ratio = (
                    abs(tp_price - entry_price) / abs(sl_price - entry_price)
                    if abs(sl_price - entry_price) > 0
                    else 0
                )
                calc_sl_pct = (
                    abs(sl_price - entry_price) / entry_price
                    if entry_price > 0
                    else (sl_pct or config.STOP_LOSS_PCT)
                )
                calc_tp_pct = (
                    abs(tp_price - entry_price) / entry_price
                    if entry_price > 0
                    else (tp_pct or config.TAKE_PROFIT_PCT)
                )
            else:
                levels = self.calculate_sl_tp(entry_price, side_upper, sl_pct, tp_pct)
                sl_price = levels["stop_loss"]
                tp_price = levels["take_profit"]
                rr_ratio = levels["risk_reward"]
                calc_sl_pct = sl_pct or config.STOP_LOSS_PCT
                calc_tp_pct = tp_pct or config.TAKE_PROFIT_PCT

            # 3. Position sizing
            qty = self.calculate_position_size(balance, entry_price, sl_price, risk_pct)
            if quote_qty:
                qty = quote_qty / entry_price if entry_price > 0 else qty
            cost = qty * entry_price
            risk_amount = balance * risk_pct

            # Cap at available balance (use max 95% to cover fees)
            max_cost = balance * 0.95
            if cost > max_cost:
                qty = max_cost / entry_price
                cost = qty * entry_price
                log.warning(f"Position capped to 95% of balance: ${cost:,.2f}")

            risk_params = RiskParams(
                entry_price=entry_price,
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                stop_loss_pct=calc_sl_pct,
                take_profit_pct=calc_tp_pct,
                risk_reward_ratio=rr_ratio,
                quantity=qty,
                cost=cost,
                risk_amount=risk_amount,
                account_balance=balance,
                position_pct=cost / balance if balance > 0 else 0,
            )

            log.info(
                f"Smart Order: {side_upper} {symbol_clean} | "
                f"Entry=${entry_price:,.2f} SL=${sl_price:,.2f} TP=${tp_price:,.2f} | "
                f"Qty={qty:.8f} Cost=${cost:,.2f} R:R={rr_ratio} Type={order_type}"
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
                if hasattr(self, "_explicit_sl") and self._explicit_sl:
                    # Note: We just check if sl_price was passed into execute_smart_order
                    # By shifting them exactly by price_diff, we maintain the exact risk $ amount per share
                    pass

                # We shift the SL and TP by the exact same dollar amount of slippage to keep distance constant
                sl_price += price_diff
                tp_price += price_diff

                risk_params.entry_price = fill_price
                risk_params.stop_loss_price = sl_price
                risk_params.take_profit_price = tp_price

            # 5. OCO exit (opposite side)
            exit_side = "SELL" if side_upper == "BUY" else "BUY"
            # Stop limit price slightly worse than stop price (0.5% buffer)
            if exit_side == "SELL":
                stop_limit = sl_price * 0.995  # Sell slightly lower
            else:
                stop_limit = sl_price * 1.005  # Buy slightly higher

            oco_result = await self.place_oco_order(
                symbol=symbol_clean,
                side=exit_side,
                quantity=exec_qty,
                take_profit_price=tp_price,
                stop_price=sl_price,
                stop_limit_price=stop_limit,
            )

            log.info(
                f"Smart Order complete: entry={entry_result.get('orderId')} "
                f"oco={oco_result.get('orderListId')}"
            )

            return OrderResult(
                success=True,
                dry_run=self.dry_run,
                side=side_upper,
                symbol=symbol_clean,
                entry_order=entry_result,
                oco_order=oco_result,
                risk=risk_params,
            )

        except Exception as e:
            log.error(f"Smart Order FAILED: {e}")
            return OrderResult(
                success=False,
                dry_run=self.dry_run,
                side=side_upper,
                symbol=symbol_clean,
                error=str(e),
            )


# ═══════════════════════════════════════════════════════════════
# MODULE-LEVEL CLIENT (singleton)
# ═══════════════════════════════════════════════════════════════

_client: BinanceClient | None = None


def get_client() -> BinanceClient:
    """Get or create singleton BinanceClient."""
    global _client
    if _client is None:
        _client = BinanceClient(
            api_key=config.BINANCE_API_KEY,
            api_secret=config.BINANCE_API_SECRET,
            testnet=config.BINANCE_TESTNET,
            dry_run=config.BINANCE_DRY_RUN,
        )
    return _client
