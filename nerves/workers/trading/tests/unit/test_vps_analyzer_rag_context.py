import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
from pathlib import Path

# Ensure server/ is in python path
server_dir = Path(__file__).resolve().parent.parent.parent
if str(server_dir) not in sys.path:
    sys.path.insert(0, str(server_dir))

class TestVpsAnalyzerRagContext(unittest.IsolatedAsyncioTestCase):
    async def test_vps_analyzer_fetches_ohlcv_and_injects_stats(self):
        """Verify that vps_analyzer.py fetches daily OHLCV, runs metrics, and injects context into the RAG prompt."""
        # 1. Mock daily OHLCV data (365 candles with simple pattern)
        # Each candle: [timestamp, open, high, low, close, volume]
        dummy_ohlcv = []
        base_price = 100.0
        import time
        now_ms = int(time.time() * 1000)
        day_ms = 24 * 60 * 60 * 1000
        
        for i in range(365):
            # Form a slight uptrend with minor contractions
            price = base_price + (i * 0.1)
            # Add volatility
            high = price * 1.02
            low = price * 0.98
            dummy_ohlcv.append([
                now_ms - (365 - i) * day_ms,
                price,
                high,
                low,
                price,
                1000.0
            ])

        # 2. Setup mock objects
        mock_capture_client = MagicMock()
        mock_capture_client.fetch_ohlcv = AsyncMock(return_value=dummy_ohlcv)
        
        # Mock LLM circuit breaker state
        mock_breaker = MagicMock()
        mock_breaker.is_available.return_value = True
        mock_breaker.call_timeout_sec = 10

        # We want to catch the call to generate_trading_advice to verify the injected stats
        mock_advice_func = AsyncMock(return_value="APPROVED: The VCP pattern is strong.")

        # 3. Patch dependencies and run analysis
        with patch("workers.vps_analyzer.llm_breaker", mock_breaker), \
             patch("capture_client.get_capture_client", return_value=mock_capture_client), \
             patch("workers.vps_analyzer.rag.generate_trading_advice", mock_advice_func) as mock_gen_advice, \
             patch("workers.vps_analyzer.rag.query_knowledge", return_value=[{"content": "mock text", "metadata": {}, "relevance_score": 0.9}]):
            
            from workers.vps_analyzer import VpsAnalyzerWorker
            worker = VpsAnalyzerWorker()
            
            # Simulated signal
            signal = {
                "symbol": "BTCUSDT",
                "action": "buy",
                "price": "136.5",
                "payload": {
                    "volume": 2000,
                    "volume_avg": 1000,
                    "rsi": 55,
                    "timeframe": "D"
                },
                "queue_id": 123
            }
            
            # Execute analysis
            result = await worker._analyze_signal_v2(signal)
            
            # Assertions
            self.assertTrue(result["approved"])
            self.assertEqual(result["analysis_mode"], "ai")
            
            # Verify fetch_ohlcv was called
            mock_capture_client.fetch_ohlcv.assert_called_once_with("BTCUSDT", timeframe="D", limit=365)
            
            # Verify generate_trading_advice was called with the modified payload containing technical stats
            called_args, called_kwargs = mock_gen_advice.call_args
            called_payload = called_kwargs.get("payload") or called_args[3]
            
            self.assertIn("vcp_stats", called_payload)
            self.assertIn("trend_stats", called_payload)
            
            # Verify RAG stats contents
            trend_stats = called_payload["trend_stats"]
            self.assertIn("score", trend_stats)
            self.assertIn("stage", trend_stats)
            self.assertIn("criteria", trend_stats)
            
            # Verify VCP stats contents
            vcp_stats = called_payload["vcp_stats"]
            self.assertIn("detected", vcp_stats)

if __name__ == "__main__":
    unittest.main()
