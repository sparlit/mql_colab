import numpy as np
import time as _time
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ==========================================
# QUANTITATIVE FINANCE MODELS
# ==========================================


class MonteCarloSimulator:
    def __init__(self):
        self._lock = threading.Lock()

    def simulate_trades(self, win_rate, avg_win, avg_loss, n_trades=1000, n_simulations=1000):
        results = []
        for _ in range(n_simulations):
            balance = 10000
            peak = balance
            max_dd = 0
            for _ in range(n_trades):
                if np.random.random() < win_rate:
                    balance += avg_win
                else:
                    balance -= avg_loss
                if balance > peak:
                    peak = balance
                dd = (peak - balance) / peak if peak > 0 else 0
                max_dd = max(max_dd, dd)
            results.append({"final": balance, "return": (balance - 10000) / 10000, "max_dd": max_dd})
        returns = [r["return"] for r in results]
        dds = [r["max_dd"] for r in results]
        return {
            "mean_return": round(np.mean(returns) * 100, 2),
            "median_return": round(np.median(returns) * 100, 2),
            "std_return": round(np.std(returns) * 100, 2),
            "prob_profit": round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
            "var_95": round(np.percentile(returns, 5) * 100, 2),
            "cvar_95": round(np.mean([r for r in returns if r <= np.percentile(returns, 5)]) * 100, 2),
            "max_dd_avg": round(np.mean(dds) * 100, 2),
            "max_dd_worst": round(max(dds) * 100, 2),
            "simulations": n_simulations,
        }


class GARCHModel:
    def __init__(self):
        self.alpha = 0.1
        self.beta = 0.85
        self.omega = 0.000001
        self.volatility = 0.01
        self._lock = threading.Lock()

    def update(self, returns):
        if len(returns) < 2:
            return self.volatility
        r = returns[-1]
        self.volatility = np.sqrt(self.omega + self.alpha * r ** 2 + self.beta * self.volatility ** 2)
        return self.volatility

    def forecast(self, steps=10):
        forecasts = []
        vol = self.volatility
        last_r = 0
        for _ in range(steps):
            vol = np.sqrt(self.omega + self.alpha * last_r ** 2 + self.beta * vol ** 2)
            last_r = 0
            forecasts.append(vol)
        return forecasts

    def get_regime(self):
        if self.volatility > 0.02:
            return "high_vol"
        elif self.volatility < 0.005:
            return "low_vol"
        return "normal"


class KalmanFilter:
    def __init__(self):
        self.state = 0
        self.covariance = 1
        self.Q = 0.01
        self.R = 0.1
        self._lock = threading.Lock()

    def update(self, measurement):
        prediction = self.state
        prediction_cov = self.covariance + self.Q
        kalman_gain = prediction_cov / (prediction_cov + self.R)
        self.state = prediction + kalman_gain * (measurement - prediction)
        self.covariance = (1 - kalman_gain) * prediction_cov
        return self.state

    def get_state(self):
        return self.state

    def get_uncertainty(self):
        return np.sqrt(self.covariance)

    def filter_series(self, measurements):
        results = []
        for m in measurements:
            results.append(self.update(m))
        return results


class HiddenMarkovModel:
    def __init__(self, n_states=3):
        self.n_states = n_states
        self.transition = np.ones((n_states, n_states)) / n_states
        self.means = np.random.randn(n_states)
        self.stds = np.ones(n_states)
        self.state_probs = np.ones(n_states) / n_states
        self._lock = threading.Lock()

    def forward(self, observation):
        likelihood = np.exp(-0.5 * ((observation - self.means) / self.stds) ** 2) / (self.stds * np.sqrt(2 * np.pi))
        likelihood = np.maximum(likelihood, 1e-10)
        predicted = self.transition.T @ self.state_probs
        predicted = np.maximum(predicted, 1e-10)
        updated = likelihood * predicted
        updated /= updated.sum()
        self.state_probs = updated
        return self.state_probs

    def predict(self):
        return self.state_probs

    def get_most_likely_state(self):
        return int(np.argmax(self.state_probs))

    def get_state_name(self, state):
        names = ["trending", "ranging", "volatile"]
        return names[state] if state < len(names) else f"state_{state}"


class CopulaModel:
    def __init__(self):
        self._lock = threading.Lock()

    def gaussian_copula(self, data1, data2):
        if len(data1) < 20 or len(data2) < 20:
            return {"correlation": 0, "tail_dep": 0}
        min_len = min(len(data1), len(data2))
        d1 = data1[-min_len:]
        d2 = data2[-min_len:]
        try:
            from scipy import stats
            u1 = stats.rankdata(d1) / (len(d1) + 1)
            u2 = stats.rankdata(d2) / (len(d2) + 1)
            n1 = stats.norm.ppf(u1)
            n2 = stats.norm.ppf(u2)
        except ImportError:
            def _rankdata(arr):
                return arr.argsort().argsort().astype(float) + 1
            u1 = _rankdata(np.asarray(d1, dtype=float)) / (len(d1) + 1)
            u2 = _rankdata(np.asarray(d2, dtype=float)) / (len(d2) + 1)
            n1 = np.where(u1 > 0.999, 3, np.where(u1 < 0.001, -3, np.sqrt(2) * np.erfinv(2 * u1 - 1)))
            n2 = np.where(u2 > 0.999, 3, np.where(u2 < 0.001, -3, np.sqrt(2) * np.erfinv(2 * u2 - 1)))
        corr = np.corrcoef(n1, n2)[0, 1]
        lower_tail = np.mean((u1 < 0.1) & (u2 < 0.1))
        upper_tail = np.mean((u1 > 0.9) & (u2 > 0.9))
        return {
            "correlation": round(corr, 4),
            "lower_tail_dep": round(lower_tail, 4),
            "upper_tail_dep": round(upper_tail, 4),
        }


class RegimeSwitchingModel:
    def __init__(self):
        self.regimes = ["bull", "bear", "sideways"]
        self.transition_probs = np.array([
            [0.9, 0.05, 0.05],
            [0.05, 0.9, 0.05],
            [0.1, 0.1, 0.8],
        ])
        self.current_regime = 1
        self._lock = threading.Lock()

    def detect_regime(self, returns):
        if len(returns) < 20:
            return "unknown"
        recent = returns[-20:]
        mean_r = np.mean(recent)
        vol_r = np.std(recent)
        if mean_r > 0.001 and vol_r < 0.02:
            regime = 0
        elif mean_r < -0.001 and vol_r < 0.02:
            regime = 1
        elif vol_r > 0.025:
            regime = 2
        else:
            regime = self.current_regime
        self.current_regime = regime
        return self.regimes[regime]

    def get_transition_prob(self):
        return self.transition_probs[self.current_regime].tolist()


class BayesianOptimizer:
    def __init__(self):
        self.observations = []
        self._lock = threading.Lock()

    def suggest_next(self, bounds):
        if len(self.observations) < 5:
            return {k: np.random.uniform(v[0], v[1]) for k, v in bounds.items()}
        params = [o["params"] for o in self.observations]
        scores = [o["score"] for o in self.observations]
        best_idx = np.argmax(scores)
        best_params = params[best_idx]
        suggestion = {}
        for k, (low, high) in bounds.items():
            noise = np.random.normal(0, (high - low) * 0.1)
            suggestion[k] = np.clip(best_params.get(k, (low + high) / 2) + noise, low, high)
        return suggestion

    def record(self, params, score):
        with self._lock:
            self.observations.append({"params": params, "score": score, "time": datetime.now().isoformat()})

    def get_best(self):
        if not self.observations:
            return None
        return max(self.observations, key=lambda x: x["score"])
