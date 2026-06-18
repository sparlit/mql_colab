import requests
import json
import time as _time
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ==========================================
# ALTERNATIVE DATA & SENTIMENT
# ==========================================


class TwitterSentiment:
    def __init__(self):
        self.cache = {}
        self.cache_time = 0
        self._lock = threading.Lock()

    def get_sentiment(self, symbol):
        now = _time.time()
        with self._lock:
            if symbol in self.cache and (now - self.cache_time) < 300:
                return self.cache[symbol]
        try:
            search_terms = {
                "EURUSD": ["EURUSD", "euro dollar"],
                "GBPUSD": ["GBPUSD", "cable"],
                "USDJPY": ["USDJPY", "dollar yen"],
                "XAUUSD": ["XAUUSD", "gold price"],
                "BTCUSD": ["BTCUSD", "bitcoin"],
            }
            terms = search_terms.get(symbol, [symbol])
            sentiment_score = 0
            for term in terms:
                url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    messages = data.get("messages", [])
                    for msg in messages[:10]:
                        sentiment = msg.get("entities", {}).get("sentiment", {})
                        if sentiment:
                            if sentiment.get("basic") == "Bullish":
                                sentiment_score += 1
                            elif sentiment.get("basic") == "Bearish":
                                sentiment_score -= 1
            result = {
                "symbol": symbol, "score": sentiment_score,
                "sentiment": "bullish" if sentiment_score > 0 else "bearish" if sentiment_score < 0 else "neutral",
                "strength": min(abs(sentiment_score) / 5, 1.0),
                "source": "stocktwits",
            }
            with self._lock:
                self.cache[symbol] = result
                self.cache_time = now
            return result
        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.debug("Twitter sentiment fetch failed: %s", e)
            return {"symbol": symbol, "score": 0, "sentiment": "unknown", "source": "unavailable"}


class GoogleTrends:
    def __init__(self):
        self.cache = {}
        self.cache_time = 0
        self._lock = threading.Lock()

    def get_trend(self, keyword):
        """Get Google Trends interest for a keyword.
        
        Note: Google Trends does not provide a public JSON API.
        This method uses a workaround via the SERP API or returns unavailable.
        For production use, consider using pytrends library or a paid API.
        """
        now = _time.time()
        with self._lock:
            if keyword in self.cache and (now - self.cache_time) < 3600:
                return self.cache[keyword]
        
        # Google Trends API is not publicly available for JSON access
        # Return unavailable status - use pytrends library for real integration
        logger.debug("Google Trends: API not available for %s (use pytrends library)", keyword)
        return {"keyword": keyword, "interest": 0, "trending": False, "source": "unavailable"}


class SatelliteDataAnalyzer:
    def __init__(self):
        self.data_cache = {}
        self._lock = threading.Lock()

    def analyze_commodity(self, commodity="oil"):
        with self._lock:
            if commodity in self.data_cache:
                return self.data_cache[commodity]
        try:
            from config import EIA_API_KEY
            if not EIA_API_KEY:
                logger.debug("EIA_API_KEY not configured, skipping satellite data")
                return None
            if commodity == "oil":
                url = f"https://api.eia.gov/v2/petroleum/pri/spt/data/?api_key={EIA_API_KEY}&frequency=monthly&data[0]=value&facets[product][]=EPM0&facets[area][]=NUS&sort[0][column]=period&sort[0][direction]=desc&length=1"
            elif commodity == "wheat":
                url = f"https://api.eia.gov/v2/total-energy/data/?api_key={EIA_API_KEY}&frequency=monthly&data[0]=value&facets[msn][]=WGTNFUS&sort[0][column]=period&sort[0][direction]=desc&length=1"
            elif commodity == "gold":
                url = f"https://api.eia.gov/v2/total-energy/data/?api_key={EIA_API_KEY}&frequency=monthly&data[0]=value&facets[msn][]=GLDFPUS&sort[0][column]=period&sort[0][direction]=desc&length=1"
            else:
                url = None
            if url:
                resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    data = resp.json()
                    records = data.get("response", {}).get("data", [])
                    if records:
                        latest = records[0]
                        result = {
                            "commodity": commodity, "source": "eia_api",
                            "period": latest.get("period", ""),
                            "value": latest.get("value", 0),
                            "unit": latest.get("units", ""),
                        }
                        with self._lock:
                            self.data_cache[commodity] = result
                        return result
        except requests.RequestException as e:
            logger.debug("Satellite API request failed: %s", e)
        except Exception as e:
            logger.debug("Satellite data error: %s", e)
        result = {"commodity": commodity, "source": "unavailable"}
        with self._lock:
            self.data_cache[commodity] = result
        return result


