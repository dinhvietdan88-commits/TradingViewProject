import sys
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, 'nerves/workers/trading')

async def main():
    dummy_ohlcv = []
    base_price = 100.0
    import time
    now_ms = int(time.time() * 1000)
    day_ms = 24 * 60 * 60 * 1000
    
    for i in range(365):
        price = base_price + (i * 0.1)
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

    mock_capture_client = MagicMock()
    mock_capture_client.fetch_ohlcv = AsyncMock(return_value=dummy_ohlcv)
    
    mock_breaker = MagicMock()
    mock_breaker.is_available.return_value = True
    mock_breaker.call_timeout_sec = 10

    mock_advice_func = AsyncMock(return_value="APPROVED: The VCP pattern is strong.")

    with patch("workers.vps_analyzer.llm_breaker", mock_breaker), \
         patch("capture_client.get_capture_client", return_value=mock_capture_client), \
         patch("workers.vps_analyzer.rag.generate_trading_advice", mock_advice_func), \
         patch("workers.vps_analyzer.rag.query_knowledge", return_value=[{"content": "mock text", "metadata": {}, "relevance_score": 0.9}]):
        
        from workers.vps_analyzer import VpsAnalyzerWorker
        worker = VpsAnalyzerWorker()
        
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
        
        result = await worker._analyze_signal_v2(signal)
        print("RESULT IS:", result)

asyncio.run(main())
