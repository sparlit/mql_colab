import numpy as np
import time as _time
import threading
import logging
from collections import deque

logger = logging.getLogger(__name__)

# ==========================================
# MARKET MICROSTRUCTURE
# ==========================================


class LatencyArbitrage:
    def __init__(self):
        self.price_history = {}
        self._lock = threading.Lock()

    def record_price(self, symbol, venue, price, timestamp):
        with self._lock:
            if symbol not in self.price_history:
                self.price_history[symbol] = {}
            if venue not in self.price_history[symbol]:
                self.price_history[symbol][venue] = deque(maxlen=100)
            self.price_history[symbol][venue].append({"price": price, "time": timestamp})

    def detect_lead_lag(self, symbol, venue1, venue2, lag_bars=1):
        with self._lock:
            v1 = list(self.price_history.get(symbol, {}).get(venue1, []))
            v2 = list(self.price_history.get(symbol, {}).get(venue2, []))
        if len(v1) < 20 or len(v2) < 20:
            return {"lead_lag": False, "lead": venue1}
        p1 = [p["price"] for p in v1]
        p2 = [p["price"] for p in v2]
        min_len = min(len(p1), len(p2))
        p1 = p1[-min_len:]
        p2 = p2[-min_len:]
        corr12 = np.corrcoef(p1[:-lag_bars], p2[lag_bars:])[0, 1] if min_len > lag_bars else 0
        corr21 = np.corrcoef(p2[:-lag_bars], p1[lag_bars:])[0, 1] if min_len > lag_bars else 0
        if corr12 > corr21:
            return {"lead_lag": True, "lead": venue1, "lag": venue2, "correlation": round(corr12, 3)}
        else:
            return {"lead_lag": True, "lead": venue2, "lag": venue1, "correlation": round(corr21, 3)}


class MarketImpactModel:
    def __init__(self):
        self.impact_history = deque(maxlen=500)
        self._lock = threading.Lock()

    def estimate_impact(self, volume, adv, sigma):
        if adv <= 0:
            return 0
        participation = volume / adv
        temporary_impact = 0.1 * sigma * np.sqrt(participation)
        permanent_impact = 0.05 * sigma * np.power(participation, 0.6)
        total_impact = temporary_impact + permanent_impact
        return {
            "temporary": round(temporary_impact * 100, 4),
            "permanent": round(permanent_impact * 100, 4),
            "total_bps": round(total_impact * 10000, 2),
            "participation_rate": round(participation * 100, 2),
        }

    def record_actual_impact(self, expected, actual, volume):
        with self._lock:
            self.impact_history.append({
                "expected": expected, "actual": actual,
                "volume": volume, "slippage": abs(actual - expected),
            })

    def get_calibrated_impact(self, volume, adv):
        with self._lock:
            history = list(self.impact_history)
        if not history:
            return self.estimate_impact(volume, adv, 0.01)
        avg_slip = np.mean([h["slippage"] for h in history])
        avg_vol = np.mean([h["volume"] for h in history])
        vol_ratio = volume / max(avg_vol, 1)
        estimated = avg_slip * vol_ratio
        return {"total_bps": round(estimated * 10000, 2), "calibrated": True}


class QueuePositionEstimator:
    def __init__(self):
        self._lock = threading.Lock()

    def estimate(self, my_volume, total_bid_volume, total_ask_volume, side="buy"):
        if side == "buy":
            total = total_bid_volume
        else:
            total = total_ask_volume
        if total == 0:
            return {"position": 0, "probability_fill": 0.5}
        position = my_volume / total
        fill_prob = min(position * 1.5, 0.95)
        return {
            "position": round(position, 4),
            "queue_ratio": round(my_volume / max(total, 1), 4),
            "probability_fill": round(fill_prob, 3),
            "estimated_wait_bars": max(1, int((1 - fill_prob) * 10)),
        }


class AdverseSelectionDetector:
    def __init__(self):
        self.trade_history = deque(maxlen=1000)
        self._lock = threading.Lock()

    def record_trade(self, side, entry_price, next_price):
        pnl = (next_price - entry_price) if side == "buy" else (entry_price - next_price)
        with self._lock:
            self.trade_history.append({"side": side, "entry": entry_price, "next": next_price, "pnl": pnl})

    def detect(self, lookback=100):
        with self._lock:
            recent = list(self.trade_history)[-lookback:]
        if len(recent) < 10:
            return {"adverse_selection": 0, "informed_flow": "unknown"}
        buy_trades = [t for t in recent if t["side"] == "buy"]
        sell_trades = [t for t in recent if t["side"] == "sell"]
        buy_adverse = np.mean([t["pnl"] for t in buy_trades]) if buy_trades else 0
        sell_adverse = np.mean([t["pnl"] for t in sell_trades]) if sell_trades else 0
        if buy_adverse < -0.0001 and sell_adverse < -0.0001:
            return {"adverse_selection": 0.8, "informed_flow": "high", "buy_impact": round(buy_adverse, 6), "sell_impact": round(sell_adverse, 6)}
        elif buy_adverse > 0.0001 and sell_adverse > 0.0001:
            return {"adverse_selection": 0.2, "informed_flow": "low", "buy_impact": round(buy_adverse, 6), "sell_impact": round(sell_adverse, 6)}
        return {"adverse_selection": 0.5, "informed_flow": "moderate"}


class PriceDiscoveryScore:
    def __init__(self):
        self.venue_prices = {}
        self._lock = threading.Lock()

    def record(self, venue, price, timestamp):
        with self._lock:
            if venue not in self.venue_prices:
                self.venue_prices[venue] = deque(maxlen=100)
            self.venue_prices[venue].append({"price": price, "time": timestamp})

    def calculate_score(self):
        with self._lock:
            venues = list(self.venue_prices.keys())
        if len(venues) < 2:
            return {}
        scores = {}
        for venue in venues:
            with self._lock:
                prices = [p["price"] for p in self.venue_prices[venue]]
            if len(prices) < 10:
                scores[venue] = 0
                continue
            returns = np.diff(prices) / prices[:-1]
            variance = np.var(returns)
            mean_abs = np.mean(np.abs(returns))
            scores[venue] = round(mean_abs * 100, 4)
        total = sum(scores.values())
        if total > 0:
            scores = {k: round(v / total * 100, 1) for k, v in scores.items()}
        return scores


_latency_arb = None
_impact = None
_queue = None
_adverse = None
_price_disc = None
_lock = threading.Lock()


def get_latency_arb():
    global _latency_arb
    if _latency_arb is None:
        with _lock:
            if _latency_arb is None:
                _latency_arb = LatencyArbitrage()
    return _latency_arb


def get_impact_model():
    global _impact
    if _impact is None:
        with _lock:
            if _impact is None:
                _impact = MarketImpactModel()
    return _impact


def get_queue_estimator():
    global _queue
    if _queue is None:
        with _lock:
            if _queue is None:
                _queue = QueuePositionEstimator()
    return _queue


def get_adverse_detector():
    global _adverse
    if _adverse is None:
        with _lock:
            if _adverse is None:
                _adverse = AdverseSelectionDetector()
    return _adverse


def get_price_discovery():
    global _price_disc
    if _price_disc is None:
        with _lock:
            if _price_disc is None:
                _price_disc = PriceDiscoveryScore()
    return _price_disc
