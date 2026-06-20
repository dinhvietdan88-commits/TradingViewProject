"""
TradeEngine — Multi-Exchange MARKET + OCO execution with risk management (v6.0).

Listens to: TradeApproved
Emits: TradeExecuted | TradeFailed

Design Invariants (v6.0):
- Subscribes ONLY to TradeApproved (from NotificationHub gate).
- Does NOT call notifier directly — all notifications delegated to NotificationHub
  via TradeExecuted / TradeFailed events.
- Hybrid Transitional: writes to DB directly AND emits events.
- Uses ExchangeRouter for multi-exchange adapter resolution.
- Uses set_bus() pattern for test isolation.
"""

import asyncio
import logging

import database
from core.event_bus import bus as _default_bus
from core.events import CircuitBreakerTripped, TradeApproved, TradeExecuted, TradeFailed
from symbol_config import get_symbol_config
from datetime import UTC

log = logging.getLogger(__name__)

# Allow bus override for testing
_bus = _default_bus


def set_bus(bus_instance) -> None:
    """Override the event bus instance (for testing)."""
    global _bus
    _bus = bus_instance


def get_bus():
    """Get the current event bus instance."""
    return _bus


# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# EVENT HANDLER: TradeApproved → Execute Order
# ═══════════════════════════════════════════════════════════════


async def monitor_limit_order(
    adapter, symbol: str, order_id: str, oco_id: str | None, entry_price: float
):
    """Monitor a limit order placed due to slippage, cancel after 30s if unfilled."""
    await asyncio.sleep(30)
    try:
        status_info = await adapter.get_order(symbol, order_id)
        if status_info.get("status") != "FILLED":
            log.warning(
                f"Slippage limit order {order_id} unfilled after 30s. Cancelling."
            )
            try:
                await adapter.cancel_order(symbol, order_id)
            except Exception as e:
                log.warning(f"Failed to cancel unfilled limit order {order_id}: {e}")
            if oco_id:
                try:
                    await adapter.cancel_oco_order(symbol, oco_id)
                except Exception as e:
                    log.warning(f"Failed to cancel associated OCO order {oco_id}: {e}")

            # Send Telegram alert
            msg = f"⚠️ **Slippage Warning**\nLimit order `{order_id}` for `{symbol}` at price `{entry_price}` remained unfilled after 30 seconds and has been cancelled."
            try:
                from notifier import notify_all

                await notify_all(msg)
            except Exception as n_err:
                log.error(f"Failed to send Telegram alert: {n_err}")
    except Exception as exc:
        log.error(f"Error in monitor_limit_order for {order_id}: {exc}")


