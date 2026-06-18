import numpy as np
import json
import os
import time as _time
import threading
import logging
from collections import deque
from datetime import datetime
import MetaTrader5 as mt5
from config import DATA_DIR

logger = logging.getLogger(__name__)

# ==========================================
# ML & AI ENHANCEMENT MODULES
# ==========================================


class FeatureStore:
    def __init__(self):
        self.features = {}
        self.feature_names = []
        self._lock = threading.Lock()

    def compute_features(self, df):
        if df is None or len(df) < 50:
            return {}
        c = df['close'].values
        h = df['high'].values
        l = df['low'].values
        v = df['tick_volume'].values if 'tick_volume' in df.columns else np.ones(len(c))
        features = {}
        features["price_return_1"] = (c[-1] - c[-2]) / c[-2] * 100 if c[-2] != 0 else 0
        features["price_return_5"] = (c[-1] - c[-5]) / c[-5] * 100 if len(c) > 5 and c[-5] != 0 else 0
        features["price_return_10"] = (c[-1] - c[-10]) / c[-10] * 100 if len(c) > 10 and c[-10] != 0 else 0
        features["volatility_10"] = np.std(np.diff(c[-10:]) / c[-10:-1]) * 100 if len(c) > 10 else 0
        features["volatility_20"] = np.std(np.diff(c[-20:]) / c[-20:-1]) * 100 if len(c) > 20 else 0
        features["high_low_range"] = (h[-1] - l[-1]) / c[-1] * 100 if c[-1] != 0 else 0
        features["close_position"] = (c[-1] - l[-20]) / (h[-20] - l[-20]) if (h[-20] - l[-20]) > 0 else 0.5
        features["volume_ratio"] = v[-1] / np.mean(v[-20:]) if np.mean(v[-20:]) > 0 else 1
        features["momentum_5"] = c[-1] - c[-5] if len(c) > 5 else 0
        features["momentum_10"] = c[-1] - c[-10] if len(c) > 10 else 0
        ema5 = self._ema(c, 5)
        ema20 = self._ema(c, 20)
        features["ema_spread"] = (ema5[-1] - ema20[-1]) / c[-1] * 100 if c[-1] != 0 else 0
        delta = np.diff(c, prepend=c[0])
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = np.mean(gain[-14:])
        avg_loss = np.mean(loss[-14:])
        rs = avg_gain / max(avg_loss, 1e-10)
        features["rsi"] = 100 - (100 / (1 + rs))
        bb_ma = np.mean(c[-20:])
        bb_std = np.std(c[-20:])
        features["bb_position"] = (c[-1] - (bb_ma - 2 * bb_std)) / (4 * bb_std) if bb_std > 0 else 0.5
        tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
        features["atr"] = np.mean(tr[-14:])
        features["atr_ratio"] = features["atr"] / np.mean(tr[-50:]) if np.mean(tr[-50:]) > 0 else 1
        features["hour"] = datetime.now().hour
        features["day_of_week"] = datetime.now().weekday()
        return features

    @staticmethod
    def _ema(data, span):
        from indicators import ema
        return ema(data, span)

    def get_feature_vector(self, features):
        if not self.feature_names:
            self.feature_names = sorted(features.keys())
        return [features.get(f, 0) for f in self.feature_names]


