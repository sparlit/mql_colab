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
from config import DATA_DIR, get_magic_number, magic_belongs_to_brain, is_system_magic

logger = logging.getLogger(__name__)

# Self-healing
MIN_TRADES_TO_DISABLE = 15
DISABLE_WIN_RATE_THRESHOLD = 0.35

# Edge decay
EDGE_DECAY_WINDOW = 30
EDGE_DECAY_THRESHOLD = 0.3

# Position scaling
SCALE_IN_CONFIDENCE = 0.80
SCALE_OUT_CONFIDENCE = 0.40
MAX_SCALE_LEVELS = 3


class StrategyAutoWeighter:
    def __init__(self):
        self.performance = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "strategy_weights.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    self.performance = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.performance = {}
                logger.debug("Performance data load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "strategy_weights.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.performance, f)
        if os.path.exists(path):
            os.replace(tmp, path)
        else:
            os.rename(tmp, path)

    def record(self, strategy, won, profit=0):
        with self._lock:
            if strategy not in self.performance:
                self.performance[strategy] = {"wins": 0, "losses": 0, "total_pnl": 0, "recent": []}
            self.performance[strategy]["total_pnl"] += profit
            self.performance[strategy]["recent"].append(1 if won else 0)
            if len(self.performance[strategy]["recent"]) > 100:
                self.performance[strategy]["recent"] = self.performance[strategy]["recent"][-100:]
            if won:
                self.performance[strategy]["wins"] += 1
            else:
                self.performance[strategy]["losses"] += 1
        self._save()

    def get_weight(self, strategy):
        with self._lock:
            stats = self.performance.get(strategy)
        return self._weight_from_stats(stats)

    @staticmethod
    def _weight_from_stats(stats):
        if not stats or stats["wins"] + stats["losses"] < 10:
            return 1.0
        recent = stats["recent"][-30:]
        win_rate = sum(recent) / len(recent) if recent else 0.5
        if win_rate > 0.6:
            return 1.0 + (win_rate - 0.5) * 0.6
        elif win_rate < 0.4:
            return max(0.3, 1.0 - (0.5 - win_rate) * 0.6)
        return 1.0

    def get_disabled_strategies(self):
        disabled = []
        with self._lock:
            items = list(self.performance.items())
        for strat, stats in items:
            total = stats["wins"] + stats["losses"]
            if total >= MIN_TRADES_TO_DISABLE:
                wr = stats["wins"] / total
                if wr < DISABLE_WIN_RATE_THRESHOLD:
                    disabled.append(strat)
        return disabled

    def get_all_weights(self):
        with self._lock:
            snapshot = dict(self.performance)
        return {s: self._weight_from_stats(stats) for s, stats in snapshot.items()}


class EdgeDecayDetector:
    def __init__(self):
        self.edge_history = deque(maxlen=200)

    def record(self, confidence, won):
        self.edge_history.append({"confidence": confidence, "won": won, "time": _time.time()})

    def detect_decay(self):
        if len(self.edge_history) < EDGE_DECAY_WINDOW:
            return {"decaying": False, "score": 0, "recent_wr": 0.5}
        recent = list(self.edge_history)[-EDGE_DECAY_WINDOW:]
        older = list(self.edge_history)[-EDGE_DECAY_WINDOW*2:-EDGE_DECAY_WINDOW] if len(self.edge_history) >= EDGE_DECAY_WINDOW * 2 else []
        recent_wr = sum(1 for r in recent if r["won"]) / len(recent)
        if older:
            older_wr = sum(1 for r in older if r["won"]) / len(older)
            decay = older_wr - recent_wr
        else:
            avg_conf = np.mean([r["confidence"] for r in recent])
            high_conf_trades = [r for r in recent if r["confidence"] > 0.65]
            if high_conf_trades:
                high_wr = sum(1 for r in high_conf_trades if r["won"]) / len(high_conf_trades)
                decay = max(0, 0.6 - high_wr)
            else:
                decay = 0
        return {
            "decaying": decay > EDGE_DECAY_THRESHOLD,
            "score": round(decay, 3),
            "recent_wr": round(recent_wr, 3),
        }


