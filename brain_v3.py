import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time as _time
import threading
import logging
from parallel_executor import get_executor
from config import MAGIC_NUMBER, DATA_DIR
from metrics import PerformanceProfiler
from io_tasks import fetch_mt5_rates
from indicators import validate_tick_freshness, validate_rate_freshness, ema
from cache_layer import get_cache

logger = logging.getLogger(__name__)

# Cache
INDICATOR_CACHE_TTL = 3.0
PRICE_MOVE_THRESHOLD = 0.00005
SYMBOL_CACHE_TTL = 60.0

# Circuit breakers
MAX_CONSECUTIVE_LOSSES = 4
CIRCUIT_BREAK_TIMEOUT = 300
# Adaptive polling
VOLATILE_POLL_MS = 200
NORMAL_POLL_MS = 1000
QUIET_POLL_MS = 3000

# Pre-computed zones
ZONE_LOOKBACK = 100
ZONE_THRESHOLD_PCT = 0.08


class DataCache:
    def __init__(self):
        from collections import OrderedDict as OD
        self._cache = OD()
        self._timestamps = {}
        self._symbol_info_cache = {}
        self._symbol_info_time = {}
        self._lock = threading.Lock()
        self._executor = get_executor()
        self._multi_tier = None
        try:
            self._multi_tier = get_cache()
        except Exception:
            pass

    def get_rates(self, symbol, timeframe, count=300):
        key = f"{symbol}_{timeframe}_{count}"
        now = _time.time()
        ttl_map = {60: 1, 300: 3, 900: 10, 3600: 30, 14400: 60, 86400: 120}
        ttl = ttl_map.get(timeframe, INDICATOR_CACHE_TTL)
        with self._lock:
            if key in self._cache and (now - self._timestamps.get(key, 0)) < ttl:
                return self._cache[key]
        if self._multi_tier:
            try:
                cached = self._multi_tier.get(key)
                if cached is not None:
                    import pandas as pd
                    df = pd.DataFrame(cached)
                    with self._lock:
                        self._cache[key] = df
                        self._timestamps[key] = now
                        self._cache.move_to_end(key)
                        while len(self._cache) > 200:
                            oldest_key, _ = self._cache.popitem(last=False)
                            self._timestamps.pop(oldest_key, None)
                    return df
            except Exception:
                pass
        
        # Use thread pool for I/O-bound MT5 data fetching
        try:
            df = self._executor.submit_io_task(fetch_mt5_rates, symbol, timeframe, count)
        except Exception:
            # Fallback to direct call
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if rates is None:
                return None
            df = pd.DataFrame(rates)
        
        if df is None:
            return None
        with self._lock:
            self._cache[key] = df
            self._timestamps[key] = now
            self._cache.move_to_end(key)
            while len(self._cache) > 200:
                oldest_key, _ = self._cache.popitem(last=False)
                self._timestamps.pop(oldest_key, None)
        if self._multi_tier and df is not None:
            try:
                self._multi_tier.set_value(key, df.to_dict(orient="list"))
            except Exception:
                pass
        return df

    def get_multiple_rates(self, symbol_timeframes):
        """Fetch rates for multiple symbol/timeframe pairs in parallel."""
        tasks = []
        for symbol, timeframe, count in symbol_timeframes:
            tasks.append(((symbol, timeframe, count), {}))
        
        def _fetch(args):
            symbol, timeframe, count = args
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if rates is None:
                return None
            return pd.DataFrame(rates)
        
        results = [_fetch(t[0]) for t in tasks]
        
        output = {}
        now = _time.time()
        for i, (symbol, timeframe, count) in enumerate(symbol_timeframes):
            key = f"{symbol}_{timeframe}_{count}"
            if results[i] is not None:
                with self._lock:
                    self._cache[key] = results[i]
                    self._timestamps[key] = now
                    self._cache.move_to_end(key)
                    while len(self._cache) > 200:
                        oldest_key, _ = self._cache.popitem(last=False)
                        self._timestamps.pop(oldest_key, None)
                output[key] = results[i]
        return output

    def get_tick(self, symbol):
        key = f"tick_{symbol}"
        now = _time.time()
        with self._lock:
            if key in self._cache and (now - self._timestamps.get(key, 0)) < 0.1:
                return self._cache[key]
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            with self._lock:
                self._cache[key] = tick
                self._timestamps[key] = now
                self._cache.move_to_end(key)
                while len(self._cache) > 200:
                    oldest_key, _ = self._cache.popitem(last=False)
                    self._timestamps.pop(oldest_key, None)
        return tick

    def get_multiple_ticks(self, symbols):
        """Fetch ticks for multiple symbols in parallel."""
        def _fetch_tick(sym):
            return mt5.symbol_info_tick(sym)
        
        results = [_fetch_tick(sym) for sym in symbols]
        output = {}
        now = _time.time()
        for i, sym in enumerate(symbols):
            if results[i] is not None:
                key = f"tick_{sym}"
                with self._lock:
                    self._cache[key] = results[i]
                    self._timestamps[key] = now
                    self._cache.move_to_end(key)
                    while len(self._cache) > 200:
                        oldest_key, _ = self._cache.popitem(last=False)
                        self._timestamps.pop(oldest_key, None)
                output[sym] = results[i]
        return output

    def get_symbol_info(self, symbol):
        now = _time.time()
        with self._lock:
            if symbol in self._symbol_info_cache and (now - self._symbol_info_time.get(symbol, 0)) < SYMBOL_CACHE_TTL:
                return self._symbol_info_cache[symbol]
        info = mt5.symbol_info(symbol)
        if info:
            with self._lock:
                self._symbol_info_cache[symbol] = info
                self._symbol_info_time[symbol] = now
        return info

    def get_multiple_symbol_info(self, symbols):
        """Fetch symbol info for multiple symbols in parallel."""
        def _fetch_info(sym):
            return mt5.symbol_info(sym)
        
        results = [_fetch_info(sym) for sym in symbols]
        output = {}
        now = _time.time()
        for i, sym in enumerate(symbols):
            if results[i] is not None:
                with self._lock:
                    self._symbol_info_cache[sym] = results[i]
                    self._symbol_info_time[sym] = now
                output[sym] = results[i]
        return output

    def invalidate(self, pattern=None):
        with self._lock:
            if pattern:
                keys = [k for k in self._cache if pattern in k]
                for k in keys:
                    del self._cache[k]
                    self._timestamps.pop(k, None)
            else:
                self._cache.clear()
                self._timestamps.clear()


