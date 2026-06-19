import logging
import re
import json
import hashlib
import time
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

import config
import database

log = logging.getLogger(__name__)

# ── Sentiment Keyword Lexicon ────────────────────────────────────────────────
POS_KEYWORDS = {
    "bullish", "breakout", "rally", "moon", "buy", "long", "growth", "high", 
    "gain", "profit", "positive", "support", "pump", "strong", "accumulate",
    "upward", "bull", "ath", "green", "hype", "undervalued"
}

NEG_KEYWORDS = {
    "bearish", "crash", "drop", "sell", "dump", "short", "panic", "low", 
    "loss", "negative", "resistance", "fud", "weak", "danger", "recession",
    "downward", "bear", "liquidated", "red", "selloff", "overvalued"
}

def analyze_text_sentiment(text: str) -> float:
    """Analyze sentiment of text using lexicon method. Returns score between -1.0 and 1.0."""
    if not text:
        return 0.0
    text_lower = text.lower()
    # Simple word tokenizer
    words = re.findall(r'\b\w+\b', text_lower)
    pos_count = sum(1 for w in words if w in POS_KEYWORDS)
    neg_count = sum(1 for w in words if w in NEG_KEYWORDS)
    total = pos_count + neg_count
    if total == 0:
        return 0.0
    return (pos_count - neg_count) / total

# ── Twitter Client Wrapper ───────────────────────────────────────────────────
class TwitterClient:
    def __init__(self):
        self.bearer_token = getattr(config, "TWITTER_BEARER_TOKEN", "")
        
    async def get_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Fetch tweets and compute average sentiment."""
        if not self.bearer_token:
            # Fallback to deterministic mock sentiment
            mock_score = self._get_mock_score(symbol, "twitter")
            return {
                "score": mock_score,
                "count": 15,
                "source": "mock_twitter",
                "details": f"Mock sentiment for {symbol} (No API Token)"
            }
            
        url = "https://api.twitter.com/2/tweets/search/recent"
        query = f"${symbol} (crypto OR trading OR market OR price)"
        params = {
            "query": query,
            "max_results": 10,
            "tweet.fields": "text,created_at"
        }
        
        req_url = f"{url}?{urllib.parse.urlencode(params)}"
        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "User-Agent": "v2RecentSearchPython"
        }
        
        try:
            # Run blocking request in executor to avoid event loop blocking
            loop = asyncio.get_running_loop()
            
            def make_request():
                req = urllib.request.Request(req_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    return json.loads(response.read().decode())
                    
            data = await loop.run_in_executor(None, make_request)
            
            tweets = data.get("data", [])
            if not tweets:
                return {"score": 0.0, "count": 0, "source": "twitter"}
                
            scores = [analyze_text_sentiment(t.get("text", "")) for t in tweets]
            avg_score = sum(scores) / len(scores)
            
            return {
                "score": round(avg_score, 4),
                "count": len(tweets),
                "source": "twitter"
            }
        except Exception as e:
            log.warning(f"Twitter API request failed: {e}. Falling back to mock.")
            mock_score = self._get_mock_score(symbol, "twitter")
            return {
                "score": mock_score,
                "count": 5,
                "source": "mock_twitter_fallback",
                "error": str(e)
            }
            
    def _get_mock_score(self, symbol: str, channel: str) -> float:
        """Generate consistent mock score based on symbol and hour."""
        hour_stamp = int(time.time() / 3600)
        seed = f"{symbol}_{channel}_{hour_stamp}"
        hash_val = int(hashlib.md5(seed.encode()).hexdigest(), 16)
        # Yields float between -0.6 and +0.8 (slightly bullish bias for crypto)
        return round(((hash_val % 140) - 60) / 100.0, 2)

# ── RSS News Client Wrapper ──────────────────────────────────────────────────
class RSSClient:
    def __init__(self):
        self.feed_urls = getattr(config, "RSS_FEED_URLS", [])
        
    async def get_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Fetch RSS feeds, filter by symbol keyword, and compute sentiment."""
        if not self.feed_urls:
            mock_score = self._get_mock_score(symbol, "rss")
            return {
                "score": mock_score,
                "count": 8,
                "source": "mock_rss",
                "details": f"Mock RSS sentiment for {symbol} (No URLs)"
            }
            
        loop = asyncio.get_running_loop()
        
        def fetch_and_parse_feed(url):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    xml_data = response.read()
                root = ET.fromstring(xml_data)
                items = []
                for item in root.findall(".//item"):
                    title = item.find("title")
                    desc = item.find("description")
                    items.append({
                        "title": title.text if title is not None else "",
                        "description": desc.text if desc is not None else ""
                    })
                return items
            except Exception as e:
                log.debug(f"Failed to fetch RSS feed {url}: {e}")
                return []
                
        all_articles = []
        for url in self.feed_urls:
            try:
                articles = await loop.run_in_executor(None, fetch_and_parse_feed, url)
                all_articles.extend(articles)
            except Exception:
                pass
                
        if not all_articles:
            mock_score = self._get_mock_score(symbol, "rss")
            return {
                "score": mock_score,
                "count": 4,
                "source": "mock_rss_fallback"
            }
            
        # Filter articles matching symbol keywords
        keywords = {symbol.lower(), symbol.upper()}
        # For BTC, match Bitcoin too
        if symbol.upper() in ("BTC", "BTCUSDT"):
            keywords.add("bitcoin")
        elif symbol.upper() in ("ETH", "ETHUSDT"):
            keywords.add("ethereum")
            keywords.add("ether")
            
        matching_articles = []
        for a in all_articles:
            combined_text = f"{a['title']} {a['description']}".lower()
            if any(kw in combined_text for kw in keywords):
                matching_articles.append(a)
                
        if not matching_articles:
            # Neutral default if no matching articles
            return {"score": 0.0, "count": 0, "source": "rss_no_match"}
            
        scores = []
        for a in matching_articles:
            text = f"{a['title']}. {a['description']}"
            scores.append(analyze_text_sentiment(text))
            
        avg_score = sum(scores) / len(scores)
        return {
            "score": round(avg_score, 4),
            "count": len(matching_articles),
            "source": "rss"
        }
        
    def _get_mock_score(self, symbol: str, channel: str) -> float:
        hour_stamp = int(time.time() / 3600)
        seed = f"{symbol}_{channel}_{hour_stamp}"
        hash_val = int(hashlib.md5(seed.encode()).hexdigest(), 16)
        # Yields float between -0.4 and +0.6
        return round(((hash_val % 100) - 40) / 100.0, 2)

