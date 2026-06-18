import requests
import json
import numpy as np
import time as _time
import threading
import logging
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)

# ==========================================
# NEWS CALENDAR — Economic events
# ==========================================

NEWS_API_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NEWS_CACHE_TTL = 3600

HIGH_IMPACT_KEYWORDS = ["NFP", "CPI", "GDP", "FOMC", "ECB", "BOE", "BOJ", "Interest Rate", "Inflation", "Employment", "Unemployment", "PMI", "Retail Sales"]


class NewsCalendar:
    def __init__(self):
        self.events = []
        self.cache_time = 0
        self._lock = threading.Lock()

    def fetch_events(self):
        now = _time.time()
        with self._lock:
            if self.events and (now - self.cache_time) < NEWS_CACHE_TTL:
                return self.events
        try:
            resp = requests.get(NEWS_API_URL, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                events = []
                for e in data:
                    event = {
                        "title": e.get("title", ""),
                        "country": e.get("country", ""),
                        "date": e.get("date", ""),
                        "time": e.get("time", ""),
                        "impact": e.get("impact", ""),
                        "forecast": e.get("forecast", ""),
                        "previous": e.get("previous", ""),
                    }
                    is_high = any(kw.lower() in event["title"].lower() for kw in HIGH_IMPACT_KEYWORDS)
                    event["is_high_impact"] = is_high or event["impact"] == "High"
                    events.append(event)
                with self._lock:
                    self.events = events
                    self.cache_time = now
                return events
        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.debug("News fetch failed: %s", e)
        return self.events

    def get_upcoming(self, hours=4):
        events = self.fetch_events()
        now = datetime.now()
        upcoming = []
        for e in events:
            try:
                event_time = datetime.strptime(f"{e['date']} {e['time']}", "%Y-%m-%d %H:%M")
                diff = (event_time - now).total_seconds() / 3600
                if 0 <= diff <= hours:
                    e["minutes_away"] = int(diff * 60)
                    upcoming.append(e)
            except (ValueError, TypeError) as e:
                logger.debug("Event time parse failed: %s", e)
        return sorted(upcoming, key=lambda x: x.get("minutes_away", 999))

    def is_high_impact_soon(self, minutes=30):
        upcoming = self.get_upcoming(hours=1)
        for e in upcoming:
            if e.get("is_high_impact") and e.get("minutes_away", 999) <= minutes:
                return True, e
        return False, None

    def get_impact_modifier(self):
        is_high, event = self.is_high_impact_soon(minutes=30)
        if is_high:
            return 0.5, f"High impact: {event['title']} in {event.get('minutes_away', '?')}min"
        is_high_4h, event_4h = self.is_high_impact_soon(minutes=240)
        if is_high_4h:
            return 0.8, f"High impact coming: {event_4h['title']}"
        return 1.0, "No imminent news"


class SentimentFeed:
    def __init__(self):
        self.sentiment_data = {}
        self.cache_time = 0
        self._lock = threading.Lock()

    def fetch_sentiment(self, symbol="EURUSD"):
        now = _time.time()
        with self._lock:
            if self.sentiment_data and (now - self.cache_time) < 300:
                return self.sentiment_data
        try:
            pair = symbol[:3] + symbol[3:] if len(symbol) == 6 else symbol
            url = f"https://www.myfxbook.com/community/outlook/{pair}"
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200:
                text = resp.text.lower()
                if "bullish" in text:
                    sentiment = "bullish"
                elif "bearish" in text:
                    sentiment = "bearish"
                else:
                    sentiment = "neutral"
                with self._lock:
                    self.sentiment_data = {"sentiment": sentiment, "source": "myfxbook"}
                    self.cache_time = now
                return self.sentiment_data
        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.debug("Sentiment fetch failed: %s", e)
        return {"sentiment": "unknown", "source": "unavailable"}


class SpreadPredictor:
    def __init__(self):
        self.spread_history = {}
        self._lock = threading.Lock()

    def record_spread(self, symbol, spread):
        with self._lock:
            if symbol not in self.spread_history:
                self.spread_history[symbol] = deque(maxlen=1440)
            self.spread_history[symbol].append({"time": _time.time(), "spread": spread})

    def predict_spread(self, symbol):
        with self._lock:
            history = list(self.spread_history.get(symbol, []))
        if len(history) < 10:
            return {"predicted": 0, "current": 0, "trend": "stable"}
        spreads = [h["spread"] for h in history]
        current = spreads[-1]
        avg = np.mean(spreads[-60:]) if len(spreads) >= 60 else np.mean(spreads)
        recent_avg = np.mean(spreads[-5:])
        if recent_avg > avg * 1.3:
            trend = "widening"
        elif recent_avg < avg * 0.7:
            trend = "tightening"
        else:
            trend = "stable"
        return {"predicted": round(avg, 1), "current": round(current, 1), "trend": trend}


class SlippageModel:
    def __init__(self):
        self.slippage_history = deque(maxlen=500)
        self._lock = threading.Lock()

    def record(self, expected, actual, volume, symbol):
        slippage = abs(actual - expected)
        with self._lock:
            self.slippage_history.append({
                "time": _time.time(),
                "symbol": symbol,
                "expected": expected,
                "actual": actual,
                "slippage": slippage,
                "volume": volume,
            })

    def estimate_slippage(self, volume, symbol=None):
        with self._lock:
            history = list(self.slippage_history)
        if not history:
            return volume * 0.0001
        relevant = [h for h in history if h["symbol"] == symbol] if symbol else history
        if not relevant:
            relevant = history
        vol_slippage = [h["slippage"] for h in relevant if h["volume"] > 0]
        if not vol_slippage:
            return volume * 0.0001
        avg = np.mean(vol_slippage)
        vol_factor = np.log1p(volume) / np.log1p(1.0)
        return avg * vol_factor

    def get_stats(self):
        with self._lock:
            history = list(self.slippage_history)
        if not history:
            return {"avg": 0, "max": 0, "count": 0}
        slippages = [h["slippage"] for h in history]
        return {
            "avg": round(np.mean(slippages), 6),
            "max": round(max(slippages), 6),
            "count": len(slippages),
        }


_news = None
_sentiment = None
_spread_predictor = None
_slippage_model = None
_lock = threading.Lock()


def get_news_calendar():
    global _news
    if _news is None:
        with _lock:
            if _news is None:
                _news = NewsCalendar()
    return _news


def get_sentiment_feed():
    global _sentiment
    if _sentiment is None:
        with _lock:
            if _sentiment is None:
                _sentiment = SentimentFeed()
    return _sentiment


def get_spread_predictor():
    global _spread_predictor
    if _spread_predictor is None:
        with _lock:
            if _spread_predictor is None:
                _spread_predictor = SpreadPredictor()
    return _spread_predictor


def get_slippage_model():
    global _slippage_model
    if _slippage_model is None:
        with _lock:
            if _slippage_model is None:
                _slippage_model = SlippageModel()
    return _slippage_model
