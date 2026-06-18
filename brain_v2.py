import MetaTrader5 as mt5
import pandas as pd
import numpy as np
# REMOVED: datetime, timezone
import time as _time
from brain_v1 import _send_order_with_fallback
from collections import deque, OrderedDict
import threading
import logging
from ai_client import get_ai_client
from config import MAGIC_BRAIN_V2, DATA_DIR, MAX_SPREAD_POINTS, get_magic_number, magic_belongs_to_brain, is_system_magic
from pattern_recognition import CandlestickAIClassifier

logger = logging.getLogger(__name__)

# Adaptive parameters
BASE_SL_ATR_MULT = 1.5
BASE_TP_ATR_MULT = 2.5
MIN_SL_ATR = 0.8
MAX_SL_ATR = 3.0

# Fractal
FRACTAL_WINDOW = 2

# Z-score
ZSCORE_PERIOD = 50
ZSCORE_ENTRY = 2.0
ZSCORE_EXIT = 0.5

# Cross-symbol
WATCH_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"]
MOMENTUM_LOOKBACK = 20


class RegimeDetector:
    def __init__(self):
        self.current_regime = "unknown"
        self.regime_confidence = 0
        self.regime_history = deque(maxlen=50)
        self._adx_cache = OrderedDict()
        self._adx_cache_times = {}
        self._adx_cache_lock = threading.Lock()

    def detect(self, df):
        now = _time.time()
        cache_key = hash(df['close'].values.tobytes())
        with self._adx_cache_lock:
            if cache_key in self._adx_cache and (now - self._adx_cache_times.get(cache_key, 0)) < 5:
                return self._adx_cache[cache_key]

        last = df.iloc[-1]

        # ADX
        plus_dm = df['high'].diff()
        minus_dm = -df['low'].diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        atr_14 = last.get('ATR', 1)
        if atr_14 == 0:
            atr_14 = 1
        plus_di_s = (plus_dm.rolling(14).mean() / atr_14) * 100
        minus_di_s = (minus_dm.rolling(14).mean() / atr_14) * 100
        di_sum_s = plus_di_s + minus_di_s
        dx_s = np.where(di_sum_s != 0, np.abs(plus_di_s - minus_di_s) / di_sum_s * 100, 0)
        adx_val = pd.Series(dx_s).rolling(14).mean().iloc[-1]
        adx = float(adx_val) if not pd.isna(adx_val) else 0

        # Price vs EMAs
        ema21 = last.get('EMA21', last['close'])
        ema50 = last.get('EMA50', last['close'])
        ema200 = last.get('EMA200', last['close'])
        close = last['close']

        # Bollinger squeeze
        bb_width = last.get('BB_WIDTH', 0)
        bb_width_avg = df['BB_WIDTH'].rolling(50).mean().iloc[-1] if 'BB_WIDTH' in df.columns else bb_width
        squeeze = bb_width < bb_width_avg * 0.7 if bb_width_avg > 0 else False

        # Range detection
        high_20 = df['high'].rolling(20).max().iloc[-1]
        low_20 = df['low'].rolling(20).min().iloc[-1]
        range_pct = (high_20 - low_20) / close * 100 if close > 0 else 0

        # Determine regime
        if adx > 25 and not squeeze:
            if ema21 > ema50 > ema200:
                regime = "strong_uptrend"
                conf = min(adx / 50, 1.0)
            elif ema21 < ema50 < ema200:
                regime = "strong_downtrend"
                conf = min(adx / 50, 1.0)
            else:
                regime = "choppy_trend"
                conf = 0.5
        elif squeeze or range_pct < 0.3:
            regime = "ranging"
            conf = 1.0 - min(adx / 30, 1.0)
        else:
            regime = "transitioning"
            conf = 0.4

        self.current_regime = regime
        self.regime_confidence = conf
        self.regime_history.append({"regime": regime, "conf": conf, "time": now})
        result = {"regime": regime, "confidence": conf, "adx": adx, "squeeze": squeeze, "range_pct": range_pct}
        with self._adx_cache_lock:
            self._adx_cache[cache_key] = result
            self._adx_cache_times[cache_key] = now
            while len(self._adx_cache) > 100:
                oldest_key, _ = self._adx_cache.popitem(last=False)
                self._adx_cache_times.pop(oldest_key, None)
        return result

    def get_regime_modifier(self, regime=None):
        modifiers = {
            "strong_uptrend": {"buy_mult": 1.3, "sell_mult": 0.5, "sl_mult": 1.0, "tp_mult": 1.4},
            "strong_downtrend": {"buy_mult": 0.5, "sell_mult": 1.3, "sl_mult": 1.0, "tp_mult": 1.4},
            "choppy_trend": {"buy_mult": 0.8, "sell_mult": 0.8, "sl_mult": 1.3, "tp_mult": 0.8},
            "ranging": {"buy_mult": 1.0, "sell_mult": 1.0, "sl_mult": 0.8, "tp_mult": 1.0},
            "transitioning": {"buy_mult": 0.6, "sell_mult": 0.6, "sl_mult": 1.5, "tp_mult": 0.7},
        }
        return modifiers.get(regime if regime is not None else self.current_regime, {"buy_mult": 1.0, "sell_mult": 1.0, "sl_mult": 1.0, "tp_mult": 1.0})


