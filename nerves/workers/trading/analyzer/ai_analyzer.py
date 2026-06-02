"""
AIAnalyzer — Stealth Capture + Vision AI + RAG analysis pipeline.

Listens to: AlertTriggered, SignalValidated
Emits: AnalysisComplete

Design Invariants (v6.0):
- Owns LAST_CAPTURE_TIME state (architecture spec: AIAnalyzer owns last_capture_time).
- Does NOT call notifier directly — all notifications go through NotificationHub via events.
- Confidence scoring: Vision (1-10) + RAG modifiers → final confidence 1-10.
- R:R enforcement is delegated to the user (Human Gate). AIAnalyzer always passes
  SL/TP/risk data through to AnalysisComplete for the user to decide.
- The confidence gate thresholds (>=8 auto, 5-7 human, <5 reject) are enforced
  by NotificationHub, NOT here. AIAnalyzer only computes the score.
"""
import logging
import re
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional

import config
import database
import vision as vision_module
from mcp_client import get_mcp_client

from core.event_bus import bus as _default_bus
from core.events import AlertTriggered, AnalysisComplete, SignalValidated

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
# OWNED STATE — Stealth Capture Cooldown
# ═══════════════════════════════════════════════════════════════

LAST_CAPTURE_TIME: Dict[str, float] = {}
CAPTURE_COOLDOWN_SEC = 300  # 5 minutes per symbol


def reset_capture_state() -> None:
    """Clear capture cooldown state — for testing."""
    LAST_CAPTURE_TIME.clear()


# ═══════════════════════════════════════════════════════════════
# EVENT HANDLER: AlertTriggered → route to unified pipeline
# ═══════════════════════════════════════════════════════════════

@_default_bus.on(AlertTriggered)
async def process_alert(event: AlertTriggered) -> None:
    """
    Handle stealth capture workflow for 'alert' actions.
    Re-emit as SignalValidated so the unified pipeline handles it.
    """
    log.info(f"AIAnalyzer: Stealth capture alert for {event.symbol} — routing to unified pipeline")
    await _bus.emit(SignalValidated(
        signal_id=event.signal_id,
        symbol=event.symbol,
        action="alert",
        price=float(event.price) if event.price else None,
        quote_qty=event.quote_qty,
        sl="",
        tp="",
        exchange=getattr(event, "exchange", None) or "binance",
        is_recovered=event.is_recovered,
        age_minutes=event.age_minutes,
    ))


# ═══════════════════════════════════════════════════════════════
# EVENT HANDLER: SignalValidated → Unified AI Analysis Pipeline
# ═══════════════════════════════════════════════════════════════

