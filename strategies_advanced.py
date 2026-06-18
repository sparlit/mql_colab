import json
import os
import time as _time
import threading
import logging
from datetime import datetime
from config import DATA_DIR

logger = logging.getLogger(__name__)

# ==========================================
# ADVANCED TRADING STRATEGIES
# ==========================================


class MarketMaker:
    def __init__(self):
        self.spread_target = 2.0
        self.inventory = 0
        self.max_inventory = 5.0
        self.orders = []
        self._lock = threading.Lock()

    def calculate_quotes(self, symbol, mid_price, volatility):
        half_spread = self.spread_target * (1 + volatility)
        inventory_skew = self.inventory * 0.1
        bid = mid_price - half_spread - inventory_skew
        ask = mid_price + half_spread - inventory_skew
        return {"bid": round(bid, 5), "ask": round(ask, 5), "spread": round(ask - bid, 5)}

    def update_inventory(self, fill_side, volume):
        with self._lock:
            if fill_side == "buy":
                self.inventory += volume
            else:
                self.inventory -= volume

    def should_hedge(self):
        return abs(self.inventory) > self.max_inventory * 0.8


class ArbitrageEngine:
    def __init__(self):
        self.price_cache = {}
        self.opportunities = deque(maxlen=100)
        self._lock = threading.Lock()

    def check_triangular(self, symbol_data):
        opportunities = []
        try:
            if "EURUSD" in symbol_data and "GBPUSD" in symbol_data and "EURGBP" in symbol_data:
                eurusd = symbol_data["EURUSD"]
                gbpusd = symbol_data["GBPUSD"]
                eurgbp = symbol_data["EURGBP"]
                synthetic = eurusd["bid"] / gbpusd["ask"]
                actual = eurgbp["ask"]
                if abs(synthetic - actual) / actual > 0.001:
                    opportunities.append({
                        "type": "triangular",
                        "symbols": ["EURUSD", "GBPUSD", "EURGBP"],
                        "edge": round((synthetic - actual) / actual * 100, 4),
                    })
        except Exception as e:
            logger.debug("Arbitrage check failed: %s", e)
        return opportunities


class SeasonalPatterns:
    def __init__(self):
        self.patterns = self._load_patterns()

    def _load_patterns(self):
        path = os.path.join(DATA_DIR, "seasonal_patterns.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Seasonal patterns load failed: %s", e)
        return self._default_patterns()

    def _default_patterns(self):
        return {
            "EURUSD": {"monthly": {1: 0.3, 2: -0.2, 3: 0.1, 4: 0.4, 5: -0.1, 6: 0.2, 7: -0.3, 8: 0.1, 9: -0.2, 10: 0.3, 11: 0.1, 12: -0.1}},
            "XAUUSD": {"monthly": {1: 0.5, 2: 0.3, 3: -0.2, 4: 0.1, 5: -0.3, 6: 0.2, 7: 0.4, 8: 0.6, 9: 0.3, 10: -0.1, 11: 0.2, 12: 0.1}},
        }

    def get_seasonal_bias(self, symbol, month=None):
        if month is None:
            month = datetime.now().month
        sym_patterns = self.patterns.get(symbol, {})
        monthly = sym_patterns.get("monthly", {})
        bias = monthly.get(month, 0)
        return {"bias": bias, "direction": 1 if bias > 0 else -1 if bias < 0 else 0, "strength": abs(bias)}


class FibonacciCluster:
    @staticmethod
    def find_clusters(df, lookback=100):
        if df is None or len(df) < lookback:
            return []
        recent = df.tail(lookback)
        high = recent['high'].max()
        low = recent['low'].min()
        fib_levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
        levels = []
        for fib in fib_levels:
            price = low + (high - low) * fib
            levels.append({"level": fib, "price": round(price, 5)})
        clusters = []
        for i, l1 in enumerate(levels):
            for j, l2 in enumerate(levels):
                if i < j and abs(l1["price"] - l2["price"]) / l1["price"] < 0.002:
                    clusters.append({
                        "price": round((l1["price"] + l2["price"]) / 2, 5),
                        "levels": [l1["level"], l2["level"]],
                        "strength": 2,
                    })
        return clusters

    @staticmethod
    def get_nearest_fib(price, df, lookback=100):
        clusters = FibonacciCluster.find_clusters(df, lookback)
        if not clusters:
            return None
        distances = [(abs(c["price"] - price), c) for c in clusters]
        distances.sort(key=lambda x: x[0])
        return distances[0][1] if distances else None


class ElliottWaveCounter:
    @staticmethod
    def count_waves(df, lookback=50):
        if df is None or len(df) < lookback:
            return {"wave": 0, "direction": 0, "confidence": 0}
        closes = df['close'].tail(lookback).values
        peaks = []
        troughs = []
        for i in range(2, len(closes) - 2):
            if closes[i] > closes[i-1] and closes[i] > closes[i-2] and closes[i] > closes[i+1] and closes[i] > closes[i+2]:
                peaks.append((i, closes[i]))
            if closes[i] < closes[i-1] and closes[i] < closes[i-2] and closes[i] < closes[i+1] and closes[i] < closes[i+2]:
                troughs.append((i, closes[i]))
        swing_points = sorted(peaks + troughs, key=lambda x: x[0])
        if len(swing_points) < 3:
            return {"wave": 0, "direction": 0, "confidence": 0}
        direction = 1 if swing_points[-1][1] > swing_points[-2][1] else -1
        wave_count = len(swing_points)
        confidence = min(wave_count / 5, 1.0)
        return {"wave": wave_count, "direction": direction, "confidence": round(confidence, 2)}


class HarmonicScanner:
    PATTERNS = {
        "gartley": {"XA": 0.618, "AB": 0.382, "BC": 0.886, "XD": 0.786},
        "butterfly": {"XA": 0.786, "AB": 0.382, "BC": 0.886, "XD": 1.27},
        "bat": {"XA": 0.5, "AB": 0.382, "BC": 0.886, "XD": 0.886},
        "crab": {"XA": 0.382, "AB": 0.382, "BC": 0.886, "XD": 1.618},
    }

    @staticmethod
    def scan(df, lookback=50):
        if df is None or len(df) < lookback:
            return []
        closes = df['close'].tail(lookback).values
        highs = df['high'].tail(lookback).values
        lows = df['low'].tail(lookback).values
        swings = []
        for i in range(3, len(closes) - 1):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                swings.append(("H", highs[i]))
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                swings.append(("L", lows[i]))
        if len(swings) < 5:
            return []
        found = []
        for name, ratios in HarmonicScanner.PATTERNS.items():
            xa = abs(swings[1][1] - swings[0][1])
            ab = abs(swings[2][1] - swings[1][1])
            bc = abs(swings[3][1] - swings[2][1])
            xd = abs(swings[4][1] - swings[3][1])
            if xa > 0 and ab > 0 and bc > 0 and xd > 0:
                ab_ratio = ab / xa
                bc_ratio = bc / ab
                xd_ratio = xd / xa
                if abs(ab_ratio - ratios["AB"]) < 0.1 and abs(bc_ratio - ratios["BC"]) < 0.15 and abs(xd_ratio - ratios["XD"]) < 0.15:
                    found.append({"pattern": name, "quality": round(1 - abs(ab_ratio - ratios["AB"]), 2)})
        return found
