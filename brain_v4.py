import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import json
import os
import time as _time
from collections import deque
import threading
import logging
from parallel_executor import get_executor
from config import DATA_DIR
from quant_models import MonteCarloSimulator

logger = logging.getLogger(__name__)

# Bayesian prior
BAYESIAN_PRIOR_WIN_RATE = 0.5
BAYESIAN_PRIOR_TRADES = 20

# Divergence
DIVERGENCE_PENALTY = 0.6
CONVERGENCE_BOOST = 1.15

# False breakout
FALSE_BREAKOUT_LOOKBACK = 10
FALSE_BREAKOUT_WICK_RATIO = 2.0
FALSE_BREAKOUT_VOL_DECLINE = 0.7

# Entry quality
ENTRY_QUALITY_DIMENSIONS = [
    "trend_alignment", "momentum_strength", "volatility_fit",
    "session_quality", "spread_quality", "structure_quality",
]

# Correlation
CORR_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD"]
CORR_LOOKBACK = 100
CORR_THRESHOLD = 0.7


class BayesianScorer:
    def __init__(self):
        self.strategy_priors = {}
        self._lock = threading.Lock()
        self._load_priors()

    def _load_priors(self):
        path = os.path.join(DATA_DIR, "bayesian_priors.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    self.strategy_priors = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.strategy_priors = {}
                logger.debug("Strategy priors load failed: %s", e)

    def _save_priors(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "bayesian_priors.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.strategy_priors, f)
        if os.path.exists(path):
            os.replace(tmp, path)
        else:
            os.rename(tmp, path)

    def update(self, strategy, won, direction=0):
        dir_key = "long" if direction >= 0 else "short"
        with self._lock:
            if strategy not in self.strategy_priors:
                self.strategy_priors[strategy] = {"wins": 0, "total": 0, "by_direction": {}}
            if dir_key not in self.strategy_priors[strategy].get("by_direction", {}):
                self.strategy_priors[strategy].setdefault("by_direction", {})[dir_key] = {"wins": 0, "total": 0}
            self.strategy_priors[strategy]["total"] += 1
            self.strategy_priors[strategy]["by_direction"][dir_key]["total"] += 1
            if won:
                self.strategy_priors[strategy]["wins"] += 1
                self.strategy_priors[strategy]["by_direction"][dir_key]["wins"] += 1
        self._save_priors()

    def get_probability(self, strategy):
        with self._lock:
            prior = self.strategy_priors.get(strategy, {"wins": 0, "total": 0})
            wins = prior["wins"]
            total = prior["total"]
        prob = (wins + BAYESIAN_PRIOR_WIN_RATE * BAYESIAN_PRIOR_TRADES) / (total + BAYESIAN_PRIOR_TRADES)
        return max(0.1, min(prob, 0.9))

    def get_direction_probability(self, strategy, signal_direction):
        dir_key = "long" if signal_direction >= 0 else "short"
        with self._lock:
            prior = self.strategy_priors.get(strategy, {})
            by_dir = prior.get("by_direction", {}).get(dir_key, {"wins": 0, "total": 0})
            wins = by_dir["wins"]
            total = by_dir["total"]
        if total < 5:
            return self.get_probability(strategy)
        prob = (wins + BAYESIAN_PRIOR_WIN_RATE * BAYESIAN_PRIOR_TRADES) / (total + BAYESIAN_PRIOR_TRADES)
        return max(0.1, min(prob, 0.9))

    def get_confidence_modifier(self, strategy, signal_direction):
        prob = self.get_direction_probability(strategy, signal_direction)
        if prob > 0.6:
            return 1.0 + (prob - 0.5) * 0.4
        elif prob < 0.4:
            return 0.6 + prob * 0.4
        return 1.0

    def get_all_probabilities(self):
        with self._lock:
            snapshot = dict(self.strategy_priors)
        return {s: self.get_probability(s) for s in snapshot}


class DivergenceDetector:
    @staticmethod
    def detect(signals):
        directions = []
        confidences = []
        for name, sig in signals.items():
            d = sig.get("direction", 0)
            c = sig.get("confidence", 0)
            if d != 0:
                directions.append(d)
                confidences.append(c)
        if len(directions) < 2:
            return {"divergent": False, "convergence_score": 1.0, "agreement": 1.0}
        buy_count = sum(1 for d in directions if d == 1)
        sell_count = sum(1 for d in directions if d == -1)
        total = len(directions)
        if buy_count == 0 or sell_count == 0:
            return {"divergent": False, "convergence_score": 1.0, "agreement": 1.0}
        minority = min(buy_count, sell_count)
        agreement = 1.0 - (minority / total * 2)
        is_divergent = minority > 0 and minority / total > 0.3
        return {
            "divergent": is_divergent,
            "convergence_score": agreement,
            "agreement": agreement,
            "buy_votes": buy_count,
            "sell_votes": sell_count,
        }


class FalseBreakoutFilter:
    @staticmethod
    def detect(df, direction):
        if len(df) < FALSE_BREAKOUT_LOOKBACK + 5:
            return False, 0
        recent = df.tail(FALSE_BREAKOUT_LOOKBACK + 2)
        last = recent.iloc[-1]
        prev = recent.iloc[-2]
        body = abs(last['close'] - last['open'])
        upper_wick = last['high'] - max(last['close'], last['open'])
        lower_wick = min(last['close'], last['open']) - last['low']
        total_range = last['high'] - last['low']
        if total_range == 0:
            return False, 0
        vol_recent = last.get('tick_volume', 1)
        vol_avg = recent['tick_volume'].mean() if 'tick_volume' in recent.columns else vol_recent
        vol_declining = vol_recent < vol_avg * FALSE_BREAKOUT_VOL_DECLINE
        if direction == 1:
            if last['close'] > prev['high']:
                if lower_wick > body * FALSE_BREAKOUT_WICK_RATIO:
                    return True, 0.7
                if vol_declining:
                    return True, 0.5
                if last['close'] < last['open']:
                    return True, 0.6
        elif direction == -1:
            if last['close'] < prev['low']:
                if upper_wick > body * FALSE_BREAKOUT_WICK_RATIO:
                    return True, 0.7
                if vol_declining:
                    return True, 0.5
                if last['close'] > last['open']:
                    return True, 0.6
        return False, 0


class EntryQualityScorer:
    @staticmethod
    def score(df, direction, regime, session, micro, zones, patterns):
        scores = {}
        last = df.iloc[-1]
        ema20 = last.get('EMA20', last['close'])
        ema50 = last.get('EMA50', last['close'])
        ema200 = last.get('EMA200', last['close'])
        if direction == 1:
            trend_aligned = ema20 > ema50 > ema200
        else:
            trend_aligned = ema20 < ema50 < ema200
        scores["trend_alignment"] = 1.0 if trend_aligned else 0.3
        macd_hist = last.get('MACD_HIST', 0)
        mom = last.get('MOM', 0)
        direction_sign = 1 if direction == 1 else -1
        scores["momentum_strength"] = min(0.5 + macd_hist * 1000 * direction_sign + mom * 100 * direction_sign, 1.0)
        atr = last.get('ATR', 0)
        atr_ma = last.get('ATR_MA', 1)
        if atr_ma > 0:
            vol_ratio = atr / atr_ma
            if 0.8 < vol_ratio < 1.5:
                scores["volatility_fit"] = 1.0
            elif vol_ratio < 0.5:
                scores["volatility_fit"] = 0.4
            else:
                scores["volatility_fit"] = 0.7
        else:
            scores["volatility_fit"] = 0.5
        session = session if isinstance(session, dict) else {}
        scores["session_quality"] = session.get("volume_mult", 1.0)
        spread_pts = micro.get("spread_pts", 5) if micro else 5
        scores["spread_quality"] = max(0.3, 1.0 - spread_pts / 30)
        near_sup = zones.get("near_support", False) if zones else False
        near_res = zones.get("near_resistance", False) if zones else False
        if direction == 1 and near_sup:
            scores["structure_quality"] = 1.0
        elif direction == -1 and near_res:
            scores["structure_quality"] = 1.0
        else:
            scores["structure_quality"] = 0.6
        weights = [0.25, 0.20, 0.15, 0.15, 0.10, 0.15]
        total = sum(scores[k] * w for k, w in zip(ENTRY_QUALITY_DIMENSIONS, weights))
        return {
            "total": round(total, 3),
            "dimensions": {k: round(v, 3) for k, v in scores.items()},
            "weakest": min(scores, key=scores.get),
            "strongest": max(scores, key=scores.get),
        }


class TimeBasedAnalyzer:
    def __init__(self):
        self.hourly_stats = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "hourly_stats.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    self.hourly_stats = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.hourly_stats = {}
                logger.debug("Hourly stats load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "hourly_stats.json")
        with open(path, "w") as f:
            json.dump(self.hourly_stats, f)

    def record(self, hour, won):
        h = str(hour)
        with self._lock:
            if h not in self.hourly_stats:
                self.hourly_stats[h] = {"wins": 0, "total": 0}
            self.hourly_stats[h]["total"] += 1
            if won:
                self.hourly_stats[h]["wins"] += 1
        self._save()

    def get_hour_win_rate(self, hour):
        h = str(hour)
        with self._lock:
            stats = self.hourly_stats.get(h, {"wins": 0, "total": 0})
            total = stats["total"]
            wins = stats["wins"]
        if total < 5:
            return 0.5
        return wins / total

    def get_hour_modifier(self, hour):
        wr = self.get_hour_win_rate(hour)
        if wr > 0.6:
            return 1.0 + (wr - 0.5) * 0.3
        elif wr < 0.4:
            return 0.7 + wr * 0.3
        return 1.0

    def get_best_hours(self, min_trades=5):
        good = []
        with self._lock:
            snapshot = dict(self.hourly_stats)
        for h, stats in snapshot.items():
            if stats["total"] >= min_trades:
                wr = stats["wins"] / stats["total"]
                if wr > 0.55:
                    good.append((int(h), wr))
        return sorted(good, key=lambda x: x[1], reverse=True)


class CorrelationMomentum:
    def __init__(self):
        self._cache = {}
        self._cache_time = 0
        self._executor = get_executor()

    def get_correlation_matrix(self):
        now = _time.time()
        if self._cache and (now - self._cache_time) < 120:
            return self._cache
        
        # Fetch price data in parallel
        from io_tasks import fetch_mt5_rates
        tasks = [(sym, mt5.TIMEFRAME_H1, CORR_LOOKBACK) for sym in CORR_SYMBOLS]
        results = [fetch_mt5_rates(sym, tf, cnt) for sym, tf, cnt in tasks]
        
        price_data = {}
        for i, sym in enumerate(CORR_SYMBOLS):
            if results[i] is not None and len(results[i]) > 20:
                price_data[sym] = results[i]['close'].pct_change().dropna().values[-CORR_LOOKBACK:]
        
        if len(price_data) < 3:
            return {}
        
        min_len = min(len(v) for v in price_data.values())
        aligned = {k: v[-min_len:] for k, v in price_data.items()}
        syms = list(aligned.keys())
        
        # Calculate correlations in parallel
        corr_tasks = []
        for i, s1 in enumerate(syms):
            for j, s2 in enumerate(syms):
                if i != j:
                    corr_tasks.append((aligned[s1], aligned[s2], s1, s2))
        
        if corr_tasks:
            from cpu_tasks import calculate_correlation_batch
            corr_results = self._executor.submit_cpu_tasks_batch(
                calculate_correlation_batch, corr_tasks
            )
            matrix = {}
            for result in corr_results:
                if result is not None:
                    matrix[result[0]] = result[1]
        else:
            matrix = {}
        
        self._cache = matrix
        self._cache_time = now
        return matrix

    def get_pair_correlation(self, sym1, sym2):
        matrix = self.get_correlation_matrix()
        key = f"{sym1}_{sym2}"
        return matrix.get(key, 0)

    def get_correlated_momentum(self, symbol):
        matrix = self.get_correlation_matrix()
        if not matrix:
            return {"score": 0, "aligned_pairs": 0, "total_pairs": 0}
        
        aligned = 0
        total = 0
        
        # Find correlated symbols
        correlated_syms = []
        for key, corr in matrix.items():
            parts = key.split("_")
            if len(parts) == 2 and symbol in parts:
                other = parts[0] if parts[1] == symbol else parts[1]
                if abs(corr) > CORR_THRESHOLD:
                    correlated_syms.append(other)
        
        if not correlated_syms:
            return {"score": 0, "aligned_pairs": 0, "total_pairs": 0}
        
        # Fetch momentum data in parallel
        from io_tasks import fetch_mt5_rates
        tasks = [(sym, mt5.TIMEFRAME_M5, 20) for sym in correlated_syms]
        results = [fetch_mt5_rates(sym, tf, cnt) for sym, tf, cnt in tasks]
        
        # Fetch symbol momentum
        sym_rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 20)
        sym_mom = 0
        if sym_rates and len(sym_rates) > 10:
            sym_df = pd.DataFrame(sym_rates)
            sym_mom = (sym_df['close'].iloc[-1] - sym_df['close'].iloc[-10]) / sym_df['close'].iloc[-10] * 100
        
        # Calculate alignment in parallel
        for i, other_sym in enumerate(correlated_syms):
            if results[i] is not None and len(results[i]) > 10:
                df = pd.DataFrame(results[i])
                mom = (df['close'].iloc[-1] - df['close'].iloc[-10]) / df['close'].iloc[-10] * 100
                if (mom > 0 and sym_mom > 0) or (mom < 0 and sym_mom < 0):
                    aligned += 1
                total += 1
        
        return {
            "score": aligned / max(total, 1),
            "aligned_pairs": aligned,
            "total_pairs": total,
        }


class AdaptiveThresholds:
    def __init__(self):
        self.recent_confidences = deque(maxlen=50)
        self.recent_outcomes = deque(maxlen=50)
        self.current_threshold = 0.55

    def record(self, confidence, won):
        self.recent_confidences.append(confidence)
        self.recent_outcomes.append(won)

    def get_optimal_threshold(self):
        if len(self.recent_confidences) < 10:
            return 0.55
        confs = list(self.recent_confidences)
        outcomes = list(self.recent_outcomes)
        bins = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.0)]
        best_threshold = 0.55
        best_score = 0
        for low, high in bins:
            trades_in_bin = [(c, o) for c, o in zip(confs, outcomes) if low <= c < high]
            if len(trades_in_bin) < 3:
                continue
            win_rate = sum(1 for _, o in trades_in_bin if o) / len(trades_in_bin)
            score = win_rate * len(trades_in_bin)
            if score > best_score:
                best_score = score
                best_threshold = low
        self.current_threshold = best_threshold
        return best_threshold