class CandlestickPatterns:
    @staticmethod
    def detect(df):
        patterns = []
        if len(df) < 5:
            return patterns
        o = df['open'].values
        h = df['high'].values
        l = df['low'].values
        c = df['close'].values
        last_idx = len(df) - 1

        body = abs(c[last_idx] - o[last_idx])
        upper_wick = h[last_idx] - max(o[last_idx], c[last_idx])
        lower_wick = min(o[last_idx], c[last_idx]) - l[last_idx]
        total_range = h[last_idx] - l[last_idx]
        if total_range == 0:
            total_range = 0.0001

        # Bullish engulfing
        prev_body = abs(c[last_idx - 1] - o[last_idx - 1])
        if (c[last_idx - 1] < o[last_idx - 1] and c[last_idx] > o[last_idx] and
                c[last_idx] > o[last_idx - 1] and o[last_idx] < c[last_idx - 1] and
                body > prev_body * 1.2):
            patterns.append(("bullish_engulfing", 0.75))

        # Bearish engulfing
        if (c[last_idx - 1] > o[last_idx - 1] and c[last_idx] < o[last_idx] and
                c[last_idx] < o[last_idx - 1] and o[last_idx] > c[last_idx - 1] and
                body > prev_body * 1.2):
            patterns.append(("bearish_engulfing", 0.75))

        # Pin bar / hammer (bullish)
        if lower_wick > body * 2.5 and upper_wick < body * 0.5 and body > 0:
            patterns.append(("hammer", 0.65))

        # Pin bar / shooting star (bearish)
        if upper_wick > body * 2.5 and lower_wick < body * 0.5 and body > 0:
            patterns.append(("shooting_star", 0.65))

        # Doji
        if body < total_range * 0.1:
            patterns.append(("doji", 0.4))

        # Three white soldiers
        if last_idx >= 2:
            if (c[last_idx - 2] > o[last_idx - 2] and c[last_idx - 1] > o[last_idx - 1] and c[last_idx] > o[last_idx] and
                    c[last_idx] > c[last_idx - 1] > c[last_idx - 2]):
                patterns.append(("three_white_soldiers", 0.7))

        # Three black crows
        if last_idx >= 2:
            if (c[last_idx - 2] < o[last_idx - 2] and c[last_idx - 1] < o[last_idx - 1] and c[last_idx] < o[last_idx] and
                    c[last_idx] < c[last_idx - 1] < c[last_idx - 2]):
                patterns.append(("three_black_crows", 0.7))

        # Morning star
        if last_idx >= 2:
            first_body = abs(c[last_idx - 2] - o[last_idx - 2])
            second_body = abs(c[last_idx - 1] - o[last_idx - 1])
            third_body = abs(c[last_idx] - o[last_idx])
            if (c[last_idx - 2] < o[last_idx - 2] and second_body < first_body * 0.3 and
                    c[last_idx] > o[last_idx] and third_body > first_body * 0.5 and
                    c[last_idx] > (o[last_idx - 2] + c[last_idx - 2]) / 2):
                patterns.append(("morning_star", 0.8))

        # Evening star
        if last_idx >= 2:
            first_body = abs(c[last_idx - 2] - o[last_idx - 2])
            second_body = abs(c[last_idx - 1] - o[last_idx - 1])
            third_body = abs(c[last_idx] - o[last_idx])
            if (c[last_idx - 2] > o[last_idx - 2] and second_body < first_body * 0.3 and
                    c[last_idx] < o[last_idx] and third_body > first_body * 0.5 and
                    c[last_idx] < (o[last_idx - 2] + c[last_idx - 2]) / 2):
                patterns.append(("evening_star", 0.8))

        # Inside bar
        if h[last_idx] <= h[last_idx - 1] and l[last_idx] >= l[last_idx - 1]:
            patterns.append(("inside_bar", 0.5))

        return patterns


