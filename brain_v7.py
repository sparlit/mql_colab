import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import json
import os
import time as _time
from collections import deque
import threading
import logging
from config import DATA_DIR

logger = logging.getLogger(__name__)

# Evolution
POPULATION_SIZE = 10
MUTATION_RATE = 0.15
GENERATION_THRESHOLD = 50
ELITE_FRACTION = 0.3

# Pattern memory
PATTERN_MEMORY_SIZE = 200
PATTERN_MATCH_THRESHOLD = 0.85
PATTERN_LOOKBACK = 50

# Adaptation
ADAPTATION_WINDOW = 30
PLATEAU_THRESHOLD = 0.02
PLATEAU_WINDOW = 20


class StrategyGenome:
    def __init__(self, params=None):
        if params:
            self.params = params.copy()
        else:
            self.params = {
                "ema_fast": np.random.choice([3, 5, 8, 10]),
                "ema_slow": np.random.choice([10, 13, 15, 21]),
                "rsi_period": np.random.choice([10, 14, 21]),
                "rsi_oversold": np.random.choice([25, 28, 30, 32, 35]),
                "rsi_overbought": np.random.choice([65, 68, 70, 72, 75]),
                "bb_period": np.random.choice([15, 20, 25]),
                "bb_std": np.random.choice([1.5, 2.0, 2.5]),
                "atr_period": np.random.choice([10, 14, 20]),
                "sl_atr_mult": round(np.random.uniform(0.8, 2.5), 2),
                "tp_atr_mult": round(np.random.uniform(1.5, 4.0), 2),
                "trail_atr_mult": round(np.random.uniform(0.5, 1.5), 2),
                "min_confidence": round(np.random.uniform(0.45, 0.65), 2),
                "vol_filter_mult": round(np.random.uniform(0.8, 1.5), 2),
            }
        self.fitness = 0
        self.trades = 0
        self.wins = 0

    def mutate(self, rate=MUTATION_RATE):
        mutated = self.params.copy()
        for key in mutated:
            if np.random.random() < rate:
                val = mutated[key]
                if isinstance(val, int):
                    mutated[key] = max(1, val + np.random.choice([-2, -1, 1, 2]))
                elif isinstance(val, float):
                    mutated[key] = round(val * (1 + np.random.uniform(-0.3, 0.3)), 2)
        return StrategyGenome(mutated)

    def crossover(self, other):
        child_params = {}
        for key in self.params:
            if np.random.random() < 0.5:
                child_params[key] = self.params[key]
            else:
                child_params[key] = other.params[key]
        return StrategyGenome(child_params)

    def to_dict(self):
        return {"params": self.params, "fitness": self.fitness, "trades": self.trades, "wins": self.wins}

    @classmethod
    def from_dict(cls, data):
        g = cls(data.get("params", {}))
        g.fitness = data.get("fitness", 0)
        g.trades = data.get("trades", 0)
        g.wins = data.get("wins", 0)
        return g