class BrainV4:
    def __init__(self, brain_v3):
        self.v3 = brain_v3
        self.bayesian = BayesianScorer()
        self.divergence = DivergenceDetector()
        self.false_breakout = FalseBreakoutFilter()
        self.entry_quality = EntryQualityScorer()
        self.time_analyzer = TimeBasedAnalyzer()
        self.corr_momentum = CorrelationMomentum()
        self.adaptive_thresholds = AdaptiveThresholds()
        self._monte_carlo = MonteCarloSimulator()

    def analyze(self, symbol, timeframe=mt5.TIMEFRAME_M1, params=None, df=None):
        decision = self.v3.analyze(symbol, timeframe, params=params, df=df)

        if decision.get("action") != "trade":
            return self._attach_v4_data(decision)

        direction = decision.get("direction", 0)
        signals = decision.get("signals", {})

        # Bayesian modifier
        bayesian_mod = 1.0
        for name, sig in signals.items():
            if sig.get("direction", 0) == direction and sig.get("confidence", 0) > 0.2:
                bmod = self.bayesian.get_confidence_modifier(name, direction)
                bayesian_mod *= bmod

        # Divergence check
        div_result = self.divergence.detect(signals)
        div_mod = DIVERGENCE_PENALTY if div_result["divergent"] else CONVERGENCE_BOOST

        # False breakout filter
        rates = df.tail(100) if df is not None and len(df) > 15 else (self.v3.cache.get_rates(symbol, timeframe, 100) if hasattr(self.v3, 'cache') else None)
        is_false_breakout = False
        fb_mod = 1.0
        if rates is not None and len(rates) > 15:
            is_false_breakout, fb_penalty = self.false_breakout.detect(rates, direction)
            if is_false_breakout:
                fb_mod = 1.0 - fb_penalty

        # Entry quality
        v3_data = decision.get("v3", {})
        micro = v3_data.get("micro", {})
        zones_data = v3_data.get("zones", {})
        patterns = v3_data.get("patterns", [])
        session_mod = self.v3.v2.session.get_session_modifier() if hasattr(self.v3.v2, 'session') else {}
        regime = self.v3.v2.regime.current_regime if hasattr(self.v3.v2, 'regime') else "unknown"
        rates_for_eq = df.tail(100) if df is not None and len(df) > 20 else (self.v3.cache.get_rates(symbol, timeframe, 100) if hasattr(self.v3, 'cache') else None)
        if rates_for_eq is not None:
            eq_result = self.entry_quality.score(rates_for_eq, direction, regime, session_mod, micro, zones_data, patterns)
        else:
            eq_result = {"total": 0.5, "dimensions": {}, "weakest": "unknown", "strongest": "unknown"}

        # Time-based
        current_hour = datetime.now(timezone.utc).hour
        time_mod = self.time_analyzer.get_hour_modifier(current_hour)

        # Correlation momentum
        corr_result = self.corr_momentum.get_correlated_momentum(symbol)
        corr_mod = 1.0 + (corr_result["score"] * 0.2)

        # Adaptive threshold
        threshold = self.adaptive_thresholds.get_optimal_threshold()

        # Combine (additive scoring - each factor has a max contribution weight)
        adjs = decision.get('confidence_adjustments', {})
        adjs['v4_bayesian'] = (bayesian_mod - 1.0) * 0.10      # max ±10%
        adjs['v4_divergence'] = (div_mod - 1.0) * 0.10          # max ±10%
        adjs['v4_false_breakout'] = (fb_mod - 1.0) * 0.10       # max -10%
        adjs['v4_entry_quality'] = (eq_result["total"] - 0.5) * 0.10  # max ±10%
        adjs['v4_time'] = (time_mod - 1.0) * 0.08               # max ±8%
        adjs['v4_correlation'] = (corr_mod - 1.0) * 0.08        # max ±8%
        decision['confidence_adjustments'] = adjs
        final_confidence = decision["confidence"] + sum(adjs.values())
        final_confidence = max(0.1, min(final_confidence, 0.98))

        # Adjust lot based on entry quality
        lot = decision.get("lot", 0.01)
        if eq_result["total"] > 0.7:
            lot *= 1.1
        elif eq_result["total"] < 0.4:
            lot *= 0.6
        info = self.v3.cache.get_symbol_info(symbol) if hasattr(self.v3, 'cache') else mt5.symbol_info(symbol)
        if info:
            lot = max(info.volume_min, min(lot, info.volume_max))
            lot = round(lot / info.volume_step) * info.volume_step
            lot = round(lot, 2)

        # Print V4 analysis
        logger.debug("Precision Report:")
        logger.debug("  Bayesian: %.3f | Divergence: %.3f (%s)", bayesian_mod, div_mod, 'DIVERGED' if div_result['divergent'] else 'converged')
        logger.debug("  False Breakout: %s (mod: %.3f)", 'YES' if is_false_breakout else 'NO', fb_mod)
        logger.debug("  Entry Quality: %.3f (weakest: %s, strongest: %s)", eq_result['total'], eq_result['weakest'], eq_result['strongest'])
        logger.debug("  Time: hour %d (mod: %.3f) | Corr: %.3f", current_hour, time_mod, corr_mod)
        logger.debug("  Threshold: %.3f | V3 Conf: %.3f -> V4 Conf: %.3f", threshold, decision['confidence'], final_confidence)

        # Monte Carlo simulation for strategy validation
        mc_result = {}
        try:
            wr = self.bayesian.get_probability("combined")
            avg_win = self.v3.v2.v1.stats.get_avg_win_loss()[0] if hasattr(self.v3, 'v2') and hasattr(self.v3.v2, 'v1') else 50
            avg_loss = self.v3.v2.v1.stats.get_avg_win_loss()[1] if hasattr(self.v3, 'v2') and hasattr(self.v3.v2, 'v1') else 30
            mc_result = self._monte_carlo.simulate_trades(wr, avg_win, avg_loss, n_trades=200, n_simulations=100)
        except Exception:
            pass

        # Override
        result = decision.copy()
        result["confidence"] = final_confidence
        result["lot"] = lot
        result["v4"] = {
            "bayesian_mod": round(bayesian_mod, 3),
            "divergence": div_result,
            "false_breakout": is_false_breakout,
            "entry_quality": eq_result,
            "time_mod": round(time_mod, 3),
            "corr_momentum": corr_result,
            "threshold": threshold,
            "monte_carlo": mc_result,
        }

        if final_confidence < threshold:
            result["action"] = "hold"
            result["reason"] = f"V4 confidence {final_confidence:.3f} below adaptive threshold {threshold:.3f}"

        return result

    def record_trade_outcome(self, strategy, confidence, won, hour, direction=0):
        self.bayesian.update(strategy, won, direction=direction)
        self.time_analyzer.record(hour, won)
        self.adaptive_thresholds.record(confidence, won)

    def manage_positions(self, symbol):
        self.v3.manage_positions(symbol)

    def execute_decision(self, decision, symbol):
        return self.v3.execute_decision(decision, symbol)

    def _attach_v4_data(self, decision):
        decision["v4"] = {
            "bayesian_probs": self.bayesian.get_all_probabilities(),
            "adaptive_threshold": self.adaptive_thresholds.current_threshold,
            "best_hours": self.time_analyzer.get_best_hours(),
        }
        return decision

    def get_dashboard_data(self):
        data = self.v3.get_dashboard_data()
        data["v4"] = {
            "bayesian_probs": self.bayesian.get_all_probabilities(),
            "adaptive_threshold": self.adaptive_thresholds.current_threshold,
            "best_hours": self.time_analyzer.get_best_hours(),
        }
        return data

    def print_status(self):
        self.v3.print_status()
        v4 = self.get_dashboard_data().get("v4", {})
        logger.info("BRAIN V4 — PRECISION STATUS")
        logger.info("  Adaptive Threshold: %.3f", v4.get('adaptive_threshold', 0.55))
        best = v4.get("best_hours", [])
        if best:
            logger.info("  Best Hours (UTC): %s", ', '.join(f'{h}:00 ({wr:.0%})' for h, wr in best[:5]))
        probs = v4.get("bayesian_probs", {})
        if probs:
            logger.info("  Strategy Probabilities:")
            for s, p in sorted(probs.items(), key=lambda x: x[1], reverse=True)[:6]:
                logger.info("    %s: %.1f%%", s, p * 100)
