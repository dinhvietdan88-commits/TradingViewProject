import asyncio
import logging
import config
from core.events import SignalReceived
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

    async def process(self, event: SignalReceived) -> bool:
        """Assess macro trend based on daily and 4h candles.

        Returns True if accepted, False if rejected due to macro trend conflict.
        """
        is_daily = event.interval.strip().lower() in {"d", "1d", "daily"}
        if is_daily:
            return True

        if not config.MTA_ENABLED:
            return True

        action = event.action.lower()
        if action in ("bo", "breakout_long"):
            action = "buy"

        if action not in ("buy", "sell"):
            return True

        try:
            from capture_client import get_capture_client

            client = get_capture_client()

            results = await asyncio.gather(
                client.fetch_ohlcv(event.symbol, "D", limit=50),
                client.fetch_ohlcv(event.symbol, "4h", limit=50),
                return_exceptions=True,
            )
            daily_candles = (
                results[0] if not isinstance(results[0], Exception) else None
            )
            fourhour_candles = (
                results[1] if not isinstance(results[1], Exception) else None
            )

            if (
                daily_candles
                and fourhour_candles
                and len(daily_candles) > 0
                and len(fourhour_candles) > 0
            ):
                sma_daily = sum(c[4] for c in daily_candles) / len(daily_candles)
                latest_close_daily = daily_candles[-1][4]

                sma_4h = sum(c[4] for c in fourhour_candles) / len(fourhour_candles)
                latest_close_4h = fourhour_candles[-1][4]

                is_bullish_daily = latest_close_daily > sma_daily
                is_bullish_4h = latest_close_4h > sma_4h

                if action == "buy" and not is_bullish_daily and not is_bullish_4h:
                    log.warning(
                        f"MacroTrendProcessor: Rejecting BUY signal for {event.symbol} due to Bearish macro trend "
                        f"(1D close {latest_close_daily:.2f} < SMA {sma_daily:.2f}, 4H close {latest_close_4h:.2f} < SMA {sma_4h:.2f})"
                    )
                    return False

                if action == "sell" and is_bullish_daily and is_bullish_4h:
                    log.warning(
                        f"MacroTrendProcessor: Rejecting SELL signal for {event.symbol} due to Bullish macro trend "
                        f"(1D close {latest_close_daily:.2f} > SMA {sma_daily:.2f}, 4H close {latest_close_4h:.2f} > SMA {sma_4h:.2f})"
                    )
                    return False
        except Exception as mta_err:
            log.warning(
                f"MacroTrendProcessor: MTA macro filter failed (fail-safe bypass): {mta_err}"
            )

        return True
