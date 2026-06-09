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

import json
import logging
import re
from datetime import datetime, UTC
from pathlib import Path

import config
import database
import vision as vision_module
from core.event_bus import bus as _default_bus
from core.events import AlertTriggered, AnalysisComplete, SignalValidated
from mcp_client import get_mcp_client

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

LAST_CAPTURE_TIME: dict[str, float] = {}
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
    log.info(
        f"AIAnalyzer: Stealth capture alert for {event.symbol} — routing to unified pipeline"
    )
    await _bus.emit(
        SignalValidated(
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
        )
    )


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
    log.info(
        f"AIAnalyzer: Processing validated signal #{event.signal_id} for {event.symbol} (Action: {event.action})"
    )

    import inspect

    res = database.update_signal_state(event.signal_id, "ANALYZING")
    if inspect.isawaitable(res):
        await res

    symbol = event.symbol
    now = datetime.now(UTC).timestamp()

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
    combined_score_str: str | None = None

    # ── Step 1: Screenshot + Vision AI ───────────────────────
    try:
        mcp = get_mcp_client()

        # Build drawings and strategy table parameters for fast rendering
        drawings = []
        if event.price is not None:
            drawings.append(
                {
                    "price": event.price,
                    "label": f"Entry ({event.price:.2f})",
                    "color": "#26a69a",
                }
            )
        try:
            if event.sl:
                drawings.append(
                    {
                        "price": float(event.sl),
                        "label": f"SL ({float(event.sl):.2f})",
                        "color": "#ef5350",
                    }
                )
        except (ValueError, TypeError):
            pass
        try:
            if event.tp:
                drawings.append(
                    {
                        "price": float(event.tp),
                        "label": f"TP ({float(event.tp):.2f})",
                        "color": "#2962ff",
                    }
                )
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
            strategy_table = {"title": f"{symbol} Setup", "rows": rows}

        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_symbol = re.sub(r"[^A-Za-z0-9_\-]", "", symbol)
        save_path = (
            Path(__file__).parent.parent
            / "screenshots"
            / f"stealth_{safe_symbol}_{ts_str}.png"
        )

        screenshot_path = await mcp.capture_screenshot(
            symbol=symbol,
            timeframe="1h",
            region="chart",
            save_path=save_path,
            active_only=False,  # Specific symbol rendering is preferred
            crop=True,
            drawings=drawings,
            strategy_table=strategy_table,
        )

        if screenshot_path and Path(screenshot_path).exists():
            vision_result = await vision_module.analyze_chart_vision(
                image_path=Path(screenshot_path),
                symbol=symbol,
            )

            if not vision_result.get("error"):
                analysis_text += (
                    "👁️ **VISION AI:**\n" + vision_result.get("analysis", "") + "\n\n"
                )
                # v6.0: Use vision confidence directly (1-10 scale)
                confidence = vision_result.get("confidence", 5)
            else:
                analysis_text += f"❌ Vision Error: {vision_result['error']}\n\n"
                confidence = 3  # Error → low confidence
        else:
            log.warning(
                "AIAnalyzer: Screenshot capture failed or not found, skipping Vision AI."
            )
            analysis_text += (
                "⚠️ Không thể chụp ảnh biểu đồ. Bỏ qua phân tích hình ảnh.\n\n"
            )
            confidence = 5

    except Exception as e:
        log.error(f"AIAnalyzer: Vision capture failed: {e}")
        analysis_text += f"❌ Lỗi chụp ảnh: {e}\n\n"
        confidence = 3  # Error → low confidence
        # BUG-02 fix: enforce cooldown even on error to prevent retry storms
        if event.action == "alert":
            LAST_CAPTURE_TIME[symbol] = now

    # ── Step 1.5: Pattern Detection (VCP/Cup/DoubleBottom) ─────
    pattern_summary = ""
    if not getattr(event, "mta_calculated", False):
        try:
            from capture_client import get_capture_client
            from utils.pattern_overlay import detect_all_patterns

            capture = get_capture_client()

            # Fetch OHLCV for pattern detection (reuse existing client)
            ohlcv_data = await capture.fetch_ohlcv(symbol, timeframe="1d", limit=150)
            if ohlcv_data and len(ohlcv_data) >= 30:
                patterns = detect_all_patterns(ohlcv_data, pivot_window=5)

                if patterns.any_detected:
                    pattern_summary = f"📐 **PATTERN DETECTION:** {patterns.summary}\n"
                    analysis_text += pattern_summary

                    # Boost confidence if VCP with high quality detected
                    if patterns.vcp.detected and patterns.vcp.quality_score >= 70:
                        confidence = min(10, confidence + 1)
                        analysis_text += f"   ↳ VCP Quality={patterns.vcp.quality_score:.0f} → confidence +1\n"

                    # Store pattern info in vision_result for chart rendering
                    vision_result["pattern_overlay"] = {
                        "vcp_detected": patterns.vcp.detected,
                        "cup_handle_detected": patterns.cup_handle.detected,
                        "double_bottom_detected": patterns.double_bottom.detected,
                        "summary": patterns.summary,
                        "vcp_quality": patterns.vcp.quality_score
                        if patterns.vcp.detected
                        else 0,
                    }
                else:
                    analysis_text += (
                        "📐 **PATTERN:** Không phát hiện VCP/Cup/DoubleBottom\n"
                    )
                    # Penalize if NO pattern and confidence is borderline
                    if confidence == 8:
                        confidence = 7
                        analysis_text += (
                            "   ↳ Không có pattern → confidence 8→7 (cần human gate)\n"
                        )
        except Exception as pat_err:
            log.warning(f"AIAnalyzer: Pattern detection failed (non-fatal): {pat_err}")

    # ── Step 2: RAG Analysis ─────────────────────────────────
    rag_advice = ""
    if config.RAG_ENABLED:
        try:
            import rag

            payload = {
                "action": event.action,
                "symbol": event.symbol,
                "alert_type": "webhook",
                "pattern_detection": pattern_summary
                if pattern_summary
                else "Không phát hiện VCP/Cup/DoubleBottom",
            }
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
                    if any(
                        kw in advice_upper
                        for kw in ("CẢNH BÁO", "WARNING", "YẾU", "CHỜ THÊM XÁC NHẬN")
                    ):
                        confidence = max(1, confidence - 2)
        except Exception as e:
            log.error(f"AIAnalyzer: RAG analysis error: {e}")
            analysis_text += f"Lỗi RAG: {e}\n\n"

    # ── Step 2.5: Sentiment Analysis ─────────────────────────
    if getattr(config, "SENTIMENT_ENABLED", True):
        try:
            from analyzer.sentiment_analyzer import SentimentAnalyzer

            sent_analyzer = SentimentAnalyzer()
            sentiment_res = await sent_analyzer.analyze_symbol(symbol)
            if sentiment_res.get("enabled"):
                t_score = sentiment_res["breakdown"]["twitter"]
                r_score = sentiment_res["breakdown"]["rss"]
                g_score = sentiment_res["breakdown"]["glassnode"]
                combined = sentiment_res["combined_score"]

                analysis_text += (
                    f"📰 **SENTIMENT ANALYSIS:** Combined={combined:.2f} "
                    f"(Twitter={t_score:.2f}, RSS={r_score:.2f}, Glassnode={g_score:.2f})\n"
                )

                is_buy = event.action.lower() == "buy"
                is_sell = event.action.lower() == "sell"

                # Apply sentiment modifier directionally
                if combined > 0.5:
                    if is_buy:
                        confidence = min(10, confidence + 1)
                        analysis_text += (
                            "   ↳ Bullish sentiment boost (BUY) → confidence +1\n\n"
                        )
                    elif is_sell:
                        confidence = max(1, confidence - 2)
                        analysis_text += (
                            "   ↳ Bullish sentiment penalty (SELL) → confidence -2\n\n"
                        )
                elif combined < -0.5:
                    if is_buy:
                        confidence = max(1, confidence - 3)
                        analysis_text += (
                            "   ↳ Bearish sentiment penalty (BUY) → confidence -3\n\n"
                        )
                    elif is_sell:
                        confidence = min(10, confidence + 1)
                        analysis_text += (
                            "   ↳ Bearish sentiment boost (SELL) → confidence +1\n\n"
                        )
                else:
                    analysis_text += (
                        "   ↳ Neutral sentiment → no confidence modifier\n\n"
                    )
        except Exception as sent_err:
            log.warning(
                f"AIAnalyzer: Sentiment analysis failed (non-fatal): {sent_err}"
            )

    # ── Step 2.7: Multi-Timeframe Alignment (MTA) & Matching Model ──
    tas = 0.0
    sts = 0.0
    mlts = 0.0
    if getattr(config, "MTA_ENABLED", True):
        try:
            if getattr(event, "mta_calculated", False):
                tas = getattr(event, "tas", 0.0)
                sts = getattr(event, "sts", 0.0)
                mlts = getattr(event, "mlts", 0.0)
                log.info(
                    f"AIAnalyzer: MTA Trend loaded from validated signal for {symbol} - "
                    f"TAS={tas:.2f} (STS={sts:.2f}, MLTS={mlts:.2f})"
                )
            else:
                from capture_client import get_capture_client

                client = get_capture_client()
                import asyncio

                tf_tasks = [
                    client.fetch_ohlcv(symbol, "1m", limit=30),
                    client.fetch_ohlcv(symbol, "5m", limit=30),
                    client.fetch_ohlcv(symbol, "15m", limit=30),
                    client.fetch_ohlcv(symbol, "30m", limit=30),
                    client.fetch_ohlcv(symbol, "1h", limit=30),
                    client.fetch_ohlcv(symbol, "4h", limit=30),
                    client.fetch_ohlcv(symbol, "D", limit=30),
                ]
                tf_results = await asyncio.gather(*tf_tasks, return_exceptions=True)

                def get_trend(res) -> int:
                    if isinstance(res, Exception) or not res or len(res) < 10:
                        return 0
                    closes = [c[4] for c in res]
                    sma = sum(closes[-20:]) / len(closes[-20:])
                    latest = closes[-1]
                    return 1 if latest > sma else (-1 if latest < sma else 0)

                t_1m = get_trend(tf_results[0])
                t_5m = get_trend(tf_results[1])
                t_15m = get_trend(tf_results[2])
                t_30m = get_trend(tf_results[3])
                t_1h = get_trend(tf_results[4])
                t_4h = get_trend(tf_results[5])
                t_1d = get_trend(tf_results[6])

                sts = (
                    config.MTA_STF_WEIGHT_1M * t_1m
                    + config.MTA_STF_WEIGHT_5M * t_5m
                    + config.MTA_STF_WEIGHT_15M * t_15m
                    + config.MTA_STF_WEIGHT_30M * t_30m
                )
                mlts = (
                    config.MTA_MLTF_WEIGHT_1H * t_1h
                    + config.MTA_MLTF_WEIGHT_4H * t_4h
                    + config.MTA_MLTF_WEIGHT_1D * t_1d
                )
                tas = sts + mlts

                log.info(
                    f"AIAnalyzer: MTA Trend calculated for {symbol} - TAS={tas:.2f} "
                    f"(STS={sts:.2f} [1m:{t_1m}, 5m:{t_5m}, 15m:{t_15m}, 30m:{t_30m}], "
                    f"MLTS={mlts:.2f} [1h:{t_1h}, 4h:{t_4h}, 1d:{t_1d}])"
                )

            analysis_text += f"📐 **TIMEFRAME ALIGNMENT:** TAS={tas:.2f} (STS={sts:.2f}, MLTS={mlts:.2f})\n"

            is_buy = event.action.lower() == "buy"
            is_sell = event.action.lower() == "sell"

            if tas >= 0.5:
                if is_buy:
                    confidence = min(10, confidence + 1)
                    analysis_text += f"   ↳ Bullish trend alignment (TAS={tas:.2f}) → confidence +1\n\n"
                elif is_sell:
                    confidence = max(1, confidence - 2)
                    analysis_text += f"   ↳ Trend conflict (SELL signal during Bullish trend, TAS={tas:.2f}) → confidence -2\n\n"
            elif tas <= -0.5:
                if is_buy:
                    confidence = max(1, confidence - 3)
                    analysis_text += f"   ↳ Trend conflict (BUY signal during Bearish trend, TAS={tas:.2f}) → confidence -3\n\n"
                elif is_sell:
                    confidence = min(10, confidence + 1)
                    analysis_text += f"   ↳ Bearish trend alignment (TAS={tas:.2f}) → confidence +1\n\n"
            else:
                analysis_text += (
                    "   ↳ Neutral trend consensus → no confidence modifier\n\n"
                )

        except Exception as mta_err:
            log.warning(f"AIAnalyzer: MTA macro filter failed: {mta_err}")

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
        sl_match = re.search(
            r"Stop\s*Loss:.*?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)",
            analysis_text,
            re.IGNORECASE,
        )
        tp_match = re.search(
            r"Take\s*Profit:.*?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)",
            analysis_text,
            re.IGNORECASE,
        )
        if sl_match and not sl_val:
            sl_val = sl_match.group(1).replace(",", "")
        if tp_match and not tp_val:
            tp_val = tp_match.group(1).replace(",", "")

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
    await _bus.emit(
        AnalysisComplete(
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
            exchange=getattr(event, "exchange", "binance"),
            is_recovered=event.is_recovered,
            age_minutes=event.age_minutes,
        )
    )
