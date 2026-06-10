"""
Extended unit tests for AIAnalyzer component (v6.0).

Tests verify gaps from original test_ai_analyzer.py:
- AlertTriggered re-emits as SignalValidated (alert routing).
- MCP not connected → skips vision, emits AnalysisComplete with default confidence 5.
- Vision error (error key in result) → confidence drops to 3.
- RAG penalty: warning keywords in rag_advice reduce confidence by 2.
- SL/TP regex extraction from analysis text when event.sl/tp are empty.
- No SL/TP in text → passes through as empty strings.
- Confidence thresholds: should_trade=True only when >= 8.
- interactive_required=True only when 5 <= confidence <= 7.
- reset_capture_state clears LAST_CAPTURE_TIME.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.event_bus import EventBus
from core.events import AlertTriggered, AnalysisComplete, SignalValidated

# ═══════════════════════════════════════════════════════════════
# ALERT → SIGNAL VALIDATED ROUTING
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_alert_triggered_re_emits_as_signal_validated():
    """process_alert should re-emit AlertTriggered as SignalValidated(action='alert')."""
    from analyzer.ai_analyzer import process_alert, reset_capture_state, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    reset_capture_state()
    re_emitted = []

    @test_bus.on(SignalValidated)
    async def on_validated(event):
        re_emitted.append(event)

    try:
        event = AlertTriggered(
            signal_id=10,
            symbol="BTCUSDT",
            price="68000.0",
            quote_qty=50.0,
            exchange="bybit",
        )
        await process_alert(event)

        assert len(re_emitted) == 1
        assert re_emitted[0].action == "alert"
        assert re_emitted[0].symbol == "BTCUSDT"
        assert re_emitted[0].signal_id == 10
        assert re_emitted[0].exchange == "bybit"
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_capture_state()


@pytest.mark.asyncio
async def test_alert_triggered_with_numeric_price():
    """process_alert should convert non-empty price string to float in SignalValidated."""
    from analyzer.ai_analyzer import process_alert, reset_capture_state, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    reset_capture_state()
    re_emitted = []

    @test_bus.on(SignalValidated)
    async def on_validated(event):
        re_emitted.append(event)

    try:
        event = AlertTriggered(
            signal_id=11, symbol="ETHUSDT", price="3500.5", quote_qty=20.0
        )
        await process_alert(event)

        assert re_emitted[0].price == pytest.approx(3500.5)
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_capture_state()


# ═══════════════════════════════════════════════════════════════
# MCP NOT CONNECTED PATH
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_mcp_not_connected_emits_analysis_complete_with_default_confidence():
    """When MCP is not connected, AIAnalyzer emits AnalysisComplete with default confidence 5."""
    from analyzer.ai_analyzer import (
        process_validated_signal,
        reset_capture_state,
        set_bus,
    )

    test_bus = EventBus()
    set_bus(test_bus)
    reset_capture_state()
    analysis_events = []

    @test_bus.on(AnalysisComplete)
    async def on_analysis(event):
        analysis_events.append(event)

    try:
        with (
            patch("analyzer.ai_analyzer.config") as mock_config,
            patch("analyzer.ai_analyzer.database") as mock_db,
            patch("analyzer.ai_analyzer.get_mcp_client") as mock_mcp_factory,
        ):
            mock_config.MCP_ENABLED = True
            mock_config.RAG_ENABLED = False
            mock_config.SENTIMENT_ENABLED = False

            mock_mcp = AsyncMock()
            mock_mcp.health_check = AsyncMock(return_value={"connected": False})
            mock_mcp_factory.return_value = mock_mcp

            mock_db.insert_brief = AsyncMock(return_value=1)
            mock_db.update_signal_state = AsyncMock()

            event = SignalValidated(
                signal_id=20, symbol="BTCUSDT", action="buy", price=68000.0
            )
            await process_validated_signal(event)

            assert len(analysis_events) == 1
            # Default confidence when no vision = 5
            assert analysis_events[0].confidence == 5
            assert analysis_events[0].should_trade is False
            assert analysis_events[0].interactive_required is True
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_capture_state()


# ═══════════════════════════════════════════════════════════════
# VISION ERROR PATH
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_vision_error_reduces_confidence_to_3():
    """When vision returns an error result, confidence should drop to 3."""
    from analyzer.ai_analyzer import (
        process_validated_signal,
        reset_capture_state,
        set_bus,
    )

    test_bus = EventBus()
    set_bus(test_bus)
    reset_capture_state()
    analysis_events = []

    @test_bus.on(AnalysisComplete)
    async def on_analysis(event):
        analysis_events.append(event)

    try:
        with (
            patch("analyzer.ai_analyzer.config") as mock_config,
            patch("analyzer.ai_analyzer.database") as mock_db,
            patch("analyzer.ai_analyzer.get_mcp_client") as mock_mcp_factory,
            patch("analyzer.ai_analyzer.vision_module") as mock_vision,
        ):
            mock_config.MCP_ENABLED = True
            mock_config.RAG_ENABLED = False
            mock_config.SENTIMENT_ENABLED = False

            mock_mcp = AsyncMock()
            mock_mcp.health_check = AsyncMock(return_value={"connected": True})

            mock_screenshot_path = Path(__file__).parent / "error_screenshot.png"
            mock_screenshot_path.touch()
            mock_mcp.capture_screenshot = AsyncMock(
                return_value=str(mock_screenshot_path)
            )
            mock_mcp_factory.return_value = mock_mcp

            # Vision returns an error
            mock_vision.analyze_chart_vision = AsyncMock(
                return_value={"error": "Image processing failed", "confidence": 0}
            )

            mock_db.insert_brief = AsyncMock(return_value=1)
            mock_db.update_signal_state = AsyncMock()

            event = SignalValidated(signal_id=21, symbol="ETHUSDT", action="buy")
            await process_validated_signal(event)

            assert len(analysis_events) == 1
            assert analysis_events[0].confidence == 3
            assert analysis_events[0].should_trade is False

            mock_screenshot_path.unlink(missing_ok=True)
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_capture_state()


# ═══════════════════════════════════════════════════════════════
# RAG PENALTY
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rag_warning_keyword_reduces_confidence():
    """RAG advice containing WARNING keyword should reduce confidence by 2 (floor 1)."""
    import sys
    from unittest.mock import AsyncMock

    from analyzer.ai_analyzer import (
        process_validated_signal,
        reset_capture_state,
        set_bus,
    )

    test_bus = EventBus()
    set_bus(test_bus)
    reset_capture_state()
    analysis_events = []

    @test_bus.on(AnalysisComplete)
    async def on_analysis(event):
        analysis_events.append(event)

    try:
        # Build a fake rag module that returns a WARNING-containing advice
        mock_rag_mod = MagicMock()
        mock_rag_mod._collection = MagicMock()  # truthy → RAG runs
        mock_rag_mod.build_rag_query = MagicMock(return_value="query")
        mock_rag_mod.query_knowledge = MagicMock(return_value=["chunk1"])
        mock_rag_mod.generate_trading_advice = AsyncMock(
            return_value="WARNING: Trend is weakening. CHỜ THÊM XÁC NHẬN before entry."
        )

        with (
            patch("analyzer.ai_analyzer.config") as mock_config,
            patch("analyzer.ai_analyzer.database") as mock_db,
            patch("analyzer.ai_analyzer.get_mcp_client") as mock_mcp_factory,
            patch("analyzer.ai_analyzer.vision_module") as mock_vision,
            patch.dict(sys.modules, {"rag": mock_rag_mod}),
        ):
            mock_config.MCP_ENABLED = True
            mock_config.RAG_ENABLED = True
            mock_config.RAG_TOP_K = 3
            mock_config.SENTIMENT_ENABLED = False

            mock_mcp = AsyncMock()
            mock_mcp.health_check = AsyncMock(return_value={"connected": True})

            mock_screenshot_path = Path(__file__).parent / "rag_test_screenshot.png"
            mock_screenshot_path.touch()
            mock_mcp.capture_screenshot = AsyncMock(
                return_value=str(mock_screenshot_path)
            )
            mock_mcp_factory.return_value = mock_mcp

            # Vision returns confidence=7
            mock_vision.analyze_chart_vision = AsyncMock(
                return_value={
                    "analysis": "Decent setup",
                    "confidence": 7,
                    "error": None,
                }
            )

            mock_db.insert_brief = AsyncMock(return_value=1)
            mock_db.update_signal_state = AsyncMock()

            event = SignalValidated(signal_id=22, symbol="BTCUSDT", action="buy")
            await process_validated_signal(event)

            assert len(analysis_events) == 1
            # 7 - 2 = 5
            assert analysis_events[0].confidence == 5

            mock_screenshot_path.unlink(missing_ok=True)
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_capture_state()


# ═══════════════════════════════════════════════════════════════
# SL/TP REGEX EXTRACTION
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sl_tp_extracted_from_analysis_text():
    """When event.sl/tp are empty, SL/TP should be regex-extracted from analysis text."""
    from analyzer.ai_analyzer import (
        process_validated_signal,
        reset_capture_state,
        set_bus,
    )

    test_bus = EventBus()
    set_bus(test_bus)
    reset_capture_state()
    analysis_events = []

    @test_bus.on(AnalysisComplete)
    async def on_analysis(event):
        analysis_events.append(event)

    try:
        with (
            patch("analyzer.ai_analyzer.config") as mock_config,
            patch("analyzer.ai_analyzer.database") as mock_db,
            patch("analyzer.ai_analyzer.get_mcp_client") as mock_mcp_factory,
            patch("analyzer.ai_analyzer.vision_module") as mock_vision,
        ):
            mock_config.MCP_ENABLED = True
            mock_config.RAG_ENABLED = False
            mock_config.SENTIMENT_ENABLED = False

            mock_mcp = AsyncMock()
            mock_mcp.health_check = AsyncMock(return_value={"connected": True})

            mock_screenshot_path = Path(__file__).parent / "sltp_test.png"
            mock_screenshot_path.touch()
            mock_mcp.capture_screenshot = AsyncMock(
                return_value=str(mock_screenshot_path)
            )
            mock_mcp_factory.return_value = mock_mcp

            mock_vision.analyze_chart_vision = AsyncMock(
                return_value={
                    "analysis": "Entry confirmed. Stop Loss: 65,000. Take Profit: 74,000. Score 8/10.",
                    "confidence": 8,
                    "error": None,
                }
            )

            mock_db.insert_brief = AsyncMock(return_value=1)
            mock_db.update_signal_state = AsyncMock()

            # sl and tp are empty in the event
            event = SignalValidated(
                signal_id=23, symbol="BTCUSDT", action="buy", sl="", tp=""
            )
            await process_validated_signal(event)

            assert len(analysis_events) == 1
            # SL and TP should be parsed from analysis text
            assert analysis_events[0].sl == "65000"
            assert analysis_events[0].tp == "74000"

            mock_screenshot_path.unlink(missing_ok=True)
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_capture_state()


@pytest.mark.asyncio
async def test_sl_tp_from_event_take_priority():
    """When event.sl/tp are set, they should NOT be overridden by regex."""
    from analyzer.ai_analyzer import (
        process_validated_signal,
        reset_capture_state,
        set_bus,
    )

    test_bus = EventBus()
    set_bus(test_bus)
    reset_capture_state()
    analysis_events = []

    @test_bus.on(AnalysisComplete)
    async def on_analysis(event):
        analysis_events.append(event)

    try:
        with (
            patch("analyzer.ai_analyzer.config") as mock_config,
            patch("analyzer.ai_analyzer.database") as mock_db,
            patch("analyzer.ai_analyzer.get_mcp_client") as mock_mcp_factory,
            patch("analyzer.ai_analyzer.vision_module") as mock_vision,
        ):
            mock_config.MCP_ENABLED = True
            mock_config.RAG_ENABLED = False
            mock_config.SENTIMENT_ENABLED = False

            mock_mcp = AsyncMock()
            mock_mcp.health_check = AsyncMock(return_value={"connected": True})

            mock_screenshot_path = Path(__file__).parent / "sltp_priority_test.png"
            mock_screenshot_path.touch()
            mock_mcp.capture_screenshot = AsyncMock(
                return_value=str(mock_screenshot_path)
            )
            mock_mcp_factory.return_value = mock_mcp

            mock_vision.analyze_chart_vision = AsyncMock(
                return_value={
                    "analysis": "Stop Loss: 60,000. Take Profit: 80,000.",
                    "confidence": 8,
                    "error": None,
                }
            )

            mock_db.insert_brief = AsyncMock(return_value=1)
            mock_db.update_signal_state = AsyncMock()

            # sl and tp already provided in event
            event = SignalValidated(
                signal_id=24, symbol="BTCUSDT", action="buy", sl="66000", tp="73000"
            )
            await process_validated_signal(event)

            # Should use event values, not regex-extracted ones
            assert analysis_events[0].sl == "66000"
            assert analysis_events[0].tp == "73000"

            mock_screenshot_path.unlink(missing_ok=True)
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_capture_state()


# ═══════════════════════════════════════════════════════════════
# CONFIDENCE THRESHOLD LOGIC
# ═══════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "confidence,should_trade,interactive",
    [
        (10, True, False),
        (8, True, False),
        (7, False, True),
        (5, False, True),
        (4, False, False),
        (1, False, False),
        (0, False, False),
    ],
)
@pytest.mark.asyncio
async def test_confidence_threshold_flags(confidence, should_trade, interactive):
    """Verify should_trade and interactive_required based on confidence thresholds."""
    from analyzer.ai_analyzer import (
        process_validated_signal,
        reset_capture_state,
        set_bus,
    )

    test_bus = EventBus()
    set_bus(test_bus)
    reset_capture_state()
    analysis_events = []

    @test_bus.on(AnalysisComplete)
    async def on_analysis(event):
        analysis_events.append(event)

    try:
        with (
            patch("analyzer.ai_analyzer.config") as mock_config,
            patch("analyzer.ai_analyzer.database") as mock_db,
            patch("analyzer.ai_analyzer.get_mcp_client") as mock_mcp_factory,
            patch("analyzer.ai_analyzer.vision_module") as mock_vision,
        ):
            mock_config.MCP_ENABLED = True
            mock_config.RAG_ENABLED = False
            mock_config.SENTIMENT_ENABLED = False

            mock_mcp = AsyncMock()
            mock_mcp.health_check = AsyncMock(return_value={"connected": True})

            mock_screenshot_path = (
                Path(__file__).parent / f"thresh_test_{confidence}.png"
            )
            mock_screenshot_path.touch()
            mock_mcp.capture_screenshot = AsyncMock(
                return_value=str(mock_screenshot_path)
            )
            mock_mcp_factory.return_value = mock_mcp

            mock_vision.analyze_chart_vision = AsyncMock(
                return_value={
                    "analysis": "Test.",
                    "confidence": confidence,
                    "error": None,
                }
            )

            mock_db.insert_brief = AsyncMock(return_value=1)
            mock_db.update_signal_state = AsyncMock()

            event = SignalValidated(
                signal_id=50 + confidence, symbol="BTCUSDT", action="buy"
            )
            await process_validated_signal(event)

            assert analysis_events[0].should_trade is should_trade
            assert analysis_events[0].interactive_required is interactive

            mock_screenshot_path.unlink(missing_ok=True)
    finally:
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_capture_state()


# ═══════════════════════════════════════════════════════════════
# RESET CAPTURE STATE
# ═══════════════════════════════════════════════════════════════


def test_reset_capture_state_clears_last_capture_time():
    """reset_capture_state() should clear LAST_CAPTURE_TIME completely."""
    import time

    from analyzer.ai_analyzer import LAST_CAPTURE_TIME, reset_capture_state

    LAST_CAPTURE_TIME["BTCUSDT"] = time.time()
    LAST_CAPTURE_TIME["ETHUSDT"] = time.time()

    assert len(LAST_CAPTURE_TIME) == 2
    reset_capture_state()
    assert len(LAST_CAPTURE_TIME) == 0
