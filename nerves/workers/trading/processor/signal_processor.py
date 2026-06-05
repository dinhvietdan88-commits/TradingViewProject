"""
SignalProcessor — Deduplication, timeframe validation, and strategy routing.

Listens to: SignalReceived
Emits: SignalValidated | SignalRejected

Design Invariants:
- Dedup cache prevents duplicate signals within a TTL window.
- Circuit Breaker: Only 1H (60/1h/60m) timeframes are allowed for live trading.
- Stateless except for in-memory dedup cache.
"""

import logging
import time
from typing import Dict, Tuple

from core.event_bus import bus as _default_bus
from core.events import (
    SignalReceived,
    SignalValidated,
    SignalRejected,
    AlertTriggered,
    IndicatorSignalReceived,
    IndicatorSignalValidated,
    IndicatorSignalRejected,
)

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
# DEDUP CACHE
# ═══════════════════════════════════════════════════════════════

# In-memory dedup: key = (symbol, action), value = timestamp
_dedup_cache: Dict[Tuple[str, str], float] = {}
DEDUP_TTL_SEC = 60  # Ignore identical signals within 60s


def _is_duplicate(symbol: str, action: str) -> bool:
    """Check if this signal is a duplicate within the TTL window."""
    # BUG-04 fix: normalize both symbol AND action to upper/lower consistently
    # Using (upper, lower) to match how the key is built throughout the module
    key = (symbol.strip().upper(), action.strip().lower())
    now = time.time()
    last_seen = _dedup_cache.get(key, 0)
    if now - last_seen < DEDUP_TTL_SEC:
        return True
    _dedup_cache[key] = now
    return False


_indicator_dedup_cache: Dict[Tuple[str, str, str], float] = {}


def _is_indicator_duplicate(symbol: str, indicator_name: str, signal_type: str) -> bool:
    key = (
        symbol.strip().upper(),
        indicator_name.strip().lower(),
        signal_type.strip().lower(),
    )
    now = time.time()
    last_seen = _indicator_dedup_cache.get(key, 0)
    if now - last_seen < DEDUP_TTL_SEC:
        return True
    _indicator_dedup_cache[key] = now
    return False


# ═══════════════════════════════════════════════════════════════
# TIMEFRAME VALIDATION (Circuit Breaker)
# ═══════════════════════════════════════════════════════════════

VALID_TRADE_INTERVALS = {"5", "5m", "15", "15m", "30", "30m", "60", "1h", "60m"}


def _is_valid_trade_interval(interval: str) -> bool:
    """A.007 v2.1: accepts 5m/15m/30m/1H timeframes for adaptive EMA strategy."""
    return interval.strip().lower() in VALID_TRADE_INTERVALS


# ═══════════════════════════════════════════════════════════════
# EVENT HANDLER
# ═══════════════════════════════════════════════════════════════


@_default_bus.on(SignalReceived)
async def process_signal(event: SignalReceived) -> None:
    """
    Core signal processing logic:
    1. Skip dedup check for 'alert' actions (they go to AIAnalyzer directly).
    2. For 'buy'/'sell': validate timeframe, check dedup.
    3. Emit SignalValidated or SignalRejected accordingly.
    """
    action = event.action.lower()
    if action in ("bo", "breakout_long"):
        action = "buy"

    # Alert signals bypass trade validation — emit AlertTriggered for AIAnalyzer
    if action == "alert":
        log.info(
            f"SignalProcessor: Alert signal #{event.signal_id} for {event.symbol} — emitting AlertTriggered"
        )
        await _bus.emit(
            AlertTriggered(
                signal_id=event.signal_id,
                symbol=event.symbol,
                price=str(event.price) if event.price else "",
                quote_qty=event.quote_qty,
                rag_advice=event.rag_advice,
                exchange=getattr(event, "exchange", "binance") or "binance",
                is_recovered=event.is_recovered,
                age_minutes=event.age_minutes,
            )
        )
        return

    # BUG-04 fix: normalize action before passing to _is_duplicate so key is consistent
    action = action.strip().lower()
    # ── Dedup Check ──────────────────────────────────────────
    if _is_duplicate(event.symbol, action):
        log.warning(
            f"SignalProcessor: Duplicate signal rejected — {action} {event.symbol}"
        )
        await _bus.emit(
            SignalRejected(
                signal_id=event.signal_id,
                symbol=event.symbol,
                action=action,
                reason="duplicate_signal",
                exchange=event.exchange,
            )
        )
        return

    # ── Timeframe & Regime Circuit Breaker ───────────────────
    from engine.regime_switcher import get_market_regime
    import database

    regime = await get_market_regime(event.symbol, event.exchange)
    await database.set_setting("market_regime", regime)

    is_daily = event.interval.strip().lower() in {"d", "1d", "daily"}
    is_1h = event.interval.strip().lower() in {"60", "1h", "60m"}

    if action in ("buy", "sell"):
        if is_daily:
            if regime == "CHOP":
                log.warning(
                    f"SignalProcessor: Rejecting Daily MTT signal for {event.symbol}: "
                    f"MTT Daily signals are blocked during CHOP market regime."
                )
                await _bus.emit(
                    SignalRejected(
                        signal_id=event.signal_id,
                        symbol=event.symbol,
                        action=action,
                        reason="market_regime_chop_block",
                        interval=event.interval,
                        exchange=event.exchange,
                    )
                )
                return
        elif not is_1h:
            log.warning(
                f"SignalProcessor: Rejecting trade for {event.symbol}: "
                f"invalid interval '{event.interval}'. Only 1h/60 or Daily (trending) is allowed."
            )
            await _bus.emit(
                SignalRejected(
                    signal_id=event.signal_id,
                    symbol=event.symbol,
                    action=action,
                    reason="invalid_timeframe",
                    interval=event.interval,
                    exchange=event.exchange,
                )
            )
            return
    else:
        # Fallback for unknown actions
        log.warning(f"SignalProcessor: Unknown action '{action}' for {event.symbol}")
        await _bus.emit(
            SignalRejected(
                signal_id=event.signal_id,
                symbol=event.symbol,
                action=action,
                reason="unknown_action",
                exchange=event.exchange,
            )
        )
        return

    # ── Validated — emit downstream ──────────────────────────
    log.info(
        f"SignalProcessor: Signal #{event.signal_id} validated — {action} {event.symbol}"
    )
    await _bus.emit(
        SignalValidated(
            signal_id=event.signal_id,
            symbol=event.symbol,
            action=action,
            price=event.price,
            quote_qty=event.quote_qty,
            sl=event.sl,
            tp=event.tp,
            exchange=event.exchange,
            mode=getattr(event, "mode", ""),
            is_recovered=event.is_recovered,
            age_minutes=event.age_minutes,
        )
    )


