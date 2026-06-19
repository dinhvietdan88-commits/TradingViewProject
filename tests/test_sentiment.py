import asyncio
import pytest
import os
import sys

# Add 'server' path to sys.path so we can import modules directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server")))

import config
import database
from analyzer.sentiment_analyzer import analyze_text_sentiment, SentimentAnalyzer

@pytest.mark.asyncio
async def test_lexicon_sentiment():
    """Test standard lexicon sentiment categorization."""
    # Positive scenarios
    assert analyze_text_sentiment("The market is looking bullish and strong, we expect breakout!") > 0.0
    assert analyze_text_sentiment("Rallying upward toward new ATH, accumulate buy signal.") > 0.0
    
    # Negative scenarios
    assert analyze_text_sentiment("Extreme panic as price dumps. Crash and heavy selloff expected.") < 0.0
    assert analyze_text_sentiment("Bearish downward resistance and FUD.") < 0.0
    
    # Neutral/Zero cases
    assert analyze_text_sentiment("Just normal day with some regular events.") == 0.0
    assert analyze_text_sentiment("") == 0.0

@pytest.mark.asyncio
async def test_sentiment_analyzer_mock_flow():
    """Test full SentimentAnalyzer orchestrator with mock fallbacks."""
    # Temporarily override database path to local test database
    original_db = config.DB_PATH
    config.DB_PATH = "test_sentiment_trades.db"
    
    # Clean old database
    if os.path.exists(config.DB_PATH):
        try:
            os.remove(config.DB_PATH)
        except Exception:
            pass
            
    try:
        await database.init_db()
        
        analyzer = SentimentAnalyzer()
        assert analyzer.enabled is True
        
        # Test BTCUSDT analysis
        result = await analyzer.analyze_symbol("BTCUSDT")
        
        assert result["enabled"] is True
        assert result["symbol"] == "BTCUSDT"
        assert "combined_score" in result
        assert "breakdown" in result
        assert "twitter" in result["breakdown"]
        assert "rss" in result["breakdown"]
        assert "glassnode" in result["breakdown"]
        assert "fear_greed" in result["breakdown"]
        assert "funding" in result["breakdown"]
        
        # Verify raw data contains all 5 sources
        assert "raw_data" in result
        raw = result["raw_data"]
        assert "twitter" in raw
        assert "rss" in raw
        assert "glassnode" in raw
        assert "fear_greed" in raw
        assert "funding_rates" in raw

        # Verify db persistence
        async with database.aiosqlite.connect(config.DB_PATH) as db:
            db.row_factory = database.aiosqlite.Row
            async with db.execute("SELECT * FROM sentiment_logs") as cursor:
                rows = await cursor.fetchall()
                assert len(rows) == 1
                row = rows[0]
                assert row["symbol"] == "BTCUSDT"
                assert row["combined_score"] == result["combined_score"]
                assert row["raw_data"] is not None
                
    finally:
        config.DB_PATH = original_db
        if os.path.exists("test_sentiment_trades.db"):
            await asyncio.sleep(0.5)
            try:
                os.remove("test_sentiment_trades.db")
            except Exception:
                pass
