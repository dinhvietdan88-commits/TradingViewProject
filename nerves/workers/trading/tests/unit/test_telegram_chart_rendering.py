import sys
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

# Fix path to include server/ if needed
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.event_bus import EventBus
from core.events import AnalysisComplete, IndicatorSignalReceived
from hub.notification_hub import (
    notify_indicator_signal,
    process_analysis_complete,
    set_bus,
)


@pytest.mark.asyncio
async def test_indicator_signal_renders_chart_and_sends_photo():
    """Verify IndicatorSignalReceived fetches klines, renders chart, and sends photo via telegram_bot."""
    test_bus = EventBus()
    set_bus(test_bus)

    event = IndicatorSignalReceived(
        signal_id=900,
        symbol="BTCUSDT",
        signal_type="indicator",
        indicator_name="VBS Buy",
        interval="1h",
        price=60000.0,
        confidence_score=75,
        conditions_met=["cond1"],
        metadata={},
    )

    mock_client = MagicMock()
    mock_client.capture_screenshot = AsyncMock(
        return_value=MagicMock(success=True, file_path="/fake/path/indicator_chart.png")
    )

    mock_bot = MagicMock()
    mock_bot.send_interactive_indicator_alert = AsyncMock(return_value=[(12345, 67890)])

    with (
        patch("hub.notification_hub.notifier") as mock_notifier,
        patch("capture_client.get_capture_client", return_value=mock_client),
        patch.dict(sys.modules, {"telegram_bot": mock_bot}),
    ):
        mock_notifier.notify_all = AsyncMock()

        await notify_indicator_signal(event)

        # Verify capture_screenshot was called with correct params
        mock_client.capture_screenshot.assert_called_once()
        args, kwargs = mock_client.capture_screenshot.call_args
        assert kwargs["symbol"] == "BTCUSDT"
        assert kwargs["method"] == "mplfinance"

        # Verify send_interactive_indicator_alert was called with the chart path
        mock_bot.send_interactive_indicator_alert.assert_called_once_with(
            signal_id=900,
            symbol="BTCUSDT",
            message=ANY,
            photo_path="/fake/path/indicator_chart.png",
        )


@pytest.mark.asyncio
async def test_analysis_complete_renders_chart_and_sends_photo():
    """Verify AnalysisComplete (medium confidence) renders chart and sends photo via telegram_bot."""
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
        analysis_text="Looking strong.",
        screenshot_path="",
        combined_score="6/10",
        vision_result={},
        should_trade=False,
        interactive_required=True,
    )

    mock_client = MagicMock()
    mock_client.capture_screenshot = AsyncMock(
        return_value=MagicMock(success=True, file_path="/fake/path/analysis.png")
    )

    mock_bot = MagicMock()
    mock_bot.send_interactive_trade_approval = AsyncMock(return_value=[(12345, 67890)])
    mock_bot.get_approval_timeout_mgr = MagicMock(return_value=None)

    with (
        patch("hub.notification_hub.notifier") as mock_notifier,
        patch("capture_client.get_capture_client", return_value=mock_client),
        patch.dict(sys.modules, {"telegram_bot": mock_bot}),
    ):
        mock_notifier.notify_all = MagicMock()

        await process_analysis_complete(event)

        # Verify capture_screenshot was called
        mock_client.capture_screenshot.assert_called_once()
        args, kwargs = mock_client.capture_screenshot.call_args
        assert kwargs["symbol"] == "ETHUSDT"
        assert kwargs["method"] == "mplfinance"
        assert kwargs["drawings"] == [
            {"price": 3000.0, "label": "Entry", "color": "#26a69a"},
            {"price": 2800.0, "label": "SL", "color": "#ef5350"},
            {"price": 3500.0, "label": "TP", "color": "#2962ff"},
        ]

        # Verify send_interactive_trade_approval was called with the photo path
        mock_bot.send_interactive_trade_approval.assert_called_once_with(
            signal_id=901, message=ANY, photo_path="/fake/path/analysis.png"
        )
