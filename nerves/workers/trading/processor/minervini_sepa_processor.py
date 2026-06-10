import logging
from core.events import MacroValidated, SignalValidated, SignalRejected
from core.event_bus import bus as _default_bus
from processor.base_processor import BaseSignalProcessor
import database
import analysis

log = logging.getLogger(__name__)


class MinerviniSepaProcessor(BaseSignalProcessor):
    """Layer 3 Processor: Minervini SEPA Strategy."""

    def __init__(self) -> None:
        super().__init__(
            name="MinerviniSepaProcessor",
            knowledge_path="lobes/knowledge/sepa/minervini_sepa_rules.md",
        )
        self.load_knowledge()

    async def process(self, event: MacroValidated) -> bool:
        """Perform Trend Template checks (score >= 5) and VCP detection."""
        from capture_client import get_capture_client

        try:
            client = get_capture_client()
            ohlcv = await client.fetch_ohlcv(event.symbol, "D", limit=365)
            if not ohlcv or len(ohlcv) < 50:
                log.warning(
                    f"MinerviniSepaProcessor: Insufficient candles ({len(ohlcv) if ohlcv else 0}) "
                    f"for {event.symbol}. Fail-safe: accepting."
                )
                return True

            # Calculate Trend Template and VCP using analysis engine
            res = analysis._calculate_scan_result(
                ohlcv, event.exchange, event.symbol, {}, []
            )
            score = res.trend_template.score
            vcp_detected = res.vcp.detected

            log.info(
                f"MinerviniSepaProcessor: Symbol {event.symbol} | "
                f"TT Score: {score}/8 | VCP Detected: {vcp_detected} ({res.vcp.note})"
            )

            # Trend Template score check (>= 5)
            return score >= 5

        except Exception as e:
            log.warning(
                f"MinerviniSepaProcessor: Error during analysis for {event.symbol} (fail-safe active): {e}"
            )
            return True


# Global instance
_processor = MinerviniSepaProcessor()


@_default_bus.on(MacroValidated)
async def process_minervini_sepa(event: MacroValidated) -> None:
    """Subscriber for MacroValidated event to run SEPA strategy filtering."""
    if event.mode not in ("MTT", "", None):
        return

    # Allow bus override for testing
    from processor.signal_processor import get_bus

    bus = get_bus() or _default_bus

    accepted = await _processor.process(event)
    if accepted:
        log.info(
            f"MinerviniSepaProcessor: Signal #{event.signal_id} validated for {event.symbol}"
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
            f"MinerviniSepaProcessor: Signal #{event.signal_id} rejected for {event.symbol}"
        )
        import inspect

        res = database.update_signal_state(
            event.signal_id, "REJECTED", "sepa_trend_template_failed"
        )
        if inspect.isawaitable(res):
            _ = await res
        await bus.emit(
            SignalRejected(
                signal_id=event.signal_id,
                symbol=event.symbol,
                action=event.action,
                reason="sepa_trend_template_failed",
                interval=event.interval,
                exchange=event.exchange,
            )
        )
