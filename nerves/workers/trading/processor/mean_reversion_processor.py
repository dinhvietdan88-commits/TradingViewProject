import logging
import math
from core.events import MacroValidated, SignalValidated, SignalRejected
from core.event_bus import bus as _default_bus
from processor.base_processor import BaseSignalProcessor
import database

log = logging.getLogger(__name__)


class MeanReversionProcessor(BaseSignalProcessor):
    """Layer 3 Processor: Mean Reversion (MIS) Strategy."""

    def __init__(self) -> None:
        super().__init__(
            name="MeanReversionProcessor",
            knowledge_path="lobes/knowledge/mean_reversion/mean_reversion_rules.md",
        )
        self.load_knowledge()

    async def process(self, event: MacroValidated) -> bool:
        """Perform Mean Reversion validation using Bollinger Bands and RSI."""
        from capture_client import get_capture_client

        try:
            client = get_capture_client()
            ohlcv = await client.fetch_ohlcv(event.symbol, "D", limit=50)
            if not ohlcv or len(ohlcv) < 50:
                log.warning(
                    f"MeanReversionProcessor: Insufficient candles ({len(ohlcv) if ohlcv else 0}) "
                    f"for {event.symbol}. Fail-safe: accepting."
                )
                return True

            closes = [c[4] for c in ohlcv]
            mean_50 = sum(closes) / 50
            variance_50 = sum((x - mean_50) ** 2 for x in closes) / 50
            std_50 = math.sqrt(variance_50)
            vol = std_50 / mean_50 if mean_50 > 0 else 0.0

            # Dynamic Bollinger Band multiplier k
            k = 2.0 + 10.0 * vol
            k = max(1.5, min(3.0, k))

            # Dynamic RSI thresholds
            buy_rsi_threshold = 30.0 - 50.0 * vol
            buy_rsi_threshold = max(20.0, min(40.0, buy_rsi_threshold))

            sell_rsi_threshold = 70.0 + 50.0 * vol
            sell_rsi_threshold = max(60.0, min(80.0, sell_rsi_threshold))

            # Bollinger Bands (standard 20-period BB)
            closes_20 = closes[-20:]
            sma_20 = sum(closes_20) / 20
            variance_20 = sum((x - sma_20) ** 2 for x in closes_20) / 20
            std_20 = math.sqrt(variance_20)

            lower_bb = sma_20 - k * std_20
            upper_bb = sma_20 + k * std_20

            # RSI 14 calculation
            rsi = self.calculate_rsi(closes, 14)

            price = event.price if event.price is not None else closes[-1]
            action = event.action.lower()

            log.info(
                f"MeanReversionProcessor: Symbol {event.symbol} | Action: {action} | "
                f"Price: {price:.2f} | Lower BB: {lower_bb:.2f} | Upper BB: {upper_bb:.2f} | "
                f"RSI: {rsi:.2f} | Buy RSI Thresh: {buy_rsi_threshold:.2f} | Sell RSI Thresh: {sell_rsi_threshold:.2f}"
            )

            if action in ("buy", "long", "bo", "breakout_long"):
                accepted = price < lower_bb and rsi < buy_rsi_threshold
            elif action in ("sell", "short", "breakout_short"):
                accepted = price > upper_bb and rsi > sell_rsi_threshold
            else:
                log.warning(
                    f"MeanReversionProcessor: Unknown action '{action}', rejecting."
                )
                accepted = False

            return accepted

        except Exception as e:
            log.warning(
                f"MeanReversionProcessor: Error during analysis for {event.symbol} (fail-safe active): {e}"
            )
            return True

    def calculate_rsi(self, closes: list[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0

        changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [x if x > 0 else 0.0 for x in changes[:period]]
        losses = [-x if x < 0 else 0.0 for x in changes[:period]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        for change in changes[period:]:
            gain = change if change > 0 else 0.0
            loss = -change if change < 0 else 0.0

            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))


# Global instance
_processor = MeanReversionProcessor()


@_default_bus.on(MacroValidated)
async def process_mean_reversion(event: MacroValidated) -> None:
    """Subscriber for MacroValidated event to run Mean Reversion strategy filtering."""
    if event.mode != "MIS":
        return

    # Allow bus override for testing
    from processor.signal_processor import get_bus

    bus = get_bus() or _default_bus

    accepted = await _processor.process(event)
    if accepted:
        log.info(
            f"MeanReversionProcessor: Signal #{event.signal_id} validated for {event.symbol}"
        )
        import inspect

        res = database.update_signal_state(event.signal_id, "STRATEGY_PASSED")
        if inspect.isawaitable(res):
            _ = await res
        await bus.emit(
            SignalValidated(
                signal_id=event.signal_id,
                symbol=event.symbol,
                action=event.action,
                price=event.price,
                quote_qty=event.quote_qty,
                sl=event.sl,
                tp=event.tp,
                exchange=event.exchange,
                mode=event.mode,
                is_recovered=event.is_recovered,
                age_minutes=event.age_minutes,
                tas=event.mta_trend_score,
                sts=0.0,
                mlts=0.0,
                mta_calculated=True,
            )
        )
    else:
        log.warning(
            f"MeanReversionProcessor: Signal #{event.signal_id} rejected for {event.symbol}"
        )
        import inspect

        res = database.update_signal_state(
            event.signal_id, "REJECTED", "mean_reversion_indicators_failed"
        )
        if inspect.isawaitable(res):
            _ = await res
        await bus.emit(
            SignalRejected(
                signal_id=event.signal_id,
                symbol=event.symbol,
                action=event.action,
                reason="mean_reversion_indicators_failed",
                interval=event.interval,
                exchange=event.exchange,
            )
        )