class MLScorer:
    def __init__(self):
        self.training_data = deque(maxlen=5000)
        self.weights = None
        self.bias = 0
        self.accuracy = 0.5
        self._lock = threading.Lock()
        self._load_model()

    def _load_model(self):
        path = os.path.join(DATA_DIR, "ml_model.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.weights = np.array(data.get("weights", []))
                    self.bias = data.get("bias", 0)
                    self.accuracy = data.get("accuracy", 0.5)
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("ML model load failed: %s", e)

    def _save_model(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "ml_model.json")
        with open(path, "w") as f:
            json.dump({
                "weights": self.weights.tolist() if self.weights is not None else [],
                "bias": self.bias,
                "accuracy": self.accuracy,
            }, f)

    def record_outcome(self, features, won):
        self.training_data.append({"features": features, "won": won})

    def train(self):
        if len(self.training_data) < 50:
            return
        X = []
        y = []
        for item in self.training_data:
            X.append(item["features"])
            y.append(1 if item["won"] else 0)
        X = np.array(X)
        y = np.array(y)
        X = (X - np.mean(X, axis=0)) / (np.std(X, axis=0) + 1e-10)
        self.weights = np.zeros(X.shape[1])
        self.bias = 0
        lr = 0.01
        for _ in range(100):
            z = X.dot(self.weights) + self.bias
            pred = 1 / (1 + np.exp(-np.clip(z, -500, 500)))
            error = pred - y
            self.weights -= lr * X.T.dot(error) / len(X)
            self.bias -= lr * np.mean(error)
        predictions = 1 / (1 + np.exp(-np.clip(X.dot(self.weights) + self.bias, -500, 500)))
        self.accuracy = np.mean((predictions > 0.5) == y)
        self._save_model()

    def predict(self, feature_vector):
        if self.weights is None or len(self.weights) == 0:
            return 0.5
        fv = np.array(feature_vector)
        if len(fv) != len(self.weights):
            return 0.5
        z = fv.dot(self.weights) + self.bias
        return float(1 / (1 + np.exp(-np.clip(z, -500, 500))))


class RulesBaseline:
    """Phase 1: Simple rule-based baseline. EMA cross + RSI + ATR.

    Proves infrastructure works before adding ML. Returns confidence 0-1.
    """

    def __init__(self):
        self._lock = threading.Lock()

    def evaluate(self, df):
        """Evaluate rules on closed-bar DataFrame.

        Returns:
            dict with 'action' (buy/sell/hold), 'confidence' (0-1), 'reasons'
        """
        if df is None or len(df) < 50:
            return {"action": "hold", "confidence": 0, "reasons": ["insufficient data"]}

        c = df['close'].values
        h = df['high'].values
        l = df['low'].values

        from indicators import ema
        ema_fast = ema(c, 10)
        ema_slow = ema(c, 30)

        # RSI
        delta = np.diff(c, prepend=c[0])
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = np.mean(gain[-14:])
        avg_loss = np.mean(loss[-14:])
        rs = avg_gain / max(avg_loss, 1e-10)
        rsi = 100 - (100 / (1 + rs))

        # ATR
        tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
        atr = np.mean(tr[-14:])

        reasons = []
        score = 0

        # Rule 1: EMA crossover (weight: 0.4)
        if ema_fast[-1] > ema_slow[-1] and ema_fast[-2] <= ema_slow[-2]:
            score += 0.4
            reasons.append("EMA bullish cross")
        elif ema_fast[-1] < ema_slow[-1] and ema_fast[-2] >= ema_slow[-2]:
            score -= 0.4
            reasons.append("EMA bearish cross")

        # Rule 2: RSI (weight: 0.3)
        if rsi < 30:
            score += 0.3
            reasons.append(f"RSI oversold ({rsi:.0f})")
        elif rsi > 70:
            score -= 0.3
            reasons.append(f"RSI overbought ({rsi:.0f})")

        # Rule 3: Price vs EMA trend (weight: 0.3)
        if c[-1] > ema_slow[-1] and c[-1] > ema_fast[-1]:
            score += 0.3
            reasons.append("Price above EMAs")
        elif c[-1] < ema_slow[-1] and c[-1] < ema_fast[-1]:
            score -= 0.3
            reasons.append("Price below EMAs")

        if score > 0.3:
            return {"action": "buy", "confidence": min(score, 1.0), "reasons": reasons}
        elif score < -0.3:
            return {"action": "sell", "confidence": min(abs(score), 1.0), "reasons": reasons}
        return {"action": "hold", "confidence": 0, "reasons": reasons}


class FeatureNormalizer:
    """Per-timeframe z-score normalizer. Prevents feature drift across regimes."""

    def __init__(self):
        self._scalers = {}  # timeframe -> {mean, std}
        self._lock = threading.Lock()

    def fit(self, timeframe, features_array):
        """Fit scaler on historical feature data.

        Args:
            timeframe: MT5 timeframe constant (60, 300, etc.)
            features_array: numpy array of shape (n_samples, n_features)
        """
        with self._lock:
            self._scalers[timeframe] = {
                "mean": np.mean(features_array, axis=0),
                "std": np.std(features_array, axis=0) + 1e-10,
            }

    def transform(self, timeframe, feature_vector):
        """Normalize a feature vector using fitted scaler.

        Args:
            timeframe: MT5 timeframe constant
            feature_vector: list or array of feature values

        Returns:
            numpy array of normalized features, or original if no scaler fitted
        """
        fv = np.array(feature_vector)
        with self._lock:
            scaler = self._scalers.get(timeframe)
        if scaler is None:
            return fv
        return (fv - scaler["mean"]) / scaler["std"]

    def save(self):
        """Persist scalers to disk."""
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "feature_scalers.json")
        data = {}
        for tf, scaler in self._scalers.items():
            data[str(tf)] = {
                "mean": scaler["mean"].tolist(),
                "std": scaler["std"].tolist(),
            }
        with open(path, "w") as f:
            json.dump(data, f)

    def load(self):
        """Load scalers from disk."""
        path = os.path.join(DATA_DIR, "feature_scalers.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                for tf_str, scaler_data in data.items():
                    self._scalers[int(tf_str)] = {
                        "mean": np.array(scaler_data["mean"]),
                        "std": np.array(scaler_data["std"]),
                    }
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Feature scaler load failed: %s", e)


class RLAgent:
    def __init__(self, state_size=20, action_size=3):
        self.state_size = state_size
        self.action_size = action_size
        self.q_table = {}
        self.learning_rate = 0.1
        self.discount_factor = 0.95
        self.epsilon = 0.1
        self.rewards = deque(maxlen=1000)

    def get_state(self, features):
        state = []
        for k in sorted(features.keys())[:self.state_size]:
            val = features[k]
            if isinstance(val, (int, float)):
                state.append(round(val, 2))
            else:
                state.append(val)
        while len(state) < self.state_size:
            state.append(0)
        return tuple(state)

    def choose_action(self, state):
        if np.random.random() < self.epsilon:
            return np.random.randint(self.action_size)
        q_values = [self.q_table.get((state, a), 0) for a in range(self.action_size)]
        return np.argmax(q_values)

    def learn(self, state, action, reward, next_state):
        best_next = max([self.q_table.get((next_state, a), 0) for a in range(self.action_size)])
        current = self.q_table.get((state, action), 0)
        self.q_table[(state, action)] = current + self.learning_rate * (reward + self.discount_factor * best_next - current)
        self.rewards.append(reward)

    def get_avg_reward(self):
        if not self.rewards:
            return 0
        return np.mean(list(self.rewards))


class EnsembleLearner:
    def __init__(self):
        self.brain_weights = {f"v{i}": 1.0 for i in range(1, 11)}
        self.brain_performance = {f"v{i}": {"correct": 0, "total": 0} for i in range(1, 11)}

    def update_weights(self, brain_name, prediction_correct):
        perf = self.brain_performance[brain_name]
        perf["total"] += 1
        if prediction_correct:
            perf["correct"] += 1
        if perf["total"] >= 10:
            accuracy = perf["correct"] / perf["total"]
            self.brain_weights[brain_name] = max(0.3, min(accuracy * 2, 2.0))

    def get_ensemble_prediction(self, brain_predictions):
        weighted_sum = 0
        total_weight = 0
        for brain, pred in brain_predictions.items():
            weight = self.brain_weights.get(brain, 1.0)
            if isinstance(pred, dict):
                direction = pred.get("direction", 0)
                confidence = pred.get("confidence", 0)
            else:
                direction = 1 if pred > 0.5 else -1 if pred < 0.5 else 0
                confidence = abs(pred - 0.5) * 2
            weighted_sum += direction * confidence * weight
            total_weight += weight
        if total_weight == 0:
            return 0, 0
        ensemble_score = weighted_sum / total_weight
        return (1 if ensemble_score > 0 else -1 if ensemble_score < 0 else 0), abs(ensemble_score)


class AnomalyDetector:
    def __init__(self):
        self.baseline = {}
        self.threshold = 3.0

    def update_baseline(self, features):
        for k, v in features.items():
            if k not in self.baseline:
                self.baseline[k] = {"mean": v, "std": 0.001, "count": 1}
            else:
                b = self.baseline[k]
                b["count"] += 1
                delta = v - b["mean"]
                b["mean"] += delta / b["count"]
                b["std"] = np.sqrt(max(b["std"] ** 2 * (b["count"] - 1) / b["count"] + delta ** 2 / b["count"], 1e-10))

    def detect(self, features):
        anomalies = []
        for k, v in features.items():
            if k in self.baseline:
                b = self.baseline[k]
                if b["std"] > 0:
                    z_score = abs(v - b["mean"]) / b["std"]
                    if z_score > self.threshold:
                        anomalies.append({"feature": k, "value": v, "z_score": round(z_score, 2)})
        return anomalies


class BacktestEngine:
    def __init__(self):
        self.results = []

    def run_backtest(self, signals, prices, initial_balance=10000, risk_per_trade=0.01):
        balance = initial_balance
        equity_curve = [balance]
        trades = []
        position = None
        for i, signal in enumerate(signals):
            price = prices[i] if i < len(prices) else prices[-1]
            if position is None:
                if signal > 0:
                    sl = price * 0.995
                    tp = price * 1.01
                    risk_amount = balance * risk_per_trade
                    position = {"type": "BUY", "entry": price, "sl": sl, "tp": tp, "risk": risk_amount}
                elif signal < 0:
                    sl = price * 1.005
                    tp = price * 0.99
                    risk_amount = balance * risk_per_trade
                    position = {"type": "SELL", "entry": price, "sl": sl, "tp": tp, "risk": risk_amount}
            else:
                hit_sl = False
                hit_tp = False
                if position["type"] == "BUY":
                    if price <= position["sl"]:
                        hit_sl = True
                    elif price >= position["tp"]:
                        hit_tp = True
                else:
                    if price >= position["sl"]:
                        hit_sl = True
                    elif price <= position["tp"]:
                        hit_tp = True
                if hit_sl:
                    balance -= position["risk"]
                    trades.append({"result": "loss", "pnl": -position["risk"]})
                    position = None
                elif hit_tp:
                    profit = position["risk"] * 2
                    balance += profit
                    trades.append({"result": "win", "pnl": profit})
                    position = None
            equity_curve.append(balance)
        wins = sum(1 for t in trades if t["result"] == "win")
        total = len(trades)
        return {
            "final_balance": round(balance, 2),
            "total_return": round((balance - initial_balance) / initial_balance * 100, 2),
            "total_trades": total,
            "win_rate": round(wins / max(total, 1) * 100, 1),
            "max_drawdown": round(self._max_drawdown(equity_curve), 2),
            "profit_factor": self._profit_factor(trades),
        }

    @staticmethod
    def _max_drawdown(equity_curve):
        peak = equity_curve[0]
        max_dd = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd * 100

    @staticmethod
    def _profit_factor(trades):
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        return round(gross_profit / max(gross_loss, 1), 2)


class EventDrivenBacktestEngine:
    """Event-driven backtester with spread, slippage, and transaction cost modeling.

    Uses bid/ask tick data, not just close prices. Models realistic execution.
    """

    def __init__(self, spread_pips=1.5, slippage_pips=0.5, commission_per_lot=7.0,
                 risk_per_trade=0.01, max_positions=5):
        self.spread_pips = spread_pips
        self.slippage_pips = slippage_pips
        self.commission_per_lot = commission_per_lot
        self.risk_per_trade = risk_per_trade
        self.max_positions = max_positions

    def run(self, signals, bars, initial_balance=10000, pip_value=10.0):
        """Run event-driven backtest.

        Args:
            signals: list of dicts with 'action' (buy/sell/hold), 'confidence', 'sl_pips', 'tp_pips'
            bars: list of dicts with 'time', 'open', 'high', 'low', 'close', 'spread' (optional)
            initial_balance: starting balance
            pip_value: value of 1 pip per lot (e.g., 10 for EURUSD)

        Returns:
            dict with metrics
        """
        balance = initial_balance
        equity_curve = [balance]
        trades = []
        positions = []

        for i, bar in enumerate(bars):
            if i >= len(signals):
                break

            signal = signals[i]
            high = bar["high"]
            low = bar["low"]
            close = bar["close"]
            spread = bar.get("spread", self.spread_pips)

            # Check existing positions for SL/TP hits
            closed_positions = []
            for pos in positions:
                if pos["type"] == "BUY":
                    if low <= pos["sl"]:
                        pnl = (pos["sl"] - pos["entry"]) * pos["lots"] * pip_value - pos["commission"]
                        balance += pnl
                        trades.append({"result": "loss", "pnl": pnl, "bars_held": i - pos["open_bar"]})
                        closed_positions.append(pos)
                    elif high >= pos["tp"]:
                        pnl = (pos["tp"] - pos["entry"]) * pos["lots"] * pip_value - pos["commission"]
                        balance += pnl
                        trades.append({"result": "win", "pnl": pnl, "bars_held": i - pos["open_bar"]})
                        closed_positions.append(pos)
                else:  # SELL
                    if high >= pos["sl"]:
                        pnl = (pos["entry"] - pos["sl"]) * pos["lots"] * pip_value - pos["commission"]
                        balance += pnl
                        trades.append({"result": "loss", "pnl": pnl, "bars_held": i - pos["open_bar"]})
                        closed_positions.append(pos)
                    elif low <= pos["tp"]:
                        pnl = (pos["entry"] - pos["tp"]) * pos["lots"] * pip_value - pos["commission"]
                        balance += pnl
                        trades.append({"result": "win", "pnl": pnl, "bars_held": i - pos["open_bar"]})
                        closed_positions.append(pos)
            for pos in closed_positions:
                positions.remove(pos)

            # Open new position on signal
            if signal.get("action") in ("buy", "sell") and len(positions) < self.max_positions:
                sl_pips = signal.get("sl_pips", 50)
                tp_pips = signal.get("tp_pips", 100)
                confidence = signal.get("confidence", 0.5)

                # Calculate lot size based on risk
                risk_amount = balance * self.risk_per_trade * min(confidence, 1.0)
                sl_distance = sl_pips * pip_value
                lots = max(0.01, round(risk_amount / sl_distance, 2))

                # Apply spread and slippage to entry
                spread_cost = spread * pip_value * lots
                slippage_cost = self.slippage_pips * pip_value * lots
                commission = self.commission_per_lot * lots + spread_cost + slippage_cost

                if signal["action"] == "buy":
                    entry = close + (spread / 2 * pip_value / lots)  # Buy at ask
                    sl = entry - sl_pips * pip_value / lots
                    tp = entry + tp_pips * pip_value / lots
                    positions.append({
                        "type": "BUY", "entry": entry, "sl": sl, "tp": tp,
                        "lots": lots, "commission": commission, "open_bar": i,
                    })
                else:
                    entry = close - (spread / 2 * pip_value / lots)  # Sell at bid
                    sl = entry + sl_pips * pip_value / lots
                    tp = entry - tp_pips * pip_value / lots
                    positions.append({
                        "type": "SELL", "entry": entry, "sl": sl, "tp": tp,
                        "lots": lots, "commission": commission, "open_bar": i,
                    })

            # Track equity (unrealized P&L)
            unrealized = 0
            for pos in positions:
                if pos["type"] == "BUY":
                    unrealized += (close - pos["entry"]) * pos["lots"] * pip_value
                else:
                    unrealized += (pos["entry"] - close) * pos["lots"] * pip_value
            equity_curve.append(balance + unrealized)

        # Close remaining positions at last bar price
        if bars and positions:
            last_close = bars[-1]["close"]
            for pos in positions:
                if pos["type"] == "BUY":
                    pnl = (last_close - pos["entry"]) * pos["lots"] * pip_value - pos["commission"]
                else:
                    pnl = (pos["entry"] - last_close) * pos["lots"] * pip_value - pos["commission"]
                balance += pnl
                trades.append({"result": "win" if pnl > 0 else "loss", "pnl": pnl, "bars_held": len(bars) - pos["open_bar"]})

        wins = sum(1 for t in trades if t["result"] == "win")
        total = len(trades)
        gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
        gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
        avg_bars = np.mean([t["bars_held"] for t in trades]) if trades else 0

        return {
            "final_balance": round(balance, 2),
            "total_return": round((balance - initial_balance) / initial_balance * 100, 2),
            "total_trades": total,
            "win_rate": round(wins / max(total, 1) * 100, 1),
            "max_drawdown": round(self._max_drawdown(equity_curve), 2),
            "profit_factor": round(gross_profit / max(gross_loss, 1), 2),
            "avg_bars_held": round(avg_bars, 1),
            "sharpe_ratio": self._sharpe_ratio(trades),
            "recovery_factor": round((balance - initial_balance) / max(self._max_drawdown_dollars(equity_curve), 1), 2),
        }

    @staticmethod
    def _max_drawdown(equity_curve):
        peak = equity_curve[0]
        max_dd = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd * 100

    @staticmethod
    def _max_drawdown_dollars(equity_curve):
        peak = equity_curve[0]
        max_dd = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            max_dd = max(max_dd, dd)
        return max_dd

    @staticmethod
    def _sharpe_ratio(trades, risk_free_rate=0.0):
        if len(trades) < 2:
            return 0
        returns = [t["pnl"] for t in trades]
        mean_ret = np.mean(returns)
        std_ret = np.std(returns)
        if std_ret == 0:
            return 0
        return round((mean_ret - risk_free_rate) / std_ret, 2)


class PaperTrader:
    def __init__(self):
        self.balance = 10000
        self.positions = []
        self.history = []
        self.is_active = False

    def enable(self, balance=10000):
        self.balance = balance
        self.is_active = True
        self.positions = []
        self.history = []

    def disable(self):
        self.is_active = False

    def open_position(self, symbol, direction, volume, price, sl, tp):
        if not self.is_active:
            return None
        pos = {
            "id": len(self.positions) + 1,
            "symbol": symbol,
            "direction": direction,
            "volume": volume,
            "entry": price,
            "sl": sl,
            "tp": tp,
            "time": datetime.now().isoformat(),
            "status": "open",
        }
        self.positions.append(pos)
        return pos

    def close_position(self, pos_id, price):
        for pos in self.positions:
            if pos["id"] == pos_id and pos["status"] == "open":
                if pos["direction"] == 1:
                    pnl = (price - pos["entry"]) * pos["volume"] * 100000
                else:
                    pnl = (pos["entry"] - price) * pos["volume"] * 100000
                pos["status"] = "closed"
                pos["exit_price"] = price
                pos["pnl"] = round(pnl, 2)
                pos["exit_time"] = datetime.now().isoformat()
                self.balance += pnl
                self.history.append(pos.copy())
                return pnl
        return 0

    def get_status(self):
        open_pnl = 0
        for pos in self.positions:
            if pos["status"] == "open":
                tick = mt5.symbol_info_tick(pos["symbol"])
                if tick:
                    current = tick.bid if pos["direction"] == 1 else tick.ask
                    if pos["direction"] == 1:
                        open_pnl += (current - pos["entry"]) * pos["volume"] * 100000
                    else:
                        open_pnl += (pos["entry"] - current) * pos["volume"] * 100000
        return {
            "active": self.is_active,
            "balance": round(self.balance, 2),
            "equity": round(self.balance + open_pnl, 2),
            "open_positions": len([p for p in self.positions if p["status"] == "open"]),
            "total_trades": len(self.history),
            "wins": sum(1 for p in self.history if p.get("pnl", 0) > 0),
        }


_feature_store = None
_ml_scorer = None
_rl_agent = None
_ensemble = None
_anomaly = None
_backtest = None
_paper = None
_lock = threading.Lock()


def get_feature_store():
    global _feature_store
    if _feature_store is None:
        with _lock:
            if _feature_store is None:
                _feature_store = FeatureStore()
    return _feature_store


def get_ml_scorer():
    global _ml_scorer
    if _ml_scorer is None:
        with _lock:
            if _ml_scorer is None:
                _ml_scorer = MLScorer()
    return _ml_scorer


def get_rl_agent():
    global _rl_agent
    if _rl_agent is None:
        with _lock:
            if _rl_agent is None:
                _rl_agent = RLAgent()
    return _rl_agent


def get_ensemble():
    global _ensemble
    if _ensemble is None:
        with _lock:
            if _ensemble is None:
                _ensemble = EnsembleLearner()
    return _ensemble


def get_anomaly_detector():
    global _anomaly
    if _anomaly is None:
        with _lock:
            if _anomaly is None:
                _anomaly = AnomalyDetector()
    return _anomaly


def get_backtest_engine():
    global _backtest
    if _backtest is None:
        with _lock:
            if _backtest is None:
                _backtest = BacktestEngine()
    return _backtest


def get_paper_trader():
    global _paper
    if _paper is None:
        with _lock:
            if _paper is None:
                _paper = PaperTrader()
    return _paper