class PriceMovementDetector:
    def __init__(self):
        self._last_price = {}
        self._last_analysis_time = {}

    def has_moved(self, symbol, current_price):
        last = self._last_price.get(symbol, 0)
        if last == 0:
            self._last_price[symbol] = current_price
            return True
        move = abs(current_price - last)
        pct = move / last * 100 if last > 0 else 0
        if pct > PRICE_MOVE_THRESHOLD * 100:
            self._last_price[symbol] = current_price
            return True
        return False

    def get_poll_interval(self, symbol, atr, atr_ma):
        if atr_ma > 0 and atr > atr_ma * 1.5:
            return VOLATILE_POLL_MS / 1000.0
        elif atr_ma > 0 and atr < atr_ma * 0.5:
            return QUIET_POLL_MS / 1000.0
        return NORMAL_POLL_MS / 1000.0


class CircuitBreaker:
    def __init__(self):
        self.consecutive_losses = 0
        self.break_until = 0
        self.total_breaks = 0
        self._lock = threading.Lock()

    def record_loss(self):
        with self._lock:
            self.consecutive_losses += 1
            if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                self.break_until = _time.time() + CIRCUIT_BREAK_TIMEOUT
                self.total_breaks += 1
                self.consecutive_losses = 0
                return True
            return False

    def record_win(self):
        with self._lock:
            self.consecutive_losses = 0

    def is_open(self):
        with self._lock:
            if _time.time() < self.break_until:
                return False
            return True

    def remaining_break_time(self):
        with self._lock:
            remaining = self.break_until - _time.time()
            return max(0, remaining)


