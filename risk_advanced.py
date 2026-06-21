import mt5_mcp as mt5
import numpy as np
import time as _time
import threading
import logging
from collections import deque

logger = logging.getLogger(__name__)

# ==========================================
# ADVANCED RISK MANAGEMENT
# ==========================================


class CorrelationStressTest:
    def __init__(self):
        self._lock = threading.Lock()

    def stress_test(self, portfolio, correlation_matrix, shock=-0.05):
        results = {}
        for symbol, pos in portfolio.items():
            shock_impact = shock * pos.get("exposure", 0)
            corr_impact = 0
            for other_symbol, other_pos in portfolio.items():
                if other_symbol != symbol:
                    corr = correlation_matrix.get(f"{symbol}_{other_symbol}", 0)
                    corr_impact += corr * shock * other_pos.get("exposure", 0) * 0.5
            total_impact = shock_impact + corr_impact
            results[symbol] = {"direct_shock": round(shock_impact, 2), "correlation_impact": round(corr_impact, 2), "total_impact": round(total_impact, 2)}
        total_loss = sum(r["total_impact"] for r in results.values())
        return {"results": results, "total_portfolio_loss": round(total_loss, 2), "shock_applied": shock}


class TailRiskHedge:
    def __init__(self):
        self.hedge_positions = deque(maxlen=10)

    def calculate_hedge(self, portfolio_value, current_dd):
        if current_dd > 0.02:
            hedge_ratio = min(0.1, current_dd * 2)
            hedge_value = portfolio_value * hedge_ratio
            return {"hedge_needed": True, "hedge_value": round(hedge_value, 2), "instrument": "XAUUSD", "direction": 1, "reason": f"DD at {current_dd:.1%}"}
        return {"hedge_needed": False}


class RiskParity:
    def __init__(self):
        self._lock = threading.Lock()

    def calculate_weights(self, symbols, returns_data):
        if not returns_data:
            return {s: 1.0 / len(symbols) for s in symbols}
        vols = {}
        for sym in symbols:
            if sym in returns_data and len(returns_data[sym]) > 10:
                vols[sym] = np.std(returns_data[sym])
            else:
                vols[sym] = 0.01
        inv_vols = {s: 1.0 / max(v, 0.001) for s, v in vols.items()}
        total = sum(inv_vols.values())
        weights = {s: inv_vols[s] / total for s in symbols}
        return weights

    def allocate(self, portfolio_value, weights):
        allocations = {}
        for symbol, weight in weights.items():
            allocations[symbol] = round(portfolio_value * weight, 2)
        return allocations


class RegimeAllocator:
    def __init__(self):
        self.allocations = {
            "trending": {"forex": 0.4, "indices": 0.3, "commodities": 0.2, "crypto": 0.1},
            "ranging": {"forex": 0.5, "indices": 0.2, "commodities": 0.2, "crypto": 0.1},
            "volatile": {"forex": 0.3, "indices": 0.1, "commodities": 0.3, "crypto": 0.3},
            "safe_haven": {"forex": 0.2, "indices": 0.1, "commodities": 0.4, "crypto": 0.0, "gold": 0.3},
        }

    def get_allocation(self, regime):
        return self.allocations.get(regime, self.allocations["ranging"])

    def get_regime(self, volatility, trend_strength):
        if volatility > 1.5:
            return "volatile"
        elif trend_strength > 0.6:
            return "trending"
        elif abs(trend_strength) < 0.2:
            return "ranging"
        return "trending"


class BlackSwanDetector:
    def __init__(self):
        self.price_history = deque(maxlen=1000)
        self._lock = threading.Lock()

    def record(self, price):
        with self._lock:
            self.price_history.append({"time": _time.time(), "price": price})

    def detect(self, lookback=100):
        with self._lock:
            history = list(self.price_history)[-lookback:]
        if len(history) < 20:
            return {"detected": False, "severity": 0}
        prices = [h["price"] for h in history]
        returns = np.diff(prices) / prices[:-1]
        if len(returns) < 10:
            return {"detected": False, "severity": 0}
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        recent_return = returns[-1] if len(returns) > 0 else 0
        if std_return > 0:
            z_score = (recent_return - mean_return) / std_return
        else:
            z_score = 0
        if abs(z_score) > 3:
            severity = min(abs(z_score) / 5, 1.0)
            return {"detected": True, "severity": round(severity, 2), "z_score": round(z_score, 2), "type": "crash" if z_score < 0 else "spike"}
        return {"detected": False, "severity": 0, "z_score": round(z_score, 2)}


class AdvancedRiskManager:
    def __init__(self):
        self.stress_test = CorrelationStressTest()
        self.tail_hedge = TailRiskHedge()
        self.risk_parity = RiskParity()
        self.regime_alloc = RegimeAllocator()
        self.black_swan = BlackSwanDetector()

    def full_risk_assessment(self):
        acct = mt5.account_info()
        if not acct:
            return {}
        dd = max(0, (acct.balance - acct.equity) / acct.balance) if acct.balance > 0 else 0
        black_swan = self.black_swan.detect()
        tail_hedge = self.tail_hedge.calculate_hedge(acct.equity, dd)
        return {
            "drawdown": round(dd, 4),
            "black_swan": black_swan,
            "tail_hedge": tail_hedge,
            "risk_level": "critical" if dd > 0.05 or black_swan["detected"] else "high" if dd > 0.03 else "normal",
        }


_risk = None
_lock = threading.Lock()


def get_advanced_risk():
    global _risk
    if _risk is None:
        with _lock:
            if _risk is None:
                _risk = AdvancedRiskManager()
    return _risk