class SessionFilter:
    @staticmethod
    def get_current_session():
        from indicators import get_current_session
        return get_current_session()

    @staticmethod
    def is_kill_zone():
        session = SessionFilter.get_current_session()
        return session in ("london", "overlap", "new_york")

    @staticmethod
    def get_session_modifier():
        session = SessionFilter.get_current_session()
        modifiers = {
            "asian": {"volume_mult": 0.6, "spread_mult": 1.3, "sl_mult": 1.0},
            "london": {"volume_mult": 1.2, "spread_mult": 0.8, "sl_mult": 0.9},
            "new_york": {"volume_mult": 1.1, "spread_mult": 0.9, "sl_mult": 0.9},
            "overlap": {"volume_mult": 1.4, "spread_mult": 0.7, "sl_mult": 0.8},
            "dead": {"volume_mult": 0.3, "spread_mult": 2.0, "sl_mult": 1.5},
        }
        return modifiers.get(session, {"volume_mult": 1.0, "spread_mult": 1.0, "sl_mult": 1.0})


class FractalEngine:
    @staticmethod
    def find_swings(df, window=FRACTAL_WINDOW):
        swings = {"highs": [], "lows": []}
        h = df['high'].values
        l = df['low'].values
        for i in range(window, len(df) - window):
            if all(h[i] >= h[i - j] for j in range(1, window + 1)) and all(h[i] >= h[i + j] for j in range(1, window + 1)):
                swings["highs"].append({"idx": i, "price": h[i]})
            if all(l[i] <= l[i - j] for j in range(1, window + 1)) and all(l[i] <= l[i + j] for j in range(1, window + 1)):
                swings["lows"].append({"idx": i, "price": l[i]})
        return swings

    @staticmethod
    def detect_pattern(df):
        swings = FractalEngine.find_swings(df)
        if len(swings["highs"]) < 2 or len(swings["lows"]) < 2:
            return "neutral", 0

        recent_highs = swings["highs"][-3:]
        recent_lows = swings["lows"][-3:]

        # Higher highs + higher lows = uptrend
        hh = all(recent_highs[i]["price"] >= recent_highs[i - 1]["price"] for i in range(1, len(recent_highs)))
        hl = all(recent_lows[i]["price"] >= recent_lows[i - 1]["price"] for i in range(1, len(recent_lows)))
        if hh and hl:
            return "uptrend", 0.8

        # Lower highs + lower lows = downtrend
        lh = all(recent_highs[i]["price"] <= recent_highs[i - 1]["price"] for i in range(1, len(recent_highs)))
        ll = all(recent_lows[i]["price"] <= recent_lows[i - 1]["price"] for i in range(1, len(recent_lows)))
        if lh and ll:
            return "downtrend", 0.8

        return "neutral", 0.3


class ZScoreEngine:
    @staticmethod
    def calculate(df, period=ZSCORE_PERIOD):
        if len(df) < period:
            return 0
        closes = df['close'].tail(period).values
        mean = np.mean(closes)
        std = np.std(closes)
        if std == 0:
            return 0
        z = (closes[-1] - mean) / std
        return z

    @staticmethod
    def signal(z_score):
        if z_score > ZSCORE_ENTRY:
            return -1, min(abs(z_score) / 4, 1.0)
        if z_score < -ZSCORE_ENTRY:
            return 1, min(abs(z_score) / 4, 1.0)
        if abs(z_score) < ZSCORE_EXIT:
            return 0, 0
        return 0, 0