class ParameterOptimizer:
    def __init__(self):
        self.trades_by_regime = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "regime_params.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    self.trades_by_regime = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.trades_by_regime = {}
                logger.debug("Trades by regime load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "regime_params.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.trades_by_regime, f)
        if os.path.exists(path):
            os.replace(tmp, path)
        else:
            os.rename(tmp, path)

    def record(self, regime, sl_mult, tp_mult, won, profit):
        key = regime
        with self._lock:
            if key not in self.trades_by_regime:
                self.trades_by_regime[key] = {"trades": [], "optimal_sl": 1.5, "optimal_tp": 2.5}
            self.trades_by_regime[key]["trades"].append({
                "sl_mult": sl_mult, "tp_mult": tp_mult, "won": won, "profit": profit
            })
            if len(self.trades_by_regime[key]["trades"]) > 200:
                self.trades_by_regime[key]["trades"] = self.trades_by_regime[key]["trades"][-200:]
        self._optimize(key)
        self._save()

    def _optimize(self, regime):
        with self._lock:
            trades = self.trades_by_regime[regime]["trades"]
            if len(trades) < 10:
                return
            best_sl = 1.5
            best_tp = 2.5
            best_score = 0
            for sl_try in np.arange(0.8, 3.0, 0.3):
                for tp_try in np.arange(1.5, 4.0, 0.3):
                    score = 0
                    count = 0
                    for t in trades:
                        sl_match = abs(t["sl_mult"] - sl_try) < 0.2
                        tp_match = abs(t["tp_mult"] - tp_try) < 0.3
                        if sl_match or tp_match:
                            if t["won"]:
                                score += t["profit"]
                            else:
                                score -= abs(t["profit"]) * 0.5
                            count += 1
                    if count >= 3:
                        avg_score = score / count
                        if avg_score > best_score:
                            best_score = avg_score
                            best_sl = sl_try
                            best_tp = tp_try
            self.trades_by_regime[regime]["optimal_sl"] = round(best_sl, 2)
            self.trades_by_regime[regime]["optimal_tp"] = round(best_tp, 2)

    def get_optimal_params(self, regime):
        with self._lock:
            data = self.trades_by_regime.get(regime)
        if not data or len(data.get("trades", [])) < 10:
            return None
        return {"sl_mult": data["optimal_sl"], "tp_mult": data["optimal_tp"]}


