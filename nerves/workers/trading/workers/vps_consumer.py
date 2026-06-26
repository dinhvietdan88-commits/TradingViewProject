import asyncio
import logging
import socket
import sqlite3
from typing import Any

import aiohttp

import config
import database
from core.event_bus import bus as _event_bus
from core.events import (
    IndicatorSignalReceived,
    SignalReceived,
    SignalRejected,
    TradeExecuted,
    TradeFailed,
)

log = logging.getLogger(__name__)


class VpsSignalConsumer:
    """
    Consumer worker that pulls pending signals from the VPS Buffer Service (VBS),
    checks for duplicates (idempotency), dispatches to EventBus, and handles ACKs.
    """

    def __init__(self):
        self.pending_acks: dict[int, int] = {}  # local_signal_id -> vbs_queue_id
        self._session = None

        # Register EventBus listeners for execution outcomes
        _event_bus.on(TradeExecuted)(self.on_trade_executed)
        _event_bus.on(TradeFailed)(self.on_trade_failed)
        _event_bus.on(SignalRejected)(self.on_signal_rejected)

    async def get_session(self) -> aiohttp.ClientSession:
        """Get or initialize the persistent aiohttp ClientSession."""
        if not self._session or self._session.closed:
            conn = aiohttp.TCPConnector(family=socket.AF_INET)
            self._session = aiohttp.ClientSession(connector=conn)
        return self._session

    async def close(self):
        """Close the ClientSession."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def pull_signals(self, limit: int = 5) -> list[dict[str, Any]]:
        """Fetch pending signals from VBS consume-long endpoint."""
        url = f"{config.VPS_BUFFER_URL}/consume-long"
        params = {"consumer_id": config.VPS_CONSUMER_ID, "limit": limit, "timeout": 30}
        if getattr(config, "VPS_BUFFER_SOURCE_FILTER", None):
            params["source"] = config.VPS_BUFFER_SOURCE_FILTER
        if getattr(config, "VPS_BUFFER_EXCLUDE_FILTER", None):
            params["exclude_source"] = config.VPS_BUFFER_EXCLUDE_FILTER

        headers = {"X-Buffer-Secret": config.VPS_BUFFER_SECRET}

        client_timeout = aiohttp.ClientTimeout(connect=10, total=35)

        try:
            session = await self.get_session()
            async with session.get(
                url, params=params, headers=headers, timeout=client_timeout
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("signals", [])
                else:
                    log.error(
                        f"[VpsConsumer] Failed to pull signals from VBS (HTTP {resp.status}): {await resp.text()}"
                    )
                    raise aiohttp.ClientResponseError(
                        request_info=resp.request_info,
                        history=resp.history,
                        status=resp.status,
                        message=f"HTTP {resp.status}",
                        headers=resp.headers,
                    )
        except Exception as e:
            log.warning(f"[VpsConsumer] Connection error pulling signals from VBS: {e}")
            raise

    async def send_acks(self, acks: list[dict[str, Any]]) -> bool:
        """Send confirmations back to VBS."""
        if not acks:
            return True

        url = f"{config.VPS_BUFFER_URL}/ack"
        headers = {
            "X-Buffer-Secret": config.VPS_BUFFER_SECRET,
            "Content-Type": "application/json",
        }
        payload = {"acks": acks}

        try:
            session = await self.get_session()
            async with session.post(
                url, json=payload, headers=headers, timeout=10
            ) as resp:
                if resp.status == 200:
                    log.info(
                        f"[VpsConsumer] Successfully ACKed {len(acks)} signal(s) back to VBS."
                    )
                    return True
                else:
                    log.error(
                        f"[VpsConsumer] Failed to ACK signals on VBS (HTTP {resp.status}): {await resp.text()}"
                    )
        except Exception as e:
            log.error(f"[VpsConsumer] Connection error sending ACKs to VBS: {e}")

        return False

    async def on_startup(self):
        """Hook into application lifespan to drain queue at boot."""
        log.info("[VpsConsumer] Running startup signal recovery from VPS Buffer...")
        try:
            signals = await self.pull_signals(limit=config.VPS_STARTUP_PULL_LIMIT)
            if signals:
                log.info(
                    f"[VpsConsumer] Found {len(signals)} pending signal(s) on startup."
                )
                for signal in signals:
                    await self._process_signal(signal)
            else:
                log.info(
                    "[VpsConsumer] Startup recovery complete: No pending signals found."
                )
        except Exception as e:
            log.warning(f"[VpsConsumer] Startup recovery skipped or failed: {e}")

    async def poll_loop(self):
        """Continuous polling background task using long-polling."""
        log.info("[VpsConsumer] Starting background long-poll loop...")
        import secrets

        _backoff = 0  # current backoff in seconds (0 = no backoff)
        _MAX_BACKOFF = 60
        _consecutive_errors = 0
        while True:
            try:
                signals = await self.pull_signals(limit=5)
                # Reset backoff on success
                _backoff = 0
                _consecutive_errors = 0
                if not signals:
                    # Sleep 1 second when the poll returns empty
                    await asyncio.sleep(1)
                    continue

                # Process any returned signals immediately
                for signal in signals:
                    await self._process_signal(signal)
            except asyncio.CancelledError:
                log.info("[VpsConsumer] Background poll loop cancelled.")
                break
            except aiohttp.ClientResponseError as e:
                _consecutive_errors += 1
                if e.status in (401, 403):
                    # Auth errors won't self-resolve — long backoff, no traceback
                    _backoff = _MAX_BACKOFF
                    if _consecutive_errors <= 3 or _consecutive_errors % 20 == 0:
                        log.error(
                            f"[VpsConsumer] AUTH ERROR (HTTP {e.status}): VPS_BUFFER_SECRET mismatch. "
                            f"Check .env VPS_BUFFER_SECRET matches Server A BUFFER_SECRET. "
                            f"Retrying in {_backoff}s (error #{_consecutive_errors})"
                        )
                else:
                    # Other HTTP errors — standard backoff
                    _backoff = min(
                        _MAX_BACKOFF,
                        max(5, _backoff * 2) + secrets.SystemRandom().uniform(0, 2),
                    )
                    log.error(
                        f"[VpsConsumer] HTTP {e.status} from VBS. Sleeping {_backoff:.0f}s: {e}"
                    )
                await asyncio.sleep(_backoff)
            except (aiohttp.ClientConnectorError, ConnectionRefusedError, OSError) as e:
                # Network/connection errors — exponential backoff with jitter
                _consecutive_errors += 1
                _backoff = min(
                    _MAX_BACKOFF,
                    max(5, _backoff * 2) + secrets.SystemRandom().uniform(0, 2),
                )
                if _consecutive_errors <= 5 or _consecutive_errors % 20 == 0:
                    log.warning(
                        f"[VpsConsumer] Connection error to VBS (attempt #{_consecutive_errors}). "
                        f"Sleeping {_backoff:.0f}s: {e}"
                    )
                await asyncio.sleep(_backoff)
            except Exception as e:
                _consecutive_errors += 1
                _backoff = min(
                    _MAX_BACKOFF,
                    max(5, _backoff * 2) + secrets.SystemRandom().uniform(0, 2),
                )
                log.exception(
                    f"[VpsConsumer] Unexpected error in poll loop. Sleeping {_backoff:.0f}s: {e}"
                )
                await asyncio.sleep(_backoff)

    async def _process_signal(self, signal: dict[str, Any]):
        """Processes a single signal pulled from VPS."""
        queue_id = signal["queue_id"]
        age_minutes = signal["age_minutes"]
        symbol = signal["symbol"]
        action = signal["action"]
        payload = signal["payload"]

        mode = (
            payload.get("mode", "").strip().upper() if isinstance(payload, dict) else ""
        )
        mode_upper = mode.upper() if mode else ""
        if getattr(config, "FORWARD_TEST_ENABLED", False) and mode_upper not in (
            "LIVE",
            "BACKTEST",
        ):
            mode = "FORWARD"
            if isinstance(payload, dict):
                payload["mode"] = "FORWARD"
            else:
                payload = {"mode": "FORWARD"}
                signal["payload"] = payload

        log.info(
            f"[VpsConsumer] Processing signal #{queue_id} for {symbol} {action.upper()} (age: {age_minutes}m) | mode: {mode}"
        )

        # 1. TTL / Stale check
        if age_minutes > config.MAX_SIGNAL_AGE_MINUTES:
            log.warning(
                f"[VpsConsumer] Signal #{queue_id} exceeds MAX_SIGNAL_AGE_MINUTES ({age_minutes}m > {config.MAX_SIGNAL_AGE_MINUTES}m). Skipping."
            )
            await self.send_acks(
                [
                    {
                        "queue_id": queue_id,
                        "status": "skipped_stale",
                        "error_msg": f"Signal age ({age_minutes}m) exceeded configured limit ({config.MAX_SIGNAL_AGE_MINUTES}m)",
                    }
                ]
            )
            return

        # 2. Idempotency Check (Duplicate check)
        import aiosqlite

        mode_upper = mode.upper() if mode else ""
        db_path = (
            config.FORWARD_DB_PATH
            if (
                mode_upper == "FORWARD"
                or (
                    mode_upper not in ("LIVE", "BACKTEST")
                    and getattr(config, "FORWARD_TEST_ENABLED", False)
                )
            )
            else config.DB_PATH
        )
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT id FROM signals WHERE vbs_queue_id = ?", (queue_id,)
            ) as cur:
                exists = await cur.fetchone()

        if exists:
            log.warning(
                f"[VpsConsumer] Duplicate detection: Signal #{queue_id} already exists locally. Sending ACK."
            )
            await self.send_acks(
                [
                    {
                        "queue_id": queue_id,
                        "status": "executed",
                        "error_msg": "Duplicate signal already stored locally",
                    }
                ]
            )
            return

        # 3. Save to local DB (injecting vbs_queue_id)
        # Note: database.insert_signal returns the local signal_id
        price = signal.get("price")
        quote_qty = signal.get("quote_qty")
        mode = payload.get("mode", "").strip().upper()

        # Inject VBS timestamps and queue ID for later downstream edit use
        payload["vbs_received_at"] = signal.get("received_at")
        payload["vbs_expires_at"] = signal.get("expires_at")
        payload["vbs_queue_id"] = queue_id

        try:
            local_signal_id = await database.insert_signal(
                symbol=symbol,
                action=action,
                price=price,
                quote_qty=quote_qty,
                source_ip=payload.get("source_ip", "127.0.0.1"),
                payload=payload,
                mode=mode,
                vbs_queue_id=queue_id,
            )
        except (aiosqlite.IntegrityError, sqlite3.IntegrityError) as e:
            log.warning(
                f"[VpsConsumer] Duplicate signal detection via database constraint violation (race condition) for queue_id {queue_id}: {e}"
            )
            await self.send_acks(
                [
                    {
                        "queue_id": queue_id,
                        "status": "executed",
                        "message": "Duplicate signal already stored locally (race condition)",
                        "error_msg": "Duplicate signal already stored locally (race condition)",
                    }
                ]
            )
            return

        # 4. Dispatch to EventBus
        source = payload.get("source", "")
        indicator_name = payload.get("indicator_name") or payload.get("indicator") or ""

        age_minutes = float(signal.get("age_minutes", 0.0))
        is_recovered = age_minutes > 2.0
        is_indicator = source == "indicator" or (
            indicator_name and action.lower() not in {"buy", "sell", "alert"}
        )

        if is_indicator:
            signal_type = payload.get("signal_type", "info")
            interval = signal.get("interval", "")

            try:
                conf_score = int(payload.get("confidence_score", 0))
            except (ValueError, TypeError):
                conf_score = 0

            raw_conditions = payload.get("conditions_met", [])
            conditions_met = (
                tuple(str(c) for c in raw_conditions)
                if isinstance(raw_conditions, list)
                else ()
            )
            metadata = payload.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}

            # Save and emit IndicatorSignal
            log.info(
                f"[VpsConsumer] Emitting IndicatorSignalReceived for signal #{queue_id} (local #{local_signal_id})"
            )
            await _event_bus.emit_background(
                IndicatorSignalReceived(
                    signal_id=local_signal_id,
                    symbol=symbol,
                    indicator_name=indicator_name,
                    signal_type=signal_type,
                    interval=interval,
                    price=price,
                    conditions_met=conditions_met,
                    confidence_score=conf_score,
                    metadata=metadata,
                    source_ip="127.0.0.1",
                    exchange=signal.get("exchange", "binance"),
                    is_recovered=is_recovered,
                    age_minutes=age_minutes,
                )
            )

            # Indicator signals do not place orders, they are just persisted. Send ACK immediately.
            await self.send_acks([{"queue_id": queue_id, "status": "executed"}])
        else:
            # Map for asynchronous ACK when trade completes
            self.pending_acks[local_signal_id] = queue_id

            sl_str = payload.get("sl", "")
            tp_str = payload.get("tp", "")
            exchange = payload.get("exchange", config.DEFAULT_EXCHANGE)

            log.info(
                f"[VpsConsumer] Emitting SignalReceived for signal #{queue_id} (local #{local_signal_id})"
            )
            await _event_bus.emit_background(
                SignalReceived(
                    signal_id=local_signal_id,
                    symbol=symbol,
                    action=action,
                    price=price,
                    quote_qty=quote_qty if quote_qty else 10.0,
                    interval=signal.get("interval", ""),
                    mode=mode,
                    sl=sl_str,
                    tp=tp_str,
                    source_ip="127.0.0.1",
                    payload=payload,
                    exchange=exchange,
                    is_recovered=is_recovered,
                    age_minutes=age_minutes,
                )
            )

    # ── EventBus Callback Handlers ───────────────────────────────────────────

    async def on_trade_executed(self, event: TradeExecuted):
        """Triggered when trade execution is successful."""
        queue_id = self.pending_acks.pop(event.signal_id, None)
        if queue_id:
            log.info(
                f"[VpsConsumer] Trade executed successfully for signal #{event.signal_id}. Sending executed ACK."
            )
            await self.send_acks([{"queue_id": queue_id, "status": "executed"}])

    async def on_trade_failed(self, event: TradeFailed):
        """Triggered when trade execution fails."""
        queue_id = self.pending_acks.pop(event.signal_id, None)
        if queue_id:
            log.warning(
                f"[VpsConsumer] Trade failed for signal #{event.signal_id}: {event.error}. Sending failed ACK."
            )
            await self.send_acks(
                [{"queue_id": queue_id, "status": "failed", "error_msg": event.error}]
            )

    async def on_signal_rejected(self, event: SignalRejected):
        """Triggered when signal processor rejects the signal."""
        queue_id = self.pending_acks.pop(event.signal_id, None)
        if queue_id:
            log.warning(
                f"[VpsConsumer] Signal #{event.signal_id} rejected: {event.reason}. Sending ACK."
            )
            # Map rejection reason to status
            status = "failed"
            reason_lower = event.reason.lower()
            if (
                "stale" in reason_lower
                or "expire" in reason_lower
                or "old" in reason_lower
            ):
                status = "skipped_stale"

            await self.send_acks(
                [{"queue_id": queue_id, "status": status, "error_msg": event.reason}]
            )
