"""
Active Position Monitor — Background tracking of active paper trading positions via Binance WebSocket.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
import aiohttp
import aiosqlite
import config

log = logging.getLogger(__name__)


class ActivePositionMonitor:
    def __init__(self):
        self.task = None
        self.running = False
        self.active_trades = []
        self._lock = asyncio.Lock()

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self.run_loop())
        log.info("ActivePositionMonitor: Background service started.")

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        log.info("ActivePositionMonitor: Background service stopped.")

    async def refresh_active_trades(self):
        """Load ACTIVE trades from forward_trades.db into memory."""
        async with self._lock:
            db_path = config.FORWARD_DB_PATH
            try:
                async with aiosqlite.connect(db_path) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        "SELECT * FROM trades WHERE status = 'ACTIVE'"
                    ) as cursor:
                        rows = await cursor.fetchall()
                        self.active_trades = [dict(r) for r in rows]
                log.debug(
                    f"ActivePositionMonitor: Refreshed active trades: {len(self.active_trades)}"
                )
            except Exception as e:
                log.warning(
                    f"ActivePositionMonitor: Failed to refresh active trades: {e}"
                )

    async def resolve_trade(self, trade_id: int, exit_price: float, reason: str):
        """Mark a trade as FILLED and calculate P&L."""
        db_path = config.FORWARD_DB_PATH
        async with self._lock:
            try:
                async with aiosqlite.connect(db_path) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        "SELECT * FROM trades WHERE id = ?", (trade_id,)
                    ) as cursor:
                        trade = await cursor.fetchone()
                    if not trade or trade["status"] != "ACTIVE":
                        return

                    is_buy = (trade["side"] or "").lower() in (
                        "buy",
                        "long",
                        "bo",
                        "breakout_long",
                    )
                    entry_price = trade["executed_price"]
                    qty = trade["executed_qty"]

                    if is_buy:
                        pnl = qty * (exit_price - entry_price)
                    else:
                        pnl = qty * (entry_price - exit_price)

                    # calculate exit fee and accumulate onto existing entry fee
                    exit_fee = qty * exit_price * config.FEE_RATE

                    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                    await db.execute(
                        """
                        UPDATE trades
                        SET status = 'FILLED', pnl = ?, commission = COALESCE(commission, 0.0) + ?, exit_price = ?, error_message = ?, created_at = ?
                        WHERE id = ?
                        """,
                        (
                            pnl,
                            exit_fee,
                            exit_price,
                            f"Closed via WebSocket: {reason} at {exit_price}",
                            now_str,
                            trade_id,
                        ),
                    )
                    await db.commit()
                    log.info(
                        f"ActivePositionMonitor: Trade #{trade_id} closed as FILLED. Exit={exit_price}, PnL={pnl:.2f} ({reason})"
                    )

                    # Trigger SSE push so the frontend updates immediately
                    try:
                        import main as _main_mod

                        _main_mod.push_sse_event(
                            "trade_update",
                            {
                                "trade_id": trade_id,
                                "status": "FILLED",
                                "exit_price": exit_price,
                                "pnl": pnl,
                                "reason": reason,
                            },
                        )
                    except Exception as sse_err:
                        log.debug(f"SSE push failed: {sse_err}")
            except Exception as db_err:
                log.error(
                    f"ActivePositionMonitor: Failed to resolve trade #{trade_id}: {db_err}"
                )

        # Trigger refreshing memory cache
        await self.refresh_active_trades()

    async def run_loop(self):
        url = "wss://stream.binance.com:9443/stream?streams=btcusdt@ticker/ethusdt@ticker/solusdt@ticker"
        refresh_counter = 0

        while self.running:
            try:
                await self.refresh_active_trades()
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url) as ws:
                        log.info(
                            "ActivePositionMonitor: Connected to Binance WebSocket stream."
                        )

                        while self.running and not ws.closed:
                            try:
                                msg = await ws.receive(timeout=2.0)
                            except asyncio.TimeoutError:
                                # Periodically refresh active trades from DB (every 20s)
                                refresh_counter += 2
                                if refresh_counter >= 20:
                                    await self.refresh_active_trades()
                                    refresh_counter = 0
                                continue

                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                ticker = data.get("data", {})

                                symbol = ticker.get("s", "").upper()
                                close_price = float(ticker.get("c", 0.0))

                                if not symbol or close_price <= 0.0:
                                    continue

                                # Check active trades for this symbol
                                async with self._lock:
                                    trades_to_check = list(self.active_trades)

                                for t in trades_to_check:
                                    if t["symbol"].upper() == symbol:
                                        trade_id = t["id"]
                                        sl = t["stop_loss_price"] or 0.0
                                        tp = t["take_profit_price"] or 0.0
                                        side = (t["side"] or "").lower()
                                        is_buy = side in (
                                            "buy",
                                            "long",
                                            "bo",
                                            "breakout_long",
                                        )

                                        if is_buy:
                                            if sl > 0.0 and close_price <= sl:
                                                await self.resolve_trade(
                                                    trade_id, sl, "Stop Loss"
                                                )
                                            elif tp > 0.0 and close_price >= tp:
                                                await self.resolve_trade(
                                                    trade_id, tp, "Take Profit"
                                                )
                                        else:
                                            if sl > 0.0 and close_price >= sl:
                                                await self.resolve_trade(
                                                    trade_id, sl, "Stop Loss"
                                                )
                                            elif tp > 0.0 and close_price <= tp:
                                                await self.resolve_trade(
                                                    trade_id, tp, "Take Profit"
                                                )

                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                log.warning(
                                    "ActivePositionMonitor: WebSocket connection closed or error. Reconnecting..."
                                )
                                break

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"ActivePositionMonitor error in run_loop: {e}")
                await asyncio.sleep(5)  # Cooldown before reconnect


# Singleton instance
active_position_monitor = ActivePositionMonitor()
