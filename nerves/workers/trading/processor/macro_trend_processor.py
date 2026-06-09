import asyncio
import logging
import config
from core.events import SignalIngested, SignalRejected
from core.event_bus import bus as _default_bus
from processor.base_processor import BaseSignalProcessor

log = logging.getLogger(__name__)


class MacroTrendProcessor(BaseSignalProcessor):
    """Specialized processor for assessing and filtering macro trend signals."""

    def __init__(self) -> None:
        super().__init__(
            name="MacroTrendProcessor",
            knowledge_path="lobes/knowledge/macro_trend/macro_regime_conditions.md",
        )
        self.load_knowledge()
        self.last_tas = 0.0
        self.last_sts = 0.0
        self.last_mlts = 0.0
        self.last_mta_calculated = False

    async def process(self, event: SignalIngested, bus=None) -> bool:
        """Assess macro trend based on daily and 4h candles.

        Returns True if accepted, False if rejected due to macro trend conflict or chop block.
        """
        if bus is None:
            bus = _default_bus

        action = event.action.lower()
        if action in ("bo", "breakout_long"):
            action = "buy"

        is_daily = event.interval.strip().lower() in {"d", "1d", "daily"}

        # ── Regime Switcher check ─────────────────────────────
        import database
        from engine.regime_switcher import get_market_regime

        try:
            regime = await get_market_regime(event.symbol, event.exchange)
            await database.set_setting("market_regime", regime)
        except Exception as regime_err:
            log.warning(
                f"MacroTrendProcessor: Failed to get market regime: {regime_err}"
            )
            regime = "TREND"  # default fail-safe

        if action in ("buy", "sell"):
            if is_daily:
                if regime == "CHOP":
                    log.warning(
                        f"MacroTrendProcessor: Rejecting Daily MTT signal for {event.symbol}: "
                        f"MTT Daily signals are blocked during CHOP market regime."
                    )
                    import inspect

                    res = database.update_signal_state(
                        event.signal_id, "REJECTED", "market_regime_chop_block"
                    )
                    if inspect.isawaitable(res):
                        await res
                    await bus.emit(
                        SignalRejected(
                            signal_id=event.signal_id,
                            symbol=event.symbol,
                            action=action,
                            reason="market_regime_chop_block",
                            interval=event.interval,
                            exchange=event.exchange,
                        )
                    )
                    return False

            if not config.MTA_ENABLED:
                self.last_tas = 0.0
                self.last_sts = 0.0
                self.last_mlts = 0.0
                self.last_mta_calculated = False
                return True

            try:
                from capture_client import get_capture_client

                client = get_capture_client()

                results = await asyncio.gather(
                    client.fetch_ohlcv(event.symbol, "D", limit=50),
                    client.fetch_ohlcv(event.symbol, "4h", limit=50),
                    client.fetch_ohlcv(event.symbol, "1h", limit=30),
                    client.fetch_ohlcv(event.symbol, "1m", limit=30),
                    client.fetch_ohlcv(event.symbol, "5m", limit=30),
                    client.fetch_ohlcv(event.symbol, "15m", limit=30),
                    client.fetch_ohlcv(event.symbol, "30m", limit=30),
                    return_exceptions=True,
                )
                daily_candles = (
                    results[0] if not isinstance(results[0], Exception) else None
                )
                fourhour_candles = (
                    results[1] if not isinstance(results[1], Exception) else None
                )
                onehour_candles = (
                    results[2] if not isinstance(results[2], Exception) else None
                )

                is_bullish_daily = False
                is_bullish_4h = False

                if daily_candles and len(daily_candles) > 0:
                    sma_daily = sum(c[4] for c in daily_candles) / len(daily_candles)
                    latest_close_daily = daily_candles[-1][4]
                    is_bullish_daily = latest_close_daily > sma_daily

                if fourhour_candles and len(fourhour_candles) > 0:
                    sma_4h = sum(c[4] for c in fourhour_candles) / len(fourhour_candles)
                    latest_close_4h = fourhour_candles[-1][4]
                    is_bullish_4h = latest_close_4h > sma_4h

                # Extract 1H local trend
                t_1h = 0
                if onehour_candles and len(onehour_candles) >= 20:
                    closes_1h = [c[4] for c in onehour_candles]
                    sma_1h = sum(closes_1h[-20:]) / 20
                    latest_close_1h = closes_1h[-1]
                    if latest_close_1h > sma_1h:
                        t_1h = 1
                    elif latest_close_1h < sma_1h:
                        t_1h = -1

                # Check sentiment layer
                combined_sentiment = 0.0
                if getattr(config, "SENTIMENT_ENABLED", True):
                    try:
                        from analyzer.sentiment_analyzer import SentimentAnalyzer

                        sent_analyzer = SentimentAnalyzer()
                        sentiment_res = await sent_analyzer.analyze_symbol(event.symbol)
                        if sentiment_res.get("enabled"):
                            combined_sentiment = sentiment_res["combined_score"]
                    except Exception as sent_err:
                        log.warning(
                            f"MacroTrendProcessor: Sentiment analysis failed (non-fatal): {sent_err}"
                        )

                # Veto rules & overrides
                veto = False
                if combined_sentiment > 0.6:
                    # bypass BUY technical vetoes, but veto SELL signals immediately
                    if action == "sell":
                        veto = True
                elif combined_sentiment < -0.6:
                    # bypass SELL technical vetoes, but veto BUY signals immediately
                    if action == "buy":
                        veto = True
                else:
                    # neutral sentiment: veto BUY if 1D and 4H bearish, veto SELL if 1D and 4H bullish
                    if action == "buy" and not is_bullish_daily and not is_bullish_4h:
                        veto = True
                    elif action == "sell" and is_bullish_daily and is_bullish_4h:
                        veto = True

                if veto:
                    log.warning(
                        f"MacroTrendProcessor: Rejecting {action.upper()} signal for {event.symbol} due to macro trend/sentiment veto "
                        f"(sentiment={combined_sentiment:.2f}, 1D close bullish={is_bullish_daily}, 4H close bullish={is_bullish_4h})"
                    )
                    import inspect

                    res = database.update_signal_state(
                        event.signal_id, "REJECTED", "macro_trend_conflict"
                    )
                    if inspect.isawaitable(res):
                        await res
                    await bus.emit(
                        SignalRejected(
                            signal_id=event.signal_id,
                            symbol=event.symbol,
                            action=action,
                            reason="macro_trend_conflict",
                            interval=event.interval,
                            exchange=event.exchange,
                        )
                    )
                    return False

                # If NOT rejected, precalculate the full MTA parameters (TAS, STS, MLTS)
                def get_trend(res) -> int:
                    if isinstance(res, Exception) or not res or len(res) < 10:
                        return 0
                    closes = [c[4] for c in res]
                    sma = sum(closes[-20:]) / len(closes[-20:])
                    latest = closes[-1]
                    return 1 if latest > sma else (-1 if latest < sma else 0)

                t_1m = get_trend(results[3])
                t_5m = get_trend(results[4])
                t_15m = get_trend(results[5])
                t_30m = get_trend(results[6])
                t_1h = get_trend(results[2])
                t_4h = get_trend(results[1])
                t_1d = get_trend(results[0])

                self.last_sts = (
                    config.MTA_STF_WEIGHT_1M * t_1m
                    + config.MTA_STF_WEIGHT_5M * t_5m
                    + config.MTA_STF_WEIGHT_15M * t_15m
                    + config.MTA_STF_WEIGHT_30M * t_30m
                )
                self.last_mlts = (
                    config.MTA_MLTF_WEIGHT_1H * t_1h
                    + config.MTA_MLTF_WEIGHT_4H * t_4h
                    + config.MTA_MLTF_WEIGHT_1D * t_1d
                )
                self.last_tas = self.last_sts + self.last_mlts
                self.last_mta_calculated = True

            except Exception as mta_err:
                log.warning(
                    f"MacroTrendProcessor: MTA macro filter failed (fail-safe bypass): {mta_err}"
                )
                self.last_tas = 0.0
                self.last_sts = 0.0
                self.last_mlts = 0.0
                self.last_mta_calculated = False

        return True