class IndicatorCache:
    def __init__(self):
        from collections import OrderedDict
        self._cache = OrderedDict()
        self._max_size = 50

    def compute_indicators(self, df):
        df_hash = hash(df['close'].values.tobytes())
        if df_hash in self._cache:
            return self._cache[df_hash]

        result = df.copy()
        c = result['close'].values
        h = result['high'].values
        l = result['low'].values
        v = result['tick_volume'].values

        result['EMA5'] = self._ema(c, 5)
        result['EMA8'] = self._ema(c, 8)
        result['EMA13'] = self._ema(c, 13)
        result['EMA21'] = self._ema(c, 21)
        result['EMA50'] = self._ema(c, 50)
        result['EMA200'] = self._ema(c, 200)
        result['EMA20'] = self._ema(c, 20)

        result['RSI'] = self._rsi(c, 14)

        result['BB_MA'] = result['EMA20']
        bb_std = pd.Series(c).rolling(20).std().values
        result['BB_UP'] = result['BB_MA'] + (bb_std * 2.0)
        result['BB_DN'] = result['BB_MA'] - (bb_std * 2.0)
        bb_range = result['BB_UP'] - result['BB_DN']
        bb_range = np.where(bb_range == 0, 1, bb_range)
        result['BB_WIDTH'] = bb_range / result['BB_MA'] * 100

        result['TR'] = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
        result.loc[result.index[0], 'TR'] = h[0] - l[0]
        result['ATR'] = pd.Series(result['TR']).rolling(14).mean().values
        result['ATR_MA'] = pd.Series(result['ATR']).rolling(30).mean().values

        result['HIGH_N'] = pd.Series(h).rolling(20).max().values
        result['LOW_N'] = pd.Series(l).rolling(20).min().values
        result['VOL_MA'] = pd.Series(v).rolling(20).mean().values

        ema12 = self._ema(c, 12)
        ema26 = self._ema(c, 26)
        result['MACD'] = ema12 - ema26
        result['MACD_SIGNAL'] = self._ema(result['MACD'], 9)
        result['MACD_HIST'] = result['MACD'] - result['MACD_SIGNAL']

        stoch_k = self._stochastic(h, l, c, 14)
        result['STOCH_K'] = stoch_k
        result['STOCH_D'] = pd.Series(stoch_k).rolling(3).mean().values

        result['MOM'] = c - np.roll(c, 10)
        result.loc[result.index[:10], 'MOM'] = 0
        result['ROC'] = pd.Series(c).pct_change(10).values * 100

        vw = v * c
        result['VWAP'] = pd.Series(vw).rolling(20).sum().values / np.maximum(pd.Series(v).rolling(20).sum().values, 1)

        obv_delta = np.sign(np.diff(c, prepend=c[0]))
        result['OBV'] = np.cumsum(obv_delta * v)

        self._cache[df_hash] = result
        self._cache.move_to_end(df_hash)
        if len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        return result

    @staticmethod
    def _ema(data, span):
        return ema(data, span)

    @staticmethod
    def _rsi(data, period):
        delta = np.diff(data, prepend=data[0])
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(gain).rolling(period).mean().values
        avg_loss = pd.Series(loss).rolling(period).mean().values
        avg_loss = np.where(np.isnan(avg_loss) | (avg_loss == 0), 1e-10, avg_loss)
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _stochastic(high, low, close, period):
        lowest = pd.Series(low).rolling(period).min().values
        highest = pd.Series(high).rolling(period).max().values
        rng = highest - lowest
        rng = np.where(rng == 0, 1, rng)
        return ((close - lowest) / rng) * 100


class PreComputedZones:
    def __init__(self):
        self._zones = {}
        self._zone_time = {}

    def compute(self, symbol, df):
        now = _time.time()
        if symbol in self._zones and (now - self._zone_time.get(symbol, 0)) < 10:
            return self._zones[symbol]

        lookback = min(ZONE_LOOKBACK, len(df))
        recent = df.tail(lookback)
        highs = recent['high'].values
        lows = recent['low'].values
        closes = recent['close'].values
        current = closes[-1]

        supports = []
        resistances = []

        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                resistances.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                supports.append(lows[i])

        supports = sorted(set(round(s, 5) for s in supports if s < current))
        resistances = sorted(set(round(r, 5) for r in resistances if r > current))

        zones = {
            "supports": supports[-3:] if supports else [],
            "resistances": resistances[:3] if resistances else [],
            "near_support": any((current - s) / current * 100 < ZONE_THRESHOLD_PCT for s in supports[-3:]) if supports else False,
            "near_resistance": any((r - current) / current * 100 < ZONE_THRESHOLD_PCT for r in resistances[:3]) if resistances else False,
        }

        self._zones[symbol] = zones
        self._zone_time[symbol] = now
        return zones


