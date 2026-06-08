"""
Extended unit tests for sentiment_analyzer.py.
Covers API communication branches (Twitter, RSS, Glassnode) by mocking the underlying network requests.
"""

import os
import pytest
from unittest.mock import MagicMock, patch

import config
import database
from analyzer.sentiment_analyzer import (
    TwitterClient,
    RSSClient,
    GlassnodeClient,
    SentimentAnalyzer,
)


@pytest.fixture
def mock_requests():
    """Mock the requests object inside sentiment_analyzer module."""
    with patch("analyzer.sentiment_analyzer.requests", create=True) as mock_req:
        yield mock_req


@pytest.mark.asyncio
async def test_twitter_client_with_token(mock_requests):
    """Test TwitterClient when BEARER_TOKEN is configured."""
    client = TwitterClient()
    client.bearer_token = "fake_bearer_token"  # noqa: S105

    # Mock response
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"data": [{"text": "Bitcoin is looking bullish and strong today!"}, {"text": "Panic sell BTC, it is dump and bearish"}]}'
    mock_requests.get.return_value.__enter__.return_value = mock_response

    res = await client.get_sentiment("BTCUSDT")
    assert res["source"] == "twitter"
    assert res["count"] == 2
    # Bullish (1 pos, 0 neg) -> score 1.0; Bearish (0 pos, 2 neg) -> score -1.0. Avg = 0.0
    assert res["score"] == 0.0


@pytest.mark.asyncio
async def test_twitter_client_exception(mock_requests):
    """Test TwitterClient exception fallback."""
    client = TwitterClient()
    client.bearer_token = "fake_bearer_token"  # noqa: S105
    mock_requests.get.side_effect = Exception("Connection error")

    res = await client.get_sentiment("BTCUSDT")
    assert "fallback" in res["source"]
    assert res["count"] == 5
    assert "Connection error" in res["error"]


@pytest.mark.asyncio
async def test_rss_client_with_feeds(mock_requests):
    """Test RSSClient parsing and keyword filtering."""
    client = RSSClient()
    client.feed_urls = ["http://fakefeed.xml"]

    # Mock XML response
    mock_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Bitcoin rally continues towards moon</title>
          <description>The bullish trend of Bitcoin shows positive profit gains.</description>
        </item>
        <item>
          <title>Other news not matching</title>
          <description>Some random description</description>
        </item>
      </channel>
    </rss>
    """
    mock_response = MagicMock()
    mock_response.read.return_value = mock_xml
    mock_requests.get.return_value.__enter__.return_value = mock_response

    res = await client.get_sentiment("BTCUSDT")
    assert res["source"] == "rss"
    assert res["count"] == 1
    assert res["score"] > 0.0  # Positive keywords present


@pytest.mark.asyncio
async def test_rss_client_no_match(mock_requests):
    """Test RSSClient when no articles match keywords."""
    client = RSSClient()
    client.feed_urls = ["http://fakefeed.xml"]

    mock_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Ethereum is down</title>
          <description>Ethereum drop bearish crash</description>
        </item>
      </channel>
    </rss>
    """
    mock_response = MagicMock()
    mock_response.read.return_value = mock_xml
    mock_requests.get.return_value.__enter__.return_value = mock_response

    res = await client.get_sentiment("BTCUSDT")  # Searching BTC, but feed only has ETH
    assert res["source"] == "rss_no_match"
    assert res["count"] == 0
    assert res["score"] == 0.0


@pytest.mark.asyncio
async def test_rss_client_empty_and_exception(mock_requests):
    """Test RSSClient when feeds return nothing or fail."""
    client = RSSClient()
    client.feed_urls = ["http://fakefeed.xml"]
    mock_requests.get.side_effect = Exception("XML parse error")

    res = await client.get_sentiment("BTCUSDT")
    assert "fallback" in res["source"]
    assert res["count"] == 4


@pytest.mark.asyncio
async def test_glassnode_client_non_applicable():
    """Test GlassnodeClient handles non-BTC/ETH symbols cleanly."""
    client = GlassnodeClient()
    res = await client.get_sentiment("SOLUSDT")
    assert res["source"] == "glassnode_not_applicable"
    assert res["score"] == 0.0


