import mt5_mcp as mt5
import numpy as np
import time as _time
import threading
import logging
from collections import deque
from config import (
    DATA_DIR, is_system_magic,
)

logger = logging.getLogger(__name__)

# ==========================================
# PORTFOLIO & RISK MANAGEMENT
# ==========================================
MAX_PORTFOLIO_RISK = 0.02
MAX_CORRELATION_EXPOSURE = 0.3
DRAWDOWN_REDUCE_THRESHOLD = 0.03
DRAWDOWN_HALT_THRESHOLD = 0.05
RECOVERY_SCALE_FACTOR = 0.5


class PortfolioOptimizer:
    def __init__(self):
        self.positions = {}
        self._lock = threading.Lock()

    def get_portfolio_state(self):
        positions = mt5.positions_get()
        my_pos = [p for p in (positions or []) if is_system_magic(p.magic)]
        portfolio = {}
        total_exposure = 0
        for p in my_pos:
            info = mt5.symbol_info(p.symbol)
            point = info.point if info else 0.0001
            exposure = p.volume * p.price_current
            total_exposure += abs(exposure)
            portfolio[p.ticket] = {
                "symbol": p.symbol,
                "type": "BUY" if p.type == 0 else "SELL",
                "volume": p.volume,
                "entry": p.price_open,
                "current": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": p.profit,
                "exposure": abs(exposure),
            }
        acct = mt5.account_info()
        if acct:
            for ticket in portfolio:
                portfolio[ticket]["weight"] = portfolio[ticket]["exposure"] / max(total_exposure, 1)
        return {"positions": portfolio, "total_exposure": total_exposure, "count": len(my_pos)}

    def calculate_optimal_size(self, symbol, direction, confidence, correlation_matrix=None):
        acct = mt5.account_info()
        if not acct:
            return 0.01
        info = mt5.symbol_info(symbol)
        if not info:
            return 0.01
        base_risk = acct.balance * 0.01
        dd = self._get_drawdown()
        if dd > DRAWDOWN_REDUCE_THRESHOLD:
            reduction = max(0.3, 1 - (dd - DRAWDOWN_REDUCE_THRESHOLD) / 0.05)
            base_risk *= reduction
        if confidence > 0.8:
            base_risk *= 1.2
        elif confidence < 0.6:
            base_risk *= 0.6
        tick_value = info.trade_tick_value
        tick_size = info.trade_tick_size
        if tick_value == 0 or tick_size == 0:
            return 0.01
        sl_distance = 100 * info.point
        lot = base_risk / (sl_distance / tick_size * tick_value)
        lot = max(info.volume_min, min(lot, info.volume_max))
        lot = round(lot / info.volume_step) * info.volume_step
        return round(lot, 2)

    def _get_drawdown(self):
        acct = mt5.account_info()
        if not acct:
            return 0
        if acct.balance > 0:
            return max(0, (acct.balance - acct.equity) / acct.balance)
        return 0


class VaRCalculator:
    def __init__(self):
        self.returns_history = deque(maxlen=1000)

    def calculate_var(self, confidence=0.95, window=100):
        if len(self.returns_history) < 20:
            return 0
        returns = list(self.returns_history)[-window:]
        sorted_returns = sorted(returns)
        idx = int((1 - confidence) * len(sorted_returns))
        return abs(sorted_returns[idx]) if idx < len(sorted_returns) else 0

    def calculate_cvar(self, confidence=0.95, window=100):
        if len(self.returns_history) < 20:
            return 0
        returns = list(self.returns_history)[-window:]
        sorted_returns = sorted(returns)
        idx = int((1 - confidence) * len(sorted_returns))
        tail = sorted_returns[:idx + 1]
        return abs(np.mean(tail)) if tail else 0

    def record_return(self, ret):
        self.returns_history.append(ret)

    def get_risk_report(self):
        var_95 = self.calculate_var(0.95)
        var_99 = self.calculate_var(0.99)
        cvar_95 = self.calculate_cvar(0.95)
        returns = list(self.returns_history)
        if returns:
            volatility = np.std(returns) * np.sqrt(252)
            sharpe = np.mean(returns) / max(np.std(returns), 1e-10) * np.sqrt(252)
        else:
            volatility = 0
            sharpe = 0
        return {
            "var_95": round(var_95, 4),
            "var_99": round(var_99, 4),
            "cvar_95": round(cvar_95, 4),
            "volatility": round(volatility, 4),
            "sharpe": round(sharpe, 2),
        }


