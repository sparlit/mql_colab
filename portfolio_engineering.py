import numpy as np
import time as _time
import threading
import logging

logger = logging.getLogger(__name__)

# ==========================================
# ADVANCED PORTFOLIO ENGINEERING
# ==========================================


class HierarchicalRiskParity:
    def __init__(self):
        self._lock = threading.Lock()

    def allocate(self, returns_matrix):
        n = returns_matrix.shape[1]
        corr = np.corrcoef(returns_matrix.T)
        dist = np.sqrt(0.5 * (1 - corr))
        np.fill_diagonal(dist, 0)
        clusters = self._cluster(dist, n)
        weights = np.ones(n)
        self._recursive_bisection(weights, clusters, returns_matrix)
        if weights.sum() > 0:
            weights = weights / weights.sum()
        return weights

    def _cluster(self, dist, n):
        def _first_leaf(c):
            while isinstance(c, tuple):
                c = c[0]
            return c
        clusters = list(range(n))
        while len(clusters) > 1:
            min_dist = float('inf')
            merge_i, merge_j = 0, 1
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    ci = _first_leaf(clusters[i])
                    cj = _first_leaf(clusters[j])
                    d = dist[ci, cj] if ci < dist.shape[0] and cj < dist.shape[1] else 0.5
                    if d < min_dist:
                        min_dist = d
                        merge_i, merge_j = i, j
            new_cluster = (clusters[merge_i], clusters[merge_j])
            clusters = [clusters[k] for k in range(len(clusters)) if k not in (merge_i, merge_j)]
            clusters.append(new_cluster)
        return clusters[0] if clusters else ()

    def _recursive_bisection(self, weights, assets, returns):
        if isinstance(assets, int):
            return
        if not isinstance(assets, tuple) or len(assets) <= 1:
            return

        def _get_leaves(a):
            if isinstance(a, int):
                return [a]
            result = []
            for item in a:
                result.extend(_get_leaves(item))
            return result

        left_sub = assets[0]
        right_sub = assets[1]
        left_idx = [i for i in _get_leaves(left_sub) if i < returns.shape[1]]
        right_idx = [i for i in _get_leaves(right_sub) if i < returns.shape[1]]
        left_vol = np.mean([np.std(returns[:, i]) for i in left_idx]) if left_idx else 0.01
        right_vol = np.mean([np.std(returns[:, i]) for i in right_idx]) if right_idx else 0.01
        total = left_vol + right_vol
        if total > 0:
            left_alloc = right_vol / total
            right_alloc = left_vol / total
        else:
            left_alloc = 0.5
            right_alloc = 0.5
        for i in left_idx:
            weights[i] *= left_alloc
        for i in right_idx:
            weights[i] *= right_alloc
        self._recursive_bisection(weights, left_sub, returns)
        self._recursive_bisection(weights, right_sub, returns)


class BlackLitterman:
    def __init__(self):
        self._lock = threading.Lock()

    def estimate(self, market_caps, covariance, views, view_confidences):
        n = len(market_caps)
        total_cap = sum(market_caps.values())
        w_mkt = np.array([market_caps[s] / total_cap for s in market_caps.keys()])
        risk_aversion = 2.5
        pi = risk_aversion * covariance @ w_mkt
        P = np.zeros((len(views), n))
        Q = np.zeros(len(views))
        symbols = list(market_caps.keys())
        for i, (sym, view) in enumerate(views.items()):
            if sym in symbols:
                idx = symbols.index(sym)
                P[i, idx] = 1
                Q[i] = view
        tau = 0.05
        omega = np.diag([view_confidences.get(k, 0.5) for k in views.keys()])
        sigma_prior = covariance * tau
        M1 = np.linalg.inv(sigma_prior)
        M2 = P.T @ np.linalg.inv(omega) @ P
        posterior_mean = np.linalg.inv(M1 + M2) @ (M1 @ pi + P.T @ np.linalg.inv(omega) @ Q)
        posterior_cov = np.linalg.inv(M1 + M2)
        w_bl = np.linalg.inv(risk_aversion * posterior_cov) @ posterior_mean
        w_bl = np.maximum(w_bl, 0)
        if w_bl.sum() > 0:
            w_bl = w_bl / w_bl.sum()
        return {s: round(w, 4) for s, w in zip(symbols, w_bl)}


