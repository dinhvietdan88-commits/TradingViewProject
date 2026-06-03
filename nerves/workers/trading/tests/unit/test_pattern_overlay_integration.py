"""
Integration tests for pattern overlay in notification_hub → chart rendering flow.
Tests the actual implementation where:
  - _render_chart_for_event() builds drawings from event data
  - capture_screenshot is called with method="mplfinance"
  - Pattern detection runs on OHLCV data inside the rendering pipeline
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock, ANY

sys.path.append(str(Path(__file__).parent.parent.parent))

from core.event_bus import EventBus
from core.events import AnalysisComplete
from hub.notification_hub import process_analysis_complete, set_bus


@pytest.mark.asyncio
async def test_analysis_complete_renders_chart_with_vcp_vision_result():
    """Verify AnalysisComplete with vcp_detected in vision_result triggers chart rendering."""
    test_bus = EventBus()
    set_bus(test_bus)

    event = AnalysisComplete(
        signal_id=901,
        symbol="ETHUSDT",
        action="buy",
        price=3000.0,
        quote_qty=50.0,
        sl="2800",
        tp="3500",
        exchange="binance",
        confidence=6,
        analysis_text="VCP contraction detected.",
        screenshot_path="",
        combined_score="6/10",
        vision_result={"vcp_detected": True, "patterns": ["VCP pattern detected"]},
        should_trade=False,
        interactive_required=True
    )

    mock_client = MagicMock()
    mock_client.capture_screenshot = AsyncMock(
        return_value=MagicMock(success=True, file_path="/fake/path/analysis.png")
    )

    mock_bot = MagicMock()
    mock_bot.send_interactive_trade_approval = AsyncMock(return_value=[(12345, 67890)])
    mock_bot.get_approval_timeout_mgr = MagicMock(return_value=None)

    with patch("hub.notification_hub.notifier") as mock_notifier, \
         patch("capture_client.get_capture_client", return_value=mock_client), \
         patch.dict(sys.modules, {"telegram_bot": mock_bot}):

        mock_notifier.notify_all = MagicMock()

        await process_analysis_complete(event)

        # Verify capture_screenshot was called with mplfinance method
        mock_client.capture_screenshot.assert_called_once()
        args, kwargs = mock_client.capture_screenshot.call_args
        assert kwargs["symbol"] == "ETHUSDT"
        assert kwargs["method"] == "mplfinance"

        # Verify drawings include Entry/SL/TP
        drawings = kwargs["drawings"]
        labels = [d["label"] for d in drawings]
        assert "Entry" in labels
        assert "SL" in labels
        assert "TP" in labels


@pytest.mark.asyncio
async def test_analysis_complete_with_cup_pattern_in_vision():
    """Verify AnalysisComplete with Cup pattern in vision_result renders chart."""
    test_bus = EventBus()
    set_bus(test_bus)

    event = AnalysisComplete(
        signal_id=902,
        symbol="BTCUSDT",
        action="buy",
        price=60000.0,
        quote_qty=50.0,
        sl="58000",
        tp="65000",
        exchange="binance",
        confidence=7,
        analysis_text="Cup pattern.",
        screenshot_path="",
        combined_score="7/10",
        vision_result={"patterns": ["Cup and handle base"]},
        should_trade=False,
        interactive_required=True
    )

    mock_client = MagicMock()
    mock_client.capture_screenshot = AsyncMock(
        return_value=MagicMock(success=True, file_path="/fake/path/cup.png")
    )

    mock_bot = MagicMock()
    mock_bot.send_interactive_trade_approval = AsyncMock(return_value=[(12345, 67890)])
    mock_bot.get_approval_timeout_mgr = MagicMock(return_value=None)

    with patch("hub.notification_hub.notifier") as mock_notifier, \
         patch("capture_client.get_capture_client", return_value=mock_client), \
         patch.dict(sys.modules, {"telegram_bot": mock_bot}):

        mock_notifier.notify_all = MagicMock()

        await process_analysis_complete(event)

        # Verify chart was rendered
        mock_client.capture_screenshot.assert_called_once()
        args, kwargs = mock_client.capture_screenshot.call_args
        assert kwargs["method"] == "mplfinance"

        # Verify send_interactive_trade_approval was called with photo
        mock_bot.send_interactive_trade_approval.assert_called_once()
        call_kwargs = mock_bot.send_interactive_trade_approval.call_args[1]
        assert call_kwargs["photo_path"] == "/fake/path/cup.png"


@pytest.mark.asyncio
async def test_chart_rendering_non_fatal_on_failure():
    """Verify that chart rendering failure does NOT prevent trade processing."""
    test_bus = EventBus()
    set_bus(test_bus)

    event = AnalysisComplete(
        signal_id=903,
        symbol="SOLUSDT",
        action="sell",
        price=150.0,
        quote_qty=30.0,
        sl="160",
        tp="130",
        exchange="weex",
        confidence=6,
        analysis_text="Short signal.",
        screenshot_path="",
        combined_score="6/10",
        vision_result={},
        should_trade=False,
        interactive_required=True
    )

    mock_client = MagicMock()
    # Simulate capture failure
    mock_client.capture_screenshot = AsyncMock(side_effect=Exception("OHLCV fetch failed"))

    mock_bot = MagicMock()
    mock_bot.send_interactive_trade_approval = AsyncMock(return_value=[(12345, 67890)])
    mock_bot.get_approval_timeout_mgr = MagicMock(return_value=None)

    with patch("hub.notification_hub.notifier") as mock_notifier, \
         patch("capture_client.get_capture_client", return_value=mock_client), \
         patch.dict(sys.modules, {"telegram_bot": mock_bot}):

        mock_notifier.notify_all = MagicMock()

        # Should NOT raise — chart failure is non-fatal
        await process_analysis_complete(event)

        # Trade approval should still be sent (without photo)
        mock_bot.send_interactive_trade_approval.assert_called_once()
        call_kwargs = mock_bot.send_interactive_trade_approval.call_args[1]
        assert call_kwargs["photo_path"] is None  # No chart due to failure