# Global instance
_processor = MacroTrendProcessor()


@_default_bus.on(SignalIngested)
async def process_macro_trend(event: SignalIngested) -> None:
    """Subscriber for SignalIngested event to run macro trend analysis."""
    # Allow bus override for testing
    from processor.signal_processor import get_bus

    bus = get_bus() or _default_bus

    accepted = await _processor.process(event, bus)
    if accepted:
        log.info(
            f"MacroTrendProcessor: Signal #{event.signal_id} macro trend validated — {event.action} {event.symbol}"
        )
        tas = getattr(_processor, "last_tas", 0.0)
        getattr(_processor, "last_sts", 0.0)
        getattr(_processor, "last_mlts", 0.0)
        getattr(_processor, "last_mta_calculated", False)

        # Reset them after read to avoid stale state for subsequent runs
        _processor.last_tas = 0.0
        _processor.last_sts = 0.0
        _processor.last_mlts = 0.0
        _processor.last_mta_calculated = False

        import database
        import inspect

        res = database.update_signal_state(event.signal_id, "MACRO_PASSED")
        if inspect.isawaitable(res):
            await res

        regime_val = database.get_setting("market_regime", "TREND")
        regime = await regime_val if inspect.isawaitable(regime_val) else "TREND"

        from core.events import MacroValidated

        await bus.emit(
            MacroValidated(
                signal_id=event.signal_id,
                symbol=event.symbol,
                action=event.action,
                price=event.price,
                quote_qty=event.quote_qty,
                interval=event.interval,
                sl=event.sl,
                tp=event.tp,
                exchange=event.exchange,
                mode=event.mode,
                is_recovered=event.is_recovered,
                age_minutes=event.age_minutes,
                mta_trend_score=tas,
                market_regime=regime,
            )
        )
