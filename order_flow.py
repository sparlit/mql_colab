import mt5_mcp as mt5
import numpy as np
from datetime import datetime
import time as _time
import threading
import logging
from collections import deque

logger = logging.getLogger(__name__)

# ==========================================
# ORDER FLOW ANALYSIS — Tick-level analysis
# ==========================================

TICK_HISTORY_SIZE = 5000
IMBALANCE_THRESHOLD = 0.6
LARGE_ORDER_THRESHOLD = 3.0


class OrderFlowAnalyzer:
    def __init__(self):
        self.tick_history = deque(maxlen=TICK_HISTORY_SIZE)
        self.bid_volume = deque(maxlen=1000)
        self.ask_volume = deque(maxlen=1000)
        self.imbalance_history = deque(maxlen=500)
        self.large_orders = deque(maxlen=100)
        self._lock = threading.Lock()
        self._last_tick = {}

    def on_tick(self, symbol, tick=None):
        if tick is None:
            tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return
        now = _time.time()
        entry = {
            "symbol": symbol,
            "time": now,
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "volume": tick.volume,
            "flags": tick.flags,
        }
        with self._lock:
            self.tick_history.append(entry)
            prev = self._last_tick.get(symbol)
            if prev:
                bid_change = tick.bid - prev["bid"]
                ask_change = tick.ask - prev["ask"]
                if bid_change > 0:
                    self.bid_volume.append({"time": now, "volume": tick.volume, "direction": "buy"})
                elif bid_change < 0:
                    self.ask_volume.append({"time": now, "volume": tick.volume, "direction": "sell"})
            self._last_tick[symbol] = entry

    def get_imbalance(self, window=100):
        with self._lock:
            recent_bids = list(self.bid_volume)[-window:]
            recent_asks = list(self.ask_volume)[-window:]
        buy_vol = sum(t["volume"] for t in recent_bids)
        sell_vol = sum(t["volume"] for t in recent_asks)
        total = buy_vol + sell_vol
        if total == 0:
            return {"imbalance": 0, "buy_vol": 0, "sell_vol": 0, "ratio": 0.5}
        imbalance = (buy_vol - sell_vol) / total
        return {
            "imbalance": round(imbalance, 4),
            "buy_vol": buy_vol,
            "sell_vol": sell_vol,
            "ratio": round(buy_vol / max(sell_vol, 1), 2),
        }

    def detect_large_orders(self, threshold=LARGE_ORDER_THRESHOLD):
        with self._lock:
            recent = list(self.tick_history)[-100:]
        if len(recent) < 2:
            return []
        avg_vol = np.mean([t["volume"] for t in recent])
        large = []
        for tick in recent:
            if tick["volume"] > avg_vol * threshold:
                large.append({
                    "time": datetime.fromtimestamp(tick["time"]).strftime("%H:%M:%S"),
                    "bid": tick["bid"],
                    "ask": tick["ask"],
                    "volume": tick["volume"],
                    "avg_multiple": round(tick["volume"] / max(avg_vol, 1), 1),
                })
        return large

    def get_delta(self, window=50):
        with self._lock:
            recent = list(self.tick_history)[-window:]
        if len(recent) < 2:
            return {"delta": 0, "cumulative_delta": 0, "absorption": False}
        deltas = []
        for i in range(1, len(recent)):
            price_change = recent[i]["bid"] - recent[i-1]["bid"]
            if price_change > 0:
                deltas.append(recent[i]["volume"])
            elif price_change < 0:
                deltas.append(-recent[i]["volume"])
            else:
                deltas.append(0)
        delta = sum(deltas)
        cum_delta = sum(deltas[:len(deltas)]) if deltas else 0
        running = 0
        for d in deltas:
            running += d
        cum_delta = running
        absorption = abs(delta) > np.std(deltas) * 2 if len(deltas) > 5 else False
        return {
            "delta": delta,
            "cumulative_delta": cum_delta,
            "absorption": absorption,
        }

    def get_vwap_deviation(self):
        with self._lock:
            recent = list(self.tick_history)[-500:]
        if not recent:
            return {"vwap": 0, "deviation": 0, "upper_band": 0, "lower_band": 0}
        prices = [(t["bid"] + t["ask"]) / 2 for t in recent]
        volumes = [t["volume"] for t in recent]
        total_vol = sum(volumes)
        if total_vol == 0:
            return {"vwap": 0, "deviation": 0, "upper_band": 0, "lower_band": 0}
        vwap = sum(p * v for p, v in zip(prices, volumes)) / total_vol
        variance = sum((p - vwap) ** 2 * v for p, v in zip(prices, volumes)) / total_vol
        std = np.sqrt(variance)
        current_price = prices[-1]
        deviation = (current_price - vwap) / vwap * 100 if vwap > 0 else 0
        return {
            "vwap": round(vwap, 5),
            "deviation": round(deviation, 4),
            "upper_band": round(vwap + 2 * std, 5),
            "lower_band": round(vwap - 2 * std, 5),
        }

    def get_cvd(self, window=200):
        with self._lock:
            recent = list(self.tick_history)[-window:]
        if len(recent) < 2:
            return {"cvd": 0, "trend": "neutral"}
        cvd = 0
        for i in range(1, len(recent)):
            if recent[i]["bid"] > recent[i-1]["bid"]:
                cvd += recent[i]["volume"]
            elif recent[i]["bid"] < recent[i-1]["bid"]:
                cvd -= recent[i]["volume"]
        if cvd > 0:
            trend = "buying"
        elif cvd < 0:
            trend = "selling"
        else:
            trend = "neutral"
        return {"cvd": cvd, "trend": trend}

    def get_full_analysis(self, symbol):
        imbalance = self.get_imbalance()
        large = self.detect_large_orders()
        delta = self.get_delta()
        vwap = self.get_vwap_deviation()
        cvd = self.get_cvd()
        return {
            "symbol": symbol,
            "imbalance": imbalance,
            "large_orders": large[:5],
            "delta": delta,
            "vwap": vwap,
            "cvd": cvd,
            "tick_count": len(self.tick_history),
        }