class EvolutionEngine:
    def __init__(self):
        self.population = []
        self.generation = 0
        self.best_genome = None
        self.history = deque(maxlen=50)
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "evolution.json")
        backup_path = path + ".bak"
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.generation = data.get("generation", 0)
                    self.population = [StrategyGenome.from_dict(g) for g in data.get("population", [])]
                    self.best_genome = StrategyGenome.from_dict(data["best"]) if "best" in data else None
                if os.path.exists(backup_path):
                    try:
                        os.remove(backup_path)
                    except OSError:
                        pass
            except (json.JSONDecodeError, OSError, KeyError) as e:
                logger.debug("Evolution data load failed: %s", e)
                if os.path.exists(backup_path):
                    try:
                        with open(backup_path, "r") as f:
                            data = json.load(f)
                            self.generation = data.get("generation", 0)
                            self.population = [StrategyGenome.from_dict(g) for g in data.get("population", [])]
                            self.best_genome = StrategyGenome.from_dict(data["best"]) if "best" in data else None
                    except (json.JSONDecodeError, OSError, KeyError):
                        logger.debug("Backup evolution data also failed")
        if not self.population:
            self.population = [StrategyGenome() for _ in range(POPULATION_SIZE)]

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "evolution.json")
        backup_path = path + ".bak"
        if os.path.exists(path):
            try:
                os.replace(path, backup_path)
            except OSError:
                pass
        with open(path, "w") as f:
            json.dump({
                "generation": self.generation,
                "population": [g.to_dict() for g in self.population[:POPULATION_SIZE]],
                "best": self.best_genome.to_dict() if self.best_genome else None,
            }, f)

    def record_trade(self, genome_idx, won):
        with self._lock:
            if 0 <= genome_idx < len(self.population):
                g = self.population[genome_idx]
                g.trades += 1
                if won:
                    g.wins += 1
                if g.trades >= 5:
                    g.fitness = g.wins / g.trades

    def evolve(self):
        with self._lock:
            self.generation += 1
            self.population.sort(key=lambda g: g.fitness, reverse=True)
            if self.best_genome is None or (self.population[0].fitness > self.best_genome.fitness):
                self.best_genome = StrategyGenome(self.population[0].params)
                self.best_genome.fitness = self.population[0].fitness

            elite_count = max(2, int(POPULATION_SIZE * ELITE_FRACTION))
            new_pop = [StrategyGenome(g.params) for g in self.population[:elite_count]]

            while len(new_pop) < POPULATION_SIZE:
                if np.random.random() < 0.7:
                    p1 = self.population[np.random.randint(0, elite_count)]
                    p2 = self.population[np.random.randint(0, len(self.population))]
                    child = p1.crossover(p2)
                    child = child.mutate()
                    new_pop.append(child)
                else:
                    new_pop.append(StrategyGenome().mutate(rate=0.3))

            self.population = new_pop
            self.history.append({
                "generation": self.generation,
                "best_fitness": self.population[0].fitness,
                "avg_fitness": np.mean([g.fitness for g in self.population]),
            })
        self._save()

    def get_best_params(self, adaptations=None):
        with self._lock:
            if self.best_genome:
                params = self.best_genome.params.copy()
                if adaptations:
                    for suggestion in adaptations:
                        param = suggestion.get("param")
                        action = suggestion.get("action")
                        if param in params:
                            if param == "min_confidence":
                                if action == "increase":
                                    params[param] = min(0.95, params[param] + 0.02)
                                elif action == "decrease":
                                    params[param] = max(0.1, params[param] - 0.02)
                            elif param == "sl_atr_mult":
                                if action == "increase":
                                    params[param] = min(5.0, params[param] + 0.1)
                                elif action == "decrease":
                                    params[param] = max(0.3, params[param] - 0.1)
                            elif param == "tp_atr_mult":
                                if action == "increase":
                                    params[param] = min(6.0, params[param] + 0.1)
                                elif action == "decrease":
                                    params[param] = max(0.5, params[param] - 0.1)
                            elif param == "mutation_rate":
                                pass
                return params
        return StrategyGenome().params

    def get_current_active(self):
        with self._lock:
            self.population.sort(key=lambda g: g.fitness, reverse=True)
            if self.population:
                return self.population[0]
        return StrategyGenome()