class CVaROptimizer:
    def __init__(self):
        self._lock = threading.Lock()

    def optimize(self, returns_matrix, alpha=0.05, target_return=None):
        n = returns_matrix.shape[1]
        mean_returns = np.mean(returns_matrix, axis=0)
        sorted_returns = np.sort(returns_matrix, axis=0)
        cutoff = int(len(sorted_returns) * alpha)
        cvar_per_asset = -np.mean(sorted_returns[:cutoff], axis=0)
        weights = 1.0 / (cvar_per_asset + 1e-10)
        weights = np.maximum(weights, 0)
        if weights.sum() > 0:
            weights = weights / weights.sum()
        return weights


class ConstrainedKelly:
    def __init__(self):
        self.max_fraction = 0.05
        self.min_fraction = 0.01
        self.max_drawdown_limit = 0.1
        self._lock = threading.Lock()

    def calculate(self, win_rate, avg_win, avg_loss, current_dd=0):
        if avg_loss == 0:
            return self.min_fraction
        win_loss_ratio = avg_win / avg_loss
        kelly = win_rate - (1 - win_rate) / win_loss_ratio
        kelly = max(0, kelly)
        kelly_half = kelly * 0.5
        if current_dd > self.max_drawdown_limit * 0.5:
            kelly_half *= 0.5
        if current_dd > self.max_drawdown_limit * 0.8:
            kelly_half *= 0.2
        kelly_half = max(self.min_fraction, min(kelly_half, self.max_fraction))
        return round(kelly_half, 4)


class PortfolioRebalancer:
    def __init__(self):
        self.target_weights = {}
        self.current_weights = {}
        self.threshold = 0.05
        self._lock = threading.Lock()

    def set_targets(self, weights):
        with self._lock:
            self.target_weights = weights

    def check_drift(self, current_weights):
        with self._lock:
            target = self.target_weights
        if not target:
            return False, {}
        drifts = {}
        needs_rebalance = False
        for symbol in set(list(target.keys()) + list(current_weights.keys())):
            target_w = target.get(symbol, 0)
            current_w = current_weights.get(symbol, 0)
            drift = abs(target_w - current_w)
            drifts[symbol] = round(drift, 4)
            if drift > self.threshold:
                needs_rebalance = True
        return needs_rebalance, drifts

    def generate_orders(self, current_weights, portfolio_value):
        with self._lock:
            target = self.target_weights
        orders = []
        for symbol in set(list(target.keys()) + list(current_weights.keys())):
            target_w = target.get(symbol, 0)
            current_w = current_weights.get(symbol, 0)
            diff = target_w - current_w
            if abs(diff) > 0.01:
                value = portfolio_value * diff
                orders.append({"symbol": symbol, "action": "buy" if diff > 0 else "sell", "value": round(value, 2), "weight_change": round(diff, 4)})
        return orders


_hrp = None
_bl = None
_cvar = None
_kelly = None
_rebalancer = None
_lock = threading.Lock()


def get_hrp():
    global _hrp
    if _hrp is None:
        with _lock:
            if _hrp is None:
                _hrp = HierarchicalRiskParity()
    return _hrp


def get_black_litterman():
    global _bl
    if _bl is None:
        with _lock:
            if _bl is None:
                _bl = BlackLitterman()
    return _bl


def get_cvar_optimizer():
    global _cvar
    if _cvar is None:
        with _lock:
            if _cvar is None:
                _cvar = CVaROptimizer()
    return _cvar


def get_constrained_kelly():
    global _kelly
    if _kelly is None:
        with _lock:
            if _kelly is None:
                _kelly = ConstrainedKelly()
    return _kelly


def get_rebalancer():
    global _rebalancer
    if _rebalancer is None:
        with _lock:
            if _rebalancer is None:
                _rebalancer = PortfolioRebalancer()
    return _rebalancer
