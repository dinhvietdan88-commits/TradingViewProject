"""
NotificationHub — Centralized notification and approval gate (v6.0).

Listens to:
  - SignalRejected      → Notify trader of rejection reason.
  - AnalysisComplete    → Confidence gate: auto-approve, human gate, or auto-reject.
  - TradeExecuted       → Notify trader of successful execution + P&L data.
  - TradeFailed         → Notify trader of execution failure.
  - PositionClosed      → Notify trader of SL/TP hit with P&L.
  - TradeApprovalTimeout → Cleanup stale interactive requests.

Emits:
  - TradeApproved       → When confidence >= 8 (auto) or human clicks Approve.
  - SignalRejected      → When confidence < 5 (auto-reject).

Design Invariants (v6.0 INV-5/6):
  - Confidence >= 8: Auto-approve → emit TradeApproved immediately.
  - Confidence 5-7: Human gate → send interactive Telegram keyboard.
  - Confidence < 5: Auto-reject → send rejection notification.
  - R:R enforcement is the USER's decision (not auto-rejected by AIAnalyzer).
  - Uses set_bus() pattern for test isolation.
"""

import json
import logging
from typing import Optional

import aiosqlite

import config
import notifier
from datetime import UTC

try:
    from database import format_vn_time
except ImportError:
    # Fallback for Server B which uses nerves layout
    def format_vn_time(s: str) -> str:  # type: ignore[misc]
        from datetime import datetime, timedelta, timezone

        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            vn = dt.astimezone(timezone(timedelta(hours=7)))
            return vn.strftime("%Y-%m-%d %H:%M:%S") + " (ICT)"
        except Exception:
            return s


