import json
import os
import time as _time
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ==========================================
# SIGNAL PROVIDER — MQL5 signal output
# ==========================================

SIGNAL_FILE = os.path.join(os.path.dirname(__file__), "brain_data", "signals.json")


class SignalProvider:
    def __init__(self):
        self.signals = []
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(SIGNAL_FILE), exist_ok=True)

    def publish_signal(self, symbol, direction, price, sl, tp, lot, confidence, strategy="combined"):
        signal = {
            "time": datetime.now().isoformat(),
            "symbol": symbol,
            "action": "BUY" if direction == 1 else "SELL",
            "price": price,
            "sl": sl,
            "tp": tp,
            "lot": lot,
            "confidence": round(confidence, 3),
            "strategy": strategy,
            "id": f"sig_{int(_time.time()*1000)}",
        }
        with self._lock:
            self.signals.append(signal)
            if len(self.signals) > 100:
                self.signals = self.signals[-50:]
        self._write_signal(signal)
        return signal

    def _write_signal(self, signal):
        try:
            data = {"signals": self.signals[-20:], "latest": signal, "updated": datetime.now().isoformat()}
            with open(SIGNAL_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except (OSError, IOError) as e:
            logger.debug("Signal file write failed: %s", e)

    def get_latest_signals(self, n=10):
        with self._lock:
            return self.signals[-n:]

    def get_signal_by_id(self, signal_id):
        with self._lock:
            for s in reversed(self.signals):
                if s["id"] == signal_id:
                    return s
        return None


class MultiAccountManager:
    def __init__(self):
        self.accounts = []
        self._lock = threading.Lock()

    def add_account(self, login, name, server):
        with self._lock:
            self.accounts.append({"login": login, "name": name, "server": server, "active": True})

    def remove_account(self, login):
        with self._lock:
            self.accounts = [a for a in self.accounts if a["login"] != login]

    def get_accounts(self):
        with self._lock:
            return self.accounts.copy()

    def copy_signal(self, signal, target_logins=None):
        results = {}
        for account in self.accounts:
            if target_logins and account["login"] not in target_logins:
                continue
            if not account["active"]:
                continue
            results[account["login"]] = {"status": "queued", "signal": signal["id"]}
        return results


class PortfolioMultiSymbol:
    def __init__(self):
        self.allocations = {}
        self._lock = threading.Lock()

    def set_allocation(self, symbol, weight):
        with self._lock:
            self.allocations[symbol] = weight

    def get_allocation(self, symbol):
        with self._lock:
            return self.allocations.get(symbol, 0)

    def get_total_allocation(self):
        with self._lock:
            return sum(self.allocations.values())

    def normalize(self):
        with self._lock:
            total = sum(self.allocations.values())
            if total > 0:
                self.allocations = {k: v / total for k, v in self.allocations.items()}


_signal_provider = None
_multi_account = None
_portfolio_multi = None
_lock = threading.Lock()


def get_signal_provider():
    global _signal_provider
    if _signal_provider is None:
        with _lock:
            if _signal_provider is None:
                _signal_provider = SignalProvider()
    return _signal_provider