class LiquidityMap:
    def __init__(self):
        self.liquidity_levels = {}
        self._lock = threading.Lock()

    def calculate_liquidity(self, symbol, df, lookback=100):
        if df is None or len(df) < lookback:
            return {}
        recent = df.tail(lookback)
        highs = recent['high'].values
        lows = recent['low'].values
        volumes = recent['tick_volume'].values if 'tick_volume' in recent.columns else np.ones(len(recent))
        current_price = df['close'].iloc[-1]
        levels = []
        price_range = np.linspace(np.min(lows), np.max(highs), 50)
        for price in price_range:
            touch_count = 0
            volume_at_level = 0
            for i in range(len(recent)):
                if abs(highs[i] - price) / price < 0.001 or abs(lows[i] - price) / price < 0.001:
                    touch_count += 1
                    volume_at_level += volumes[i]
            if touch_count >= 3:
                level_type = "resistance" if price > current_price else "support"
                strength = touch_count * (volume_at_level / np.max(volumes))
                levels.append({
                    "price": round(price, 5),
                    "type": level_type,
                    "touches": touch_count,
                    "volume": round(volume_at_level, 0),
                    "strength": round(strength, 2),
                })
        levels.sort(key=lambda x: x["strength"], reverse=True)
        with self._lock:
            self.liquidity_levels[symbol] = levels[:10]
        return levels[:10]

    def get_nearest_levels(self, symbol, direction, current_price=None):
        levels = self.liquidity_levels.get(symbol, [])
        if current_price is None:
            # Try to get current price from MT5
            import mt5_mcp as mt5
            tick = mt5.symbol_info_tick(symbol)
            current_price = tick.bid if tick else 0
        if direction == 1:
            supports = [l for l in levels if l["type"] == "support" and l["price"] < current_price]
            return sorted(supports, key=lambda x: x["price"], reverse=True)[:3]
        else:
            resistances = [l for l in levels if l["type"] == "resistance"]
            return sorted(resistances, key=lambda x: x["price"])[:3]


_order_flow = None
_liquidity = None
_lock = threading.Lock()


def get_order_flow():
    global _order_flow
    if _order_flow is None:
        with _lock:
            if _order_flow is None:
                _order_flow = OrderFlowAnalyzer()
    return _order_flow


def get_liquidity_map():
    global _liquidity
    if _liquidity is None:
        with _lock:
            if _liquidity is None:
                _liquidity = LiquidityMap()
    return _liquidity