from core.event_bus import bus as _default_bus
from core.events import (
    AnalysisComplete,
    CircuitBreakerTripped,
    IndicatorSignalReceived,
    IndicatorSignalRejected,
    PositionClosed,
    SignalRejected,
    TradeApprovalTimeout,
    TradeApproved,
    TradeExecuted,
    TradeFailed,
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
# PENDING TRADES STATE (in-memory for interactive approvals)
# ═══════════════════════════════════════════════════════════════

PENDING_TRADES = {}


def get_pending_trade(signal_id: int):
    """Retrieve a pending trade event by signal_id."""
    return PENDING_TRADES.get(signal_id)


def remove_pending_trade(signal_id: int):
    """Remove a pending trade from the store."""
    return PENDING_TRADES.pop(signal_id, None)


async def _get_vbs_metadata(signal_id: int) -> dict:
    """Helper to query VBS message metadata from local database payload."""
    try:
        async with aiosqlite.connect(config.DB_PATH) as db:
            async with db.execute(
                "SELECT payload FROM signals WHERE id = ?", (signal_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    payload = json.loads(row[0])
                    return {
                        "tg_messages": payload.get("tg_messages", []),
                        "vbs_received_at": payload.get("vbs_received_at", ""),
                        "vbs_expires_at": payload.get("vbs_expires_at", ""),
                        "vbs_queue_id": payload.get("vbs_queue_id"),
                        "payload": payload,
                    }
    except Exception as e:
        log.warning(
            f"NotificationHub: Failed to fetch VBS metadata for signal #{signal_id}: {e}"
        )
    return {}


async def _render_chart_for_event(event: AnalysisComplete) -> str | None:
    """Render a Matplotlib chart with Entry/SL/TP overlay for an AnalysisComplete event.

    Returns the file path to the generated PNG, or None on failure.
    Non-blocking: chart failure does NOT block trade flow.
    """
    try:
        from capture_client import get_capture_client

        # Build drawings from event price levels
        drawings = []
        if event.price:
            drawings.append(
                {"price": float(event.price), "label": "Entry", "color": "#26a69a"}
            )
        if event.sl:
            try:
                sl_val = float(str(event.sl).replace(",", ""))
                if sl_val > 0:
                    drawings.append(
                        {"price": sl_val, "label": "SL", "color": "#ef5350"}
                    )
            except (ValueError, TypeError):
                pass
        if event.tp:
            try:
                tp_val = float(str(event.tp).replace(",", ""))
                if tp_val > 0:
                    drawings.append(
                        {"price": tp_val, "label": "TP", "color": "#2962ff"}
                    )
            except (ValueError, TypeError):
                pass

        # Build strategy table from vision_result
        strategy_table = None
        if event.vision_result:
            vr = event.vision_result.get("vision_data") or event.vision_result
            if isinstance(vr, dict):
                rows = []
                if vr.get("trend_template_score") is not None:
                    rows.append(("TT Score", f"{vr['trend_template_score']}/8"))
                if vr.get("trend_template_stage"):
                    rows.append(("Stage", vr["trend_template_stage"]))
                if vr.get("vcp_detected") is not None:
                    rows.append(
                        ("VCP", "Detected ✅" if vr["vcp_detected"] else "Not found")
                    )
                if vr.get("volume_ratio") is not None:
                    rows.append(("Vol Ratio", f"{vr['volume_ratio']:.1f}x"))
                if rows:
                    strategy_table = {"title": "SEPA Analysis", "rows": rows}

        # Resolve timeframe from vision_result or default
        timeframe = "D"
        if event.vision_result:
            vr = event.vision_result.get("vision_data") or event.vision_result
            if isinstance(vr, dict):
                timeframe = vr.get("timeframe") or vr.get("interval") or "D"

        client = get_capture_client()
        result = await client.capture_screenshot(
            symbol=event.symbol,
            timeframe=timeframe,
            drawings=drawings or None,
            strategy_table=strategy_table,
            method="mplfinance",
        )

        if result.success and result.file_path:
            log.info(
                f"NotificationHub: 📊 Chart rendered for {event.symbol} → {result.file_path}"
            )
            return result.file_path
        else:
            log.warning(
                f"NotificationHub: Chart render failed for {event.symbol}: {result.error}"
            )
    except Exception as exc:
        log.warning(
            f"NotificationHub: Chart rendering skipped for {event.symbol}: {exc}"
        )

    return None


async def _render_chart_for_indicator(event: IndicatorSignalReceived) -> str | None:
    """Render a Matplotlib chart for an IndicatorSignalReceived event.

    Uses the indicator's symbol and interval to fetch OHLCV and render a
    clean dark-theme candlestick chart. The indicator_name is shown in the
    strategy table overlay.

    Returns the file path to the generated PNG, or None on failure.
    Non-blocking: chart failure does NOT block notification flow.
    """
    try:
        from capture_client import get_capture_client

        # Build entry price drawing if present
        drawings = []
        if event.price:
            try:
                price_val = float(str(event.price).replace(",", ""))
                if price_val > 0:
                    drawings.append(
                        {"price": price_val, "label": "Price", "color": "#2962ff"}
                    )
            except (ValueError, TypeError):
                pass

        # Strategy table: indicator name + confidence
        rows = [("Indicator", event.indicator_name or "N/A")]
        if event.confidence_score:
            rows.append(("Confidence", f"{event.confidence_score}%"))
        if event.conditions_met:
            rows.append(("Conditions", ", ".join(event.conditions_met[:2])))
        strategy_table = {"title": "Indicator Alert", "rows": rows}

        # Resolve timeframe
        timeframe = event.interval or "1h"

        client = get_capture_client()
        result = await client.capture_screenshot(
            symbol=event.symbol,
            timeframe=timeframe,
            drawings=drawings or None,
            strategy_table=strategy_table,
            method="mplfinance",
        )

        if result.success and result.file_path:
            log.info(
                f"NotificationHub: 📊 Indicator chart rendered for {event.symbol} → {result.file_path}"
            )
            return result.file_path
        else:
            log.warning(
                f"NotificationHub: Indicator chart render failed for {event.symbol}: {result.error}"
            )
    except Exception as exc:
        log.warning(
            f"NotificationHub: Indicator chart rendering skipped for {event.symbol}: {exc}"
        )

    return None


def _format_indicator_details_for_rejection(payload: dict) -> str:
    """Format indicator name, timeframe, price, confidence, and metadata for rejection message."""
    details = []

    # 1. Chỉ báo
    ind_name = payload.get("indicator_name") or payload.get("indicator")
    if ind_name:
        details.append(f"• Chỉ báo: {ind_name}")

    # 2. Chi tiết: Khung TG, Giá, Độ tin cậy
    specs = []
    interval = payload.get("interval")
    if interval:
        specs.append(f"Khung TG: {interval}")

    price = payload.get("price")
    if price is not None:
        try:
            price_val = f"{float(str(price).replace(',', '')):,.2f}"
            specs.append(f"Giá: {price_val}")
        except (ValueError, TypeError):
            specs.append(f"Giá: {price}")

    conf = payload.get("confidence_score") or payload.get("confidence")
    if conf is not None:
        specs.append(f"Độ tin cậy: {conf}%")

    if specs:
        details.append(f"• Chi tiết: {', '.join(specs)}")

    # 3. Metadata
    meta = payload.get("metadata")
    if meta:
        if isinstance(meta, dict):
            # Strip secret and format nicely
            meta_clean = {k: v for k, v in meta.items() if k not in {"secret"}}
            meta_str = json.dumps(meta_clean)
        else:
            meta_str = str(meta)
        details.append(f"• Metadata: <code>{meta_str}</code>")

    return "\n".join(details)


# ═══════════════════════════════════════════════════════════════
# HANDLER: SignalRejected → Rejection Notification
# ═══════════════════════════════════════════════════════════════


@_default_bus.on(SignalRejected)
async def notify_signal_rejected(event: SignalRejected) -> None:
    """
    Send Telegram/Discord notification when a signal is rejected.

    Rejection reasons:
    - duplicate_signal: Same (symbol, action) within 60s dedup window.
    - invalid_timeframe: Interval not in {60, 1h, 60m}.
    - low_confidence: AI confidence < 5 (auto-reject by gate).
    """
    reason_map = {
        "duplicate_signal": "Tín hiệu trùng lặp (dedup 60s)",
        "invalid_timeframe": f"Khung thời gian không hợp lệ: `{event.interval}`",
        "unknown_action": f"Hành động không xác định: `{event.action}`",
        "low_confidence": "Điểm AI quá thấp (< 5/10) — tự động từ chối",
    }

    reason_text = reason_map.get(event.reason, event.reason)

    if event.reason == "low_confidence" and getattr(event, "analysis_text", ""):
        from utils.html_chunker import truncate_caption_html_safe

        msg = (
            f"🔴 **TỰ ĐỘNG TỪ CHỐI** — `{event.symbol}` trên `{getattr(event, 'exchange', 'binance').upper()}`\n"
            f"- Hành động: `{event.action.upper()}`\n"
            f"- Lý do: {reason_text}\n\n"
            f"🧠 **Phân tích AI:**\n{truncate_caption_html_safe(event.analysis_text, 500)}"
        )
    else:
        msg = (
            f"⛔ **Tín Hiệu Bị Từ Chối**\n"
            f"- Sàn: `{getattr(event, 'exchange', 'binance').upper()}`\n"
            f"- Mã: `{event.symbol}`\n"
            f"- Hành động: `{event.action.upper()}`\n"
            f"- Lý do: {reason_text}\n"
            f"- Signal ID: `#{event.signal_id}`"
        )
        if event.reason == "invalid_timeframe":
            msg += (
                "\n\n💡 Chiến lược MIS v1 chỉ cho phép khung 1H (60). "
                "Vui lòng kiểm tra cài đặt TradingView Alert."
            )

    log.info(
        f"NotificationHub: Rejected signal #{event.signal_id} on {getattr(event, 'exchange', 'binance')} — {event.reason}"
    )

    # Try editing original VBS Queue message to avoid spam
    vbs_meta = await _get_vbs_metadata(event.signal_id)
    tg_msgs = vbs_meta.get("tg_messages")
    payload = vbs_meta.get("payload") or {}
    if tg_msgs:
        vbs_time = vbs_meta.get("vbs_received_at") or "N/A"
        vbs_qid = vbs_meta.get("vbs_queue_id") or "N/A"

        ind_details = _format_indicator_details_for_rejection(payload)
        strategy_text = ""
        if not payload.get("indicator_name") and not payload.get("indicator"):
            strategy_text = f" - Chiến lược: {event.action.upper()}"

        edit_msg = (
            f"📥 VBS Signal Queued - Time: <code>{format_vn_time(vbs_time)}</code>\n"
            f"⛔️ <b>Tín Hiệu Chỉ Báo Bị Từ Chối</b> ( ID: #{vbs_qid} Queue - #{event.signal_id}: Signal )\n"
            f"Symbol: {event.symbol} - Action: ~~{event.action.upper()}~~ (cancel)\n\n"
            f"• Sàn: {getattr(event, 'exchange', 'binance').upper()}{strategy_text}\n"
        )
        if ind_details:
            edit_msg += f"{ind_details}\n"

        edit_msg += f"• Lý do: {reason_text}"

        if event.reason == "low_confidence" and getattr(event, "analysis_text", ""):
            from utils.html_chunker import truncate_caption_html_safe

            edit_msg += f"\n• 🧠 Phân tích AI: {truncate_caption_html_safe(event.analysis_text, 300)}"
        elif event.reason == "invalid_timeframe":
            edit_msg += " (Khung 1H/Daily mới hợp lệ)"

        edited = False
        for m in tg_msgs:
            if await notifier.edit_telegram_message(
                m["chat_id"], m["message_id"], edit_msg
            ):
                edited = True

        if edited:
            log.info(
                f"NotificationHub: Edited original VBS Telegram message for signal #{event.signal_id}"
            )
            await notifier.send_discord_alert(msg)
            return

    # Fallback to normal broadcast if not edited
    await notifier.notify_all(msg)


@_default_bus.on(IndicatorSignalRejected)
async def notify_indicator_signal_rejected(event: IndicatorSignalRejected) -> None:
    """Send Notification when an indicator signal is rejected (e.g. invalid type, duplicate)."""
    reason_map = {
        "duplicate_signal": "Tín hiệu trùng lặp (dedup 60s)",
        "invalid_timeframe": "Khung thời gian không hợp lệ cho lệnh entry",
        "invalid_signal_type": f"Loại tín hiệu không hợp lệ: `{event.signal_type}`",
    }
    reason_text = reason_map.get(event.reason, event.reason)

    if event.is_recovered:
        msg = (
            f"🕒 **[PHỤC HỒI] Tín Hiệu Bị Từ Chối (cách đây {event.age_minutes}p)**\n"
            f"- Mã: `{event.symbol}` | Lý do: {reason_text}"
        )
    else:
        msg = (
            f"⛔ **Tín Hiệu Chỉ Báo Bị Từ Chối**\n"
            f"- Sàn: `{getattr(event, 'exchange', 'binance').upper()}`\n"
            f"- Mã: `{event.symbol}`\n"
            f"- Chỉ báo: `{event.indicator_name}`\n"
            f"- Lý do: {reason_text}\n"
            f"- Signal ID: `#{event.signal_id}`"
        )
    log.info(
        f"NotificationHub: Rejected indicator signal #{event.signal_id} on {event.exchange} — {event.reason}"
    )

    # Try editing original VBS Queue message to avoid spam
    if not event.is_recovered:
        vbs_meta = await _get_vbs_metadata(event.signal_id)
        tg_msgs = vbs_meta.get("tg_messages")
        payload = vbs_meta.get("payload") or {}
        if tg_msgs:
            vbs_time = vbs_meta.get("vbs_received_at") or "N/A"
            vbs_qid = vbs_meta.get("vbs_queue_id") or "N/A"
            action_val = event.signal_type.upper() if event.signal_type else "INDICATOR"

            ind_details = _format_indicator_details_for_rejection(payload)

            edit_msg = (
                f"📥 VBS Signal Queued - Time: <code>{format_vn_time(vbs_time)}</code>\n"
                f"⛔️ <b>Tín Hiệu Chỉ Báo Bị Từ Chối</b> ( ID: #{vbs_qid} Queue - #{event.signal_id}: Signal )\n"
                f"Symbol: {event.symbol} - Action: ~~{action_val}~~ (cancel)\n\n"
                f"• Sàn: {getattr(event, 'exchange', 'binance').upper()}\n"
            )
            if ind_details:
                edit_msg += f"{ind_details}\n"

            edit_msg += f"• Lý do: {reason_text}"

            edited = False
            for m in tg_msgs:
                if await notifier.edit_telegram_message(
                    m["chat_id"], m["message_id"], edit_msg
                ):
                    edited = True

            if edited:
                log.info(
                    f"NotificationHub: Edited original VBS Telegram message for indicator signal #{event.signal_id}"
                )
                await notifier.send_discord_alert(msg)
                return

    # Fallback to normal broadcast if not edited
    await notifier.notify_all(msg)


# ═══════════════════════════════════════════════════════════════
# HANDLER: IndicatorSignalReceived → Rich Telegram Notification
# ═══════════════════════════════════════════════════════════════


@_default_bus.on(IndicatorSignalReceived)
async def notify_indicator_signal(event: IndicatorSignalReceived) -> None:
    """
    Format and send a rich Telegram notification for indicator alerts.
    High-priority prefix added when confidence_score > 80 (REQ 6.4, Prop 17).
    """
    if event.signal_type in {"entry", "exit"}:
        log.info(
            f"NotificationHub: Suppressing rich alert for trade signal {event.symbol} "
            f"({event.signal_type}) to avoid duplication."
        )
        return

    exchange = getattr(event, "exchange", "binance")

    # REQ 6.4 / Prop 17: High-priority gate
    priority_prefix = "🔴 **KHẨN CẤP** — " if event.confidence_score > 80 else ""

    if event.is_recovered:
        msg = (
            f"🕒 **[PHỤC HỒI] Chỉ Báo Kỹ Thuật (cách đây {event.age_minutes}p)**\n"
            f"- Mã: `{event.symbol}` | Chỉ báo: `{event.indicator_name}`\n"
            f"- Khung TG: `{event.interval or 'N/A'}` | Giá: `{event.price or 'N/A'}`\n"
            f"- Độ tin cậy: `{event.confidence_score}%`"
        )
        if event.conditions_met:
            msg += f"\n- Điều kiện: `{', '.join(event.conditions_met)}`"
    else:
        msg = (
            f"{priority_prefix}📊 **Chỉ Báo Kỹ Thuật (Indicator Alert)**\n"
            f"- Sàn: `{exchange.upper()}`\n"
            f"- Mã: `{event.symbol}`\n"
            f"- Loại tín hiệu: `{event.signal_type.upper()}`\n"
            f"- Chỉ báo: `{event.indicator_name}`\n"
            f"- Khung TG: `{event.interval or 'N/A'}`\n"
            f"- Giá: `{event.price or 'N/A'}`\n"
            f"- Độ tin cậy: `{event.confidence_score}%`\n"
        )

        if event.conditions_met:
            cond_str = ", ".join(event.conditions_met)
            msg += f"- Điều kiện: `{cond_str}`\n"

        if event.metadata:
            msg += f"\n📝 **Metadata:**\n```json\n{event.metadata}\n```"

    log.info(
        f"NotificationHub: Indicator Alert for {event.symbol} "
        f"({event.indicator_name}, confidence={event.confidence_score}%)"
    )

    if event.is_recovered:
        await notifier.notify_all(msg)
    else:
        # Render chart for indicator signal (non-blocking)
        chart_path = await _render_chart_for_indicator(event)

        try:
            import telegram_bot

            await telegram_bot.send_interactive_indicator_alert(
                signal_id=event.signal_id,
                symbol=event.symbol,
                message=msg,
                photo_path=chart_path,
            )
        except Exception as e:
            log.error(
                f"NotificationHub: Failed to trigger interactive indicator alert: {e}"
            )
            await notifier.notify_all(msg + f"\n\n*(Lỗi tương tác: {e})*")
            if chart_path:
                import asyncio

                await asyncio.to_thread(
                    notifier.send_telegram_photo,
                    chart_path,
                    f"📊 {event.symbol} — Indicator",
                )


# ═══════════════════════════════════════════════════════════════
# HANDLER: AnalysisComplete → Confidence Gate (INV-5/6)
# ═══════════════════════════════════════════════════════════════


@_default_bus.on(AnalysisComplete)
async def process_analysis_complete(event: AnalysisComplete) -> None:
    """
    v6.0 Confidence Gate (INV-5/6):

    - Confidence >= 8: Auto-approve → emit TradeApproved immediately.
    - Confidence 5-7: Human gate → send interactive Telegram message.
    - Confidence < 5: Auto-reject → send rejection notification.

    R:R and risk data are passed through for the user to evaluate.
    The AIAnalyzer does NOT reject based on R:R — user decides (per user directive).
    """
    confidence = event.confidence
    exchange = getattr(event, "exchange", "binance")

    # ── Tier 1: Auto-Approve (confidence >= 8) ───────────────
    if confidence >= 8:
        prefix = (
            f"🕒 **[PHỤC HỒI - {event.age_minutes}p]** "
            if getattr(event, "is_recovered", False)
            else ""
        )
        log.info(
            f"NotificationHub: ✅ Auto-approving trade for #{event.signal_id} {event.symbol} "
            f"(confidence={confidence}/10, recovered={getattr(event, 'is_recovered', False)})"
        )

        # Render chart with Entry/SL/TP (non-blocking)
        chart_path = await _render_chart_for_event(event)

        await notifier.notify_all(
            f"{prefix}🟢 **AUTO-APPROVE** — `{event.symbol}` trên `{exchange.upper()}`\n"
            f"- Điểm AI: `{confidence}/10`\n"
            f"- Hành động: `{event.action.upper()}`\n"
            f"- Giá: `{event.price or 'Market'}`\n"
            f"- SL: `{event.sl or 'N/A'}` | TP: `{event.tp or 'N/A'}`\n\n"
            f"🤖 Tự động gửi lệnh..."
        )

        # Send chart photo if available
        if chart_path:
            caption = f"📊 {event.symbol} — Auto-Approve (AI {confidence}/10)"
            import asyncio

            await asyncio.to_thread(notifier.send_telegram_photo, chart_path, caption)

        await _bus.emit(
            TradeApproved(
                signal_id=event.signal_id,
                symbol=event.symbol,
                action=event.action,
                price=event.price,
                quote_qty=event.quote_qty,
                sl=event.sl,
                tp=event.tp,
                exchange=exchange,
                approved_by="AI (Auto-Green)",
                analysis_text=event.analysis_text,
            )
        )
        return

    # ── Tier 2: Human Gate (confidence 5-7) ──────────────────
    if 5 <= confidence <= 7:
        log.info(
            f"NotificationHub: ⚠️ Interactive approval required for #{event.signal_id} {event.symbol} "
            f"(confidence={confidence}/10)"
        )
        PENDING_TRADES[event.signal_id] = event

        # Render chart with Entry/SL/TP (non-blocking)
        chart_path = await _render_chart_for_event(event)

        from utils.telegram_templates import render_template

        symbol_val = event.symbol
        action_val = event.action.upper()
        price_val = (
            f"{event.price:,.2f}"
            if event.price and isinstance(event.price, (int, float))
            else (event.price or "Market")
        )

        # Get VCP & Trend Template details from vision_result if available
        vcp_status = "N/A"
        tt_score = "N/A"
        stage_val = "N/A"
        volume_ratio = "N/A"
        timeframe = "1D"

        if event.vision_result:
            vr = event.vision_result.get("vision_data") or event.vision_result
            if isinstance(vr, str):
                try:
                    import json

                    vr = json.loads(vr)
                except Exception:
                    vr = {}
            if isinstance(vr, dict):
                vcp_status = (
                    "Đã xác nhận" if vr.get("vcp_detected") else "Không xác định"
                )
                tt_score = str(vr.get("trend_template_score", "N/A"))
                stage_val = vr.get("trend_template_stage") or (
                    "Stage 2" if tt_score == "8" else "Stage 1"
                )
                volume_ratio = f"{vr.get('volume_ratio', 'N/A')}"
                timeframe = vr.get("timeframe") or vr.get("interval") or "1D"

        # Default/Fallback parsing from combined_score if N/A
        if tt_score == "N/A" and event.combined_score:
            if "/" in event.combined_score:
                parts = event.combined_score.split("/")
                tt_score = parts[0].strip().split()[-1]
                stage_val = "Stage 2" if tt_score == "8" else "Stage 1"

        # Risk Management (SL/TP)
        sl_val = event.sl or "N/A"
        tp_val = event.tp or "N/A"
        sl_pct = "N/A"
        tp_pct = "N/A"
        try:
            if event.price and isinstance(event.price, (int, float)):
                if event.sl and float(event.sl) > 0:
                    sl_pct = (
                        f"{((float(event.sl) - event.price) / event.price) * 100:+.1f}"
                    )
                if event.tp and float(event.tp) > 0:
                    tp_pct = (
                        f"{((float(event.tp) - event.price) / event.price) * 100:+.1f}"
                    )
        except (ValueError, TypeError):
            pass

        from utils.html_chunker import truncate_caption_html_safe

        ai_advice = truncate_caption_html_safe(event.analysis_text, 800)

        msg = render_template(
            "A",
            symbol=symbol_val,
            action=action_val,
            price=price_val,
            timeframe=timeframe,
            tt_score=tt_score,
            stage=stage_val,
            vcp_status=vcp_status,
            volume_ratio=volume_ratio,
            ai_provider="Claude RAG",
            ai_advice=ai_advice,
            stop_loss=sl_val,
            sl_pct=sl_pct,
            take_profit=tp_val,
            tp_pct=tp_pct,
        )

        is_recovered = getattr(event, "is_recovered", False)
        if is_recovered:
            msg = (
                f"🕒 **[PHỤC HỒI VBS Queue - cách đây {event.age_minutes}p] Lệnh Cần Duyệt**\n\n"
                + msg
            )
            # Disable interactive buttons for recovered signals (User Request)
            await notifier.notify_all(
                msg + "\n\n*(Tín hiệu phục hồi không có nút tương tác)*"
            )
            # Send chart for recovered signals too
            if chart_path:
                caption = f"📊 {event.symbol} — Recovered (AI {confidence}/10)"
                import asyncio

                await asyncio.to_thread(
                    notifier.send_telegram_photo, chart_path, caption
                )
        else:
            try:
                import telegram_bot

                sent_pairs = await telegram_bot.send_interactive_trade_approval(
                    signal_id=event.signal_id,
                    message=msg,
                    photo_path=chart_path,
                )
                if not sent_pairs:
                    # Fallback to normal notify if bot not running
                    await notifier.notify_all(
                        msg + "\n\n*(Bot chưa bật, không thể dùng nút bấm duyệt lệnh)*"
                    )
                    if chart_path:
                        import asyncio

                        await asyncio.to_thread(
                            notifier.send_telegram_photo,
                            chart_path,
                            f"📊 {event.symbol}",
                        )
                else:
                    # REQ7: Register sent messages with ApprovalTimeoutManager for auto-timeout
                    timeout_mgr = telegram_bot.get_approval_timeout_mgr()
                    if timeout_mgr and isinstance(sent_pairs, list):
                        for chat_id, message_id in sent_pairs:
                            timeout_mgr.track_message(
                                event.signal_id, chat_id, message_id
                            )
            except Exception as e:
                log.error(
                    f"NotificationHub: Failed to trigger interactive message: {e}"
                )
                await notifier.notify_all(msg + f"\n\n*(Lỗi tương tác: {e})*")
                if chart_path:
                    import asyncio

                    await asyncio.to_thread(
                        notifier.send_telegram_photo, chart_path, f"📊 {event.symbol}"
                    )
        return

    # ── Tier 3: Auto-Reject (confidence < 5) ─────────────────
    log.info(
        f"NotificationHub: 🔴 Auto-rejecting trade for #{event.signal_id} {event.symbol} "
        f"(confidence={confidence}/10)"
    )
    # BUG-01 fix: Emit SignalRejected to honour the event contract.
    # Passes analysis_text so the subscriber notify_signal_rejected can edit VBS message or fallback.
    await _bus.emit(
        SignalRejected(
            signal_id=event.signal_id,
            symbol=event.symbol,
            action=event.action,
            reason="low_confidence",
            exchange=exchange,
            analysis_text=event.analysis_text,
        )
    )
    return


# ═══════════════════════════════════════════════════════════════
# HANDLER: TradeExecuted → Execution Confirmation
# ═══════════════════════════════════════════════════════════════


@_default_bus.on(TradeExecuted)
async def notify_trade_executed(event: TradeExecuted) -> None:
    """
    v6.0: Centralized execution notification.
    TradeEngine emits TradeExecuted → NotificationHub formats and sends.
    """
    exchange = getattr(event, "exchange", "binance")
    order_type = event.order_type or "MARKET"

    price_str = (
        f"{event.executed_price:.4f}" if event.executed_price is not None else "N/A"
    )
    msg = (
        f"✅ **Đã Đặt Lệnh {exchange.title()}**\n"
        f"- Mã: `{event.symbol}`\n"
        f"- Lệnh: `{event.side} {order_type}`\n"
        f"- Số lượng: `{event.executed_qty}` (Value: `~{event.quote_qty}$`)\n"
        f"- Giá khớp: `{price_str}`\n"
    )
    if event.stop_loss_price:
        msg += f"- Cắt lỗ (SL): `{event.stop_loss_price}`\n"
    if event.take_profit_price:
        msg += f"- Chốt lời (TP): `{event.take_profit_price}`\n"
    if order_type == "DRY_RUN":
        msg += "\n⚠️ `CHẾ ĐỘ DRY_RUN — KHÔNG KHỚP LỆNH THỰC TẾ`"

    if event.rag_advice:
        from utils.html_chunker import truncate_caption_html_safe

        msg += f"\n\n🧠 **Phân tích AI:**\n{truncate_caption_html_safe(event.rag_advice, 500)}"

    log.info(f"NotificationHub: Trade executed #{event.trade_id} on {exchange}")
    await notifier.notify_all(msg)

    # Send screenshot if available
    if event.telegram_message:
        log.debug(
            f"NotificationHub: Trade #{event.trade_id} inline message already sent by engine."
        )


# ═══════════════════════════════════════════════════════════════
# HANDLER: TradeFailed → Failure Alert
# ═══════════════════════════════════════════════════════════════


@_default_bus.on(TradeFailed)
async def notify_trade_failed(event: TradeFailed) -> None:
    """
    v6.0: Centralized failure notification.
    TradeEngine emits TradeFailed → NotificationHub formats and sends.
    """
    exchange = getattr(event, "exchange", "binance")

    msg = (
        f"❌ **Lỗi Đặt Lệnh {exchange.title()}**\n"
        f"- Mã: `{event.symbol}`\n"
        f"- Lệnh: `{event.side}`\n"
        f"- Chi tiết lỗi: `{event.error}`\n"
        f"- Signal ID: `#{event.signal_id}`"
    )

    log.info(f"NotificationHub: Trade failed for #{event.signal_id} on {exchange}")
    await notifier.notify_all(msg)


# ═══════════════════════════════════════════════════════════════
# HANDLER: PositionClosed → P&L Notification
# ═══════════════════════════════════════════════════════════════


@_default_bus.on(PositionClosed)
async def notify_position_closed(event: PositionClosed) -> None:
    """
    REQ2: P&L Notification on SL/TP Hit.
    PositionMonitor emits PositionClosed → NotificationHub sends P&L.
    """
    exchange = getattr(event, "exchange", "binance")
    pnl_emoji = "🟢" if event.pnl >= 0 else "🔴"
    exit_reason_map = {
        "STOP_LOSS": "🛑 Cắt lỗ (Stop Loss)",
        "TAKE_PROFIT": "🎯 Chốt lời (Take Profit)",
        "MANUAL": "✋ Đóng thủ công",
    }
    exit_text = exit_reason_map.get(event.exit_reason, event.exit_reason)

    msg = (
        f"{pnl_emoji} **Đóng Vị Thế — {exit_text}**\n"
        f"- Sàn: `{exchange.upper()}`\n"
        f"- Mã: `{event.symbol}`\n"
        f"- Vào lệnh: `{event.entry_price}`\n"
        f"- Thoát lệnh: `{event.exit_price}`\n"
        f"- Số lượng: `{event.quantity}`\n"
        f"- P&L: `{event.pnl:+.4f}` ({event.pnl_pct:+.2f}%)\n"
    )

    log.info(
        f"NotificationHub: Position closed {event.symbol} on {exchange} — "
        f"P&L: {event.pnl:+.4f} ({event.exit_reason})"
    )
    await notifier.notify_all(msg)


# ═══════════════════════════════════════════════════════════════
# HANDLER: TradeApprovalTimeout → Cleanup Stale Requests
# ═══════════════════════════════════════════════════════════════


@_default_bus.on(TradeApprovalTimeout)
async def handle_approval_timeout(event: TradeApprovalTimeout) -> None:
    """
    v6.0: Garbage collection for stale interactive approval requests.
    Removes from PENDING_TRADES and notifies the user.
    """
    pending = remove_pending_trade(event.signal_id)
    if pending:
        log.info(
            f"NotificationHub: Approval timeout for #{event.signal_id} {event.symbol}"
        )
        await notifier.notify_all(
            f"⏰ **Hết thời gian duyệt lệnh**\n"
            f"- Mã: `{event.symbol}`\n"
            f"- Signal ID: `#{event.signal_id}`\n"
            f"- Lý do: {event.reason}\n\n"
            f"Lệnh đã bị hủy tự động."
        )
    else:
        log.debug(
            f"NotificationHub: Timeout for #{event.signal_id} but no pending trade found (already processed)."
        )


# ═══════════════════════════════════════════════════════════════
# HANDLER: CircuitBreakerTripped → Emergency Telegram Notification
# ═══════════════════════════════════════════════════════════════


@_default_bus.on(CircuitBreakerTripped)
async def notify_circuit_breaker_tripped(event: CircuitBreakerTripped) -> None:
    """
    Format and send an emergency Telegram alert when a circuit breaker trips to OPEN.
    Includes the inline buttons [Reset Closed] and [Bypass 1h] to let the admin
    approve/reset directly from Telegram.
    """
    exchange = event.exchange.upper()
    reason = event.reason
    prev_state = event.prev_state

    msg = (
        f"🚨 **CẢNH BÁO KHẨN CẤP: BỘ NGẮT MẠCH BỊ KÍCH HOẠT (OPEN)**\n\n"
        f"🏦 Sàn giao dịch: <code>{exchange}</code>\n"
        f"📌 Mã giao dịch: <code>{event.symbol or 'N/A'}</code>\n"
        f"📉 Trạng thái trước: <code>{prev_state}</code>\n"
        f"⚠️ Lý do: <b>{reason}</b>\n\n"
        f"<i>Hệ thống đã chặn toàn bộ lệnh giao dịch trên sàn này và chuyển sang các sàn Fallback dự phòng.</i>"
    )

    log.info(
        f"NotificationHub: Circuit Breaker Tripped for {exchange} to OPEN. Reason: {reason}"
    )

    # Render chart if possible
    chart_path = None
    if event.symbol:
        try:
            dummy_analysis = AnalysisComplete(symbol=event.symbol)
            chart_path = await _render_chart_for_event(dummy_analysis)
        except Exception as chart_err:
            log.warning(
                f"NotificationHub: Failed to render chart for circuit breaker trip: {chart_err}"
            )

    try:
        import importlib

        _tg_bot = importlib.import_module("telegram_bot")
        sent_pairs = await _tg_bot.send_circuit_breaker_alert(
            exchange=event.exchange,
            symbol=event.symbol,
            message=msg,
            photo_path=chart_path,
        )
        if not sent_pairs:
            # Fallback to normal notify if bot not running
            await notifier.notify_all(
                msg + "\n\n*(Bot chưa bật, không thể dùng nút bấm tương tác)*"
            )
            if chart_path:
                import asyncio

                await asyncio.to_thread(
                    notifier.send_telegram_photo,
                    chart_path,
                    f"🚨 {exchange} Circuit Breaker Tripped",
                )
    except Exception as e:
        log.error(
            f"NotificationHub: Failed to trigger interactive circuit breaker message: {e}"
        )
        await notifier.notify_all(msg + f"\n\n*(Lỗi tương tác: {e})*")
        if chart_path:
            import asyncio

            await asyncio.to_thread(
                notifier.send_telegram_photo,
                chart_path,
                f"🚨 {exchange} Circuit Breaker Tripped",
            )