class PatternMemory:
    def __init__(self):
        self.patterns = deque(maxlen=PATTERN_MEMORY_SIZE)
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "pattern_memory.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.patterns = deque(data.get("patterns", [])[-PATTERN_MEMORY_SIZE:], maxlen=PATTERN_MEMORY_SIZE)
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Pattern memory load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "pattern_memory.json")
        with open(path, "w") as f:
            json.dump({"patterns": list(self.patterns)[-100:]}, f)

    def record_pattern(self, market_snapshot, outcome, confidence):
        pattern = {
            "snapshot": market_snapshot,
            "won": outcome >= 0,
            "profit": outcome,
            "confidence": confidence,
            "time": datetime.now().isoformat(),
        }
        with self._lock:
            self.patterns.append(pattern)
        self._save()

    def find_similar(self, current_snapshot, top_k=5):
        with self._lock:
            patterns_snapshot = list(self.patterns)
        if not patterns_snapshot:
            return []
        similarities = []
        for p in patterns_snapshot:
            sim = self._compare_snapshots(current_snapshot, p["snapshot"])
            if sim >= PATTERN_MATCH_THRESHOLD:
                similarities.append({"pattern": p, "similarity": sim})
        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:top_k]

    def _compare_snapshots(self, s1, s2):
        if not s1 or not s2:
            return 0
        keys = set(s1.keys()) & set(s2.keys())
        if not keys:
            return 0
        matches = 0
        for k in keys:
            v1 = s1.get(k, 0)
            v2 = s2.get(k, 0)
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                if abs(v1) + abs(v2) > 0:
                    diff = abs(v1 - v2) / (abs(v1) + abs(v2) + 1e-10)
                    if diff < 0.15:
                        matches += 1
            elif v1 == v2:
                matches += 1
        return matches / len(keys) if keys else 0

    def get_prediction(self, current_snapshot):
        similar = self.find_similar(current_snapshot)
        if not similar:
            return None
        total_weight = sum(s["similarity"] for s in similar)
        weighted_outcome = sum(s["pattern"]["profit"] * s["similarity"] for s in similar) / total_weight
        win_count = sum(1 for s in similar if s["pattern"]["won"])
        win_rate = win_count / len(similar)
        return {
            "predicted_direction": 1 if weighted_outcome > 0 else -1 if weighted_outcome < 0 else 0,
            "predicted_pnl": weighted_outcome,
            "confidence": win_rate,
            "similar_count": len(similar),
            "avg_similarity": np.mean([s["similarity"] for s in similar]),
        }


class PerformanceAdaptor:
    def __init__(self):
        self.performance_history = deque(maxlen=200)
        self.current_params = {}
        self.adaptation_count = 0
        self.plateau_detected = False
        self._lock = threading.Lock()

    def record(self, confidence, won, profit):
        with self._lock:
            self.performance_history.append({
                "confidence": confidence,
                "won": won,
                "profit": profit,
                "time": _time.time(),
            })

    def detect_plateau(self):
        with self._lock:
            if len(self.performance_history) < PLATEAU_WINDOW:
                return False
            recent = list(self.performance_history)[-PLATEAU_WINDOW:]
        profits = [p["profit"] for p in recent]
        mean_profit = np.mean(profits)
        std_profit = np.std(profits)
        if std_profit < max(PLATEAU_THRESHOLD * abs(mean_profit), 0.01):
            with self._lock:
                self.plateau_detected = True
            return True
        with self._lock:
            self.plateau_detected = False
        return False

    def suggest_adaptation(self):
        with self._lock:
            if len(self.performance_history) < ADAPTATION_WINDOW:
                return None
            recent = list(self.performance_history)[-ADAPTATION_WINDOW:]
        win_rate = sum(1 for p in recent if p["won"]) / len(recent)
        avg_profit = np.mean([p["profit"] for p in recent])
        avg_conf = np.mean([p["confidence"] for p in recent])
        suggestions = []
        if win_rate < 0.45:
            suggestions.append({"param": "min_confidence", "action": "increase", "reason": f"Low win rate {win_rate:.1%}"})
        elif win_rate > 0.65:
            suggestions.append({"param": "min_confidence", "action": "decrease", "reason": f"High win rate {win_rate:.1%}, can trade more"})
        if avg_profit < 0:
            suggestions.append({"param": "sl_atr_mult", "action": "increase", "reason": "Negative average profit"})
        if self.plateau_detected:
            suggestions.append({"param": "mutation_rate", "action": "increase", "reason": "Performance plateau detected"})
        return suggestions if suggestions else None