class MicroPriceAnalyzer:
    @staticmethod
    def analyze(tick, info):
        if not tick or not info:
            return {"imbalance": 0, "spread_ratio": 1.0, "mid_distance": 0}

        bid = tick.bid
        ask = tick.ask
        spread = ask - bid
        mid = (ask + bid) / 2
        spread_ratio = spread / info.point if info.point > 0 else 1
        mid_distance = (bid - mid) / info.point if info.point > 0 else 0

        if spread > 0:
            imbalance = (mid - bid) / spread * 2 - 1
        else:
            imbalance = 0

        return {
            "imbalance": imbalance,
            "spread_ratio": spread_ratio,
            "mid_distance": mid_distance,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread_pts": spread / info.point if info.point > 0 else 0,
        }


class PatternMatcher:
    @staticmethod
    def find_swings_fast(df, window=2):
        h = df['high'].values
        l = df['low'].values
        n = len(df)
        swing_highs = []
        swing_lows = []
        for i in range(window, n - window):
            if all(h[i] >= h[i-j] for j in range(1, window+1)) and all(h[i] >= h[i+j] for j in range(1, window+1)):
                swing_highs.append((i, h[i]))
            if all(l[i] <= l[i-j] for j in range(1, window+1)) and all(l[i] <= l[i+j] for j in range(1, window+1)):
                swing_lows.append((i, l[i]))
        return swing_highs, swing_lows

    @staticmethod
    def match_patterns(df):
        swing_highs, swing_lows = PatternMatcher.find_swings_fast(df)
        patterns_found = []
        if len(swing_highs) >= 2:
            h1, h2 = swing_highs[-2][1], swing_highs[-1][1]
            if abs(h1 - h2) / h1 * 100 < 0.1:
                patterns_found.append({"type": "double_top", "level": (h1 + h2) / 2, "reliability": 0.72})
        if len(swing_lows) >= 2:
            l1, l2 = swing_lows[-2][1], swing_lows[-1][1]
            if abs(l1 - l2) / l1 * 100 < 0.1:
                patterns_found.append({"type": "double_bottom", "level": (l1 + l2) / 2, "reliability": 0.72})
        if len(swing_highs) >= 3:
            h1, h2, h3 = swing_highs[-3][1], swing_highs[-2][1], swing_highs[-1][1]
            if h2 > h1 and h2 > h3 and abs(h1 - h3) / h1 * 100 < 0.15:
                patterns_found.append({"type": "head_shoulders", "neckline": min(h1, h3), "reliability": 0.68})
        if len(swing_lows) >= 3:
            l1, l2, l3 = swing_lows[-3][1], swing_lows[-2][1], swing_lows[-1][1]
            if l2 < l1 and l2 < l3 and abs(l1 - l3) / l1 * 100 < 0.15:
                patterns_found.append({"type": "inv_head_shoulders", "neckline": max(l1, l3), "reliability": 0.68})
        return patterns_found


