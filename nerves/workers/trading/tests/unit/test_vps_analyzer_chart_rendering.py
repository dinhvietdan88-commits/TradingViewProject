import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
from pathlib import Path

# Ensure server/ is in python path
server_dir = Path(__file__).resolve().parent.parent.parent
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

class TestVpsAnalyzerChartAndRejectionMetadata(unittest.IsolatedAsyncioTestCase):
    async def test_rejection_preserves_signal_metadata(self):
        """Verify that analyze_single preserves all critical signal metadata (symbol, action, price, exchange, analysis_mode) on rejections."""
        # 1. Setup mock objects for V1 rejected signal
        mock_breaker = MagicMock()
        mock_breaker.is_available.return_value = False  # force algorithmic mode
        
        from workers.vps_analyzer import VpsAnalyzerWorker
        worker = VpsAnalyzerWorker()
        
        # Mock _analyze_signal to return None (rejected)
        worker._analyze_signal = AsyncMock(return_value=None)
        
        # Test signal
        signal = {
            "symbol": "BTCUSDT",
            "action": "buy",
            "price": "50000.0",
            "payload": {
                "exchange": "BINANCE",
                "volume": 2000,
                "volume_avg": 1000,
                "rsi": 55,
                "timeframe": "D"
            },
            "queue_id": 999
        }
        
        # We need to test the analyze_single inner function within poll_and_analyze.
        # Since analyze_single is defined inside poll_and_analyze, we can mock _long_poll
        # to return our signal, and call poll_and_analyze.
        worker._long_poll = AsyncMock(return_value=[signal])
        
        with patch("workers.vps_analyzer.llm_breaker", mock_breaker):
            results = await worker.poll_and_analyze()
            
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertFalse(res["approved"])
        self.assertEqual(res["queue_id"], 999)
        self.assertEqual(res["symbol"], "BTCUSDT")
        self.assertEqual(res["action"], "buy")
        self.assertEqual(float(res["price"]), 50000.0)
        self.assertEqual(res["exchange"], "BINANCE")
        self.assertEqual(res["analysis_mode"], "algorithmic")
        self.assertIn("payload", res)

    async def test_notify_telegram_calls_render_and_sends_photo(self):
        """Verify that _notify_analysis_telegram renders the chart and calls send_telegram_photo."""
        from workers.vps_analyzer import VpsAnalyzerWorker
        worker = VpsAnalyzerWorker()
        
        # Mock rendering to return a fake chart path
        worker._render_chart_for_signal = AsyncMock(return_value="/fake/path/to/chart.png")
        
        mock_send_photo = MagicMock()
        mock_send_alert = AsyncMock()
        
        # Setup analyzed data structure
        analyzed = {
            "queue_id": 1001,
            "approved": True,
            "analysis_mode": "ai",
            "symbol": "ETHUSDT",
            "action": "buy",
            "price": 3000.0,
            "trade_payload": {
                "symbol": "ETHUSDT",
                "action": "buy",
                "price": 3000.0,
                "qty": 0.5,
                "sl": 2800.0,
                "tp": 3500.0,
                "ai_confidence": 85,
                "analysis": "Test approved signal. [Provider: agy-cli]",
            }
        }
        
        with patch("notifier.send_telegram_photo", mock_send_photo), \
             patch("notifier.send_telegram_alert", mock_send_alert):
             
            await worker._notify_analysis_telegram(analyzed)
            
            # Since send_telegram_photo is run via asyncio.to_thread, we verify it was called
            # (which runs synchronously in a separate thread)
            mock_send_photo.assert_called_once()
            args, kwargs = mock_send_photo.call_args
            self.assertEqual(args[0], "/fake/path/to/chart.png")
            self.assertIn("AI Core Analysis #1001", args[1])
            self.assertIn("ETHUSDT", args[1])
            
            # send_telegram_alert should NOT be called since photo rendering succeeded
            mock_send_alert.assert_not_called()

    async def test_notify_telegram_falls_back_to_alert_on_render_failure(self):
        """Verify that if chart rendering fails, _notify_analysis_telegram falls back to send_telegram_alert text message."""
        from workers.vps_analyzer import VpsAnalyzerWorker
        worker = VpsAnalyzerWorker()
        
        # Mock rendering to return None (failure)
        worker._render_chart_for_signal = AsyncMock(return_value=None)
        
        mock_send_photo = MagicMock()
        mock_send_alert = AsyncMock()
        
        analyzed = {
            "queue_id": 1002,
            "approved": False,
            "analysis_mode": "algorithmic",
            "symbol": "SOLUSDT",
            "action": "buy",
            "price": 150.0,
            "reason": "Test rejected signal",
        }
        
        with patch("notifier.send_telegram_photo", mock_send_photo), \
             patch("notifier.send_telegram_alert", mock_send_alert):
             
            await worker._notify_analysis_telegram(analyzed)
            
            # send_telegram_photo should NOT be called
            mock_send_photo.assert_not_called()
            
            # send_telegram_alert should be called as fallback
            mock_send_alert.assert_called_once()
            args, kwargs = mock_send_alert.call_args
            self.assertIn("AI Core Analysis #1002", args[0])
            self.assertIn("SOLUSDT", args[0])
            self.assertIn("Test rejected signal", args[0])

if __name__ == "__main__":
    unittest.main()