class MarketConditionMemory:
    def __init__(self):
        self.best_strategies_by_condition = {}

    def record(self, regime, session, volatility, strategy, won):
        key = f"{regime}_{session}_{self._vol_bucket(volatility)}"
        if key not in self.best_strategies_by_condition:
            self.best_strategies_by_condition[key] = {}
        if strategy not in self.best_strategies_by_condition[key]:
            self.best_strategies_by_condition[key][strategy] = {"wins": 0, "total": 0}
        self.best_strategies_by_condition[key][strategy]["total"] += 1
        if won:
            self.best_strategies_by_condition[key][strategy]["wins"] += 1

    def get_best_strategy(self, regime, session, volatility):
        key = f"{regime}_{session}_{self._vol_bucket(volatility)}"
        strats = self.best_strategies_by_condition.get(key, {})
        if not strats:
            return None
        best = max(strats.items(), key=lambda x: x[1]["wins"] / max(x[1]["total"], 1))
        if best[1]["total"] >= 5:
            return {"strategy": best[0], "win_rate": best[1]["wins"] / best[1]["total"]}
        return None

    @staticmethod
    def _vol_bucket(volatility):
        if volatility < 0.5:
            return "low"
        elif volatility < 1.0:
            return "medium"
        return "high"


class ContinuousImprover:
    def __init__(self):
        self.improvement_score = 0
        self.version = 1
        self.changelog = deque(maxlen=50)
        self.metrics_over_time = deque(maxlen=100)

    def record_metrics(self, metrics):
        self.metrics_over_time.append({
            "time": _time.time(),
            "win_rate": metrics.get("win_rate", 0),
            "profit_factor": metrics.get("profit_factor", 0),
            "sharpe": metrics.get("sharpe", 0),
            "expectancy": metrics.get("expectancy", 0),
        })

    def calculate_improvement(self):
        if len(self.metrics_over_time) < 10:
            return 0
        recent = list(self.metrics_over_time)[-10:]
        older = list(self.metrics_over_time)[-20:-10] if len(self.metrics_over_time) >= 20 else list(self.metrics_over_time)[:10]
        recent_wr = np.mean([m["win_rate"] for m in recent])
        older_wr = np.mean([m["win_rate"] for m in older])
        recent_pf = np.mean([m["profit_factor"] for m in recent])
        older_pf = np.mean([m["profit_factor"] for m in older])
        wr_change = recent_wr - older_wr
        pf_change = recent_pf - older_pf
        self.improvement_score = (wr_change * 0.5 + pf_change * 0.3) / 100
        return self.improvement_score

    def log_change(self, description):
        self.changelog.append({
            "time": datetime.now().isoformat(),
            "version": self.version,
            "description": description,
        })
        self.version += 1


