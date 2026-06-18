import numpy as np
import time as _time
import threading
import logging

logger = logging.getLogger(__name__)

# ==========================================
# AI PATTERN RECOGNITION
# ==========================================


class CandlestickAIClassifier:
    def __init__(self):
        self.pattern_db = {}
        self._lock = threading.Lock()

    def classify(self, df):
        if df is None or len(df) < 5:
            return []
        patterns = []
        o = df['open'].values
        h = df['high'].values
        l = df['low'].values
        c = df['close'].values
        last = len(df) - 1
        body = abs(c[last] - o[last])
        upper = h[last] - max(o[last], c[last])
        lower = min(o[last], c[last]) - l[last]
        total = h[last] - l[last]
        if total == 0:
            total = 0.0001
        prev_body = abs(c[last-1] - o[last-1])
        if body > prev_body * 1.5 and c[last] > o[last] and c[last-1] < o[last-1]:
            patterns.append({"pattern": "bullish_engulfing", "confidence": 0.8, "direction": 1})
        if body > prev_body * 1.5 and c[last] < o[last] and c[last-1] > o[last-1]:
            patterns.append({"pattern": "bearish_engulfing", "confidence": 0.8, "direction": -1})
        if lower > body * 2 and upper < body * 0.3:
            patterns.append({"pattern": "hammer", "confidence": 0.7, "direction": 1})
        if upper > body * 2 and lower < body * 0.3:
            patterns.append({"pattern": "shooting_star", "confidence": 0.7, "direction": -1})
        if body < total * 0.1:
            patterns.append({"pattern": "doji", "confidence": 0.5, "direction": 0})
        if last >= 2:
            if c[last-2] < o[last-2] and c[last-1] < o[last-1] and c[last] < o[last]:
                if c[last] < c[last-1] < c[last-2]:
                    patterns.append({"pattern": "three_black_crows", "confidence": 0.85, "direction": -1})
            if c[last-2] > o[last-2] and c[last-1] > o[last-1] and c[last] > o[last]:
                if c[last] > c[last-1] > c[last-2]:
                    patterns.append({"pattern": "three_white_soldiers", "confidence": 0.85, "direction": 1})
        return patterns


class ChartPatternNeuralNet:
    def __init__(self):
        self.weights = None
        self._lock = threading.Lock()

    def detect_double_top(self, df, lookback=50):
        if df is None or len(df) < lookback:
            return None
        highs = df['high'].tail(lookback).values
        peaks = []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                peaks.append((i, highs[i]))
        if len(peaks) >= 2:
            p1, p2 = peaks[-2], peaks[-1]
            if abs(p1[1] - p2[1]) / p1[1] < 0.02:
                return {"pattern": "double_top", "confidence": 0.75, "level": round((p1[1] + p2[1]) / 2, 5)}
        return None

    def detect_double_bottom(self, df, lookback=50):
        if df is None or len(df) < lookback:
            return None
        lows = df['low'].tail(lookback).values
        troughs = []
        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                troughs.append((i, lows[i]))
        if len(troughs) >= 2:
            t1, t2 = troughs[-2], troughs[-1]
            if abs(t1[1] - t2[1]) / t1[1] < 0.02:
                return {"pattern": "double_bottom", "confidence": 0.75, "level": round((t1[1] + t2[1]) / 2, 5)}
        return None

    def detect_head_shoulders(self, df, lookback=50):
        if df is None or len(df) < lookback:
            return None
        highs = df['high'].tail(lookback).values
        peaks = []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                peaks.append((i, highs[i]))
        if len(peaks) >= 3:
            p1, p2, p3 = peaks[-3], peaks[-2], peaks[-1]
            if p2[1] > p1[1] and p2[1] > p3[1] and abs(p1[1] - p3[1]) / p1[1] < 0.03:
                return {"pattern": "head_shoulders", "confidence": 0.8, "neckline": round(min(p1[1], p3[1]), 5)}
        return None

    def detect_all(self, df):
        patterns = []
        dt = self.detect_double_top(df)
        if dt:
            patterns.append(dt)
        db = self.detect_double_bottom(df)
        if db:
            patterns.append(db)
        hs = self.detect_head_shoulders(df)
        if hs:
            patterns.append(hs)
        return patterns