class ShippingDataAnalyzer:
    def __init__(self):
        self.data_cache = {}
        self._lock = threading.Lock()

    def get_shipping_index(self):
        now = _time.time()
        with self._lock:
            if "bdi" in self.data_cache and (now - self.data_cache["bdi"].get("_ts", 0)) < 3600:
                return self.data_cache["bdi"]
        try:
            url = "https://api.tradingeconomics.com/markets/commodities?c=guest:guest"
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                data = resp.json()
                for item in data:
                    if "baltic" in item.get("Name", "").lower():
                        result = {
                            "index": "BDI", "source": "tradingeconomics",
                            "status": "available", "value": item.get("Last", 0),
                            "change_pct": item.get("DailyChange", 0),
                        }
                        with self._lock:
                            self.data_cache["bdi"] = result
                        return result
        except requests.RequestException as e:
            logger.debug("Shipping data API request failed: %s", e)
        except Exception as e:
            logger.debug("Shipping data error: %s", e)
        result = {"index": "BDI", "source": "unavailable", "value": 0}
        with self._lock:
            self.data_cache["bdi"] = result
        return result


class CDSSpreadAnalyzer:
    def __init__(self):
        self.spread_history = {}
        self.cache_time = 0
        self._lock = threading.Lock()

    def get_spread(self, entity="default"):
        """Get CDS spread for an entity.
        
        Note: The MarkitWire API is not publicly available.
        For production use, consider using Bloomberg, Reuters, or Markit CDX data.
        """
        now = _time.time()
        with self._lock:
            if entity in self.spread_history and (now - self.cache_time) < 600:
                return self.spread_history[entity]
        
        # MarkitWire API is not publicly available
        logger.debug("CDS spread: API not available for %s (use Bloomberg/Reuters)", entity)
        result = {
            "entity": entity, "spread_bps": 0, "source": "unavailable",
            "date": datetime.now().strftime("%Y-%m-%d")
        }
        with self._lock:
            self.spread_history[entity] = result
        return result


class AlternativeDataAggregator:
    def __init__(self):
        self.twitter = TwitterSentiment()
        self.google = GoogleTrends()
        self.satellite = SatelliteDataAnalyzer()
        self.shipping = ShippingDataAnalyzer()
        self.cds = CDSSpreadAnalyzer()

    def get_all_sentiment(self, symbol):
        twitter = self.twitter.get_sentiment(symbol)
        google = self.google.get_trend(symbol)
        return {"twitter": twitter, "google_trends": google}

    def get_commodity_data(self, commodity):
        satellite = self.satellite.analyze_commodity(commodity)
        shipping = self.shipping.get_shipping_index()
        return {"satellite": satellite, "shipping": shipping}

    def get_risk_sentiment(self):
        cds = self.cds.get_spread("default")
        return {"cds_spread": cds}


_twitter = None
_google = None
_satellite = None
_shipping = None
_cds = None
_aggregator = None
_lock = threading.Lock()


def get_twitter_sentiment():
    global _twitter
    if _twitter is None:
        with _lock:
            if _twitter is None:
                _twitter = TwitterSentiment()
    return _twitter


def get_google_trends():
    global _google
    if _google is None:
        with _lock:
            if _google is None:
                _google = GoogleTrends()
    return _google


def get_satellite_analyzer():
    global _satellite
    if _satellite is None:
        with _lock:
            if _satellite is None:
                _satellite = SatelliteDataAnalyzer()
    return _satellite


def get_shipping_analyzer():
    global _shipping
    if _shipping is None:
        with _lock:
            if _shipping is None:
                _shipping = ShippingDataAnalyzer()
    return _shipping


def get_cds_analyzer():
    global _cds
    if _cds is None:
        with _lock:
            if _cds is None:
                _cds = CDSSpreadAnalyzer()
    return _cds


def get_alt_data_aggregator():
    global _aggregator
    if _aggregator is None:
        with _lock:
            if _aggregator is None:
                _aggregator = AlternativeDataAggregator()
    return _aggregator
