import numpy as np
import time as _time
import threading
import logging
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)

# ==========================================
# RESEARCH & DEVELOPMENT
# ==========================================


class AlphaDecayAnalyzer:
    def __init__(self):
        self.alpha_history = deque(maxlen=500)
        self._lock = threading.Lock()

    def record_alpha(self, strategy_name, alpha, timestamp=None):
        with self._lock:
            self.alpha_history.append({
                "strategy": strategy_name,
                "alpha": alpha,
                "time": timestamp or datetime.now().isoformat(),
            })

    def analyze_decay(self, strategy_name, window=50):
        with self._lock:
            alphas = [a["alpha"] for a in self.alpha_history if a["strategy"] == strategy_name]
        if len(alphas) < window:
            return {"decay": False, "current_alpha": alphas[-1] if alphas else 0}
        recent = alphas[-window:]
        older = alphas[-window*2:-window] if len(alphas) >= window * 2 else alphas[:window]
        recent_avg = np.mean(recent)
        older_avg = np.mean(older)
        decay = older_avg - recent_avg
        decay_rate = decay / max(abs(older_avg), 1e-10)
        return {
            "decay": decay_rate > 0.1,
            "decay_rate": round(decay_rate, 4),
            "current_alpha": round(recent_avg, 4),
            "previous_alpha": round(older_avg, 4),
            "change": round(recent_avg - older_avg, 4),
        }

    def get_all_strategies(self):
        with self._lock:
            strategies = set(a["strategy"] for a in self.alpha_history)
        return {s: self.analyze_decay(s) for s in strategies}


class FactorExposureAnalyzer:
    def __init__(self):
        self.returns_history = deque(maxlen=1000)
        self._lock = threading.Lock()

    def record_return(self, portfolio_return, factors):
        with self._lock:
            self.returns_history.append({"return": portfolio_return, "factors": factors})

    def analyze(self, lookback=100):
        with self._lock:
            data = list(self.returns_history)[-lookback:]
        if len(data) < 20:
            return {}
        returns = [d["return"] for d in data]
        factor_names = list(data[0]["factors"].keys())
        factor_exposures = {}
        for factor in factor_names:
            factor_values = [d["factors"].get(factor, 0) for d in data]
            if np.std(factor_values) > 0:
                corr = np.corrcoef(returns, factor_values)[0, 1]
                beta = np.polyfit(factor_values, returns, 1)[0]
                factor_exposures[factor] = {"beta": round(beta, 4), "correlation": round(corr, 4)}
        portfolio_vol = np.std(returns) * np.sqrt(252)
        return {"factor_exposures": factor_exposures, "portfolio_volatility": round(portfolio_vol, 4)}


class CrossValidationFramework:
    def __init__(self):
        self._lock = threading.Lock()

    def k_fold_cross_validate(self, X, y, model_func, k=5):
        n = len(X)
        fold_size = n // k
        scores = []
        for i in range(k):
            test_start = i * fold_size
            test_end = min(test_start + fold_size, n)
            X_train = np.concatenate([X[:test_start], X[test_end:]])
            y_train = np.concatenate([y[:test_start], y[test_end:]])
            X_test = X[test_start:test_end]
            y_test = y[test_start:test_end]
            model = model_func(X_train, y_train)
            predictions = model(X_test)
            accuracy = np.mean((predictions > 0.5) == (y_test > 0.5))
            scores.append(accuracy)
        return {
            "mean_accuracy": round(np.mean(scores), 4),
            "std_accuracy": round(np.std(scores), 4),
            "fold_scores": [round(s, 4) for s in scores],
            "overfitting_risk": "high" if np.std(scores) > 0.1 else "low",
        }

    def walk_forward_validate(self, X, y, model_func, train_pct=0.7, n_splits=5):
        n = len(X)
        split_size = n // n_splits
        scores = []
        for i in range(n_splits):
            train_end = int(n * train_pct) + i * split_size
            test_end = min(train_end + split_size, n)
            if test_end > n or train_end >= n:
                break
            X_train = X[:train_end]
            y_train = y[:train_end]
            X_test = X[train_end:test_end]
            y_test = y[train_end:test_end]
            if len(X_test) == 0:
                continue
            model = model_func(X_train, y_train)
            predictions = model(X_test)
            accuracy = np.mean((predictions > 0.5) == (y_test > 0.5))
            scores.append(accuracy)
        return {
            "mean_accuracy": round(np.mean(scores), 4) if scores else 0,
            "std_accuracy": round(np.std(scores), 4) if scores else 0,
            "n_splits": len(scores),
        }


class WalkForwardOptimizer:
    def __init__(self):
        self._lock = threading.Lock()

    def optimize(self, strategy_func, param_grid, X, y, train_pct=0.7, n_splits=5):
        n = len(X)
        split_size = n // n_splits
        best_params = None
        best_score = -float('inf')
        all_results = []
        for i in range(n_splits):
            train_end = int(n * train_pct) + i * split_size
            test_end = min(train_end + split_size, n)
            if test_end > n or train_end >= n:
                break
            X_train = X[:train_end]
            y_train = y[:train_end]
            X_test = X[train_end:test_end]
            y_test = y[train_end:test_end]
            if len(X_test) == 0:
                continue
            for params in param_grid:
                try:
                    score = strategy_func(X_train, y_train, X_test, y_test, params)
                    all_results.append({"split": i, "params": params, "score": score})
                    if score > best_score:
                        best_score = score
                        best_params = params
                except Exception as e:
                    logger.debug("Walk-forward test failed: %s", e)
                    continue
        return {
            "best_params": best_params,
            "best_score": round(best_score, 4),
            "total_tests": len(all_results),
            "results": all_results[-10:],
        }


_alpha_decay = None
_factor = None
_cross_val = None
_walk_forward = None
_lock = threading.Lock()

