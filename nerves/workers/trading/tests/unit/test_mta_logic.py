"""
Unit tests for Multi-Timeframe Alignment (MTA) & Matching Model (v6.1).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from core.event_bus import EventBus
from core.events import (
    AnalysisComplete,
    SignalReceived,
    SignalRejected,
    SignalValidated,
)


# Helper mock candles
# A candle is [timestamp, open, high, low, close, volume]
def make_candles(trend_type, num_candles=30):
    candles = []
    val = 100
    for i in range(num_candles):
        if trend_type == "bullish":
            val += 2
        elif trend_type == "bearish":
            val -= 2
        candles.append([i * 1000, 100, 100, 100, val, 10])
    return candles


@pytest.mark.asyncio
async def test_signal_processor_mta_buy_rejected_on_bearish_macro(
    mock_global_capture_client,
):
    """SignalProcessor: Reject BUY signal if both 1D and 4H are bearish."""
    from processor.signal_processor import process_signal, reset_dedup_cache, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()

    rejected_events = []

    @test_bus.on(SignalRejected)
    async def on_rejected(event):
        rejected_events.append(event)

    # Set mock candles on the global fixture
    bearish_candles = make_candles("bearish")
    mock_global_capture_client.return_value = bearish_candles

    orig_mta = config.MTA_ENABLED

    try:
        config.MTA_ENABLED = True
        with (
            patch(
                "engine.regime_switcher.get_market_regime",
                return_value="TREND",
            ),
            patch("database.set_setting") as mock_set_setting,
        ):
            mock_set_setting.return_value = None

            event = SignalReceived(
                signal_id=101,
                symbol="BTCUSDT",
                action="buy",
                price=60000.0,
                quote_qty=10.0,
                interval="5m",
                sl="",
                tp="",
                exchange="binance",
            )
            await process_signal(event)

            assert len(rejected_events) == 1
            assert rejected_events[0].reason == "macro_trend_conflict"
            assert rejected_events[0].signal_id == 101
    finally:
        config.MTA_ENABLED = orig_mta
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


@pytest.mark.asyncio
async def test_signal_processor_mta_sell_rejected_on_bullish_macro(
    mock_global_capture_client,
):
    """SignalProcessor: Reject SELL signal if both 1D and 4H are bullish."""
    from processor.signal_processor import process_signal, reset_dedup_cache, set_bus

    test_bus = EventBus()
    set_bus(test_bus)
    reset_dedup_cache()

    rejected_events = []

    @test_bus.on(SignalRejected)
    async def on_rejected(event):
        rejected_events.append(event)

    # Set mock candles on the global fixture
    bullish_candles = make_candles("bullish")
    mock_global_capture_client.return_value = bullish_candles

    orig_mta = config.MTA_ENABLED

    try:
        config.MTA_ENABLED = True
        with (
            patch(
                "engine.regime_switcher.get_market_regime",
                return_value="TREND",
            ),
            patch("database.set_setting") as mock_set_setting,
        ):
            mock_set_setting.return_value = None

            event = SignalReceived(
                signal_id=102,
                symbol="BTCUSDT",
                action="sell",
                price=60000.0,
                quote_qty=10.0,
                interval="5m",
                sl="",
                tp="",
                exchange="binance",
            )
            await process_signal(event)

            assert len(rejected_events) == 1
            assert rejected_events[0].reason == "macro_trend_conflict"
            assert rejected_events[0].signal_id == 102
    finally:
        config.MTA_ENABLED = orig_mta
        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_dedup_cache()


@pytest.mark.asyncio
async def test_ai_analyzer_mta_boosts_and_penalizes_buy_correctly(
    mock_global_capture_client,
):
    """AIAnalyzer: TAS trend consensus boosts/penalizes BUY signals accordingly."""
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

    # Bullish candles for all timeframes -> TAS = 1.0
    bullish_candles = make_candles("bullish")
    mock_global_capture_client.return_value = bullish_candles

    # Create mock screenshot file on disk so Vision AI isn't skipped
    mock_screenshot_path = Path(__file__).parent / "mta_test_screenshot.png"
    mock_screenshot_path.touch()

    # Save original configs
    orig_mta = config.MTA_ENABLED
    orig_stf_1m = config.MTA_STF_WEIGHT_1M
    orig_stf_5m = config.MTA_STF_WEIGHT_5M
    orig_stf_15m = config.MTA_STF_WEIGHT_15M
    orig_stf_30m = config.MTA_STF_WEIGHT_30M
    orig_mltf_1h = config.MTA_MLTF_WEIGHT_1H
    orig_mltf_4h = config.MTA_MLTF_WEIGHT_4H
    orig_mltf_1d = config.MTA_MLTF_WEIGHT_1D
    orig_sent = config.SENTIMENT_ENABLED
    orig_mcp = config.MCP_ENABLED
    orig_rag = config.RAG_ENABLED

    try:
        config.MTA_ENABLED = True
        config.MTA_STF_WEIGHT_1M = 0.05
        config.MTA_STF_WEIGHT_5M = 0.10
        config.MTA_STF_WEIGHT_15M = 0.12
        config.MTA_STF_WEIGHT_30M = 0.13
        config.MTA_MLTF_WEIGHT_1H = 0.15
        config.MTA_MLTF_WEIGHT_4H = 0.20
        config.MTA_MLTF_WEIGHT_1D = 0.25
        config.SENTIMENT_ENABLED = False
        config.MCP_ENABLED = True
        config.RAG_ENABLED = False

        with (
            patch("analyzer.ai_analyzer.get_mcp_client") as mock_mcp_factory,
            patch("analyzer.ai_analyzer.vision_module") as mock_vision,
            patch("database.insert_brief") as mock_insert_brief,
        ):
            mock_insert_brief.return_value = 1
            mock_mcp = AsyncMock()
            mock_mcp.health_check = AsyncMock(return_value={"connected": True})
            mock_mcp.capture_screenshot = AsyncMock(
                return_value=str(mock_screenshot_path)
            )
            mock_mcp_factory.return_value = mock_mcp

            # Vision default confidence = 7
            mock_vision.analyze_chart_vision = AsyncMock(
                return_value={
                    "confidence": 7,
                    "analysis": "Bullish structure",
                    "error": None,
                }
            )

            # Test Case 1: BUY signal in Bullish trend -> TAS = 1.0. Confidence 7 + 1 = 8.
            event1 = SignalValidated(
                signal_id=201,
                symbol="BTCUSDT",
                action="buy",
                price=60000.0,
                quote_qty=10.0,
                exchange="binance",
            )
            await process_validated_signal(event1)

            assert len(analysis_events) == 1
            assert analysis_events[0].confidence == 8
            assert "Bullish trend alignment" in analysis_events[0].analysis_text

            # Test Case 2: BUY signal in Bearish trend -> TAS = -1.0. Confidence 7 - 3 = 4.
            analysis_events.clear()
            bearish_candles = make_candles("bearish")
            mock_global_capture_client.return_value = bearish_candles

            event2 = SignalValidated(
                signal_id=202,
                symbol="BTCUSDT",
                action="buy",
                price=60000.0,
                quote_qty=10.0,
                exchange="binance",
            )
            await process_validated_signal(event2)

            assert len(analysis_events) == 1
            assert analysis_events[0].confidence == 4
            assert "Trend conflict" in analysis_events[0].analysis_text
    finally:
        mock_screenshot_path.unlink(missing_ok=True)
        config.MTA_ENABLED = orig_mta
        config.MTA_STF_WEIGHT_1M = orig_stf_1m
        config.MTA_STF_WEIGHT_5M = orig_stf_5m
        config.MTA_STF_WEIGHT_15M = orig_stf_15m
        config.MTA_STF_WEIGHT_30M = orig_stf_30m
        config.MTA_MLTF_WEIGHT_1H = orig_mltf_1h
        config.MTA_MLTF_WEIGHT_4H = orig_mltf_4h
        config.MTA_MLTF_WEIGHT_1D = orig_mltf_1d
        config.SENTIMENT_ENABLED = orig_sent
        config.MCP_ENABLED = orig_mcp
        config.RAG_ENABLED = orig_rag

        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_capture_state()


@pytest.mark.asyncio
async def test_ai_analyzer_directional_sentiment(mock_global_capture_client):
    """AIAnalyzer: Directional sentiment boosts/penalizes signal confidence based on action."""
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

    # Neutral candles (close=100, SMA=100) -> TAS = 0.0
    neutral_candles = make_candles("neutral")
    mock_global_capture_client.return_value = neutral_candles

    # Create mock screenshot file on disk
    mock_screenshot_path = Path(__file__).parent / "sentiment_test_screenshot.png"
    mock_screenshot_path.touch()

    # Mock Sentiment Analyzer to return Bullish sentiment (score = 0.8)
    mock_sentiment_analyzer = MagicMock()
    mock_sentiment_analyzer.analyze_symbol = AsyncMock(
        return_value={
            "enabled": True,
            "combined_score": 0.8,
            "breakdown": {"twitter": 0.8, "rss": 0.8, "glassnode": 0.8},
        }
    )

    # Save original configs
    orig_mta = config.MTA_ENABLED
    orig_stf_1m = config.MTA_STF_WEIGHT_1M
    orig_stf_5m = config.MTA_STF_WEIGHT_5M
    orig_stf_15m = config.MTA_STF_WEIGHT_15M
    orig_stf_30m = config.MTA_STF_WEIGHT_30M
    orig_mltf_1h = config.MTA_MLTF_WEIGHT_1H
    orig_mltf_4h = config.MTA_MLTF_WEIGHT_4H
    orig_mltf_1d = config.MTA_MLTF_WEIGHT_1D
    orig_sent = config.SENTIMENT_ENABLED
    orig_mcp = config.MCP_ENABLED
    orig_rag = config.RAG_ENABLED

    try:
        config.MTA_ENABLED = True
        config.MTA_STF_WEIGHT_1M = 0.05
        config.MTA_STF_WEIGHT_5M = 0.10
        config.MTA_STF_WEIGHT_15M = 0.12
        config.MTA_STF_WEIGHT_30M = 0.13
        config.MTA_MLTF_WEIGHT_1H = 0.15
        config.MTA_MLTF_WEIGHT_4H = 0.20
        config.MTA_MLTF_WEIGHT_1D = 0.25
        config.SENTIMENT_ENABLED = True
        config.MCP_ENABLED = True
        config.RAG_ENABLED = False

        with (
            patch("analyzer.ai_analyzer.get_mcp_client") as mock_mcp_factory,
            patch("analyzer.ai_analyzer.vision_module") as mock_vision,
            patch("database.insert_brief") as mock_insert_brief,
            patch(
                "analyzer.sentiment_analyzer.SentimentAnalyzer",
                return_value=mock_sentiment_analyzer,
            ),
        ):
            mock_insert_brief.return_value = 1
            mock_mcp = AsyncMock()
            mock_mcp.health_check = AsyncMock(return_value={"connected": True})
            mock_mcp.capture_screenshot = AsyncMock(
                return_value=str(mock_screenshot_path)
            )
            mock_mcp_factory.return_value = mock_mcp

            # Vision default confidence = 7
            mock_vision.analyze_chart_vision = AsyncMock(
                return_value={
                    "confidence": 7,
                    "analysis": "Neutral chart",
                    "error": None,
                }
            )

            # Test Case 1: BUY signal + Bullish Sentiment (0.8) -> Confidence 7 + 1 = 8
            event1 = SignalValidated(
                signal_id=301,
                symbol="BTCUSDT",
                action="buy",
                price=60000.0,
                quote_qty=10.0,
                exchange="binance",
            )
            await process_validated_signal(event1)

            assert len(analysis_events) == 1
            assert analysis_events[0].confidence == 8
            assert "Bullish sentiment boost (BUY)" in analysis_events[0].analysis_text

            # Test Case 2: SELL signal + Bullish Sentiment (0.8) -> Confidence 7 - 2 = 5
            analysis_events.clear()
            event2 = SignalValidated(
                signal_id=302,
                symbol="BTCUSDT",
                action="sell",
                price=60000.0,
                quote_qty=10.0,
                exchange="binance",
            )
            await process_validated_signal(event2)

            assert len(analysis_events) == 1
            assert analysis_events[0].confidence == 5
            assert (
                "Bullish sentiment penalty (SELL)" in analysis_events[0].analysis_text
            )
    finally:
        mock_screenshot_path.unlink(missing_ok=True)
        config.MTA_ENABLED = orig_mta
        config.MTA_STF_WEIGHT_1M = orig_stf_1m
        config.MTA_STF_WEIGHT_5M = orig_stf_5m
        config.MTA_STF_WEIGHT_15M = orig_stf_15m
        config.MTA_STF_WEIGHT_30M = orig_stf_30m
        config.MTA_MLTF_WEIGHT_1H = orig_mltf_1h
        config.MTA_MLTF_WEIGHT_4H = orig_mltf_4h
        config.MTA_MLTF_WEIGHT_1D = orig_mltf_1d
        config.SENTIMENT_ENABLED = orig_sent
        config.MCP_ENABLED = orig_mcp
        config.RAG_ENABLED = orig_rag

        from core.event_bus import bus as default_bus

        set_bus(default_bus)
        reset_capture_state()