class CrossSymbolMomentum:
    def __init__(self):
        self.momentum_cache = {}
        self._cache_time = 0

    def analyze(self, current_symbol):
        now = _time.time()
        if self.momentum_cache and (now - self._cache_time) < 30:
            return self.momentum_cache

        def _fetch_sym(sym):
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, MOMENTUM_LOOKBACK + 10)
            if rates is None:
                return sym, None
            df = pd.DataFrame(rates)
            if len(df) < MOMENTUM_LOOKBACK:
                return sym, None
            mom = (df['close'].iloc[-1] - df['close'].iloc[-MOMENTUM_LOOKBACK]) / df['close'].iloc[-MOMENTUM_LOOKBACK] * 100
            vol = df['tick_volume'].tail(5).mean() / df['tick_volume'].tail(20).mean() if df['tick_volume'].tail(20).mean() > 0 else 1
            return sym, {"momentum": mom, "volume_ratio": vol}

        momentums = {}
        for sym in WATCH_SYMBOLS:
            sym, result = _fetch_sym(sym)
            if result is not None:
                momentums[sym] = result

        if not momentums:
            return {}

        avg_mom = np.mean([v["momentum"] for v in momentums.values()])
        avg_vol = np.mean([v["volume_ratio"] for v in momentums.values()])

        current_mom = momentums.get(current_symbol, {}).get("momentum", 0)
        is_risk_on = avg_mom > 0

        result = {
            "average_momentum": avg_mom,
            "average_volume_ratio": avg_vol,
            "risk_on": is_risk_on,
            "current_symbol_momentum": current_mom,
            "symbol_vs_average": current_mom - avg_mom,
            "individual": momentums,
        }

        self.momentum_cache = result
        self._cache_time = now
        return result


class ExecutionMonitor:
    def __init__(self):
        self.spread_history = deque(maxlen=100)
        self.slippage_history = deque(maxlen=100)
        self.execution_times = deque(maxlen=100)

    def record_spread(self, symbol):
        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if tick and info:
            spread = (tick.ask - tick.bid) / info.point
            self.spread_history.append({"time": _time.time(), "spread": spread, "symbol": symbol})
            return spread
        return 0

    def record_execution(self, result, expected_price):
        if result and hasattr(result, 'price'):
            slippage = abs(result.price - expected_price)
            self.slippage_history.append({"time": _time.time(), "slippage": slippage, "ticket": result.order})

    def get_avg_spread(self, symbol, last_n=20):
        relevant = [s for s in self.spread_history if s["symbol"] == symbol][-last_n:]
        if not relevant:
            info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            if info and tick:
                return (tick.ask - tick.bid) / info.point
            return 0
        return np.mean([s["spread"] for s in relevant])

    def get_avg_slippage(self, last_n=20):
        relevant = list(self.slippage_history)[-last_n:]
        if not relevant:
            return 0
        return np.mean([s["slippage"] for s in relevant])

    def is_spread_too_high(self, symbol, max_spread=MAX_SPREAD_POINTS):
        current = self.record_spread(symbol)
        return current > max_spread


class AdaptiveSLTP:
    @staticmethod
    def calculate(df, direction, regime_info, session_mod, regime_mod, symbol):
        last = df.iloc[-1]
        atr = last.get('ATR', 1)
        if atr == 0:
            atr = 1
        info = mt5.symbol_info(symbol)
        point = info.point if info else 0.0001

        sl_mult = regime_mod["sl_mult"] * session_mod.get("sl_mult", 1.0)
        tp_mult = regime_mod["tp_mult"]

        if regime_info["regime"] in ("strong_uptrend", "strong_downtrend"):
            sl_atr = BASE_SL_ATR_MULT * sl_mult * 1.2
            tp_atr = BASE_TP_ATR_MULT * tp_mult * 1.3
        elif regime_info["regime"] == "ranging":
            sl_atr = BASE_SL_ATR_MULT * sl_mult * 0.8
            tp_atr = BASE_TP_ATR_MULT * tp_mult * 0.9
        else:
            sl_atr = BASE_SL_ATR_MULT * sl_mult
            tp_atr = BASE_TP_ATR_MULT * tp_mult

        sl_atr = max(MIN_SL_ATR, min(sl_atr, MAX_SL_ATR))

        tick = mt5.symbol_info_tick(symbol)
        if direction == 1:
            sl = tick.ask - (atr * sl_atr)
            tp = tick.ask + (atr * tp_atr)
        else:
            sl = tick.bid + (atr * sl_atr)
            tp = tick.bid - (atr * tp_atr)

        sl_points = round(atr * sl_atr / point)
        tp_points = round(atr * tp_atr / point)

        return sl, tp, sl_points, tp_points, sl_atr, tp_atr


