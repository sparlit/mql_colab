import mt5_mcp as mt5
import numpy as np
import time as _time
import threading
import logging
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)

# ==========================================
# INSTITUTIONAL-GRADE ANALYTICS
# ==========================================


class OrderBookHeatmap:
    """Order book depth visualization using tick data.
    
    Note: MT5 does not provide full DOM (Depth of Market) data via Python API.
    This implementation uses tick data to estimate order book depth.
    For full DOM data, use MT5 Terminal's built-in Depth of Market panel.
    """
    def __init__(self):
        self.snapshots = deque(maxlen=100)
        self._lock = threading.Lock()

    def capture_snapshot(self, symbol, levels=10):
        """Capture order book snapshot using tick data.
        
        Uses spread and volume to estimate depth at each level.
        """
        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if not tick or not info:
            return None
        point = info.point
        spread = (tick.ask - tick.bid) / point
        mid = (tick.bid + tick.ask) / 2
        bids = []
        asks = []
        # Estimate volumes based on spread and typical market depth
        base_volume = max(10, int(100 / max(spread, 1)))
        spread_factor = max(0.2, 1.0 - min(spread, 100) * 0.005)
        for i in range(levels):
            depth_decay = max(0.2, 1.0 - i * 0.08)
            bid_volume = max(1, int(base_volume * spread_factor * depth_decay))
            ask_volume = max(1, int(base_volume * spread_factor * depth_decay))
            bids.append({"price": round(mid - (i + 1) * point * 10, 5), "volume": bid_volume})
            asks.append({"price": round(mid + (i + 1) * point * 10, 5), "volume": ask_volume})
        snapshot = {"time": datetime.now().isoformat(), "bids": bids, "asks": asks, "mid": mid, "spread": spread}
        with self._lock:
            self.snapshots.append(snapshot)
        return snapshot

    def get_imbalance_ratio(self):
        with self._lock:
            if not self.snapshots:
                return 1.0
            latest = self.snapshots[-1]
        bid_vol = sum(b["volume"] for b in latest["bids"])
        ask_vol = sum(a["volume"] for a in latest["asks"])
        return bid_vol / max(ask_vol, 1)


class VolumeProfile:
    def __init__(self):
        self._lock = threading.Lock()

    def calculate(self, df, num_bins=50):
        if df is None or len(df) < 20:
            return {}
        prices = df['close'].values
        volumes = df['tick_volume'].values if 'tick_volume' in df.columns else np.ones(len(prices))
        price_min = prices.min()
        price_max = prices.max()
        bins = np.linspace(price_min, price_max, num_bins + 1)
        profile = {}
        for i in range(len(bins) - 1):
            mask = (prices >= bins[i]) & (prices < bins[i + 1])
            vol = volumes[mask].sum()
            profile[round((bins[i] + bins[i + 1]) / 2, 5)] = round(vol, 0)
        poc_price = max(profile, key=profile.get) if profile else 0
        total_vol = sum(profile.values())
        sorted_by_vol = sorted(profile.items(), key=lambda x: x[1], reverse=True)
        cumulative = 0
        value_area = []
        for price, vol in sorted_by_vol:
            cumulative += vol
            value_area.append(price)
            if cumulative >= total_vol * 0.7:
                break
        vah = max(value_area) if value_area else price_max
        val = min(value_area) if value_area else price_min
        return {
            "poc": poc_price,
            "vah": vah,
            "val": val,
            "profile": profile,
            "total_volume": total_vol,
        }


class DeltaDivergence:
    def __init__(self):
        self.price_history = deque(maxlen=500)
        self.delta_history = deque(maxlen=500)
        self._lock = threading.Lock()

    def record(self, price, delta):
        with self._lock:
            self.price_history.append(price)
            self.delta_history.append(delta)

    def detect_divergence(self, lookback=20):
        with self._lock:
            prices = list(self.price_history)[-lookback:]
            deltas = list(self.delta_history)[-lookback:]
        if len(prices) < lookback or len(deltas) < lookback:
            return {"divergence": False, "type": "none"}
        price_trend = np.polyfit(range(len(prices)), prices, 1)[0]
        delta_trend = np.polyfit(range(len(deltas)), deltas, 1)[0]
        if price_trend > 0 and delta_trend < 0:
            return {"divergence": True, "type": "bearish", "price_trend": "up", "delta_trend": "down"}
        elif price_trend < 0 and delta_trend > 0:
            return {"divergence": True, "type": "bullish", "price_trend": "down", "delta_trend": "up"}
        return {"divergence": False, "type": "none"}