@_default_bus.on(SignalValidated)
async def process_validated_signal(event: SignalValidated) -> None:
    """
    Unified AI Analysis Pipeline (Vision + RAG).
    1. Capture screenshot via MCP.
    2. Run Vision AI analysis → confidence 1-10.
    3. Run RAG Analysis → modifier on confidence.
    4. Compute final confidence score.
    5. Emit AnalysisComplete (NotificationHub decides the gate).

    v6.0: AIAnalyzer does NOT enforce confidence thresholds.
    That responsibility belongs to NotificationHub (INV-5/6).
    """
    log.info(f"AIAnalyzer: Processing validated signal #{event.signal_id} for {event.symbol} (Action: {event.action})")

    symbol = event.symbol
    now = datetime.now(timezone.utc).timestamp()

    # ── Cooldown check (only for 'alert' actions) ────────────
    if event.action == "alert":
        last_time = LAST_CAPTURE_TIME.get(symbol, 0)
        if now - last_time < CAPTURE_COOLDOWN_SEC:
            log.warning(f"AIAnalyzer: Cooldown active for {symbol}. Skipping capture.")
            return
        LAST_CAPTURE_TIME[symbol] = now

    screenshot_path = ""
    vision_result = {}
    analysis_text = ""
    confidence = 5  # v6.0: Neutral default — forces human gate unless Vision raises it
    combined_score_str: Optional[str] = None

    # ── Step 1: Screenshot + Vision AI ───────────────────────
    try:
        mcp = get_mcp_client()
        
        # Build drawings and strategy table parameters for fast rendering
        drawings = []
        if event.price is not None:
            drawings.append({"price": event.price, "label": f"Entry ({event.price:.2f})", "color": "#26a69a"})
        try:
            if event.sl:
                drawings.append({"price": float(event.sl), "label": f"SL ({float(event.sl):.2f})", "color": "#ef5350"})
        except (ValueError, TypeError):
            pass
        try:
            if event.tp:
                drawings.append({"price": float(event.tp), "label": f"TP ({float(event.tp):.2f})", "color": "#2962ff"})
        except (ValueError, TypeError):
            pass

        rows = []
        if event.action:
            rows.append(("Action", event.action.upper()))
        if event.price is not None:
            rows.append(("Entry Price", f"{event.price:.2f}"))
        try:
            if event.sl:
                rows.append(("Stop Loss", f"{float(event.sl):.2f}"))
        except (ValueError, TypeError):
            pass
        try:
            if event.tp:
                rows.append(("Take Profit", f"{float(event.tp):.2f}"))
        except (ValueError, TypeError):
            pass

        strategy_table = None
        if rows:
            strategy_table = {
                "title": f"{symbol} Setup",
                "rows": rows
            }

        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_symbol = re.sub(r'[^A-Za-z0-9_\-]', '', symbol)
        save_path = Path(__file__).parent.parent / "screenshots" / f"stealth_{safe_symbol}_{ts_str}.png"

        screenshot_path = await mcp.capture_screenshot(
            symbol=symbol,
            timeframe="1h",
            region="chart",
            save_path=save_path,
            active_only=False,  # Specific symbol rendering is preferred
            crop=True,
            drawings=drawings,
            strategy_table=strategy_table
        )

        if screenshot_path and Path(screenshot_path).exists():
            vision_result = await vision_module.analyze_chart_vision(
                image_path=Path(screenshot_path),
                symbol=symbol,
            )

            if not vision_result.get("error"):
                analysis_text += "👁️ **VISION AI:**\n" + vision_result.get("analysis", "") + "\n\n"
                # v6.0: Use vision confidence directly (1-10 scale)
                confidence = vision_result.get("confidence", 5)
            else:
                analysis_text += f"❌ Vision Error: {vision_result['error']}\n\n"
                confidence = 3  # Error → low confidence
        else:
            log.warning("AIAnalyzer: Screenshot capture failed or not found, skipping Vision AI.")
            analysis_text += "⚠️ Không thể chụp ảnh biểu đồ. Bỏ qua phân tích hình ảnh.\n\n"
            confidence = 5

    except Exception as e:
        log.error(f"AIAnalyzer: Vision capture failed: {e}")
        analysis_text += f"❌ Lỗi chụp ảnh: {e}\n\n"
        confidence = 3  # Error → low confidence
        # BUG-02 fix: enforce cooldown even on error to prevent retry storms
        if event.action == "alert":
            LAST_CAPTURE_TIME[symbol] = now

    # ── Step 2: RAG Analysis ─────────────────────────────────
    rag_advice = ""
    if config.RAG_ENABLED:
        try:
            import rag
            payload = {"action": event.action, "symbol": event.symbol, "alert_type": "webhook"}
            query = rag.build_rag_query(event.symbol, event.action, payload)
            if rag._collection is not None:
                chunks = rag.query_knowledge(query, n_results=config.RAG_TOP_K)
                if chunks:
                    rag_advice = await rag.generate_trading_advice(
                        symbol=event.symbol,
                        action=event.action,
                        price=str(event.price) if event.price else "Market",
                        payload=payload,
                        rag_chunks=chunks,
                    )
                    analysis_text += "📚 **RAG KNOWLEDGE:**\n" + rag_advice

                    # v6.0: RAG can penalize confidence for warnings
                    advice_upper = rag_advice.upper()
                    if any(kw in advice_upper for kw in ("CẢNH BÁO", "WARNING", "YẾU", "CHỜ THÊM XÁC NHẬN")):
                        confidence = max(1, confidence - 2)
        except Exception as e:
            log.error(f"AIAnalyzer: RAG analysis error: {e}")
            analysis_text += f"Lỗi RAG: {e}"

    # ── Step 3: Compute final verdict flags ──────────────────
    # v6.0 INV-5/6: Threshold enforcement is in NotificationHub.
    # AIAnalyzer only computes and passes the confidence score.
    should_trade = confidence >= 8
    interactive_required = 5 <= confidence <= 7

    combined_score_str = f"{confidence}/10"

    # ── Step 4: Persist to DB (Hybrid — direct write) ────────
    try:
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        await database.insert_brief(
            symbols_scanned=1,
            scan_data=json.dumps([{"symbol": symbol, "source": "unified_pipeline"}]),
            ai_analysis=analysis_text,
            vision_data=json.dumps(vision_result),
            screenshot=str(screenshot_path) if screenshot_path else "",
            brief_text=f"[{event.action.upper()}] {symbol} @ {ts_str}\n\n{analysis_text}",
            success=1,
        )
    except Exception as db_err:
        log.warning(f"AIAnalyzer: Failed to persist capture to DB: {db_err}")

    # ── Step 5: Parse SL & TP from AI analysis text ──────────
    sl_val = event.sl
    tp_val = event.tp
    if not sl_val or not tp_val:
        sl_match = re.search(r"Stop\s*Loss:.*?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)", analysis_text, re.IGNORECASE)
        tp_match = re.search(r"Take\s*Profit:.*?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)", analysis_text, re.IGNORECASE)
        if sl_match and not sl_val: sl_val = sl_match.group(1).replace(",", "")
        if tp_match and not tp_val: tp_val = tp_match.group(1).replace(",", "")

    # BUG-05 fix: Directional validation of AI-extracted SL/TP.
    # Vision AI / RAG text may output SL/TP using BUY-side convention
    # regardless of the actual trade direction. Swap if mismatched.
    if sl_val and tp_val and event.price:
        try:
            _sl = float(str(sl_val).replace(",", ""))
            _tp = float(str(tp_val).replace(",", ""))
            _entry = float(event.price)
            if _entry > 0 and _sl > 0 and _tp > 0:
                if event.action.lower() == "sell":
                    # SELL: SL should be ABOVE entry, TP should be BELOW entry
                    if _sl < _entry and _tp > _entry:
                        log.warning(
                            f"AIAnalyzer: BUG-05 SL/TP direction mismatch for SELL {event.symbol}. "
                            f"Swapping SL={sl_val}↔TP={tp_val}"
                        )
                        sl_val, tp_val = tp_val, sl_val
                elif event.action.lower() == "buy":
                    # BUY: SL should be BELOW entry, TP should be ABOVE entry
                    if _sl > _entry and _tp < _entry:
                        log.warning(
                            f"AIAnalyzer: BUG-05 SL/TP direction mismatch for BUY {event.symbol}. "
                            f"Swapping SL={sl_val}↔TP={tp_val}"
                        )
                        sl_val, tp_val = tp_val, sl_val
        except (ValueError, TypeError):
            pass  # Non-numeric SL/TP values — leave as-is

    # ── Step 6: Emit AnalysisComplete → NotificationHub ──────
    log.info(
        f"AIAnalyzer: Analysis complete for #{event.signal_id} {symbol} — "
        f"confidence={confidence}/10, should_trade={should_trade}, interactive={interactive_required}"
    )
    await _bus.emit(AnalysisComplete(
        signal_id=event.signal_id,
        symbol=event.symbol,
        action=event.action,
        price=event.price,
        quote_qty=event.quote_qty,
        sl=sl_val,
        tp=tp_val,
        confidence=confidence,
        analysis_text=analysis_text,
        screenshot_path=str(screenshot_path) if screenshot_path else "",
        should_trade=should_trade,
        interactive_required=interactive_required,
        vision_result=vision_result,
        combined_score=combined_score_str,
        exchange=getattr(event, 'exchange', 'binance'),
        is_recovered=event.is_recovered,
        age_minutes=event.age_minutes,
    ))
