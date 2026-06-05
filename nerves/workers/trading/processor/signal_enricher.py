"""
SignalEnricher — Bridges IndicatorSignalValidated into the main pipeline.

Design Invariant DI-2:
    For entry/exit signals: emit SignalValidated (ATR-based SL/TP) → TradeEngine path.
    For info signals: notify directly via notifier (no trade execution, no AIAnalyzer screenshot).

REQ 5: ATR-based SL/TP computation
REQ 6: Informational signals notify only, no trade trigger
"""

import logging
from typing import Tuple

import notifier as _notifier
from core.event_bus import bus
from core.events import (
    IndicatorSignalValidated,
    SignalValidated,
    SignalRejected,
    IndicatorSignalRejected,
)

log = logging.getLogger(__name__)

_bus = bus


def set_bus(bus_instance) -> None:
    """Override the event bus instance (for testing)."""
    global _bus
    _bus = bus_instance


def _compute_sl_tp(price: float, metadata: dict) -> Tuple[str, str]:
    """
    Compute SL/TP based on ATR or percentage defaults.

    REQ 5.1 / 5.2: ATR path — sl = price - (atr*2), tp = price + (atr*3)
    REQ 5.3: Default path — sl = price * 0.95, tp = price * 1.10
    Property 12 & 13.
    """
    try:
        atr_raw = metadata.get("atr_value")
        if atr_raw is not None:
            atr = float(atr_raw)
            if atr > 0:
                sl = price - (atr * 2)
                tp = price + (atr * 3)
                return f"{sl:.6f}", f"{tp:.6f}"
    except (ValueError, TypeError) as e:
        log.warning(
            f"SignalEnricher: atr_value parse error — using percentage defaults ({e})"
        )

    # Default: 5% / 10%
    sl = price * 0.95
    tp = price * 1.10
    return f"{sl:.6f}", f"{tp:.6f}"


async def _validate_vision_and_route(
    event: IndicatorSignalValidated, action: str, sl: str, tp: str
) -> None:
    """Run screenshot capture + Vision-AI check in a background task."""
    try:
        from mcp_client import get_mcp_client

        mcp = get_mcp_client()

        drawings = [
            {
                "price": event.price,
                "label": f"Entry ({event.price:.2f})",
                "color": "#26a69a",
            }
        ]
        try:
            drawings.append(
                {
                    "price": float(sl),
                    "label": f"SL ({float(sl):.2f})",
                    "color": "#ef5350",
                }
            )
            drawings.append(
                {
                    "price": float(tp),
                    "label": f"TP ({float(tp):.2f})",
                    "color": "#2962ff",
                }
            )
        except (ValueError, TypeError):
            pass

        import re
        from pathlib import Path
        from datetime import datetime

        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_symbol = re.sub(r"[^A-Za-z0-9_\-]", "", event.symbol)
        save_path = (
            Path(__file__).parent.parent
            / "screenshots"
            / f"indicator_{safe_symbol}_{ts_str}.png"
        )

        screenshot_path = await mcp.capture_screenshot(
            symbol=event.symbol,
            timeframe="1h",
            region="chart",
            save_path=save_path,
            active_only=False,
            crop=True,
            drawings=drawings,
        )
    except Exception as e:
        log.warning(f"Vision Enricher: Screenshot capture failed: {e}")
        screenshot_path = None

    try:
        import vision as vision_module

        vision_result = await vision_module.analyze_chart_vision(
            image_path=Path(screenshot_path)
            if screenshot_path
            else Path("nonexistent.png"),
            symbol=event.symbol,
            scan_result=event.metadata,
        )
    except Exception as e:
        log.error(f"Vision Enricher: Vision validation raised exception: {e}")
        vision_result = {"confidence": 0, "error": str(e)}

    confidence = vision_result.get("confidence", 0)
    log.info(f"Vision Enricher: {event.symbol} vision confidence is {confidence}/10")

    # Reject if visual confidence < 7.0
    if confidence < 7:
        log.warning(
            f"Vision Enricher: Signal rejected due to low visual confidence ({confidence}/10 < 7.0)"
        )
        await _bus.emit(
            IndicatorSignalRejected(
                signal_id=event.signal_id,
                symbol=event.symbol,
                indicator_name=event.indicator_name,
                signal_type=event.signal_type,
                reason=f"low_visual_confidence_{confidence}",
                exchange=event.exchange,
            )
        )
    else:
        # Check market regime before routing (Part of Component 2)
        # We will route the validated signal to SignalValidated event
        await _bus.emit(
            SignalValidated(
                signal_id=event.signal_id,
                symbol=event.symbol,
                action=action,
                price=event.price,
                quote_qty=10.0,
                sl=sl,
                tp=tp,
                exchange=event.exchange,
            )
        )


@bus.on(IndicatorSignalValidated)
async def enrich_indicator_signal(event: IndicatorSignalValidated) -> None:
    """
    Bridges IndicatorSignalValidated to the main execution pipeline.

    entry/exit → ATR-computed SL/TP → emit SignalValidated → TradeEngine
    info       → Vietnamese Telegram notification (REQ 6, no trade execution)
    """
    if event.signal_type in {"entry", "exit"}:
        # REQ 5.4: entry → buy, exit → sell
        action = "buy" if event.signal_type == "entry" else "sell"

        # REQ 5.1-5.3: ATR-based or percentage SL/TP
        if event.price is None:
            log.error(
                f"SignalEnricher: Cannot compute SL/TP — price is None "
                f"(indicator={event.indicator_name}, signal_id={event.signal_id})"
            )
            await _bus.emit(
                SignalRejected(
                    signal_id=event.signal_id,
                    symbol=event.symbol,
                    action=action,
                    reason="enrichment_failed",
                    exchange=event.exchange,
                )
            )
            return

        metadata = event.metadata or {}
        sl, tp = _compute_sl_tp(event.price, metadata)

        if event.signal_type == "entry":
            # Asynchronous background task for vision AI check
            import asyncio

            asyncio.create_task(_validate_vision_and_route(event, action, sl, tp))
        else:
            # exit signal directly routes to execute
            await _bus.emit(
                SignalValidated(
                    signal_id=event.signal_id,
                    symbol=event.symbol,
                    action=action,
                    price=event.price,
                    quote_qty=10.0,
                    sl=sl,
                    tp=tp,
                    exchange=event.exchange,
                )
            )

    else:
        # REQ 6.1-6.3: info → notify directly (no AIAnalyzer / no screenshot capture)
        conditions_str = (
            ", ".join(event.conditions_met) if event.conditions_met else "Không có"
        )
        priority_prefix = "🔴 **KHẨN CẤP** — " if event.confidence_score > 80 else ""

        msg = (
            f"{priority_prefix}📊 **Tín Hiệu Thông Tin — {event.indicator_name}**\n"
            f"- Mã: `{event.symbol}`\n"
            f"- Sàn: `{event.exchange.upper()}`\n"
            f"- Điều kiện: `{conditions_str}`\n"
            f"- Độ tin cậy: `{event.confidence_score}%`\n"
            f"- Signal ID: `#{event.signal_id}`"
        )

        log.info(
            f"SignalEnricher: info signal for {event.symbol} "
            f"({event.indicator_name}, confidence={event.confidence_score}%)"
        )
        try:
            await _notifier.notify_all(msg)
        except Exception as e:
            log.error(
                f"SignalEnricher: Telegram notify failed for info signal #{event.signal_id}: {e}"
            )
