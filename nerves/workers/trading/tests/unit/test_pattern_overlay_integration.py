import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# Fix path to include workers/trading
sys.path.append(str(Path(__file__).parent.parent.parent))

from core.event_bus import EventBus
from core.events import AnalysisComplete
from hub.notification_hub import process_analysis_complete, set_bus

@pytest.mark.asyncio
async def test_analysis_complete_passes_vcp_pattern_overlay():
    """Verify AnalysisComplete with VCP detected passes pattern_overlay='VCP' to capture_screenshot."""
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
        analysis_text="VCP contraction.",
        screenshot_path="",
        combined_score="6/10",
        vision_result={"patterns": ["VCP pattern detected"]},
        should_trade=False,
        interactive_required=True
    )
    
    mock_client = MagicMock()
    mock_client.capture_screenshot = AsyncMock(return_value=MagicMock(success=True, file_path="/fake/path/analysis.png"))
    
    mock_bot = MagicMock()
    mock_bot.send_interactive_trade_approval = AsyncMock(return_value=[(12345, 67890)])
    mock_bot.get_approval_timeout_mgr = MagicMock(return_value=None)
    
    with patch("hub.notification_hub.notifier") as mock_notifier, \
         patch("capture_client.get_capture_client", return_value=mock_client), \
         patch.dict(sys.modules, {"telegram_bot": mock_bot}):
         
        mock_notifier.notify_all = MagicMock()
        
        await process_analysis_complete(event)
        
        # Verify capture_screenshot was called with pattern_overlay="VCP"
        mock_client.capture_screenshot.assert_called_once()
        args, kwargs = mock_client.capture_screenshot.call_args
        assert kwargs["pattern_overlay"] == "VCP"

@pytest.mark.asyncio
async def test_analysis_complete_passes_cup_pattern_overlay():
    """Verify AnalysisComplete with Cup pattern detected passes pattern_overlay='Cup & Handle'."""
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
    mock_client.capture_screenshot = AsyncMock(return_value=MagicMock(success=True, file_path="/fake/path/analysis.png"))
    
    mock_bot = MagicMock()
    mock_bot.send_interactive_trade_approval = AsyncMock(return_value=[(12345, 67890)])
    mock_bot.get_approval_timeout_mgr = MagicMock(return_value=None)
    
    with patch("hub.notification_hub.notifier") as mock_notifier, \
         patch("capture_client.get_capture_client", return_value=mock_client), \
         patch.dict(sys.modules, {"telegram_bot": mock_bot}):
         
        mock_notifier.notify_all = MagicMock()
        
        await process_analysis_complete(event)
        
        mock_client.capture_screenshot.assert_called_once()
        args, kwargs = mock_client.capture_screenshot.call_args
        assert kwargs["pattern_overlay"] == "Cup & Handle"

@pytest.mark.asyncio
async def test_telegram_bot_vision_command_truncates_caption_and_overlays():
    """Verify cmd_vision handles screenshot path, overlays VCP, and truncates caption for Telegram bot."""
    import telegram_bot
    from telegram import Update
    from telegram.ext import CallbackContext
    
    update = MagicMock(spec=Update)
    update.effective_chat = MagicMock()
    update.effective_chat.id = 12345
    update.effective_message = MagicMock()
    
    context = MagicMock(spec=CallbackContext)
    context.args = ["BTCUSDT"]
    context.bot = MagicMock()
    context.bot.send_photo = AsyncMock()
    context.bot.send_message = AsyncMock()
    
    # Mocking Vision AI result
    mock_result = {
        "symbol": "BTCUSDT",
        "analysis": "A" * 1500, # Large caption text to trigger truncation
        "confidence": 7,
        "patterns": ["VCP Pattern"],
        "combined_score": "7/10",
        "error": None
    }
    
    # Create a fake screenshot file
    fake_screenshot = Path("C:/Users/pesil/working/mj_trading/TradingViewProject/nerves/workers/trading/screenshots/test_btc.png")
    fake_screenshot.parent.mkdir(parents=True, exist_ok=True)
    fake_screenshot.touch()
    
    mock_mcp = MagicMock()
    mock_mcp.health_check = AsyncMock(return_value={"connected": True})
    mock_mcp.capture_screenshot = AsyncMock(return_value=str(fake_screenshot))
    
    try:
        with patch("vision.analyze_chart_vision", AsyncMock(return_value=mock_result)), \
             patch("mcp_client.get_mcp_client", return_value=mock_mcp):
             
            # Call cmd_vision inner handler or cmd_vision directly
            # We can mock active_commands to bypass already running check.
            telegram_bot.active_commands = set()
            
            await telegram_bot.cmd_vision(update, context)
            
            # Await all background tasks to complete
            import asyncio
            while telegram_bot.running_tasks:
                await asyncio.gather(*list(telegram_bot.running_tasks), return_exceptions=True)
            
            # Verify send_photo was called with truncated caption
            context.bot.send_photo.assert_called_once()
            kwargs = context.bot.send_photo.call_args[1]
            assert len(kwargs["caption"]) <= 1003
            assert kwargs["caption"].endswith("...")
            
            # Verify send_message was called with the full analysis and the status message
            # status message is sent at start of cmd_vision, full analysis text at the end of process_task
            assert context.bot.send_message.call_count >= 1
            full_msg_call = None
            for call in context.bot.send_message.call_args_list:
                call_text = call[1].get("text", "")
                if len(call_text) > 1000:
                    full_msg_call = call
                    break
            assert full_msg_call is not None, "Full analysis send_message not called"
            full_msg_kwargs = full_msg_call[1]
            assert len(full_msg_kwargs["text"]) > 1000
            
            # Verify capture_screenshot was called to generate the overlay
            mock_mcp.capture_screenshot.assert_called()
            # The second call should have pattern_overlay="VCP"
            vcp_calls = [c for c in mock_mcp.capture_screenshot.call_args_list if c[1].get("pattern_overlay") == "VCP"]
            assert len(vcp_calls) > 0
            
    finally:
        if fake_screenshot.exists():
            fake_screenshot.unlink()