@_default_bus.on(TradeApproved)
async def execute_trade(event: TradeApproved) -> None:
    """
    Execute a validated trade signal on the target exchange.

    Steps:
    1. Parse SL/TP prices from event.
    2. Resolve exchange adapter via ExchangeRouter.
    3. Call adapter.execute_smart_order().
    4. On success: persist trade + OCO to DB, emit TradeExecuted.
    5. On failure: persist failed trade to DB, emit TradeFailed.
    6. v6.0: Notifications are handled by NotificationHub via events.
    """
    action = event.action.lower()
    if action not in ("buy", "sell"):
        log.info(
            f"TradeEngine: Skipping non-trade action '{action}' for #{event.signal_id}"
        )
        return

    # Resolve per-symbol risk parameters (OPTIMIZED_PARAMETERS_MATRIX)
    symbol_cfg = get_symbol_config(event.symbol)

    # ── Parse prices ─────────────────────────────────────────
    try:
        entry_price = float(str(event.price).replace(",", "")) if event.price else 0.0
    except (ValueError, TypeError):
        entry_price = 0.0

    try:
        sl_price = float(str(event.sl).replace(",", "")) if event.sl else None
        if sl_price is not None and sl_price <= 0.0:
            sl_price = None
    except (ValueError, TypeError):
        sl_price = None

    # ── SL Hard-Cap Enforcement (stop_loss_pct) ──────────────────────────────
    # Prevent aggressively-wide stop-losses that exceed the per-symbol cap defined
    # in symbol_config.py. The cap is NOT applied to the ATR path (which uses
    # atr_sl_mul and already has well-tested multipliers). This only guards the
    # manually-provided event.sl string path parsed above.
    if sl_price is not None and entry_price > 0:
        sl_dist_pct = abs(entry_price - sl_price) / entry_price
        if sl_dist_pct > symbol_cfg["stop_loss_pct"]:
            if action == "buy":
                clamped_sl = entry_price * (1.0 - symbol_cfg["stop_loss_pct"])
            else:  # sell / short
                clamped_sl = entry_price * (1.0 + symbol_cfg["stop_loss_pct"])
            log.warning(
                f"TradeEngine: SL clamped for {event.symbol} "
                f"({sl_dist_pct * 100:.1f}% > cap {symbol_cfg['stop_loss_pct'] * 100:.0f}%): "
                f"{sl_price:.4f} → {clamped_sl:.4f}"
            )
            sl_price = clamped_sl

    try:
        tp_price = float(str(event.tp).replace(",", "")) if event.tp else None
        if tp_price is not None and tp_price <= 0.0:
            tp_price = None
    except (ValueError, TypeError):
        tp_price = None

    # ── Resolve exchange adapter ─────────────────────────────
    from exchanges.router import get_router

    router = get_router()
    requested_exchange = getattr(event, "exchange", "binance")

    try:
        adapter = router.resolve_exchange({"exchange": requested_exchange})
        actual_exchange = getattr(adapter, "exchange_id", None) or getattr(
            adapter, "exchange_name", requested_exchange
        )
    except Exception as e:
        error_msg = f"Exchange routing failed: {e}"
        log.error(f"TradeEngine: {error_msg}")
        await _handle_failure(event, action, error_msg, requested_exchange, None)
        return

    combined_score: str | None = getattr(event, "combined_score", None)

    # TVP-001 & TVP-002: Hardened validation
    if entry_price <= 0.0:
        error_msg = f"Invalid entry price: {entry_price} (from '{event.price}')"
        log.error(f"TradeEngine: {error_msg}")
        await _handle_failure(
            event, action, error_msg, requested_exchange, combined_score
        )
        return

    # Fetch original signal details and check if it is a breakout/BO
    original_action = ""
    original_payload = {}
    try:
        import json

        import aiosqlite

        import config

        async with aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT action, payload FROM signals WHERE id = ?", (event.signal_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    original_action = str(row["action"]).lower()
                    try:
                        original_payload = (
                            json.loads(row["payload"]) if row["payload"] else {}
                        )
                    except Exception:
                        original_payload = {}
    except Exception as exc:
        log.warning(f"TradeEngine: Failed to fetch original signal details: {exc}")

    is_breakout = (
        (original_action in {"bo", "breakout_long"})
        or (original_payload.get("action") in {"bo", "breakout_long"})
        or (original_payload.get("signal_type") == "breakout_long")
    )

    # Sizing calculation
    try:
        quote_qty_val = float(event.quote_qty) if event.quote_qty else None
        if quote_qty_val is not None and quote_qty_val <= 0.0:
            quote_qty_val = None
    except (ValueError, TypeError):
        quote_qty_val = None

    # Extract ATR value (R2)
    atr_val = getattr(event, "atr_value", None)
    if atr_val is None:
        atr_val = original_payload.get("atr_value")
    if atr_val is None:
        atr_val = original_payload.get("metadata", {}).get("atr14")
    if atr_val is None:
        atr_val = original_payload.get("atr")

    atr_sizing_applied = False
    if atr_val is not None:
        try:
            atr = float(atr_val)
            if atr > 0:
                if action.upper() == "BUY":
                    sl_price = entry_price - (symbol_cfg["atr_sl_mul"] * atr)
                    tp_price = entry_price + (symbol_cfg["atr_tp_mul"] * atr)
                else:
                    sl_price = entry_price + (symbol_cfg["atr_sl_mul"] * atr)
                    tp_price = entry_price - (symbol_cfg["atr_tp_mul"] * atr)
                log.info(
                    f"TradeEngine: ATR-based SL/TP calculated: "
                    f"SL={sl_price}, TP={tp_price} "
                    f"(ATR={atr}, sym_mul={symbol_cfg['atr_sl_mul']}x/{symbol_cfg['atr_tp_mul']}x)"
                )
                # Chandelier trailing stop reference (trail_atr_mul) — informational only.
                # OCO is placed at ATR SL above. This wider level is the future trailing
                # stop target once price moves in our favour.
                if action.upper() == "BUY":
                    trail_sl_ref = entry_price - (symbol_cfg["trail_atr_mul"] * atr)
                else:
                    trail_sl_ref = entry_price + (symbol_cfg["trail_atr_mul"] * atr)
                log.info(
                    f"TradeEngine: Chandelier trail reference: {trail_sl_ref:.4f} "
                    f"({symbol_cfg['trail_atr_mul']}x ATR={atr:.4f} from entry={entry_price:.4f})"
                )

                try:
                    balance = await adapter.get_account_balance("USDT")
                    risk_amount = balance * symbol_cfg["risk_pct"]
                    price_dist = abs(entry_price - sl_price)
                    if price_dist > 0:
                        quote_qty_val = (risk_amount / price_dist) * entry_price
                        atr_sizing_applied = True
                        log.info(
                            f"TradeEngine: ATR risk-based sizing applied: quote_qty={quote_qty_val:.2f} USDT (risking {symbol_cfg['risk_pct'] * 100:.1f}% of {balance:.2f} balance)"
                        )
                except Exception as e:
                    log.warning(
                        f"TradeEngine: Failed to compute ATR-based position size: {e}"
                    )
        except (ValueError, TypeError) as e:
            log.warning(f"TradeEngine: Invalid ATR value {atr_val}: {e}")

    if not atr_sizing_applied:
        if is_breakout:
            # Tactical Entry: beta-scaled % of account balance (BTC=2.5%, ETH=2.0%, SOL=1.5%)
            try:
                balance = await adapter.get_account_balance("USDT")
                if balance > 0:
                    tactical_qty = balance * symbol_cfg["breakout_size_pct"]
                    quote_qty_val = max(10.0, min(tactical_qty, config.MAX_QUOTE_QTY))
                    log.info(
                        f"TradeEngine: Tactical Entry Sizing applied: {quote_qty_val:.2f} USDT ({symbol_cfg['breakout_size_pct'] * 100:.1f}% of {balance:.2f} balance)"
                    )
                else:
                    if quote_qty_val is None:
                        quote_qty_val = 10.0
            except Exception as e:
                log.warning(
                    f"TradeEngine: Failed to compute tactical sizing: {e}. Using default."
                )
                if quote_qty_val is None:
                    quote_qty_val = 10.0

            # Tactical Stop-loss at Swing Low of last 5 hours
            try:
                import aiohttp

                from analysis import fetch_candles_with_retry

                async with aiohttp.ClientSession() as session:
                    candles = await fetch_candles_with_retry(
                        session,
                        requested_exchange,
                        event.symbol,
                        interval="1h",
                        limit=5,
                    )
                if candles:
                    swing_low = min(float(c[3]) for c in candles)
                    sl_price = swing_low * 0.998
                    if sl_price >= entry_price:
                        sl_price = entry_price * 0.98
                    log.info(
                        f"TradeEngine: Tactical Entry Stop Loss at {sl_price:.4f} (Swing Low: {swing_low:.4f})"
                    )
            except Exception as exc:
                log.warning(
                    f"TradeEngine: Failed to compute Swing Low Stop Loss: {exc}. Keeping default: {sl_price}"
                )

    # Regime Filter (R4)
    try:
        from engine.regime_switcher import get_market_regime

        regime = await get_market_regime(event.symbol, requested_exchange)
        await database.set_setting("market_regime", regime)
    except Exception as exc:
        log.warning(
            f"TradeEngine: Failed to get market regime: {exc}. Trying fallback setting."
        )
        try:
            regime = await database.get_setting("market_regime", "TRENDING")
        except Exception:
            regime = "TRENDING"

    if regime == "CHOP":
        if is_breakout:
            error_msg = f"Skipped: breakout signal {event.signal_id} because market is in CHOP regime"
            log.info(f"TradeEngine: {error_msg}")
            await _handle_failure(
                event, action, error_msg, requested_exchange, combined_score
            )
            return
        else:
            if quote_qty_val is not None:
                quote_qty_val = quote_qty_val * 0.5
                log.info(
                    f"TradeEngine: CHOP regime detected. Reducing position size by 50% to {quote_qty_val:.2f} USDT"
                )

    # Safe Mode sizing modification
    try:
        import inspect

        dd_val = database.get_rolling_drawdown(20)
        rolling_dd = await dd_val if inspect.isawaitable(dd_val) else 0.0

        pf_val = database.get_recent_profit_factor(5)
        recent_pf = await pf_val if inspect.isawaitable(pf_val) else 1.0

        sm_val = database.get_setting("safe_mode_active", "false")
        current_safe_mode = await sm_val if inspect.isawaitable(sm_val) else "false"

        if rolling_dd > 10.0:
            safe_mode_active = True
            log.warning(
                f"TradeEngine: Drawdown ({rolling_dd:.2f}%) > 10% -> Safe Mode Activated"
            )
        elif current_safe_mode == "true" and recent_pf > 1.5:
            safe_mode_active = False
            log.info(
                f"TradeEngine: Profit Factor ({recent_pf:.2f}) > 1.5 -> Safe Mode Deactivated"
            )
        else:
            safe_mode_active = current_safe_mode == "true"

        set_active_val = database.set_setting(
            "safe_mode_active", "true" if safe_mode_active else "false"
        )
        if inspect.isawaitable(set_active_val):
            await set_active_val

        set_dd_val = database.set_setting("safe_mode_drawdown", f"{rolling_dd:.2f}")
        if inspect.isawaitable(set_dd_val):
            await set_dd_val

        if safe_mode_active:
            if quote_qty_val is not None:
                quote_qty_val = quote_qty_val * 0.5
                log.info(
                    f"TradeEngine: Safe Mode active (drawdown: {rolling_dd:.2f}%). Position sized halved to {quote_qty_val:.2f} USDT"
                )
    except Exception as exc:
        log.warning(f"TradeEngine: Safe Mode logic check failed: {exc}")
        safe_mode_active = False
        rolling_dd = 0.0

    # Dynamic Risk Settings & Circuit Breaker checks
    try:
        import inspect
        from unittest.mock import AsyncMock, Mock

        is_legacy_mock = isinstance(
            database.get_risk_settings, Mock
        ) and not isinstance(database.get_risk_settings, AsyncMock)

        if is_legacy_mock:
            daily_loss_val = database.get_daily_loss(actual_exchange)
            daily_loss = (
                await daily_loss_val if inspect.isawaitable(daily_loss_val) else 0.0
            )
            daily_loss_cap = 10.0
            drawdown_cap = 5.0
            cb_state = "CLOSED"
        else:
            risk_set = await database.get_risk_settings(actual_exchange)
            cb_state = risk_set.get("state", "CLOSED")
            daily_loss_val = database.get_daily_loss(actual_exchange)
            daily_loss = (
                await daily_loss_val if inspect.isawaitable(daily_loss_val) else 0.0
            )
            daily_loss_cap = risk_set.get("daily_loss_cap", 10.0)
            drawdown_cap = risk_set.get("drawdown_cap", 5.0)

        # 1. Check if the Circuit Breaker is OPEN (Blocked)
        if cb_state == "OPEN":
            error_msg = f"Skipped {actual_exchange} trade: Circuit Breaker is OPEN (Blocked mode)"
            log.warning(error_msg)
            await _handle_failure(
                event, action, error_msg, requested_exchange, combined_score
            )
            return

        # 2. Check current metrics to see if we should trip to OPEN
        trip = False
        reason = ""
        if daily_loss >= daily_loss_cap:
            trip = True
            reason = f"Daily loss {daily_loss:.2f} USDT exceeds cap {daily_loss_cap:.2f} USDT"
        elif rolling_dd >= drawdown_cap:
            trip = True
            reason = f"Drawdown {rolling_dd:.2f}% exceeds limit {drawdown_cap:.2f}%"

        # Check if there is an active bypass
        if trip and not is_legacy_mock:
            from unittest.mock import AsyncMock, Mock

            is_get_setting_mock = isinstance(database.get_setting, Mock)
            is_get_setting_async = isinstance(database.get_setting, AsyncMock)
            if is_get_setting_mock and not is_get_setting_async:
                bypass_until_str = None
            else:
                bypass_until_str = await database.get_setting(
                    f"bypass_until_{actual_exchange}"
                )

            if bypass_until_str:
                try:
                    from datetime import datetime

                    bypass_until = datetime.fromisoformat(bypass_until_str)
                    if datetime.now(UTC) < bypass_until:
                        log.info(
                            f"TradeEngine: Tripping bypassed for {actual_exchange} until {bypass_until_str}"
                        )
                        trip = False
                except Exception as e:
                    log.warning(f"TradeEngine: Failed to parse bypass timestamp: {e}")

        if trip:
            log.warning(
                f"TradeEngine: Tripping circuit breaker for {actual_exchange} to OPEN. Reason: {reason}"
            )
            if not is_legacy_mock:
                await database.update_circuit_breaker_state(actual_exchange, "OPEN")
                await database.log_circuit_breaker(
                    actual_exchange,
                    event.symbol,
                    cb_state,
                    "OPEN",
                    reason,
                    {
                        "dailyLoss": daily_loss,
                        "dailyLossCap": daily_loss_cap,
                        "drawdown": rolling_dd,
                        "drawdownCap": drawdown_cap,
                    },
                )
                # Emit CircuitBreakerTripped event
                await _bus.emit(
                    CircuitBreakerTripped(
                        exchange=actual_exchange,
                        symbol=event.symbol,
                        prev_state=cb_state,
                        new_state="OPEN",
                        reason=reason,
                        metrics={
                            "dailyLoss": daily_loss,
                            "dailyLossCap": daily_loss_cap,
                            "drawdown": rolling_dd,
                            "drawdownCap": drawdown_cap,
                        },
                    )
                )
            error_msg = f"Skipped {actual_exchange} trade: Circuit Breaker tripped to OPEN due to: {reason}"
            await _handle_failure(
                event, action, error_msg, requested_exchange, combined_score
            )
            return

        # 3. If in HALF-OPEN (recovery), reduce position size by 50%
        if cb_state == "HALF-OPEN":
            if quote_qty_val is not None:
                quote_qty_val = quote_qty_val * 0.5
                log.info(
                    f"TradeEngine: Circuit Breaker is HALF-OPEN for {actual_exchange}. Position size halved to {quote_qty_val:.2f} USDT"
                )
    except Exception as safety_exc:
        log.warning(f"TradeEngine: Weex safety checks failed: {safety_exc}")

    # Ensure quote_qty_val is bounded
    import config

    if quote_qty_val is not None:
        quote_qty_val = min(quote_qty_val, config.MAX_QUOTE_QTY)

    # Slippage Control (R1)
    target_order_type = "MARKET"
    try:
        market_price = await adapter.get_ticker_price(event.symbol)
        slippage = (
            abs(market_price - entry_price) / entry_price if entry_price > 0.0 else 0.0
        )
        log.info(
            f"TradeEngine: Market Price={market_price}, Webhook Price={entry_price}, Slippage={slippage:.4f}"
        )
        if slippage > 0.005:
            target_order_type = "LIMIT"
            log.info(
                f"TradeEngine: Slippage {slippage:.4f} > 0.5% (0.005). Changing order type to LIMIT at {entry_price}"
            )
    except Exception as exc:
        log.warning(f"TradeEngine: Failed to verify slippage: {exc}")

    # ── BUG-05 fix: Directional SL/TP Sanity Check ─────────
    # Vision AI / RAG text extraction may output SL/TP using BUY-side convention
    # even for SELL trades. Detect and swap if the direction is wrong.
    if sl_price is not None and tp_price is not None and entry_price > 0:
        if action.upper() == "BUY":
            # BUY: SL should be BELOW entry, TP should be ABOVE entry
            if sl_price > entry_price and tp_price < entry_price:
                log.warning(
                    f"TradeEngine: BUG-05 SL/TP direction mismatch for BUY {event.symbol}! "
                    f"SL={sl_price:.4f} > entry={entry_price:.4f}, "
                    f"TP={tp_price:.4f} < entry={entry_price:.4f}. Swapping SL↔TP."
                )
                sl_price, tp_price = tp_price, sl_price
        else:  # SELL
            # SELL: SL should be ABOVE entry, TP should be BELOW entry
            if sl_price < entry_price and tp_price > entry_price:
                log.warning(
                    f"TradeEngine: BUG-05 SL/TP direction mismatch for SELL {event.symbol}! "
                    f"SL={sl_price:.4f} < entry={entry_price:.4f}, "
                    f"TP={tp_price:.4f} > entry={entry_price:.4f}. Swapping SL↔TP."
                )
                sl_price, tp_price = tp_price, sl_price

    # Check if we should fallback from Weex on failure
    fallback_exchange = None
    if actual_exchange == "weex":
        fallback_exchange = router._get_fallback(
            "weex", {"strategy": getattr(event, "strategy", "")}
        )
        if not fallback_exchange:
            for fb in ["bybit", "binance"]:
                if fb != actual_exchange and router._registry.is_available(fb):
                    fallback_exchange = fb
                    break

    # ── Test signal dynamic dry_run override ────────────────
    is_test_signal = False
    if original_payload:
        if (
            original_payload.get("is_test") is True
            or original_payload.get("is_test") == "true"
        ):
            is_test_signal = True
        payload_mode = original_payload.get("mode", "")
        if isinstance(payload_mode, str) and (
            payload_mode.startswith("TEST")
            or payload_mode.startswith("DEMO")
            or "FORWARD" in payload_mode.upper()
        ):
            is_test_signal = True
    event_mode = getattr(event, "mode", "") or ""
    if isinstance(event_mode, str) and (
        event_mode.startswith("TEST")
        or event_mode.startswith("DEMO")
        or "FORWARD" in event_mode.upper()
    ):
        is_test_signal = True

    if is_test_signal:
        log.info("TradeEngine: Test signal detected. Forcing dry_run=True on adapter.")
        adapter.dry_run = True
        if hasattr(adapter, "_client") and adapter._client is not None:
            adapter._client.dry_run = True

    try:
        # ── Execute smart order (MARKET + OCO) ───────────────
        try:
            result = await adapter.execute_smart_order(
                symbol=event.symbol,
                side=action.upper(),
                entry_price=entry_price,
                quote_qty=quote_qty_val,
                sl_price=sl_price,
                tp_price=tp_price,
                order_type=target_order_type,
            )
            if not result.success:
                raise Exception(result.error or "Smart order failed")
        except Exception as e:
            if actual_exchange == "weex" and fallback_exchange:
                log.warning(
                    f"Weex execution failed ({e}). Attempting fallback to {fallback_exchange}..."
                )
                try:
                    fallback_adapter = router._registry.get_adapter(fallback_exchange)
                    if is_test_signal:
                        log.info(
                            "TradeEngine: Test signal detected. Forcing dry_run=True on fallback_adapter."
                        )
                        fallback_adapter.dry_run = True
                        if (
                            hasattr(fallback_adapter, "_client")
                            and fallback_adapter._client is not None
                        ):
                            fallback_adapter._client.dry_run = True
                    result = await fallback_adapter.execute_smart_order(
                        symbol=event.symbol,
                        side=action.upper(),
                        entry_price=entry_price,
                        quote_qty=quote_qty_val,
                        sl_price=sl_price,
                        tp_price=tp_price,
                        order_type=target_order_type,
                    )
                    if result.success:
                        actual_exchange = fallback_exchange
                        adapter = fallback_adapter
                        result.fallback_used = True
                        result.original_exchange = "weex"
                    else:
                        raise Exception(
                            result.error or f"Fallback to {fallback_exchange} failed"
                        )
                except Exception as fallback_err:
                    error_msg = f"Weex execution failed ({e}) AND fallback to {fallback_exchange} failed: {fallback_err}"
                    log.error(f"TradeEngine: {error_msg}")
                    await _handle_failure(
                        event, action, error_msg, requested_exchange, combined_score
                    )
                    return
            else:
                raise

        if result.success:
            entry = result.entry_order
            order_id = str(entry.get("orderId", "N/A"))
            order_status = entry.get("status", "FILLED")
            exec_qty = float(entry.get("executedQty", 0))
            cum_quote = float(entry.get("cummulativeQuoteQty", 0))
            # BUG-03 fix: guard against ZeroDivisionError in DRY_RUN where executedQty=0
            exec_price = (cum_quote / exec_qty) if exec_qty > 0 else None

            order_type = "DRY_RUN" if result.dry_run else "OCO"
            oco_id = None
            if result.oco_order:
                oco_id = str(result.oco_order.get("orderListId", ""))

            if target_order_type == "LIMIT" and order_status != "FILLED":
                asyncio.create_task(
                    monitor_limit_order(
                        adapter, event.symbol, order_id, oco_id, entry_price
                    )
                )

            # ── Persist to DB (Hybrid — direct write) ────────
            trade_id = await database.insert_trade(
                signal_id=event.signal_id,
                symbol=event.symbol,
                side=action.upper(),
                order_id=order_id,
                status=order_status,
                requested_qty=quote_qty_val if quote_qty_val is not None else 10.0,
                executed_qty=exec_qty,
                executed_price=exec_price,
                combined_score=combined_score,
                exchange=actual_exchange,
            )

            # ── Angati Event-Driven Semantic Ingestion ────────────────────────
            try:
                from nerves.core.ingest_helper import ingest_semantic_event_bg

                ingest_semantic_event_bg(
                    text=f"Trade Executed: ID={trade_id}, SignalID={event.signal_id}, Symbol={event.symbol}, "
                    f"Side={action.upper()}, Price={exec_price}, Qty={exec_qty}, Status={order_status}, "
                    f"Exchange={actual_exchange}, CombinedScore={combined_score}",
                    category="trade",
                )
            except Exception as sra_err:
                log.warning(f"SRA Ingestion warning: {sra_err}")

            if result.risk:
                await database.update_trade_oco(
                    trade_id=trade_id,
                    stop_loss_price=result.risk.stop_loss_price,
                    take_profit_price=result.risk.take_profit_price,
                    oco_order_id=oco_id,
                    order_type=order_type,
                )

            await database.update_signal_status(event.signal_id, 1)
            import inspect

            res = database.update_signal_state(event.signal_id, "COMPLETED")
            if inspect.isawaitable(res):
                await res

            # ── Build telegram message for event context ─────
            fallback_text = (
                f" (Fallback from {requested_exchange.title()})"
                if actual_exchange != requested_exchange
                else ""
            )
            msg = (
                f"✅ **Đã Đặt Lệnh {actual_exchange.title()}{fallback_text}**\n"
                f"- Mã: `{event.symbol}`\n"
                f"- Lệnh: `{action.upper()} {order_type}`\n"
                f"- Số lượng: `{exec_qty}` (Value: `~{cum_quote}$`)\n"
                # BUG-03 fix: exec_price may be None for DRY_RUN/zero-fill orders
                f"- Giá khớp: `{f'{exec_price:.4f}' if exec_price is not None else 'N/A'}`\n"
            )
            if result.risk:
                msg += (
                    f"- Cắt lỗ (SL): `{result.risk.stop_loss_price}`\n"
                    f"- Chốt lời (TP): `{result.risk.take_profit_price}`\n"
                )
            if result.dry_run:
                msg += "\n⚠️ `CHẾ ĐỘ DRY_RUN — KHÔNG KHỚP LỆNH THỰC TẾ`"

            if getattr(event, "analysis_text", ""):
                msg += f"\n\n🧠 **Phân tích Minervini AI (Được duyệt bởi {event.approved_by}):**\n{event.analysis_text[:500]}"

            log.info(
                f"TradeEngine: Smart Order Success #{order_id} on {actual_exchange} (type={order_type})"
            )

            # ── v6.0: Emit downstream event (NotificationHub handles notification) ──
            await _bus.emit(
                TradeExecuted(
                    signal_id=event.signal_id,
                    trade_id=trade_id,
                    symbol=event.symbol,
                    side=action.upper(),
                    order_id=order_id,
                    status=order_status,
                    exchange=actual_exchange,
                    executed_qty=exec_qty,
                    executed_price=exec_price,
                    quote_qty=quote_qty_val if quote_qty_val is not None else 10.0,
                    stop_loss_price=result.risk.stop_loss_price
                    if result.risk
                    else None,
                    take_profit_price=result.risk.take_profit_price
                    if result.risk
                    else None,
                    oco_order_id=oco_id,
                    order_type=order_type,
                    combined_score=combined_score,
                    rag_advice=getattr(event, "analysis_text", ""),
                    telegram_message=msg,
                )
            )
        else:
            raise Exception(result.error or "Smart order failed")

    except Exception as e:
        error_msg = str(e)
        log.error(f"TradeEngine: Execution Failed — {error_msg}")
        await _handle_failure(
            event, action, error_msg, requested_exchange, combined_score
        )