@pytest.mark.asyncio
async def test_glassnode_client_with_api_key(mock_requests):
    """Test GlassnodeClient maps NUPL values to scores correctly."""
    client = GlassnodeClient()
    client.api_key = "fake_glassnode_key"

    # NUPL Optimistic (0.35)
    mock_response = MagicMock()
    mock_response.read.return_value = b'[{"t": 1234567, "v": 0.35}]'
    mock_requests.get.return_value.__enter__.return_value = mock_response

    res = await client.get_sentiment("BTCUSDT")
    assert res["source"] == "glassnode"
    assert res["nupl"] == 0.35
    assert res["score"] == 0.5


@pytest.mark.asyncio
async def test_glassnode_client_exception(mock_requests):
    """Test GlassnodeClient exception fallback."""
    client = GlassnodeClient()
    client.api_key = "fake_glassnode_key"
    mock_requests.get.side_effect = Exception("Glassnode API Timeout")

    res = await client.get_sentiment("BTCUSDT")
    assert "fallback" in res["source"]
    assert res["score"] in (0.2, 0.6, 0.8)


@pytest.mark.asyncio
async def test_unified_sentiment_analyzer_adaptive_weights(mock_requests):
    """Test SentimentAnalyzer orchestrates sub-clients and uses correct weights."""
    analyzer = SentimentAnalyzer()
    analyzer.twitter.bearer_token = "fake"  # noqa: S105
    analyzer.rss.feed_urls = ["http://fake"]
    analyzer.glassnode.api_key = "fake"

    # Mock returns
    # Twitter
    mock_twitter_res = MagicMock()
    mock_twitter_res.read.return_value = b'{"data": [{"text": "bullish positive"}]}'

    # RSS
    mock_rss_res = MagicMock()
    mock_rss_res.read.return_value = b"""<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><item><title>Bitcoin moon profit</title><description>buy pump</description></item></channel></rss>"""

    # Glassnode
    mock_glassnode_res = MagicMock()
    mock_glassnode_res.read.return_value = (
        b'[{"t": 12345, "v": 0.6}]'  # Belief (0.8 score)
    )

    def side_effect(req_or_url, **kwargs):
        resp = MagicMock()
        url_str = (
            getattr(req_or_url, "full_url", str(req_or_url))
            if hasattr(req_or_url, "full_url")
            else str(req_or_url)
        )
        if "twitter" in url_str:
            resp.read.return_value = b'{"data": [{"text": "bullish positive"}]}'
        elif "nupl" in url_str:
            resp.read.return_value = b'[{"t": 12345, "v": 0.6}]'
        else:
            resp.read.return_value = b"""<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><item><title>Bitcoin moon profit</title><description>buy pump</description></item></channel></rss>"""
        mock_val = MagicMock()
        mock_val.__enter__.return_value = resp
        return mock_val

    def request_side_effect(url, **kwargs):
        mock_req = MagicMock()
        mock_req.full_url = url
        return mock_req

    mock_requests.Request.side_effect = request_side_effect
    mock_requests.get.side_effect = side_effect

    original_db = config.DB_PATH
    config.DB_PATH = "test_sentiment_extended.db"

    # Clean old database
    if os.path.exists(config.DB_PATH):
        try:
            os.remove(config.DB_PATH)
        except Exception:  # noqa: S110
            pass

    try:
        await database.init_db()
        res = await analyzer.analyze_symbol("BTCUSDT")
        assert res["enabled"] is True
        assert res["sources"]["twitter"] == "twitter"
        assert res["sources"]["rss"] == "rss"
        assert res["sources"]["glassnode"] == "glassnode"
        assert res["combined_score"] > 0.0
    finally:
        config.DB_PATH = original_db
        if os.path.exists("test_sentiment_extended.db"):
            try:
                os.remove("test_sentiment_extended.db")
            except Exception:  # noqa: S110
                pass
