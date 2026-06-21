import mt5_mcp as mt5
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
# DATA & ANALYTICS
# ==========================================


class TickDatabase:
    def __init__(self):
        self.ticks = deque(maxlen=100000)
        self._lock = threading.Lock()
        os.makedirs(os.path.join(DATA_DIR, "ticks"), exist_ok=True)

    def record_tick(self, symbol, tick):
        with self._lock:
            self.ticks.append({
                "time": datetime.now().isoformat(),
                "symbol": symbol,
                "bid": tick.bid,
                "ask": tick.ask,
                "last": tick.last,
                "volume": tick.volume,
            })

    def get_ticks(self, symbol, n=1000):
        with self._lock:
            return [t for t in self.ticks if t["symbol"] == symbol][-n:]

    def save_to_file(self, symbol):
        ticks = self.get_ticks(symbol, 10000)
        if not ticks:
            return
        path = os.path.join(DATA_DIR, "ticks", f"{symbol}_{datetime.now().strftime('%Y%m%d')}.json")
        try:
            with open(path, "w") as f:
                json.dump(ticks, f)
        except (OSError, IOError) as e:
            logger.debug("Tick save failed for %s: %s", symbol, e)


class RealTimePnL:
    def __init__(self):
        self.equity_curve = deque(maxlen=5000)
        self._lock = threading.Lock()

    def record(self):
        acct = mt5.account_info()
        if acct:
            with self._lock:
                self.equity_curve.append({
                    "time": datetime.now().isoformat(),
                    "equity": acct.equity,
                    "balance": acct.balance,
                    "profit": acct.profit,
                })

    def get_curve(self, n=200):
        with self._lock:
            return list(self.equity_curve)[-n:]

    def get_stats(self):
        with self._lock:
            curve = list(self.equity_curve)
        if len(curve) < 2:
            return {}
        equities = [c["equity"] for c in curve]
        returns = np.diff(equities) / equities[:-1]
        peak = equities[0]
        max_dd = 0
        for eq in equities:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return {
            "current_equity": equities[-1],
            "total_return": round((equities[-1] - equities[0]) / equities[0] * 100, 2),
            "max_drawdown": round(max_dd * 100, 2),
            "volatility": round(np.std(returns) * 100, 4) if len(returns) > 1 else 0,
            "data_points": len(curve),
        }


class TradeReplay:
    def __init__(self):
        self.trades = []
        self._lock = threading.Lock()

    def record_trade(self, ticket, symbol, direction, entry, sl, tp, exit_price, profit, duration):
        with self._lock:
            self.trades.append({
                "ticket": ticket, "symbol": symbol, "direction": direction,
                "entry": entry, "sl": sl, "tp": tp, "exit": exit_price,
                "profit": profit, "duration": duration,
                "time": datetime.now().isoformat(),
            })

    def get_trades(self, n=50):
        with self._lock:
            return self.trades[-n:]

    def replay_trade(self, trade):
        steps = []
        entry = trade["entry"]
        exit_p = trade["exit"]
        sl = trade["sl"]
        tp = trade["tp"]
        n_steps = 20
        for i in range(n_steps):
            progress = i / n_steps
            price = entry + (exit_p - entry) * progress
            hit_sl = (trade["direction"] == 1 and price <= sl) or (trade["direction"] == -1 and price >= sl)
            hit_tp = (trade["direction"] == 1 and price >= tp) or (trade["direction"] == -1 and price <= tp)
            steps.append({"step": i + 1, "price": round(price, 5), "hit_sl": hit_sl, "hit_tp": hit_tp})
        return steps


class PerformanceAttribution:
    def __init__(self):
        self.brain_pnl = {}
        self._lock = threading.Lock()

    def record(self, brain_name, pnl):
        with self._lock:
            if brain_name not in self.brain_pnl:
                self.brain_pnl[brain_name] = {"pnl": 0, "trades": 0, "wins": 0}
            self.brain_pnl[brain_name]["pnl"] += pnl
            self.brain_pnl[brain_name]["trades"] += 1
            if pnl > 0:
                self.brain_pnl[brain_name]["wins"] += 1

    def get_attribution(self):
        with self._lock:
            data = dict(self.brain_pnl)
        result = {}
        for brain, stats in data.items():
            wr = stats["wins"] / max(stats["trades"], 1) * 100
            result[brain] = {
                "total_pnl": round(stats["pnl"], 2),
                "trades": stats["trades"],
                "win_rate": round(wr, 1),
                "avg_pnl": round(stats["pnl"] / max(stats["trades"], 1), 2),
            }
        return result


class LiveCorrelationMatrix:
    def __init__(self):
        self.price_data = {}
        self._lock = threading.Lock()

    def update(self, symbol, price):
        with self._lock:
            if symbol not in self.price_data:
                self.price_data[symbol] = deque(maxlen=500)
            self.price_data[symbol].append(price)

    def get_matrix(self):
        with self._lock:
            symbols = list(self.price_data.keys())
            if len(symbols) < 2:
                return {}
            min_len = min(len(self.price_data[s]) for s in symbols)
            if min_len < 20:
                return {}
            aligned = {s: list(self.price_data[s])[-min_len:] for s in symbols}
            matrix = {}
            for i, s1 in enumerate(symbols):
                for j, s2 in enumerate(symbols):
                    if i < j:
                        returns1 = np.diff(aligned[s1]) / np.array(aligned[s1][:-1])
                        returns2 = np.diff(aligned[s2]) / np.array(aligned[s2][:-1])
                        returns1 = np.where(np.isinf(returns1), 0, returns1)
                        returns2 = np.where(np.isinf(returns2), 0, returns2)
                        if np.std(returns1) > 0 and np.std(returns2) > 0:
                            corr = np.corrcoef(returns1, returns2)[0, 1]
                            matrix[f"{s1}_{s2}"] = round(corr, 3)
            return matrix


_tick_db = None
_pnl = None
_replay = None
_attribution = None
_corr_matrix = None
_lock = threading.Lock()


def get_tick_db():
    global _tick_db
    if _tick_db is None:
        with _lock:
            if _tick_db is None:
                _tick_db = TickDatabase()
    return _tick_db


def get_realtime_pnl():
    global _pnl
    if _pnl is None:
        with _lock:
            if _pnl is None:
                _pnl = RealTimePnL()
    return _pnl


def get_trade_replay():
    global _replay
    if _replay is None:
        with _lock:
            if _replay is None:
                _replay = TradeReplay()
    return _replay


def get_attribution():
    global _attribution
    if _attribution is None:
        with _lock:
            if _attribution is None:
                _attribution = PerformanceAttribution()
    return _attribution


def get_live_correlation():
    global _corr_matrix
    if _corr_matrix is None:
        with _lock:
            if _corr_matrix is None:
                _corr_matrix = LiveCorrelationMatrix()
    return _corr_matrix