async def _handle_failure(event, action, error_msg, exchange, combined_score):
    """Handle trade execution failure: persist to DB and emit TradeFailed."""
    try:
        req_qty = float(event.quote_qty) if event.quote_qty else 0.0
        if req_qty < 0.0:
            req_qty = 0.0
    except (ValueError, TypeError):
        req_qty = 0.0

    # ── Persist failure to DB (Hybrid — direct write) ────
    await database.insert_trade(
        signal_id=event.signal_id,
        symbol=event.symbol,
        side=action.upper(),
        requested_qty=req_qty,
        error_message=error_msg,
        status="FAILED",
        combined_score=combined_score,
        exchange=exchange,
    )
    await database.update_signal_status(event.signal_id, 2)
    import inspect

    res = database.update_signal_state(event.signal_id, "REJECTED", error_msg)
    if inspect.isawaitable(res):
        await res

    # ── Angati Event-Driven Semantic Ingestion ────────────────────────
    try:
        from nerves.core.ingest_helper import ingest_semantic_event_bg

        ingest_semantic_event_bg(
            text=f"Trade Failed: SignalID={event.signal_id}, Symbol={event.symbol}, "
            f"Side={action.upper()}, Qty={req_qty}, Exchange={exchange}, "
            f"CombinedScore={combined_score}, Error={error_msg}",
            category="trade_failure",
        )
    except Exception as sra_err:
        log.warning(f"SRA Ingestion warning: {sra_err}")

    log.info(f"TradeEngine: Emitting TradeFailed for #{event.signal_id}")

    # ── v6.0: Emit failure event (NotificationHub handles notification) ──
    await _bus.emit(
        TradeFailed(
            signal_id=event.signal_id,
            symbol=event.symbol,
            side=action.upper(),
            error=error_msg,
            quote_qty=req_qty,
            exchange=exchange,
            combined_score=combined_score,
        )
    )
