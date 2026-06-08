"""
Integration test: Full event-driven pipeline (v6.0).

This test exercises the complete 5-hop signal lifecycle:
  WebhookGateway → SignalProcessor → AIAnalyzer → NotificationHub → TradeEngine

Scenario A (Happy path — high confidence):
  1. Webhook receives a valid buy signal and emits SignalReceived.
  2. SignalProcessor validates it and emits SignalValidated.
  3. AIAnalyzer emits AnalysisComplete(confidence=9, should_trade=True).
  4. NotificationHub auto-approves and emits TradeApproved.
  5. TradeEngine executes and emits TradeExecuted.

Scenario B (Human gate — medium confidence):
  1-2. Same as above.
  3. AIAnalyzer emits AnalysisComplete(confidence=6, interactive_required=True).
  4. NotificationHub holds trade for human approval (not auto-approved).

Scenario C (Auto-reject — low confidence):
  1-2. Same as above.
  3. AIAnalyzer emits AnalysisComplete(confidence=3, should_trade=False).
  4. NotificationHub emits notification but NO TradeApproved.

Scenario D (Rejection — invalid timeframe):
  Webhook emits SignalReceived with interval=4h.
  SignalProcessor emits SignalRejected immediately.
  No further events.

Scenario E (Dedup — duplicate signal):
  Two identical signals arrive within 60s.
  Only the first passes; second is rejected with reason=duplicate_signal.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event_bus import EventBus
from core.events import (
    AnalysisComplete,
    SignalReceived,
    SignalRejected,
    SignalValidated,
    TradeApproved,
    TradeExecuted,
)

# ═══════════════════════════════════════════════════════════════
# SHARED FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def pipeline_bus():
    """Create an isolated EventBus and wire up all 5 pipeline components."""
    bus = EventBus()

    # --- SignalProcessor ---
    from processor.signal_processor import (
        process_signal,
        reset_dedup_cache,
    )
    from processor.signal_processor import (
        set_bus as sp_set_bus,
    )

    sp_set_bus(bus)
    reset_dedup_cache()
    bus.on(SignalReceived)(process_signal)

    yield bus

    # Teardown
    from core.event_bus import bus as default_bus

    sp_set_bus(default_bus)
    reset_dedup_cache()


# ═══════════════════════════════════════════════════════════════
# SCENARIO A: HAPPY PATH (HIGH CONFIDENCE)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario_a_full_pipeline_high_confidence(pipeline_bus):
    """Full pipeline: buy signal → AI confidence 9 → auto-approve → TradeExecuted."""
    from analyzer.ai_analyzer import (
        process_validated_signal,
        reset_capture_state,
    )
    from analyzer.ai_analyzer import (
        set_bus as ai_set_bus,
    )
    from engine.trade_engine import execute_trade
    from engine.trade_engine import set_bus as te_set_bus
    from hub.notification_hub import (
        PENDING_TRADES,
        process_analysis_complete,
    )
    from hub.notification_hub import (
        set_bus as hub_set_bus,
    )

    PENDING_TRADES.clear()
    ai_set_bus(pipeline_bus)
    hub_set_bus(pipeline_bus)
    te_set_bus(pipeline_bus)
    reset_capture_state()

    pipeline_bus.on(SignalValidated)(process_validated_signal)
    pipeline_bus.on(AnalysisComplete)(process_analysis_complete)
    pipeline_bus.on(TradeApproved)(execute_trade)

    final_events = []

    async def on_done(event):
        final_events.append(event)

    pipeline_bus.on(TradeExecuted)(on_done)

    try:
        with (
            patch("analyzer.ai_analyzer.config") as mock_ai_config,
            patch("analyzer.ai_analyzer.database") as mock_ai_db,
            patch("analyzer.ai_analyzer.get_mcp_client") as mock_mcp_factory,
            patch("analyzer.ai_analyzer.vision_module") as mock_vision,
            patch("hub.notification_hub.notifier") as mock_notifier,
            patch("exchanges.router.get_router") as mock_router_factory,
            patch("engine.trade_engine.database") as mock_te_db,
        ):
            # AI Config
            mock_ai_config.MCP_ENABLED = True
            mock_ai_config.RAG_ENABLED = False

            # MCP/Vision
            mock_mcp = AsyncMock()
            mock_mcp.health_check = AsyncMock(return_value={"connected": True})
            screenshot_path = Path(__file__).parent / "pipeline_a.png"
            screenshot_path.touch()
            mock_mcp.capture_screenshot = AsyncMock(return_value=str(screenshot_path))
            mock_mcp_factory.return_value = mock_mcp

            mock_vision.analyze_chart_vision = AsyncMock(
                return_value={
                    "analysis": "Strong bullish momentum. Stop Loss: 66000. Take Profit: 72000.",
                    "confidence": 9,
                    "error": None,
                }
            )

            # Hub notifier
            mock_notifier.notify_all = AsyncMock()

            # Exchange adapter
            from tests.unit.test_trade_engine_extended import MockOrderResult

            mock_adapter = AsyncMock()
            mock_adapter.exchange_id = "binance"
            mock_adapter.execute_smart_order = AsyncMock(return_value=MockOrderResult())

            mock_router = MagicMock()
            mock_router.resolve_exchange.return_value = mock_adapter
            mock_router_factory.return_value = mock_router

            # DB
            mock_ai_db.insert_brief = AsyncMock(return_value=1)
            mock_te_db.insert_trade = AsyncMock(return_value=1)
            mock_te_db.update_trade_oco = AsyncMock()
            mock_te_db.update_signal_status = AsyncMock()

            # FIRE the pipeline
            await pipeline_bus.emit(
                SignalReceived(
                    signal_id=1000,
                    symbol="BTCUSDT",
                    action="buy",
                    price=68000.0,
                    quote_qty=50.0,
                    interval="60",
                    sl="",
                    tp="",
                    exchange="binance",
                )
            )

            assert len(final_events) == 1, "TradeExecuted should be emitted once"
            assert final_events[0].symbol == "BTCUSDT"
            assert final_events[0].exchange == "binance"

            screenshot_path.unlink(missing_ok=True)
    finally:
        from analyzer.ai_analyzer import set_bus as ai_reset
        from core.event_bus import bus as default_bus
        from engine.trade_engine import set_bus as te_reset
        from hub.notification_hub import set_bus as hub_reset

        ai_reset(default_bus)
        hub_reset(default_bus)
        te_reset(default_bus)
        PENDING_TRADES.clear()
        reset_capture_state()


# ═══════════════════════════════════════════════════════════════
# SCENARIO B: HUMAN GATE (MEDIUM CONFIDENCE)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario_b_medium_confidence_held_for_approval(pipeline_bus):
    """Medium confidence (6) → trade held in PENDING_TRADES, no TradeExecuted."""
    from analyzer.ai_analyzer import (
        process_validated_signal,
        reset_capture_state,
    )
    from analyzer.ai_analyzer import (
        set_bus as ai_set_bus,
    )
    from hub.notification_hub import (
        PENDING_TRADES,
        get_pending_trade,
        process_analysis_complete,
    )
    from hub.notification_hub import (
        set_bus as hub_set_bus,
    )

    PENDING_TRADES.clear()
    ai_set_bus(pipeline_bus)
    hub_set_bus(pipeline_bus)
    reset_capture_state()

    pipeline_bus.on(SignalValidated)(process_validated_signal)
    pipeline_bus.on(AnalysisComplete)(process_analysis_complete)

    approved_events = []

    async def on_approved(event):
        approved_events.append(event)

    pipeline_bus.on(TradeApproved)(on_approved)

    try:
        with (
            patch("analyzer.ai_analyzer.config") as mock_ai_config,
            patch("analyzer.ai_analyzer.database") as mock_ai_db,
            patch("analyzer.ai_analyzer.get_mcp_client") as mock_mcp_factory,
            patch("analyzer.ai_analyzer.vision_module") as mock_vision,
            patch("hub.notification_hub.notifier") as mock_notifier,
            patch("hub.notification_hub.telegram_bot", create=True) as mock_bot,
        ):
            mock_ai_config.MCP_ENABLED = True
            mock_ai_config.RAG_ENABLED = False

            mock_mcp = AsyncMock()
            mock_mcp.health_check = AsyncMock(return_value={"connected": True})
            screenshot_path = Path(__file__).parent / "pipeline_b.png"
            screenshot_path.touch()
            mock_mcp.capture_screenshot = AsyncMock(return_value=str(screenshot_path))
            mock_mcp_factory.return_value = mock_mcp

            mock_vision.analyze_chart_vision = AsyncMock(
                return_value={
                    "analysis": "Moderate setup. Stop Loss: 66000. Take Profit: 71000.",
                    "confidence": 6,
                    "error": None,
                }
            )

            mock_notifier.notify_all = AsyncMock()
            mock_bot.send_interactive_trade_approval = AsyncMock(
                return_value=[(12345, 67890)]
            )
            mock_bot.get_approval_timeout_mgr = MagicMock(return_value=None)

            import sys

            sys.modules.setdefault("telegram_bot", mock_bot)

            mock_ai_db.insert_brief = AsyncMock(return_value=1)

            await pipeline_bus.emit(
                SignalReceived(
                    signal_id=2000,
                    symbol="BTCUSDT",
                    action="buy",
                    price=68000.0,
                    quote_qty=50.0,
                    interval="1h",
                    sl="",
                    tp="",
                    exchange="binance",
                )
            )

            assert len(approved_events) == 0, (
                "Should NOT auto-approve medium confidence"
            )
            pending = get_pending_trade(2000)
            assert pending is not None, "Trade should be stored in PENDING_TRADES"

            screenshot_path.unlink(missing_ok=True)
    finally:
        from analyzer.ai_analyzer import set_bus as ai_reset
        from core.event_bus import bus as default_bus
        from hub.notification_hub import set_bus as hub_reset

        ai_reset(default_bus)
        hub_reset(default_bus)
        PENDING_TRADES.clear()
        reset_capture_state()


# ═══════════════════════════════════════════════════════════════
# SCENARIO C: AUTO-REJECT (LOW CONFIDENCE)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario_c_low_confidence_no_trade(pipeline_bus):
    """Low confidence (3) → auto-reject, no TradeApproved or TradeExecuted."""
    from analyzer.ai_analyzer import (
        process_validated_signal,
        reset_capture_state,
    )
    from analyzer.ai_analyzer import (
        set_bus as ai_set_bus,
    )
    from hub.notification_hub import (
        PENDING_TRADES,
        notify_signal_rejected,
        process_analysis_complete,
    )
    from hub.notification_hub import (
        set_bus as hub_set_bus,
    )

    PENDING_TRADES.clear()
    ai_set_bus(pipeline_bus)
    hub_set_bus(pipeline_bus)
    reset_capture_state()

    pipeline_bus.on(SignalValidated)(process_validated_signal)
    pipeline_bus.on(AnalysisComplete)(process_analysis_complete)
    pipeline_bus.on(SignalRejected)(notify_signal_rejected)

    trade_events = []

    async def on_approved(event):
        trade_events.append(("approved", event))

    pipeline_bus.on(TradeApproved)(on_approved)

    async def on_executed(event):
        trade_events.append(("executed", event))

    pipeline_bus.on(TradeExecuted)(on_executed)

    try:
        with (
            patch("analyzer.ai_analyzer.config") as mock_ai_config,
            patch("analyzer.ai_analyzer.database") as mock_ai_db,
            patch("analyzer.ai_analyzer.get_mcp_client") as mock_mcp_factory,
            patch("analyzer.ai_analyzer.vision_module") as mock_vision,
            patch("hub.notification_hub.notifier") as mock_notifier,
        ):
            mock_ai_config.MCP_ENABLED = True
            mock_ai_config.RAG_ENABLED = False

            mock_mcp = AsyncMock()
            mock_mcp.health_check = AsyncMock(return_value={"connected": True})
            screenshot_path = Path(__file__).parent / "pipeline_c.png"
            screenshot_path.touch()
            mock_mcp.capture_screenshot = AsyncMock(return_value=str(screenshot_path))
            mock_mcp_factory.return_value = mock_mcp

            mock_vision.analyze_chart_vision = AsyncMock(
                return_value={
                    "analysis": "Weak setup, avoid.",
                    "confidence": 3,
                    "error": None,
                }
            )

            mock_notifier.notify_all = AsyncMock()
            mock_ai_db.insert_brief = AsyncMock(return_value=1)

            await pipeline_bus.emit(
                SignalReceived(
                    signal_id=3000,
                    symbol="BTCUSDT",
                    action="buy",
                    price=68000.0,
                    quote_qty=50.0,
                    interval="60",
                    sl="",
                    tp="",
                    exchange="binance",
                )
            )

            assert len(trade_events) == 0, (
                "No TradeApproved or TradeExecuted should fire"
            )
            # But notification should be sent
            mock_notifier.notify_all.assert_awaited()

            screenshot_path.unlink(missing_ok=True)
    finally:
        from analyzer.ai_analyzer import set_bus as ai_reset
        from core.event_bus import bus as default_bus
        from hub.notification_hub import set_bus as hub_reset

        ai_reset(default_bus)
        hub_reset(default_bus)
        PENDING_TRADES.clear()
        reset_capture_state()


# ═══════════════════════════════════════════════════════════════
# SCENARIO D: INVALID TIMEFRAME REJECTION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario_d_invalid_timeframe_stops_at_processor(pipeline_bus):
    """4h interval → SignalProcessor emits SignalRejected, no further events."""
    rejected_events = []
    analysis_events = []

    async def on_rejected(event):
        rejected_events.append(event)

    pipeline_bus.on(SignalRejected)(on_rejected)

    async def on_analysis(event):
        analysis_events.append(event)

    pipeline_bus.on(AnalysisComplete)(on_analysis)

    await pipeline_bus.emit(
        SignalReceived(
            signal_id=4000,
            symbol="BTCUSDT",
            action="buy",
            price=68000.0,
            quote_qty=50.0,
            interval="4h",
            sl="",
            tp="",
            exchange="binance",
        )
    )

    assert len(rejected_events) == 1
    assert rejected_events[0].reason == "invalid_timeframe"
    assert rejected_events[0].signal_id == 4000
    assert len(analysis_events) == 0


# ═══════════════════════════════════════════════════════════════
# SCENARIO E: DEDUP — DUPLICATE SIGNAL
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scenario_e_duplicate_signal_blocked_by_dedup(pipeline_bus):
    """Two identical signals within 60s → only first validated, second rejected with dedup."""
    validated = []
    rejected = []

    async def on_validated(event):
        validated.append(event)

    pipeline_bus.on(SignalValidated)(on_validated)

    async def on_rejected(event):
        rejected.append(event)

    pipeline_bus.on(SignalRejected)(on_rejected)

    await pipeline_bus.emit(
        SignalReceived(
            signal_id=5000,
            symbol="SOLUSDT",
            action="buy",
            price=150.0,
            quote_qty=30.0,
            interval="60",
            sl="",
            tp="",
            exchange="bybit",
        )
    )
    await pipeline_bus.emit(
        SignalReceived(
            signal_id=5001,
            symbol="SOLUSDT",
            action="buy",
            price=150.5,
            quote_qty=30.0,
            interval="60",
            sl="",
            tp="",
            exchange="bybit",
        )
    )

    assert len(validated) == 1
    assert validated[0].signal_id == 5000

    assert len(rejected) == 1
    assert rejected[0].reason == "duplicate_signal"
    assert rejected[0].signal_id == 5001
