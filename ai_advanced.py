import numpy as np
import json
import os
import time as _time
import threading
import logging
from datetime import datetime
from collections import deque
from config import DATA_DIR

logger = logging.getLogger(__name__)

# ==========================================
# ADVANCED AI & ML
# ==========================================


class MomentumPredictor:
    """Momentum-based price predictor using trend, volatility, and momentum scoring.
    
    Note: Despite the original name, this is NOT a transformer neural network.
    It uses simple statistical features (momentum, trend, volatility) for prediction.
    """
    def __init__(self):
        self.weights = None
        self.seq_len = 20
        self.hidden_dim = 32
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "transformer_model.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.weights = {k: np.array(v) for k, v in data.get("weights", {}).items()}
            except (json.JSONDecodeError, OSError, KeyError) as e:
                logger.debug("Transformer model load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "transformer_model.json")
        data = {"weights": {k: v.tolist() for k, v in (self.weights or {}).items()}}
        with open(path, "w") as f:
            json.dump(data, f)

    def predict(self, price_sequence):
        if len(price_sequence) < self.seq_len:
            return {"prediction": 0, "confidence": 0}
        seq = np.array(price_sequence[-self.seq_len:])
        returns = np.diff(seq) / seq[:-1]
        returns = np.where(np.isinf(returns), 0, returns)
        momentum = np.mean(returns[-5:])
        volatility = np.std(returns[-10:])
        trend = np.polyfit(range(len(returns)), returns, 1)[0]
        score = momentum * 2 + trend * 10 - volatility * 0.5
        confidence = min(abs(score) * 10, 1.0)
        prediction = 1 if score > 0 else -1 if score < 0 else 0
        return {"prediction": prediction, "confidence": round(confidence, 3), "score": round(score, 4)}

    def train(self, price_data, labels):
        if len(price_data) < 50:
            return
        X = []
        for seq in price_data:
            if len(seq) >= self.seq_len:
                X.append(seq[-self.seq_len:])
        if not X:
            return
        X = np.array(X)
        X_norm = (X - np.mean(X, axis=0)) / (np.std(X, axis=0) + 1e-10)
        self.weights = {"mean": np.mean(X, axis=0), "std": np.std(X, axis=0) + 1e-10}
        self._save()


class GPTCommentary:
    def __init__(self):
        self.ai = None
        self._lock = threading.Lock()

    def _get_ai(self):
        if self.ai is None:
            try:
                from ai_client import get_ai_client
                self.ai = get_ai_client()
            except ImportError as e:
                logger.debug("AI client import failed: %s", e)
        return self.ai

    def generate_commentary(self, market_data, positions, recent_trades):
        ai = self._get_ai()
        if not ai or not ai.is_available():
            return {"commentary": "AI not available", "timestamp": datetime.now().isoformat()}
        messages = [
            {"role": "system", "content": "You are a professional market analyst providing real-time commentary. Be concise and actionable. Respond in JSON."},
            {"role": "user", "content": f"""Generate market commentary:

Market: {json.dumps(market_data)[:2000]}
Positions: {json.dumps(positions)[:1000]}
Recent: {json.dumps(recent_trades)[:500]}

Respond in JSON:
{{"summary": "2-3 sentence market summary", "bias": "bullish/bearish/neutral", "key_levels": ["support", "resistance"], "alerts": ["any concerns"], "outlook": "short term outlook"}}"""}
        ]
        result = ai.chat_json(messages, temperature=0.4, max_tokens=400)
        if result:
            result["timestamp"] = datetime.now().isoformat()
            return result
        return {"commentary": "Unable to generate", "timestamp": datetime.now().isoformat()}


class MultiAgentRL:
    def __init__(self):
        self.agents = {
            "trend": {"q_table": {}, "epsilon": 0.1, "lr": 0.1},
            "mean_reversion": {"q_table": {}, "epsilon": 0.15, "lr": 0.1},
            "breakout": {"q_table": {}, "epsilon": 0.12, "lr": 0.1},
        }
        self.agent_performance = {name: {"rewards": deque(maxlen=100)} for name in self.agents}

    def get_state(self, features):
        state = tuple(round(features.get(k, 0), 3) for k in sorted(features.keys())[:10])
        return state

    def choose_action(self, agent_name, state):
        agent = self.agents[agent_name]
        if np.random.random() < agent["epsilon"]:
            return np.random.randint(3)
        q_values = [agent["q_table"].get((state, a), 0) for a in range(3)]
        return np.argmax(q_values)

    def learn(self, agent_name, state, action, reward, next_state):
        agent = self.agents[agent_name]
        best_next = max([agent["q_table"].get((next_state, a), 0) for a in range(3)])
        current = agent["q_table"].get((state, action), 0)
        agent["q_table"][(state, action)] = current + agent["lr"] * (reward + 0.95 * best_next - current)
        self.agent_performance[agent_name]["rewards"].append(reward)

    def get_best_agent(self):
        best = None
        best_reward = -float('inf')
        for name, perf in self.agent_performance.items():
            rewards = list(perf["rewards"])
            if rewards:
                avg = np.mean(rewards[-20:])
                if avg > best_reward:
                    best_reward = avg
                    best = name
        return best, best_reward


class FederatedLearner:
    def __init__(self):
        self.local_models = {}
        self.global_model = None
        self.rounds = 0

    def contribute_update(self, account_id, model_update):
        self.local_models[account_id] = model_update

    def aggregate(self):
        if not self.local_models:
            return None
        all_weights = []
        for update in self.local_models.values():
            if isinstance(update, dict) and "weights" in update:
                all_weights.append(np.array(update["weights"]))
        if not all_weights:
            return None
        self.global_model = np.mean(all_weights, axis=0).tolist()
        self.rounds += 1
        self.local_models.clear()
        return self.global_model


class AdversarialTester:
    def __init__(self):
        self.test_results = deque(maxlen=100)

    def test_strategy(self, strategy_func, test_cases):
        results = []
        for case in test_cases:
            try:
                result = strategy_func(case)
                results.append({"input": case, "output": result, "passed": result is not None})
            except Exception as e:
                results.append({"input": case, "error": str(e), "passed": False})
        pass_rate = sum(1 for r in results if r["passed"]) / max(len(results), 1) * 100
        return {"pass_rate": round(pass_rate, 1), "total": len(results), "results": results[-5:]}


class AutoStrategyGenerator:
    def __init__(self):
        self.generated = []
        self._lock = threading.Lock()

    def generate(self, market_features):
        strategies = []
        if market_features.get("volatility", 0) > 1.5:
            strategies.append({"name": "Volatility Breakout", "type": "breakout", "params": {"atr_mult": 1.5, "confirm_bars": 2}})
        if market_features.get("trend_strength", 0) > 0.6:
            strategies.append({"name": "Trend Following", "type": "trend", "params": {"ema_fast": 10, "ema_slow": 30, "trail_atr": 2.0}})
        if market_features.get("rsi", 50) < 30:
            strategies.append({"name": "RSI Mean Reversion", "type": "reversion", "params": {"rsi_buy": 25, "rsi_sell": 75, "hold_bars": 3}})
        with self._lock:
            self.generated.extend(strategies)
            if len(self.generated) > 50:
                self.generated = self.generated[-30:]
        return strategies


_transformer = None
_gpt = None
_multi_rl = None
_federated = None
_adversarial = None
_auto_gen = None
_lock = threading.Lock()


def get_transformer():
    global _transformer
    if _transformer is None:
        with _lock:
            if _transformer is None:
                _transformer = TransformerPredictor()
    return _transformer


def get_gpt_commentary():
    global _gpt
    if _gpt is None:
        with _lock:
            if _gpt is None:
                _gpt = GPTCommentary()
    return _gpt


def get_multi_agent_rl():
    global _multi_rl
    if _multi_rl is None:
        with _lock:
            if _multi_rl is None:
                _multi_rl = MultiAgentRL()
    return _multi_rl


def get_federated():
    global _federated
    if _federated is None:
        with _lock:
            if _federated is None:
                _federated = FederatedLearner()
    return _federated


def get_adversarial():
    global _adversarial
    if _adversarial is None:
        with _lock:
            if _adversarial is None:
                _adversarial = AdversarialTester()
    return _adversarial


def get_auto_strategy():
    global _auto_gen
    if _auto_gen is None:
        with _lock:
            if _auto_gen is None:
                _auto_gen = AutoStrategyGenerator()
    return _auto_gen

# Backward compatibility alias
TransformerPredictor = MomentumPredictor