class SupportResistanceAI:
    def __init__(self):
        self._lock = threading.Lock()

    def find_levels(self, df, lookback=100):
        if df is None or len(df) < lookback:
            return {"supports": [], "resistances": []}
        recent = df.tail(lookback)
        highs = recent['high'].values
        lows = recent['low'].values
        closes = recent['close'].values
        current = closes[-1]
        supports = []
        resistances = []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                resistances.append({"price": round(highs[i], 5), "touches": 1, "strength": 0})
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                supports.append({"price": round(lows[i], 5), "touches": 1, "strength": 0})
        for s in supports:
            count = sum(1 for l in lows if abs(l - s["price"]) / s["price"] < 0.002)
            s["touches"] = count
            s["strength"] = min(count / 5, 1.0)
        for r in resistances:
            count = sum(1 for h in highs if abs(h - r["price"]) / r["price"] < 0.002)
            r["touches"] = count
            r["strength"] = min(count / 5, 1.0)
        supports.sort(key=lambda x: x["strength"], reverse=True)
        resistances.sort(key=lambda x: x["strength"], reverse=True)
        return {"supports": supports[:5], "resistances": resistances[:5]}


class TrendlineAutoDrawer:
    def __init__(self):
        self._lock = threading.Lock()

    def detect_trendlines(self, df, lookback=50):
        if df is None or len(df) < lookback:
            return []
        closes = df['close'].tail(lookback).values
        trendlines = []
        up_points = []
        down_points = []
        for i in range(len(closes)):
            if i >= 2 and closes[i] > closes[i-1] and closes[i] > closes[i-2]:
                up_points.append((i, closes[i]))
            if i >= 2 and closes[i] < closes[i-1] and closes[i] < closes[i-2]:
                down_points.append((i, closes[i]))
        if len(up_points) >= 2:
            x = np.array([p[0] for p in up_points[-5:]])
            y = np.array([p[1] for p in up_points[-5:]])
            if len(x) >= 2:
                slope, intercept = np.polyfit(x, y, 1)
                if slope > 0:
                    trendlines.append({"type": "uptrend", "slope": round(slope, 6), "intercept": round(intercept, 5), "points": len(up_points)})
        if len(down_points) >= 2:
            x = np.array([p[0] for p in down_points[-5:]])
            y = np.array([p[1] for p in down_points[-5:]])
            if len(x) >= 2:
                slope, intercept = np.polyfit(x, y, 1)
                if slope < 0:
                    trendlines.append({"type": "downtrend", "slope": round(slope, 6), "intercept": round(intercept, 5), "points": len(down_points)})
        return trendlines


class GapAnalyzer:
    def __init__(self):
        self._lock = threading.Lock()

    def detect_gaps(self, df, threshold_pct=0.1):
        if df is None or len(df) < 2:
            return []
        gaps = []
        o = df['open'].values
        c = df['close'].values
        h = df['high'].values
        l = df['low'].values
        for i in range(1, len(df)):
            gap = o[i] - c[i-1]
            gap_pct = abs(gap) / c[i-1] * 100 if c[i-1] != 0 else 0
            if gap_pct > threshold_pct:
                gap_type = "gap_up" if gap > 0 else "gap_down"
                gap_range = h[i] - l[i]
                filled = False
                if gap_type == "gap_up":
                    for j in range(i+1, min(i+20, len(df))):
                        if l[j] <= c[i-1]:
                            filled = True
                            break
                else:
                    for j in range(i+1, min(i+20, len(df))):
                        if h[j] >= c[i-1]:
                            filled = True
                            break
                gaps.append({
                    "bar": i, "type": gap_type, "gap_pct": round(gap_pct, 3),
                    "gap_price": round(c[i-1], 5), "filled": filled,
                })
        return gaps


_classifier = None
_chart_nn = None
_sr_ai = None
_trendline = None
_gap = None
_lock = threading.Lock()


def get_candlestick_classifier():
    global _classifier
    if _classifier is None:
        with _lock:
            if _classifier is None:
                _classifier = CandlestickAIClassifier()
    return _classifier


def get_chart_pattern_nn():
    global _chart_nn
    if _chart_nn is None:
        with _lock:
            if _chart_nn is None:
                _chart_nn = ChartPatternNeuralNet()
    return _chart_nn


def get_sr_ai():
    global _sr_ai
    if _sr_ai is None:
        with _lock:
            if _sr_ai is None:
                _sr_ai = SupportResistanceAI()
    return _sr_ai


def get_trendline_drawer():
    global _trendline
    if _trendline is None:
        with _lock:
            if _trendline is None:
                _trendline = TrendlineAutoDrawer()
    return _trendline


def get_gap_analyzer():
    global _gap
    if _gap is None:
        with _lock:
            if _gap is None:
                _gap = GapAnalyzer()
    return _gap