class BrainV7:
    def __init__(self, brain_v6):
        self.v6 = brain_v6
        self.evolution = EvolutionEngine()
        self.pattern_memory = PatternMemory()
        self.adaptor = PerformanceAdaptor()
        self.condition_memory = MarketConditionMemory()
        self.improver = ContinuousImprover()
        self._active_genome_idx = 0

    def analyze(self, symbol, timeframe=mt5.TIMEFRAME_M1, df=None):
        # Get best evolutionary params
        best_params = self.evolution.get_best_params()

        # Check pattern memory
        snapshot = self._take_snapshot(symbol, timeframe, df=df)
        prediction = self.pattern_memory.get_prediction(snapshot) if snapshot else None

        # Detect plateau
        plateau = self.adaptor.detect_plateau()

        # Get V6 analysis (which calls V5->V4->V3->V2->V1)
        decision = self.v6.safe_analyze(symbol, timeframe, params=best_params, df=df)

        if decision.get("action") != "trade":
            return self._attach_v7_data(decision, best_params, prediction, plateau)

        direction = decision.get("direction", 0)
        confidence = decision.get("confidence", 0)

        # Pattern memory boost
        pattern_boost = 1.0
        v7_notes = []
        if prediction:
            if prediction["predicted_direction"] == direction:
                pattern_boost = 1.0 + (prediction["confidence"] * 0.2)
                v7_notes.append(f"Pattern match: {prediction['similar_count']} similar (WR: {prediction['confidence']:.0%})")
            elif prediction["predicted_direction"] != 0:
                pattern_boost = 0.7
                v7_notes.append(f"Pattern conflict (predicted {'BUY' if prediction['predicted_direction']==1 else 'SELL'})")

        # Condition-based strategy selection
        regime = decision.get("v2_analysis", {}).get("regime", "unknown")
        session = decision.get("v2_analysis", {}).get("session", "unknown")
        vol = decision.get("v3", {}).get("micro", {}).get("spread_pts", 5)
        best_strat = self.condition_memory.get_best_strategy(regime, session, vol)
        condition_boost = 1.0
        if best_strat:
            condition_boost = 1.1

        # Plateau adaptation
        adapt_mod = 1.0
        if plateau:
            adapt_mod = 0.9
            v7_notes.append("Plateau detected - exploring")

        # Final confidence (additive scoring - each factor has a max contribution weight)
        adjs = decision.get('confidence_adjustments', {})
        adjs['v7_pattern'] = (pattern_boost - 1.0) * 0.10        # max ±10%
        adjs['v7_condition'] = (condition_boost - 1.0) * 0.08    # max ±8%
        adjs['v7_adapt'] = (adapt_mod - 1.0) * 0.05              # max -5%
        decision['confidence_adjustments'] = adjs
        final_confidence = confidence + sum(adjs.values())
        final_confidence = max(0.1, min(final_confidence, 0.98))

        # Adjust lot
        lot = decision.get("lot", 0.01)
        if final_confidence > 0.8:
            lot *= 1.15
        info = self.v6.v5.v4.v3.cache.get_symbol_info(symbol) if hasattr(self.v6.v5.v4.v3, 'cache') else mt5.symbol_info(symbol)
        if info:
            lot = max(info.volume_min, min(lot, info.volume_max))
            lot = round(lot / info.volume_step) * info.volume_step
            lot = round(lot, 2)

        logger.debug("[BRAIN V7] --- Learning Report ---")
        if self.evolution.best_genome:
            logger.debug("  Evolution: Gen %d | Best Fitness: %.2f", self.evolution.generation, self.evolution.best_genome.fitness)
        else:
            logger.debug("  Evolution: Initializing")
        logger.debug("  Pattern Memory: %d patterns | Prediction: %s", len(self.pattern_memory.patterns), prediction['predicted_direction'] if prediction else 'None')
        logger.debug("  Plateau: %s | Improvement: %.3f", 'YES' if plateau else 'NO', self.improver.calculate_improvement())
        if best_strat:
            logger.debug("  Best Strategy: %s (%.0f%%)", best_strat['strategy'], best_strat['win_rate'] * 100)
        else:
            logger.debug("  Best Strategy: N/A")
        logger.debug("  V6 Conf: %.3f -> V7 Conf: %.3f", confidence, final_confidence)
        if v7_notes:
            logger.debug("  V7 Notes: %s", ' | '.join(v7_notes))

        # Override
        result = decision.copy()
        result["confidence"] = final_confidence
        result["lot"] = lot
        result["v7_notes"] = v7_notes
        result["v7"] = {
            "evolution_gen": self.evolution.generation,
            "best_fitness": self.evolution.best_genome.fitness if self.evolution.best_genome else 0,
            "pattern_prediction": prediction,
            "plateau": plateau,
            "improvement": self.improver.calculate_improvement(),
            "condition_strategy": best_strat,
            "active_genome": self._active_genome_idx,
        }

        return result

    def record_trade_outcome(self, confidence, won, profit, regime="unknown", session="unknown", strategy="combined"):
        # Evolution
        self.evolution.record_trade(self._active_genome_idx, won)
        if self.evolution.generation > 0 and self.evolution.generation % GENERATION_THRESHOLD == 0:
            self.evolution.evolve()
            logger.info("BRAIN V7 Evolved to generation %d", self.evolution.generation)

        # Pattern memory
        self.adaptor.record(confidence, won, profit)
        self.condition_memory.record(regime, session, 1.0, strategy, won)

        # Improvement tracking
        try:
            stats = self.v6.v5.v4.v3.v1.stats.get_full_report()
        except AttributeError:
            stats = {}
        self.improver.record_metrics(stats)

        # Check for adaptation suggestions and apply them
        suggestions = self.adaptor.suggest_adaptation()
        if suggestions:
            for s in suggestions:
                logger.info("BRAIN V7 Adaptation: %s -> %s (%s)", s['param'], s['action'], s['reason'])
            self.evolution.get_best_params(adaptations=suggestions)

    def save_pattern(self, symbol, timeframe, outcome, confidence):
        snapshot = self._take_snapshot(symbol, timeframe)
        if snapshot:
            self.pattern_memory.record_pattern(snapshot, outcome, confidence)

    def _take_snapshot(self, symbol, timeframe, df=None):
        try:
            if df is not None and len(df) >= PATTERN_LOOKBACK:
                snapshot_df = df.tail(PATTERN_LOOKBACK)
            else:
                rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, PATTERN_LOOKBACK)
                if rates is None:
                    return None
                snapshot_df = pd.DataFrame(rates)
                if len(snapshot_df) < PATTERN_LOOKBACK:
                    return None
            return {
                "close_pct_change": (snapshot_df['close'].iloc[-1] - snapshot_df['close'].iloc[-PATTERN_LOOKBACK]) / snapshot_df['close'].iloc[-PATTERN_LOOKBACK] * 100,
                "high_low_range": (snapshot_df['high'].max() - snapshot_df['low'].min()) / snapshot_df['close'].iloc[-1] * 100,
                "avg_volume": snapshot_df['tick_volume'].mean(),
                "last_close": snapshot_df['close'].iloc[-1],
                "volatility": snapshot_df['close'].pct_change().std() * 100,
                "trend_strength": (snapshot_df['close'].iloc[-1] - snapshot_df['close'].iloc[-20]) / snapshot_df['close'].iloc[-20] * 100 if len(snapshot_df) >= 20 else 0,
            }
        except Exception as e:
            logger.debug("Snapshot creation failed: %s", e)
            return None

    def manage_positions(self, symbol):
        self.v6.manage_positions(symbol)

    def execute_decision(self, decision, symbol):
        return self.v6.safe_execute(decision, symbol)

    def _attach_v7_data(self, decision, best_params, prediction, plateau):
        decision["v7"] = {
            "evolution_gen": self.evolution.generation,
            "best_fitness": self.evolution.best_genome.fitness if self.evolution.best_genome else 0,
            "pattern_prediction": prediction,
            "plateau": plateau,
            "improvement": self.improver.calculate_improvement(),
        }
        return decision

    def get_dashboard_data(self):
        data = self.v6.get_dashboard_data()
        data["v7"] = {
            "generation": self.evolution.generation,
            "best_fitness": self.evolution.best_genome.fitness if self.evolution.best_genome else 0,
            "pattern_count": len(self.pattern_memory.patterns),
            "plateau": self.adaptor.plateau_detected,
            "improvement": self.improver.calculate_improvement(),
            "version": self.improver.version,
            "changelog": list(self.improver.changelog)[-5:],
        }
        return data

    def print_status(self):
        self.v6.print_status()
        v7 = self.get_dashboard_data().get("v7", {})
        logger.info("  BRAIN V7 — LEARNING & EVOLUTION")
        logger.info("  Evolution: Gen %d | Best Fitness: %.2f", v7.get('generation', 0), v7.get('best_fitness', 0))
        logger.info("  Patterns: %d | Plateau: %s", v7.get('pattern_count', 0), 'YES' if v7.get('plateau') else 'NO')
        logger.info("  Improvement Score: %.3f | Version: %d", v7.get('improvement', 0), v7.get('version', 1))
        changelog = v7.get("changelog", [])
        if changelog:
            logger.info("  Recent Changes:")
            for c in changelog[-3:]:
                logger.info("    v%d: %s", c['version'], c['description'][:60])