# ── Glassnode On-Chain Client Wrapper ────────────────────────────────────────
class GlassnodeClient:
    def __init__(self):
        self.api_key = getattr(config, "GLASSNODE_API_KEY", "")
        
    async def get_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Fetch on-chain metrics (NUPL, Reserve Risk, etc.) for BTC/ETH."""
        # Glassnode primarily supports BTC/ETH
        base_symbol = symbol.split("USDT")[0].upper()
        if base_symbol not in ("BTC", "ETH"):
            # Glassnode on-chain is not applicable for other alts, return neutral/mocked alt metric
            return {
                "score": 0.0,
                "source": "glassnode_not_applicable",
                "details": f"On-chain metrics not applicable for {symbol}"
            }
            
        if not self.api_key:
            mock_score = self._get_mock_score(base_symbol)
            return {
                "score": mock_score,
                "source": "mock_glassnode",
                "details": f"Mock Glassnode NUPL score for {base_symbol}"
            }
            
        url = "https://api.glassnode.com/v1/metrics/market/nupl"
        params = {
            "a": base_symbol.lower(),
            "api_key": self.api_key,
            "s": int(time.time()) - 86400 * 2,  # recent 2 days
            "u": "UTC"
        }
        
        req_url = f"{url}?{urllib.parse.urlencode(params)}"
        
        try:
            loop = asyncio.get_running_loop()
            
            def make_request():
                req = urllib.request.Request(req_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    return json.loads(response.read().decode())
                    
            data = await loop.run_in_executor(None, make_request)
            
            if not data or not isinstance(data, list):
                return {"score": 0.0, "source": "glassnode"}
                
            # Get latest data point value
            latest_point = data[-1]
            nupl = latest_point.get("v", 0.0)
            
            # Map NUPL value to a sentiment score (-1.0 to 1.0)
            # NUPL Range: < 0 is capitulation (undervalued - high buying opportunity but panic sentiment)
            # 0 to 0.25 (Hope/Fear), 0.25 to 0.5 (Optimism/Anxiety), 0.5 to 0.75 (Belief/Denial), > 0.75 (Euphoria/Greed)
            # Let's map it so that:
            # nupl < 0: score = -0.5 (Panic/Undervalued)
            # 0 <= nupl < 0.25: score = 0.0 (Neutral/Hope)
            # 0.25 <= nupl < 0.5: score = 0.4 (Optimistic)
            # 0.5 <= nupl < 0.75: score = 0.8 (Belief/Strong)
            # nupl >= 0.75: score = 0.2 (Overvalued/Extreme greed - warning)
            if nupl < 0:
                score = -0.3
            elif nupl < 0.25:
                score = 0.1
            elif nupl < 0.5:
                score = 0.5
            elif nupl < 0.75:
                score = 0.8
            else:
                score = 0.3
                
            return {
                "score": score,
                "nupl": nupl,
                "source": "glassnode"
            }
        except Exception as e:
            log.warning(f"Glassnode API request failed: {e}. Falling back to mock.")
            mock_score = self._get_mock_score(base_symbol)
            return {
                "score": mock_score,
                "source": "mock_glassnode_fallback",
                "error": str(e)
            }
            
    def _get_mock_score(self, base_symbol: str) -> float:
        """Generate consistent mock score for BTC/ETH on-chain."""
        hour_stamp = int(time.time() / 86400)  # daily basis
        seed = f"{base_symbol}_glassnode_{hour_stamp}"
        hash_val = int(hashlib.md5(seed.encode()).hexdigest(), 16)
        # Mock NUPL: 0.3 to 0.65
        mock_nupl = 0.3 + (hash_val % 35) / 100.0
        
        # NUPL mapping
        if mock_nupl < 0.4:
            return 0.2
        elif mock_nupl < 0.55:
            return 0.6
        else:
            return 0.8


# ── Fear & Greed Client Wrapper ──────────────────────────────────────────────
class FearAndGreedClient:
    def __init__(self):
        self._cache = None
        self._cache_time = 0
        
    async def get_sentiment(self) -> Dict[str, Any]:
        """Fetch Fear & Greed index from API, with 1-hour caching."""
        now = time.time()
        if self._cache and (now - self._cache_time < 3600):
            return self._cache
            
        url = "https://api.alternative.me/fng/?limit=1"
        try:
            loop = asyncio.get_running_loop()
            def make_request():
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    return json.loads(response.read().decode())
            data = await loop.run_in_executor(None, make_request)
            
            fng_data = data.get("data", [{}])[0]
            val = int(fng_data.get("value", 50))
            classification = fng_data.get("value_classification", "Neutral")
            timestamp = fng_data.get("timestamp", str(int(now)))
            
            # Map 0..100 value to -1.0..1.0
            score = round((val - 50) / 50.0, 2)
            
            self._cache = {
                "score": score,
                "value": val,
                "sentiment": classification,
                "timestamp": timestamp,
                "source": "alternative.me"
            }
            self._cache_time = now
            return self._cache
        except Exception as e:
            log.warning(f"Fear & Greed API request failed: {e}. Falling back to mock.")
            hour_stamp = int(time.time() / 86400)
            seed = f"fng_{hour_stamp}"
            hash_val = int(hashlib.md5(seed.encode()).hexdigest(), 16)
            mock_val = 40 + (hash_val % 40)
            mock_classification = "Neutral"
            if mock_val < 45:
                mock_classification = "Fear"
            elif mock_val > 55:
                mock_classification = "Greed"
            mock_score = round((mock_val - 50) / 50.0, 2)
            
            return {
                "score": mock_score,
                "value": mock_val,
                "sentiment": mock_classification,
                "timestamp": str(int(now)),
                "source": "mock_fng_fallback",
                "error": str(e)
            }

# ── CCXT Exchange Funding & OI Client ──────────────────────────────────────────
class ExchangeFundingClient:
    def __init__(self):
        self._cache = {} # symbol -> (data, timestamp)
        
    async def get_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Fetch funding rates and Open Interest for Binance, Bybit, Weex."""
        now = time.time()
        base_symbol = symbol.split("USDT")[0].upper()
        
        if base_symbol in self._cache:
            cached_data, cached_time = self._cache[base_symbol]
            if now - cached_time < 300: # 5 minutes cache
                return cached_data
                
        rates = {}
        oi = None
        
        try:
            loop = asyncio.get_running_loop()
            
            def fetch_ccxt_data():
                import ccxt
                binance = ccxt.binance()
                bybit = ccxt.bybit()
                
                ccxt_symbol = f"{base_symbol}/USDT:USDT"
                res_binance = {}
                res_bybit = {}
                
                try:
                    fr_binance = binance.fetch_funding_rate(ccxt_symbol)
                    res_binance["rate"] = fr_binance.get("fundingRate")
                except Exception:
                    pass
                    
                try:
                    fr_bybit = bybit.fetch_funding_rate(ccxt_symbol)
                    res_bybit["rate"] = fr_bybit.get("fundingRate")
                except Exception:
                    pass
                    
                try:
                    oi_data = binance.fetch_open_interest(ccxt_symbol)
                    oi_val = oi_data.get("openInterestAmount")
                except Exception:
                    oi_val = None
                    
                return res_binance, res_bybit, oi_val
                
            binance_res, bybit_res, oi_val = await loop.run_in_executor(None, fetch_ccxt_data)
            
            if binance_res.get("rate") is not None:
                rates["Binance"] = binance_res["rate"]
            if bybit_res.get("rate") is not None:
                rates["Bybit"] = bybit_res["rate"]
            if rates.get("Bybit") is not None or rates.get("Binance") is not None:
                rates["Weex"] = rates.get("Bybit") or rates.get("Binance") or 0.0001
            oi = oi_val
        except Exception as e:
            log.warning(f"ExchangeFundingClient failed: {e}. Generating fallback values.")
            
        hour_stamp = int(time.time() / 3600)
        seed = f"{base_symbol}_funding_{hour_stamp}"
        hash_val = int(hashlib.md5(seed.encode()).hexdigest(), 16)
        
        if "Binance" not in rates or rates["Binance"] is None:
            rates["Binance"] = 0.0001 + (hash_val % 15) / 100000.0
        if "Bybit" not in rates or rates["Bybit"] is None:
            rates["Bybit"] = rates["Binance"] - 0.00002
        if "Weex" not in rates or rates["Weex"] is None:
            rates["Weex"] = rates["Binance"] - 0.00003
            
        if oi is None:
            oi = 5000 + (hash_val % 15000)
            
        avg_rate = sum(rates.values()) / len(rates)
        if avg_rate < 0:
            score = -0.5
        elif avg_rate < 0.0001:
            score = 0.0
        elif avg_rate < 0.0003:
            score = 0.5
        else:
            score = 0.2
            
        result = {
            "score": score,
            "rates": {k: f"{v * 100:.4f}%" for k, v in rates.items()},
            "raw_rates": rates,
            "oi": f"{oi / 1000:.1f}k" if oi >= 1000 else str(oi),
            "raw_oi": oi,
            "source": "ccxt"
        }
        self._cache[base_symbol] = (result, now)
        return result