def reset_dedup_cache() -> None:
    """Clear dedup cache — for testing."""
    _dedup_cache.clear()
    _indicator_dedup_cache.clear()


@_default_bus.on(IndicatorSignalReceived)
async def process_indicator_signal(event: IndicatorSignalReceived) -> None:
    """
    Indicator signal validation:
    1. Validate signal_type in {"entry", "exit", "info"}
    2. Clamp confidence_score to [0, 100]
    3. Dedup check using (symbol, indicator_name, signal_type) key
    4. Timeframe validation for entry signals only
    5. Emit IndicatorSignalValidated or IndicatorSignalRejected
    """
    if event.signal_type not in {"entry", "exit", "info"}:
        await _bus.emit(
            IndicatorSignalRejected(
                signal_id=event.signal_id,
                symbol=event.symbol,
                indicator_name=event.indicator_name,
                signal_type=event.signal_type,
                reason="invalid_signal_type",
                exchange=event.exchange,
            )
        )
        return

    clamped_score = max(0, min(100, event.confidence_score))

    if clamped_score < 50:
        await _bus.emit(
            IndicatorSignalRejected(
                signal_id=event.signal_id,
                symbol=event.symbol,
                indicator_name=event.indicator_name,
                signal_type=event.signal_type,
                reason="low_confidence",
                exchange=event.exchange,
            )
        )
        return

    if _is_indicator_duplicate(event.symbol, event.indicator_name, event.signal_type):
        await _bus.emit(
            IndicatorSignalRejected(
                signal_id=event.signal_id,
                symbol=event.symbol,
                indicator_name=event.indicator_name,
                signal_type=event.signal_type,
                reason="duplicate_signal",
                exchange=event.exchange,
            )
        )
        return

    from engine.regime_switcher import get_market_regime
    import database

    regime = await get_market_regime(event.symbol, event.exchange)
    await database.set_setting("market_regime", regime)

    is_daily = event.interval.strip().lower() in {"d", "1d", "daily"}
    is_1h = event.interval.strip().lower() in {"60", "1h", "60m"}

    if event.signal_type == "entry":
        if is_daily:
            if regime == "CHOP":
                log.warning(
                    f"SignalProcessor: Rejecting Daily indicator entry for {event.symbol} due to CHOP regime"
                )
                await _bus.emit(
                    IndicatorSignalRejected(
                        signal_id=event.signal_id,
                        symbol=event.symbol,
                        indicator_name=event.indicator_name,
                        signal_type=event.signal_type,
                        reason="market_regime_chop_block",
                        exchange=event.exchange,
                    )
                )
                return
        elif not is_1h:
            log.warning(
                f"SignalProcessor: Rejecting indicator entry for {event.symbol} - invalid interval {event.interval}"
            )
            await _bus.emit(
                IndicatorSignalRejected(
                    signal_id=event.signal_id,
                    symbol=event.symbol,
                    indicator_name=event.indicator_name,
                    signal_type=event.signal_type,
                    reason="invalid_timeframe",
                    exchange=event.exchange,
                )
            )
            return

    await _bus.emit(
        IndicatorSignalValidated(
            signal_id=event.signal_id,
            symbol=event.symbol,
            indicator_name=event.indicator_name,
            signal_type=event.signal_type,
            price=event.price,
            conditions_met=event.conditions_met,
            confidence_score=clamped_score,
            metadata=event.metadata,
            exchange=event.exchange,
        )
    )