class TradeJournalAnalyzer:
    def __init__(self):
        self.journal = []
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "trade_journal.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    self.journal = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.journal = []
                logger.debug("Journal load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "trade_journal.json")
        with open(path, "w") as f:
            json.dump(self.journal[-500:], f)

    def add_entry(self, entry):
        with self._lock:
            self.journal.append(entry)
        self._save()

    def analyze_patterns(self):
        with self._lock:
            journal_snapshot = list(self.journal)
        if len(journal_snapshot) < 20:
            return {}
        patterns = {}
        for i in range(1, len(journal_snapshot)):
            prev = journal_snapshot[i-1]
            curr = journal_snapshot[i]
            if prev.get("won") is False and curr.get("won") is True:
                key = "loss_then_win"
            elif prev.get("won") is True and curr.get("won") is True:
                key = "win_streak"
            elif prev.get("won") is False and curr.get("won") is False:
                key = "loss_streak"
            else:
                key = "win_then_loss"
            if key not in patterns:
                patterns[key] = {"count": 0, "total_profit": 0}
            patterns[key]["count"] += 1
            patterns[key]["total_profit"] += curr.get("profit", 0)
        for k in patterns:
            if patterns[k]["count"] > 0:
                patterns[k]["avg_profit"] = patterns[k]["total_profit"] / patterns[k]["count"]
        return patterns

    def get_streak_prediction(self):
        with self._lock:
            recent = list(self.journal)[-10:]
        if not recent:
            return None
        last_won = recent[-1].get("won", None)
        if last_won is None:
            return None
        consecutive = 0
        for t in reversed(recent):
            if t.get("won") == last_won:
                consecutive += 1
            else:
                break
        return {
            "current_streak": consecutive,
            "type": "win" if last_won else "loss",
            "revert_likelihood": min(consecutive / 5, 0.8) if consecutive >= 3 else 0,
        }


class SessionMemory:
    def __init__(self):
        self.session_stats = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "session_memory.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    self.session_stats = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.session_stats = {}
                logger.debug("Session stats load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "session_memory.json")
        with open(path, "w") as f:
            json.dump(self.session_stats, f)

    def record(self, session, won, profit):
        with self._lock:
            if session not in self.session_stats:
                self.session_stats[session] = {"wins": 0, "losses": 0, "total_pnl": 0, "recent": []}
            self.session_stats[session]["total_pnl"] += profit
            self.session_stats[session]["recent"].append(1 if won else 0)
            if len(self.session_stats[session]["recent"]) > 50:
                self.session_stats[session]["recent"] = self.session_stats[session]["recent"][-50:]
            if won:
                self.session_stats[session]["wins"] += 1
            else:
                self.session_stats[session]["losses"] += 1
        self._save()

    def get_session_modifier(self, session):
        with self._lock:
            stats = self.session_stats.get(session)
        if not stats or stats["wins"] + stats["losses"] < 5:
            return 1.0
        recent = stats["recent"][-20:]
        wr = sum(recent) / len(recent) if recent else 0.5
        if wr > 0.6:
            return 1.0 + (wr - 0.5) * 0.4
        elif wr < 0.4:
            return max(0.5, 0.8 + wr * 0.2)
        return 1.0

    def get_all_stats(self):
        result = {}
        with self._lock:
            items = dict(self.session_stats)
        for session, stats in items.items():
            total = stats["wins"] + stats["losses"]
            if total > 0:
                result[session] = {
                    "win_rate": round(stats["wins"] / total * 100, 1),
                    "total_trades": total,
                    "total_pnl": round(stats["total_pnl"], 2),
                }
        return result


class PositionScalingEngine:
    def __init__(self):
        self.active_scales = {}
        self._lock = threading.Lock()

    def should_scale_in(self, position, current_confidence):
        ticket = position.ticket
        with self._lock:
            if ticket not in self.active_scales:
                self.active_scales[ticket] = {"level": 1, "initial_volume": position.volume}
            scale_data = self.active_scales[ticket]
        if scale_data["level"] >= MAX_SCALE_LEVELS:
            return False, 0
        if current_confidence < SCALE_IN_CONFIDENCE:
            return False, 0
        pnl_pct = position.profit / (position.volume * position.contract_size) * 100 if position.volume > 0 and position.contract_size > 0 else 0
        if pnl_pct > 0.05:
            additional = position.volume * 0.5
            with self._lock:
                self.active_scales[ticket]["level"] += 1
            return True, round(additional, 2)
        return False, 0

    def should_scale_out(self, position, current_confidence):
        ticket = position.ticket
        if current_confidence < SCALE_OUT_CONFIDENCE and position.profit > 0:
            pnl_pct = position.profit / (position.volume * position.contract_size) * 100 if position.volume > 0 and position.contract_size > 0 else 0
            if pnl_pct > 0.1:
                close_volume = round(position.volume * 0.5, 2)
                info = mt5.symbol_info(position.symbol)
                if info:
                    close_volume = max(info.volume_min, min(close_volume, position.volume))
                    close_volume = round(close_volume / info.volume_step) * info.volume_step
                return True, close_volume
        return False, 0

    def cleanup(self, closed_tickets):
        with self._lock:
            for t in closed_tickets:
                self.active_scales.pop(t, None)


class BrainV5:
    def __init__(self, brain_v4):
        self.v4 = brain_v4
        self.auto_weighter = StrategyAutoWeighter()
        self.edge_decay = EdgeDecayDetector()
        self.optimizer = ParameterOptimizer()
        self.journal = TradeJournalAnalyzer()
        self.session_memory = SessionMemory()
        self.scaling = PositionScalingEngine()

    def analyze(self, symbol, timeframe=mt5.TIMEFRAME_M1, params=None, df=None):
        decision = self.v4.analyze(symbol, timeframe, params=params, df=df)

        if decision.get("action") != "trade":
            return self._attach_v5_data(decision)

        direction = decision.get("direction", 0)
        signals = decision.get("signals", {})
        confidence = decision.get("confidence", 0)

        # Strategy auto-weighting
        auto_weight = 1.0
        disabled_strategies = self.auto_weighter.get_disabled_strategies()
        for name in disabled_strategies:
            if name in signals and signals[name].get("direction", 0) == direction:
                auto_weight *= 0.3
                logger.warning("Disabled strategy '%s' penalized", name)

        active_weight = 1.0
        for name, sig in signals.items():
            if sig.get("direction", 0) == direction and sig.get("confidence", 0) > 0.2:
                w = self.auto_weighter.get_weight(name)
                active_weight *= w

        # Edge decay check
        edge = self.edge_decay.detect_decay()
        edge_mod = 1.0
        if edge["decaying"]:
            edge_mod = 0.6
            logger.warning("EDGE DECAY DETECTED (score: %.3f, recent WR: %.1f%%)", edge['score'], edge['recent_wr'] * 100)

        # Streak prediction
        streak = self.journal.get_streak_prediction()
        streak_mod = 1.0
        if streak and streak["revert_likelihood"] > 0.5:
            streak_mod = 0.7
            logger.warning("Streak revert likely: %d%ss (%.0f%%)", streak['current_streak'], streak['type'], streak['revert_likelihood'] * 100)

        # Session memory
        v2_data = decision.get("v2_analysis", {})
        session_name = v2_data.get("session", "unknown")
        session_mod = self.session_memory.get_session_modifier(session_name)

        # Optimized SL/TP
        regime = v2_data.get("regime", "unknown")
        optimal = self.optimizer.get_optimal_params(regime)
        sl_mod = 1.0
        tp_mod = 1.0
        if optimal:
            original_sl = decision.get("sl_points", 100)
            original_tp = decision.get("tp_points", 200)
            if optimal["sl_mult"] and optimal["tp_mult"]:
                sl_mod = optimal["sl_mult"] / 1.5
                tp_mod = optimal["tp_mult"] / 2.5

        # Combine (additive scoring - each factor has a max contribution weight)
        adjs = decision.get('confidence_adjustments', {})
        adjs['v5_auto_weight'] = (auto_weight - 1.0) * 0.12     # max ±12%
        adjs['v5_active_weight'] = (active_weight - 1.0) * 0.10  # max ±10%
        adjs['v5_edge_decay'] = (edge_mod - 1.0) * 0.10         # max -10%
        adjs['v5_streak'] = (streak_mod - 1.0) * 0.08           # max -8%
        adjs['v5_session'] = (session_mod - 1.0) * 0.08         # max ±8%
        decision['confidence_adjustments'] = adjs
        final_confidence = confidence + sum(adjs.values())
        final_confidence = max(0.1, min(final_confidence, 0.98))

        # Adjust lot
        lot = decision.get("lot", 0.01)
        if edge["decaying"]:
            lot *= 0.5
        if streak and streak["revert_likelihood"] > 0.5:
            lot *= 0.7
        info = self.v4.v3.cache.get_symbol_info(symbol) if hasattr(self.v4.v3, 'cache') else mt5.symbol_info(symbol)
        if info:
            lot = max(info.volume_min, min(lot, info.volume_max))
            lot = round(lot / info.volume_step) * info.volume_step
            lot = round(lot, 2)

        # Adjust SL/TP with optimized params
        sl_points = decision.get("sl_points", 100)
        tp_points = decision.get("tp_points", 200)
        if optimal:
            sl_points = int(sl_points * sl_mod)
            tp_points = int(tp_points * tp_mod)

        # Print V5 analysis
        logger.debug("Self-Learning Report:")
        logger.debug("  Auto-Weight: %.3f | Edge Decay: %s (%.3f)", active_weight, 'YES' if edge['decaying'] else 'NO', edge['score'])
        logger.debug("  Streak: %s", f"{streak['current_streak']}{streak['type']} (revert: {streak['revert_likelihood']:.0%})" if streak else "None")
        logger.debug("  Session Memory: %s (mod: %.3f)", session_name, session_mod)
        if optimal:
            logger.debug("  Optimized SL/TP: SL %.2fx | TP %.2fx", optimal['sl_mult'], optimal['tp_mult'])
        logger.debug("  Disabled Strategies: %s", disabled_strategies if disabled_strategies else 'None')
        logger.debug("  V4 Conf: %.3f -> V5 Conf: %.3f", confidence, final_confidence)

        # Override
        result = decision.copy()
        result["confidence"] = final_confidence
        result["lot"] = lot
        result["sl_points"] = sl_points
        result["tp_points"] = tp_points
        result["v5"] = {
            "auto_weight": round(auto_weight, 3),
            "active_weight": round(active_weight, 3),
            "edge_decay": edge,
            "streak": streak,
            "session_memory": session_name,
            "session_mod": round(session_mod, 3),
            "optimized_params": optimal,
            "disabled_strategies": disabled_strategies,
        }

        return result

    def record_trade_outcome(self, ticket, symbol, direction, lot, price, sl, tp, profit, confidence, strategy, regime, session, sl_mult=None, tp_mult=None):
        won = profit >= 0
        hour = datetime.now(timezone.utc).hour
        self.auto_weighter.record(strategy, won, profit)
        self.edge_decay.record(confidence, won)
        actual_sl = sl_mult if sl_mult is not None else 1.5
        actual_tp = tp_mult if tp_mult is not None else 2.5
        self.optimizer.record(regime, actual_sl, actual_tp, won, profit)
        self.session_memory.record(session, won, profit)
        self.journal.add_entry({
            "ticket": ticket, "symbol": symbol, "direction": direction,
            "lot": lot, "price": price, "sl": sl, "tp": tp,
            "profit": profit, "won": won, "confidence": confidence,
            "strategy": strategy, "regime": regime, "session": session,
            "time": datetime.now().isoformat(),
        })

    def manage_positions(self, symbol):
        self.v4.manage_positions(symbol)
        open_pos = mt5.positions_get()
        my_pos = [p for p in (open_pos or []) if is_system_magic(p.magic) and magic_belongs_to_brain(p.magic, "v5") and p.symbol == symbol]
        for pos in my_pos:
            scale_in, vol = self.scaling.should_scale_in(pos, 0.7)
            if scale_in and vol > 0:
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    continue
                # Validate tick freshness before scale-in
                from indicators import validate_tick_freshness
                tick_check = validate_tick_freshness(tick, symbol)
                if not tick_check["fresh"]:
                    continue
                order_type = mt5.ORDER_TYPE_BUY if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_SELL
                price = tick.ask if pos.type == mt5.ORDER_TYPE_BUY else tick.bid
                request = {
                    "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
                    "volume": vol, "type": order_type, "price": price,
                     "sl": pos.sl, "tp": pos.tp, "magic": pos.magic,
                    "comment": "ScaleIn", "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                mt5.order_send(request)


    def execute_decision(self, decision, symbol):
        if decision.get("action") != "trade":
            return False
        # Ensure magic number is set in decision
        decision["magic"] = decision.get("magic", get_magic_number("v5", "technical", symbol))
        success = self.v4.execute_decision(decision, symbol)
        return success

    def _attach_v5_data(self, decision):
        decision["v5"] = {
            "auto_weight": 1.0,
            "active_weight": 1.0,
            "edge_decay": self.edge_decay.detect_decay(),
            "streak": self.journal.get_streak_prediction(),
            "session_memory": "unknown",
            "session_mod": 1.0,
            "optimized_params": None,
            "disabled_strategies": self.auto_weighter.get_disabled_strategies(),
        }
        return decision

    def get_dashboard_data(self):
        data = self.v4.get_dashboard_data()
        data["v5"] = {
            "strategy_weights": self.auto_weighter.get_all_weights(),
            "disabled_strategies": self.auto_weighter.get_disabled_strategies(),
            "edge_decay": self.edge_decay.detect_decay(),
            "session_memory": self.session_memory.get_all_stats(),
            "journal_patterns": self.journal.analyze_patterns(),
            "streak": self.journal.get_streak_prediction(),
        }
        return data

    def print_status(self):
        self.v4.print_status()
        v5 = self.get_dashboard_data().get("v5", {})
        logger.info("BRAIN V5 — SELF-LEARNING STATUS")
        disabled = v5.get("disabled_strategies", [])
        logger.info("  Disabled Strategies: %s", disabled if disabled else 'None')
        weights = v5.get("strategy_weights", {})
        if weights:
            logger.info("  Strategy Weights:")
            for s, w in sorted(weights.items(), key=lambda x: x[1], reverse=True)[:6]:
                logger.info("    %s: %.3f", s, w)
        edge = v5.get("edge_decay", {})
        logger.info("  Edge Decay: %s (score: %.3f, WR: %.1f%%)", 'YES' if edge.get('decaying') else 'NO', edge.get('score', 0), edge.get('recent_wr', 0.5) * 100)
        streak = v5.get("streak")
        if streak:
            logger.info("  Streak: %s%ss (revert: %.0f%%)", streak['current_streak'], streak['type'], streak['revert_likelihood'] * 100)
        sessions = v5.get("session_memory", {})
        if sessions:
            logger.info("  Session Memory:")
            for s, stats in sessions.items():
                logger.info("    %s: WR %s%% | Trades %d | PnL $%.2f", s, stats['win_rate'], stats['total_trades'], stats['total_pnl'])
        patterns = v5.get("journal_patterns", {})
        if patterns:
            logger.info("  Journal Patterns:")
            for p, data in list(patterns.items())[:4]:
                logger.info("    %s: %dx | avg profit $%.2f", p, data['count'], data.get('avg_profit', 0))