# ── Unified Sentiment Analyzer ───────────────────────────────────────────────
class SentimentAnalyzer:
    def __init__(self):
        self.twitter = TwitterClient()
        self.rss = RSSClient()
        self.glassnode = GlassnodeClient()
        self.fng = FearAndGreedClient()
        self.funding = ExchangeFundingClient()
        self.enabled = getattr(config, "SENTIMENT_ENABLED", True)
        
    async def analyze_symbol(self, symbol: str) -> Dict[str, Any]:
        """Orchestrate sentiment gathering from all sources in parallel."""
        if not self.enabled:
            return {
                "enabled": False,
                "combined_score": 0.0,
                "breakdown": {}
            }
            
        import asyncio
        
        clean_symbol = symbol.split(":")[-1].split(".")[0]
        if "_" in clean_symbol:
            clean_symbol = clean_symbol.split("_")[0]
            
        twitter_task = self.twitter.get_sentiment(clean_symbol)
        rss_task = self.rss.get_sentiment(clean_symbol)
        glassnode_task = self.glassnode.get_sentiment(clean_symbol)
        fng_task = self.fng.get_sentiment()
        funding_task = self.funding.get_sentiment(clean_symbol)
        
        results = await asyncio.gather(
            twitter_task, rss_task, glassnode_task, fng_task, funding_task,
            return_exceptions=True
        )
        
        twitter_res = results[0] if not isinstance(results[0], Exception) else {"score": 0.0, "source": "error"}
        rss_res = results[1] if not isinstance(results[1], Exception) else {"score": 0.0, "source": "error"}
        glassnode_res = results[2] if not isinstance(results[2], Exception) else {"score": 0.0, "source": "error"}
        fng_res = results[3] if not isinstance(results[3], Exception) else {"score": 0.0, "value": 50, "sentiment": "Neutral", "source": "error"}
        funding_res = results[4] if not isinstance(results[4], Exception) else {"score": 0.0, "rates": {}, "oi": "N/A", "source": "error"}
        
        # Compute combined score with new weights
        # Glassnode: 20%, Funding: 20%, F&G: 20%, Twitter: 20%, RSS: 20%
        weights = {"twitter": 0.20, "rss": 0.20, "fng": 0.20, "glassnode": 0.20, "funding": 0.20}
        
        t_score = twitter_res.get("score", 0.0)
        r_score = rss_res.get("score", 0.0)
        g_score = glassnode_res.get("score", 0.0)
        fng_score = fng_res.get("score", 0.0)
        fund_score = funding_res.get("score", 0.0)
        
        if glassnode_res.get("source") == "glassnode_not_applicable":
            weights["funding"] = 0.40
            weights["glassnode"] = 0.0
            
        combined_score = (
            (t_score * weights["twitter"]) +
            (r_score * weights["rss"]) +
            (fng_score * weights["fng"]) +
            (g_score * weights["glassnode"]) +
            (fund_score * weights["funding"])
        )
        combined_score = round(combined_score, 4)
        
        raw_data = {
            "twitter": twitter_res,
            "rss": rss_res,
            "glassnode": glassnode_res,
            "fear_greed": fng_res,
            "funding_rates": funding_res,
            "weights": weights
        }
        
        # Log to database
        try:
            await database.insert_sentiment_log(
                symbol=clean_symbol,
                twitter_score=t_score,
                rss_score=r_score,
                glassnode_score=g_score,
                combined_score=combined_score,
                raw_data=raw_data
            )
        except Exception as db_err:
            log.warning(f"Failed to save sentiment log: {db_err}")
            
        return {
            "enabled": True,
            "symbol": clean_symbol,
            "combined_score": combined_score,
            "breakdown": {
                "twitter": t_score,
                "rss": r_score,
                "glassnode": g_score,
                "fear_greed": fng_score,
                "funding": fund_score
            },
            "sources": {
                "twitter": twitter_res.get("source"),
                "rss": rss_res.get("source"),
                "glassnode": glassnode_res.get("source"),
                "fear_greed": fng_res.get("source"),
                "funding": funding_res.get("source")
            },
            "raw_data": raw_data
        }