class BrainV3:
    def __init__(self, brain_v2):
        self.v2 = brain_v2
        self.cache = DataCache()
        self.price_detector = PriceMovementDetector()
        self.circuit_breaker = CircuitBreaker()
        self.profiler = PerformanceProfiler()
        self.indicator_cache = IndicatorCache()
        self.pre_zones = PreComputedZones()
        self.micro_price = MicroPriceAnalyzer()
        self.pattern_matcher = PatternMatcher()
        self._analysis_count = 0
        self._trade_count = 0
        self._skip_count = 0

    def analyze(self, symbol, timeframe=mt5.TIMEFRAME_M1, params=None, df=None):
        self._analysis_count += 1
        self.profiler.start("total_analyze")

        # Circuit breaker
        if not self.circuit_breaker.is_open():
            remaining = self.circuit_breaker.remaining_break_time()
            if self._analysis_count % 30 == 0:
                logger.warning("Circuit breaker active. Resuming in %.0fs", remaining)
            return {"action": "hold", "confidence": 0, "reason": f"Circuit breaker ({remaining:.0f}s)"}

        # Get tick + check movement
        self.profiler.start("data_fetch")
        tick = self.cache.get_tick(symbol)
        if not tick:
            return {"action": "hold", "confidence": 0, "reason": "No tick data"}

        # Validate tick freshness
        tick_check = validate_tick_freshness(tick, symbol)
        if not tick_check["fresh"]:
            return {"action": "hold", "confidence": 0, "reason": f"market_closed: {tick_check['reason']}"}

        mid_price = (tick.bid + tick.ask) / 2
        if not self.price_detector.has_moved(symbol, mid_price):
            self._skip_count += 1
            return self.v2.last_analysis if hasattr(self.v2, 'last_analysis') and self.v2.last_analysis else {"action": "hold", "confidence": 0, "reason": "Price unchanged"}
        self.profiler.end("data_fetch")

        # Fetch data — skip if df provided from upstream
        self.profiler.start("rates_fetch")
        rates_df = df
        if rates_df is None:
            rates_df = self.cache.get_rates(symbol, timeframe, 300)
            if rates_df is None:
                return {"action": "hold", "confidence": 0, "reason": "No rate data"}

            # Validate rate freshness using cached data
            rate_check = validate_rate_freshness(rates_df.to_records(index=False).tolist(), timeframe)
            if not rate_check["fresh"]:
                return {"action": "hold", "confidence": 0, "reason": f"market_closed: {rate_check['reason']}"}

        self.profiler.end("rates_fetch")

        # Compute indicators (cached)
        self.profiler.start("indicators")
        df = self.indicator_cache.compute_indicators(rates_df)
        self.profiler.end("indicators")

        # Micro price
        self.profiler.start("micro_price")
        info = self.cache.get_symbol_info(symbol)
        micro = self.micro_price.analyze(tick, info)
        self.profiler.end("micro_price")

        # Pre-computed zones
        self.profiler.start("zones")
        zones = self.pre_zones.compute(symbol, df)
        self.profiler.end("zones")

        # Pattern matching
        self.profiler.start("patterns")
        patterns = self.pattern_matcher.match_patterns(df)
        self.profiler.end("patterns")

        # Adaptive poll interval
        last = df.iloc[-1]
        atr_val = last.get('ATR', 0)
        atr_ma_val = last.get('ATR_MA', 1)
        poll_interval = self.price_detector.get_poll_interval(symbol, atr_val, atr_ma_val)

        # Pass enriched data to V2
        self.profiler.start("v2_analyze")
        decision = self.v2.analyze(symbol, timeframe, params=params, df=rates_df)
        self.profiler.end("v2_analyze")

        # V3 enhancements
        self.profiler.start("v3_enhance")
        if decision.get("action") == "trade":
            direction = decision.get("direction", 0)
            adjs = decision.get('confidence_adjustments', {})

            # Zone filter (max ±10%)
            if direction == 1 and zones.get("near_resistance"):
                adjs['v3_zone'] = -0.10
                decision.setdefault("v3_notes", []).append("Near resistance - reduced confidence")
            elif direction == -1 and zones.get("near_support"):
                adjs['v3_zone'] = -0.10
                decision.setdefault("v3_notes", []).append("Near support - reduced confidence")
            else:
                adjs['v3_zone'] = 0.0

            # Micro price timing (max +10%)
            if micro["imbalance"] > 0.3 and direction == 1:
                adjs['v3_micro'] = 0.10
                decision.setdefault("v3_notes", []).append("Buy-side imbalance")
            elif micro["imbalance"] < -0.3 and direction == -1:
                adjs['v3_micro'] = 0.10
                decision.setdefault("v3_notes", []).append("Sell-side imbalance")
            else:
                adjs['v3_micro'] = 0.0

            # Spread filter (max -40%)
            if micro["spread_pts"] > 15:
                adjs['v3_spread'] = -0.40
                decision.setdefault("v3_notes", []).append(f"High spread ({micro['spread_pts']:.0f}pts)")
            else:
                adjs['v3_spread'] = 0.0

            # Pattern alignment (max +15%)
            pattern_adj = 0.0
            for p in patterns:
                if p["type"] in ("double_bottom", "inv_head_shoulders") and direction == 1:
                    pattern_adj += 0.15
                    decision.setdefault("v3_notes", []).append(f"Bullish pattern: {p['type']}")
                elif p["type"] in ("double_top", "head_shoulders") and direction == -1:
                    pattern_adj += 0.15
                    decision.setdefault("v3_notes", []).append(f"Bearish pattern: {p['type']}")
            adjs['v3_pattern'] = min(pattern_adj, 0.15)

            decision['confidence_adjustments'] = adjs
            # Final confidence clamp
            base = decision.get("confidence", 0)
            decision["confidence"] = max(0.1, min(base + sum(adjs.values()), 0.97))

            if decision.get("confidence", 0) < 0.55:
                decision["action"] = "hold"
                decision["reason"] = f"V3 confidence {decision['confidence']:.3f} below threshold"

        self.profiler.end("v3_enhance")

        # Attach V3 data
        decision["v3"] = {
            "micro": micro,
            "zones": {"supports": len(zones.get("supports", [])), "resistances": len(zones.get("resistances", [])), "near_support": zones.get("near_support", False), "near_resistance": zones.get("near_resistance", False)},
            "patterns": [{"type": p["type"], "reliability": p["reliability"]} for p in patterns],
            "poll_interval": round(poll_interval, 2),
            "skips": self._skip_count,
            "analyses": self._analysis_count,
        }

        self.profiler.end("total_analyze")

        # Print V3 summary on trade
        if decision.get("action") == "trade":
            v3 = decision.get("v3", {})
            perf = self.profiler.call_counts.get("total_analyze", {})
            total_ms = perf.get("total_ms", 0) / max(perf.get("count", 1), 1)
            logger.debug("Efficiency Report:")
            logger.debug("  Micro: Imbalance %.2f | Spread %.0fpts", micro['imbalance'], micro['spread_pts'])
            logger.debug("  Zones: %d supports, %d resistances", len(zones.get('supports', [])), len(zones.get('resistances', [])))
            logger.debug("  Patterns: %s", [p['type'] for p in patterns] if patterns else 'None')
            logger.debug("  Poll: %.1fs | Skips: %d | Analyses: %d", poll_interval, self._skip_count, self._analysis_count)
            logger.debug("  Avg Analysis: %.1fms", total_ms)
            notes = decision.get("v3_notes", [])
            if notes:
                logger.debug("  V3 Notes: %s", ' | '.join(notes))

        return decision

    def manage_positions(self, symbol):
        self.v2.manage_positions(symbol)

    def execute_decision(self, decision, symbol):
        if decision.get("action") != "trade":
            return False

        # Pre-execution circuit check
        if not self.circuit_breaker.is_open():
            logger.warning("Circuit breaker active, skipping execution")
            return False

        success = self.v2.execute_decision(decision, symbol)
        if success:
            self._trade_count += 1
        return success

    def record_trade_result(self, ticket, symbol, direction, lot, price, sl, tp, profit, strategy="combined"):
        self.v2.v1.record_trade_result(ticket, symbol, direction, lot, price, sl, tp, profit, strategy)
        if profit >= 0:
            self.circuit_breaker.record_win()
        else:
            self.circuit_breaker.record_loss()

    def get_dashboard_data(self):
        data = self.v2.get_dashboard_data()
        data["v3"] = {
            "analysis_count": self._analysis_count,
            "trade_count": self._trade_count,
            "skip_count": self._skip_count,
            "skip_rate": round(self._skip_count / max(self._analysis_count, 1) * 100, 1),
            "circuit_breaker_open": self.circuit_breaker.is_open(),
            "circuit_breaks": self.circuit_breaker.total_breaks,
            "consecutive_losses": self.circuit_breaker.consecutive_losses,
            "profiler": self.profiler.get_report(),
        }
        return data

    def print_status(self):
        self.v2.print_status()
        report = self.get_dashboard_data().get("v3", {})
        perf = report.get("profiler", {})
        logger.info("BRAIN V3 — EFFICIENCY STATUS")
        logger.info("  Analyses: %d | Trades: %d | Skips: %d (%s%%)", report.get('analysis_count', 0), report.get('trade_count', 0), report.get('skip_count', 0), report.get('skip_rate', 0))
        logger.info("  Circuit Breaker: %s (trips: %d, losses: %d)", 'OPEN' if report.get('circuit_breaker_open') else 'CLOSED', report.get('circuit_breaks', 0), report.get('consecutive_losses', 0))
        if perf:
            logger.info("  Performance Profile:")
            total = perf.get("total_analyze", {})
            logger.info("    Total analyze: avg %.1fms | max %.1fms", total.get('avg_ms', 0), total.get('max_ms', 0))
            for label in ["data_fetch", "rates_fetch", "indicators", "micro_price", "zones", "patterns", "v2_analyze", "v3_enhance"]:
                p = perf.get(label, {})
                if p:
                    logger.info("    %s: avg %.1fms | max %.1fms (%d calls)", label, p.get('avg_ms', 0), p.get('max_ms', 0), p.get('calls', 0))