class HedgingEngine:
    def __init__(self):
        self.hedge_rules = {
            "EURUSD_USDJPY": {"correlation": -0.7, "hedge_ratio": 0.8},
            "XAUUSD_XAGUSD": {"correlation": 0.85, "hedge_ratio": 0.3},
            "US500_NAS100": {"correlation": 0.9, "hedge_ratio": 0.5},
        }

    def check_hedge_needed(self, portfolio_state):
        positions = portfolio_state.get("positions", {})
        if len(positions) < 2:
            return False, {}
        symbols = [p["symbol"] for p in positions.values()]
        for rule_name, rule in self.hedge_rules.items():
            pair = rule_name.split("_")
            if all(s in symbols for s in pair):
                return True, {"rule": rule_name, "ratio": rule["hedge_ratio"]}
        return False, {}

    def calculate_hedge_size(self, position, hedge_ratio):
        return round(position["volume"] * hedge_ratio, 2)


class DrawdownCircuit:
    def __init__(self):
        self.peak_equity = 0
        self.circuit_open = False
        self.status = "normal"

    def update(self):
        acct = mt5.account_info()
        if not acct:
            return self.status
        if acct.equity > self.peak_equity:
            self.peak_equity = acct.equity
        dd = (self.peak_equity - acct.equity) / self.peak_equity if self.peak_equity > 0 else 0
        if dd >= DRAWDOWN_HALT_THRESHOLD:
            self.status = "halted"
            self.circuit_open = True
        elif dd >= DRAWDOWN_REDUCE_THRESHOLD:
            self.status = "reduced"
            self.circuit_open = False
        else:
            self.status = "normal"
            self.circuit_open = False
        return self.status

    def get_size_multiplier(self):
        if self.status == "halted":
            return 0
        elif self.status == "reduced":
            return RECOVERY_SCALE_FACTOR
        return 1.0


class RecoveryMode:
    def __init__(self):
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.mode = "normal"
        self._lock = threading.Lock()

    def record_trade(self, won):
        with self._lock:
            if won:
                self.consecutive_wins += 1
                self.consecutive_losses = 0
            else:
                self.consecutive_losses += 1
                self.consecutive_wins = 0
            if self.consecutive_losses >= 5:
                self.mode = "halted"
            elif self.consecutive_losses >= 3:
                self.mode = "conservative"
            elif self.consecutive_wins >= 3:
                self.mode = "aggressive"
            else:
                self.mode = "normal"

    def get_size_multiplier(self):
        if self.mode == "halted":
            return 0
        elif self.mode == "conservative":
            return 0.5
        elif self.mode == "aggressive":
            return 1.3
        return 1.0


class PortfolioManager:
    def __init__(self):
        self.optimizer = PortfolioOptimizer()
        self.var_calc = VaRCalculator()
        self.hedger = HedgingEngine()
        self.drawdown = DrawdownCircuit()
        self.recovery = RecoveryMode()

    def get_full_risk_assessment(self):
        portfolio = self.optimizer.get_portfolio_state()
        self.drawdown.update()
        var_report = self.var_calc.get_risk_report()
        need_hedge, hedge_info = self.hedger.check_hedge_needed(portfolio)
        return {
            "portfolio": portfolio,
            "drawdown_status": self.drawdown.status,
            "size_multiplier": self.drawdown.get_size_multiplier() * self.recovery.get_size_multiplier(),
            "recovery_mode": self.recovery.mode,
            "var": var_report,
            "hedge_needed": need_hedge,
            "hedge_info": hedge_info,
        }


_portfolio = None
_lock = threading.Lock()


def get_portfolio_manager():
    global _portfolio
    if _portfolio is None:
        with _lock:
            if _portfolio is None:
                _portfolio = PortfolioManager()
    return _portfolio