class FootprintChart:
    def __init__(self):
        self.footprints = {}
        self._lock = threading.Lock()

    def record_tick(self, symbol, bid, ask, volume):
        price = round((bid + ask) / 2, 5)
        with self._lock:
            if symbol not in self.footprints:
                self.footprints[symbol] = {}
            if price not in self.footprints[symbol]:
                self.footprints[symbol][price] = {"bid_vol": 0, "ask_vol": 0, "count": 0}
            self.footprints[symbol][price]["bid_vol"] += volume if bid < ask else 0
            self.footprints[symbol][price]["ask_vol"] += volume if bid >= ask else 0
            self.footprints[symbol][price]["count"] += 1

    def get_imprint(self, symbol, levels=20):
        with self._lock:
            fp = self.footprints.get(symbol, {})
        if not fp:
            return []
        sorted_prices = sorted(fp.items(), key=lambda x: x[0], reverse=True)
        result = []
        for price, data in sorted_prices[:levels]:
            net = data["ask_vol"] - data["bid_vol"]
            result.append({
                "price": price,
                "bid_vol": data["bid_vol"],
                "ask_vol": data["ask_vol"],
                "net": net,
                "absorption": abs(net) > (data["bid_vol"] + data["ask_vol"]) * 0.7,
            })
        return result


class SmartMoneyIndex:
    def __init__(self):
        self.smi_history = deque(maxlen=200)
        self._lock = threading.Lock()

    def calculate(self, df):
        if df is None or len(df) < 20:
            return {"smi": 0, "signal": "neutral"}
        opens = df['open'].values
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        smi = 0
        for i in range(1, len(df)):
            body = closes[i] - opens[i]
            range_val = highs[i] - lows[i]
            if range_val > 0:
                candle_strength = body / range_val
            else:
                candle_strength = 0
            if closes[i] > opens[i]:
                smi += candle_strength
            else:
                smi -= candle_strength
        smi_normalized = smi / len(df) * 100
        if smi_normalized > 5:
            signal = "bullish"
        elif smi_normalized < -5:
            signal = "bearish"
        else:
            signal = "neutral"
        return {"smi": round(smi_normalized, 2), "signal": signal}


class COTReport:
    """Commitments of Traders (COT) report analyzer.
    
    Note: The CFTC website provides COT data in HTML format, not JSON.
    For production use, consider using:
    - CFTC's bulk download files (CSV format)
    - Quandl/NASDAQ Data Link COT datasets
    - Bloomberg/Reuters COT feeds
    """
    def __init__(self):
        self.data = {}
        self.cache_time = 0
        self._lock = threading.Lock()

    def get_latest(self, symbol="EURUSD"):
        """Get latest COT data for a currency pair.
        
        Returns:
            dict: COT data with net positioning, bias, and date
        """
        now = _time.time()
        with self._lock:
            if symbol in self.data and (now - self.cache_time) < 3600:
                return self.data[symbol]
        
        # CFTC website doesn't provide JSON API - need CSV parser
        # For now, return unavailable status
        logger.debug("COT data: API not available for %s (use CFTC bulk CSV)", symbol)
        result = {
            "symbol": symbol, "source": "unavailable", "nc_net": 0,
            "bias": "neutral", "date": datetime.now().strftime("%Y-%m-%d")
        }
        with self._lock:
            self.data[symbol] = result
        return result


_order_book = None
_volume_profile = None
_delta_div = None
_footprint = None
_smart_money = None
_cot = None
_lock = threading.Lock()


def get_order_book():
    global _order_book
    if _order_book is None:
        with _lock:
            if _order_book is None:
                _order_book = OrderBookHeatmap()
    return _order_book


def get_volume_profile():
    global _volume_profile
    if _volume_profile is None:
        with _lock:
            if _volume_profile is None:
                _volume_profile = VolumeProfile()
    return _volume_profile


def get_delta_divergence():
    global _delta_div
    if _delta_div is None:
        with _lock:
            if _delta_div is None:
                _delta_div = DeltaDivergence()
    return _delta_div


def get_footprint():
    global _footprint
    if _footprint is None:
        with _lock:
            if _footprint is None:
                _footprint = FootprintChart()
    return _footprint


def get_smart_money():
    global _smart_money
    if _smart_money is None:
        with _lock:
            if _smart_money is None:
                _smart_money = SmartMoneyIndex()
    return _smart_money


def get_cot_report():
    global _cot
    if _cot is None:
        with _lock:
            if _cot is None:
                _cot = COTReport()
    return _cot