class SignalDecayTracker:
    def __init__(self):
        self.signal_history = deque(maxlen=20)

    def record(self, signals, decision):
        self.signal_history.append({
            "time": _time.time(),
            "signals": {k: v.get("direction", 0) for k, v in signals.items()},
            "decision": decision,
        })

    def get_decay_score(self):
        if len(self.signal_history) < 3:
            return 1.0
        recent = list(self.signal_history)[-3:]
        consistency_scores = []
        for i in range(1, len(recent)):
            prev = recent[i - 1]["signals"]
            curr = recent[i]["signals"]
            matches = sum(1 for k in prev if k in curr and prev[k] == curr[k] and prev[k] != 0)
            total_active = sum(1 for v in prev.values() if v != 0)
            if total_active > 0:
                consistency_scores.append(matches / total_active)
        if not consistency_scores:
            return 1.0
        return np.mean(consistency_scores)


class BrainV2:
    def __init__(self, brain_v1):
        self.v1 = brain_v1
        self.regime = RegimeDetector()
        self.candles = CandlestickPatterns()
        self.session = SessionFilter()
        self.fractals = FractalEngine()
        self.zscore = ZScoreEngine()
        self.cross_momentum = CrossSymbolMomentum()
        self.execution = ExecutionMonitor()
        self.decay = SignalDecayTracker()
        self.last_analysis = {}
        self.ai = get_ai_client()
        self._ai_classifier = CandlestickAIClassifier()
        self._rates_cache = {}
        self._rates_cache_time = {}

    def analyze(self, symbol, timeframe=mt5.TIMEFRAME_M1, params=None, df=None):
        # Get V1 signals (V1 already has its own market state gate)
        v1_decision = self.v1.analyze(symbol, timeframe, params=params, df=df)

        # If V1 already blocked due to market state, propagate immediately
        if v1_decision.get("action") == "hold" and "market_closed" in v1_decision.get("reason", ""):
            return v1_decision

        # Get data for V2 analysis (reuse if recently fetched or use provided df)
        if df is None:
            now_ts = _time.time()
            cached_rates = self._rates_cache.get(symbol)
            cached_time = self._rates_cache_time.get(symbol, 0)
            if cached_rates is not None and (now_ts - cached_time) < 2:
                rates = cached_rates
            else:
                rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 300)
                if rates is not None:
                    self._rates_cache[symbol] = rates
                    self._rates_cache_time[symbol] = now_ts
            if rates is None:
                return v1_decision

            # Validate rate freshness — reject stale data
            from indicators import validate_rate_freshness
            rate_check = validate_rate_freshness(rates, timeframe)
            if not rate_check["fresh"]:
                logger.debug("V2 rate gate: %s — %s", symbol, rate_check["reason"])
                return {
                    "action": "hold",
                    "direction": 0,
                    "confidence": 0,
                    "reason": f"market_closed: {rate_check['reason']}",
                    "signals": {},
                    "active": [],
                }

            df = pd.DataFrame(rates)
            self.v1.analyzer._calc_indicators(df)

        # Regime
        regime_info = self.regime.detect(df)
        regime_mod = self.regime.get_regime_modifier()

        # AI regime enhancement
        try:
            if self.ai.is_available():
                market_data = {"close": float(df['close'].iloc[-1]), "atr": float(df.get('ATR', pd.Series([0])).iloc[-1]) if 'ATR' in df.columns else 0, "rsi": float(df.get('RSI', pd.Series([50])).iloc[-1]) if 'RSI' in df.columns else 50}
                ai_regime = self.ai.analyze_regime(market_data, {})
                if ai_regime and isinstance(ai_regime, dict):
                    regime_info["ai_regime"] = ai_regime.get("regime", regime_info.get("regime", "unknown"))
                    regime_info["ai_bias"] = ai_regime.get("bias", "neutral")
        except Exception as e:
            logger.debug("AI regime enhancement failed: %s", e)

        # Session
        session_name = self.session.get_current_session()
        session_mod = self.session.get_session_modifier()

        # Candlestick patterns
        candle_patterns = self.candles.detect(df)

        # AI-enhanced candlestick classification
        try:
            ai_patterns = self._ai_classifier.classify(df)
            for ap in ai_patterns:
                pname = ap.get("pattern", "")
                pconf = ap.get("confidence", 0)
                pdirec = ap.get("direction", 0)
                if pconf > 0.6:
                    exists = any(p[0] == pname for p in candle_patterns)
                    if not exists:
                        candle_patterns.append((pname, pconf))
        except Exception:
            pass

        # Fractal structure
        fractal_trend, fractal_conf = self.fractals.detect_pattern(df)

        # Z-score
        z_score = self.zscore.calculate(df)
        z_dir, z_conf = self.zscore.signal(z_score)

        # Cross-symbol momentum
        cross_mom = self.cross_momentum.analyze(symbol)

        # Execution quality
        spread = self.execution.record_spread(symbol)
        avg_spread = self.execution.get_avg_spread(symbol)
        spread_too_high = spread > MAX_SPREAD_POINTS

        # Signal decay
        decay_score = self.decay.get_decay_score()

        # === COMBINE V1 + V2 ===
        if v1_decision.get("action") != "trade":
            return self._build_result(v1_decision, regime_info, session_name, candle_patterns,
                                      fractal_trend, z_score, cross_mom, spread, decay_score)

        direction = v1_decision["direction"]
        base_confidence = v1_decision["confidence"]

        # Apply regime modifier
        if direction == 1:
            regime_boost = regime_mod["buy_mult"]
        else:
            regime_boost = regime_mod["sell_mult"]

        # Apply session modifier
        session_vol_mult = session_mod.get("volume_mult", 1.0)
        if session_name == "dead":
            session_boost = 0.4
        elif session_name == "overlap":
            session_boost = 1.3
        else:
            session_boost = 1.0

        # Candlestick boost
        candle_boost = 1.0
        candle_direction = 0
        for name, conf in candle_patterns:
            if "bullish" in name or name in ("hammer", "morning_star", "three_white_soldiers"):
                candle_direction += 1
                candle_boost += 0.15
            elif "bearish" in name or name in ("shooting_star", "evening_star", "three_black_crows"):
                candle_direction -= 1
                candle_boost += 0.15
        candle_boost = min(candle_boost, 1.5)
        candle_aligned = (candle_direction > 0 and direction == 1) or (candle_direction < 0 and direction == -1)
        if not candle_aligned and candle_direction != 0:
            candle_boost = 0.7

        # Fractal alignment
        fractal_boost = 1.0
        if (fractal_trend == "uptrend" and direction == 1) or (fractal_trend == "downtrend" and direction == -1):
            fractal_boost = 1.2
        elif (fractal_trend == "uptrend" and direction == -1) or (fractal_trend == "downtrend" and direction == 1):
            fractal_boost = 0.6

        # Z-score
        z_boost = 1.0
        if z_dir == direction:
            z_boost = 1.2
        elif z_dir != 0 and z_dir != direction:
            z_boost = 0.5

        # Cross-symbol momentum
        cross_boost = 1.0
        if cross_mom:
            risk_on = cross_mom.get("risk_on", True)
            sym_mom = cross_mom.get("symbol_vs_average", 0)
            if direction == 1 and risk_on and sym_mom > 0:
                cross_boost = 1.15
            elif direction == -1 and not risk_on and sym_mom < 0:
                cross_boost = 1.15
            elif (direction == 1 and not risk_on) or (direction == -1 and risk_on):
                cross_boost = 0.8

        # Spread penalty
        spread_penalty = 1.0
        if spread_too_high:
            spread_penalty = 0.5
        elif avg_spread > MAX_SPREAD_POINTS * 0.7:
            spread_penalty = 0.8

        # Decay penalty
        decay_penalty = 0.7 + (decay_score * 0.3)

        # FINAL CONFIDENCE (additive scoring - each factor has a max contribution weight)
        adjustments = decision.get('confidence_adjustments', {}) if isinstance(decision, dict) else {}
        adjustments['regime'] = (regime_boost - 1.0) * 0.15          # max ±15%
        adjustments['session'] = (session_boost - 1.0) * 0.10        # max ±10%
        adjustments['candle'] = (candle_boost - 1.0) * 0.10          # max ±10%
        adjustments['fractal'] = (fractal_boost - 1.0) * 0.08       # max ±8%
        adjustments['z_score'] = (z_boost - 1.0) * 0.08             # max ±8%
        adjustments['cross_symbol'] = (cross_boost - 1.0) * 0.05    # max ±5%
        adjustments['spread'] = (spread_penalty - 1.0) * 0.10       # max -10%
        adjustments['decay'] = (decay_penalty - 1.0) * 0.05         # max -5%
        decision['confidence_adjustments'] = adjustments
        final_confidence = base_confidence + sum(adjustments.values())
        final_confidence = max(0.1, min(final_confidence, 0.98))

        # Apply confidence to lot size
        lot = v1_decision.get("lot", 0.01)
        if final_confidence < 0.5:
            lot *= 0.5
        elif final_confidence > 0.8:
            lot *= 1.2
        info = mt5.symbol_info(symbol)
        if info:
            lot = max(info.volume_min, min(lot, info.volume_max))
            lot = round(lot / info.volume_step) * info.volume_step
            lot = round(lot, 2)

        # Dynamic SL/TP
        sl, tp, sl_pts, tp_pts, _, _ = AdaptiveSLTP.calculate(df, direction, regime_info, session_mod, regime_mod, symbol)

        # Print V2 analysis
        logger.debug("Analysis for %s", symbol)
        logger.debug("  Regime: %s (ADX: %.1f)", regime_info['regime'], regime_info['adx'])
        logger.debug("  Session: %s", session_name)
        logger.debug("  Candle Patterns: %s", [p[0] for p in candle_patterns] if candle_patterns else 'None')
        logger.debug("  Fractal: %s (%.2f)", fractal_trend, fractal_conf)
        logger.debug("  Z-Score: %.2f", z_score)
        logger.debug("  Cross-Symbol: Risk %s | Mom: %.3f%%", 'ON' if cross_mom.get('risk_on') else 'OFF', cross_mom.get('average_momentum', 0))
        logger.debug("  Spread: %.0fpts (avg: %.0f)", spread, avg_spread)
        logger.debug("  Decay Score: %.2f", decay_score)
        logger.debug("  V1 Conf: %.3f -> V2 Conf: %.3f", base_confidence, final_confidence)
        logger.debug("  Adjustments: R:%+.3f S:%+.3f C:%+.3f F:%+.3f Z:%+.3f X:%+.3f Sp:%+.3f D:%+.3f", adjustments.get('regime', 0), adjustments.get('session', 0), adjustments.get('candle', 0), adjustments.get('fractal', 0), adjustments.get('z_score', 0), adjustments.get('cross_symbol', 0), adjustments.get('spread', 0), adjustments.get('decay', 0))
        logger.debug("  DECISION: %s %s", 'TRADE' if final_confidence >= 0.55 else 'HOLD', v1_decision.get('direction_str', ''))
        logger.debug("  Lot: %s | SL: %dpts | TP: %dpts", lot, sl_pts, tp_pts)

        # Override V1 decision with V2 values
        result = v1_decision.copy()
        result["confidence"] = final_confidence
        result["confidence_adjustments"] = adjustments
        result["lot"] = lot
        result["sl"] = sl
        result["tp"] = tp
        result["sl_points"] = sl_pts
        result["tp_points"] = tp_pts
        result["v2_analysis"] = {
            "regime": regime_info["regime"],
            "session": session_name,
            "candle_patterns": [p[0] for p in candle_patterns],
            "fractal_trend": fractal_trend,
            "z_score": z_score,
            "cross_momentum": cross_mom.get("average_momentum", 0),
            "spread": spread,
            "decay_score": decay_score,
        }
        result["active"] = v1_decision.get("active", [])

        self.decay.record(v1_decision.get("signals", {}), result)
        self.last_analysis = result

        if final_confidence < 0.55:
            result["action"] = "hold"
            result["reason"] = f"V2 confidence {final_confidence:.3f} below threshold"

        return result

    def _build_result(self, v1_decision, regime_info, session_name, candle_patterns,
                      fractal_trend, z_score, cross_mom, spread, decay_score):
        result = v1_decision.copy()
        result["v2_analysis"] = {
            "regime": regime_info["regime"],
            "session": session_name,
            "candle_patterns": [p[0] for p in candle_patterns],
            "fractal_trend": fractal_trend,
            "z_score": z_score,
            "cross_momentum": cross_mom.get("average_momentum", 0),
            "spread": spread,
            "decay_score": decay_score,
        }
        return result

    def manage_positions(self, symbol):
        self.v1.manage_positions(symbol)

    def execute_decision(self, decision, symbol):
        if decision.get("action") != "trade":
            return False

        # Pre-execution checks
        if decision.get("v2_analysis", {}).get("spread", 0) > MAX_SPREAD_POINTS:
            logger.warning("Spread too high (%.0fpts), skipping", decision['v2_analysis']['spread'])
            return False

        # Full market state check
        from indicators import is_tradeable_now
        tradeable = is_tradeable_now(symbol)
        if not tradeable["can_trade"]:
            return False

        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return False
        # Validate tick freshness
        from indicators import validate_tick_freshness
        tick_check = validate_tick_freshness(tick, symbol)
        if not tick_check["fresh"]:
            return False
        info = mt5.symbol_info(symbol)
        direction = decision["direction"]
        if direction == 1:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid

        # Ensure magic number is set in decision
        decision["magic"] = decision.get("magic", get_magic_number("v2", "technical", symbol))
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": decision["lot"],
            "type": order_type,
            "price": price,
            "sl": decision["sl"],
            "tp": decision["tp"],
             "magic": decision["magic"],
            "comment": f"BV2:{decision['confidence']:.2f}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        exec_start = _time.time()
        result = _send_order_with_fallback(request)
        exec_time = (_time.time() - exec_start) * 1000

        if result is None:
            logger.warning("Trade Failed: order_send returned None")
            return False

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.warning("Trade Error: %s", result.comment)
            return False

        self.execution.record_execution(result, price)

        v2_info = decision.get("v2_analysis", {})
        logger.info("EXECUTED %s @ %s", decision['direction_str'], price)
        logger.info("  Lot: %s | SL: %dpts | TP: %dpts", decision['lot'], decision['sl_points'], decision['tp_points'])
        logger.info("  Confidence: %.3f | Exec: %.0fms", decision['confidence'], exec_time)
        logger.info("  Regime: %s | Session: %s", v2_info.get('regime', '?'), v2_info.get('session', '?'))
        logger.info("  Spread: %.0fpts | Decay: %.2f", v2_info.get('spread', 0), v2_info.get('decay_score', 1))

        self.v1.record_trade_result(result.order, symbol, direction, decision["lot"], price,
                                     decision["sl"], decision["tp"], 0)
        return True

    def get_dashboard_data(self):
        data = self.v1.get_dashboard_data()
        data["v2"] = {
            "regime": self.regime.current_regime,
            "regime_confidence": self.regime.regime_confidence,
            "session": self.session.get_current_session(),
            "is_kill_zone": self.session.is_kill_zone(),
            "spread": self.execution.get_avg_spread("EURUSD"),
            "slippage": self.execution.get_avg_slippage(),
            "decay_score": self.decay.get_decay_score(),
            "last_analysis": self.last_analysis.get("v2_analysis", {}),
        }
        return data

    def print_status(self):
        self.v1.print_status()
        v2 = self.get_dashboard_data().get("v2", {})
        logger.info("BRAIN V2 STATUS")
        logger.info("  Regime: %s (%.2f)", v2.get('regime', '?'), v2.get('regime_confidence', 0))
        logger.info("  Session: %s | Kill Zone: %s", v2.get('session', '?'), 'YES' if v2.get('is_kill_zone') else 'NO')
        logger.info("  Avg Spread: %.0fpts | Avg Slippage: %.4f", v2.get('spread', 0), v2.get('slippage', 0))
        logger.info("  Signal Decay: %.2f", v2.get('decay_score', 1))
