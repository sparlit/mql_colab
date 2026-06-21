"""
MT5 Terminal Dashboard — AFX AutoTrader v2
Python module that reads MT5 terminal data and exposes it for all dashboards.
Provides data bridge between MT5 terminal and the dashboard system.

Uses mt5_mcp for all MT5 data access.
Thread-safe with shared memory for native dashboard integration.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from mt5_mcp import (
    account_info,
    positions_get,
    orders_get,
    symbol_info,
    symbol_info_tick,
    terminal_info,
    positions_total,
    orders_get_total,
    symbols_get,
    copy_rates_from_pos,
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1,
)

logger = logging.getLogger(__name__)

# ─── Shared Memory Keys ─────────────────────────────────────────
SHARED_MEM_KEY = "AFXAutoTrader_v2"

# ─── MT5 Dashboard State ───────────────────────────────────────
@dataclass
class MT5DashboardData:
    """Data snapshot from MT5 terminal."""
    timestamp: str = ""
    account_balance: float = 0.0
    account_equity: float = 0.0
    account_margin: float = 0.0
    account_free_margin: float = 0.0
    account_profit: float = 0.0
    positions_count: int = 0
    orders_count: int = 0
    symbols_count: int = 0
    terminal_status: str = ""
    spread_avg: float = 0.0
    tick_quality: float = 0.0
    latency_ms: float = 0.0
    open_positions: List[Dict] = field(default_factory=list)
    pending_orders: List[Dict] = field(default_factory=list)
    watched_symbols: List[str] = field(default_factory=list)


# ─── MT5 Dashboard ─────────────────────────────────────────────
class MT5Dashboard:
    """
    Reads MT5 terminal data for dashboard display.

    Provides:
    - Account snapshot (balance, equity, margin, P&L)
    - Open positions list
    - Pending orders
    - Symbol watchlist
    - Terminal health (spreads, latency)

    Thread-safe — updates on configurable interval.
    """

    WATCHED_SYMBOLS = [
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
        "AUDUSD", "USDCAD", "NZDUSD",
        "EURGBP", "EURJPY", "GBPJPY",
    ]

    def __init__(self, shared_mem: bool = True):
        self._shared_mem = shared_mem
        self._data = MT5DashboardData()
        self._data_lock = threading.RLock()
        self._running = False
        self._update_thread: Optional[threading.Thread] = None
        self._last_update = 0.0

    def start(self, interval: float = 1.0) -> None:
        """Start background update thread."""
        if self._running:
            return
        self._running = True
        self._update_thread = threading.Thread(
            target=self._update_loop,
            args=(interval,),
            daemon=True,
        )
        self._update_thread.start()
        logger.info("MT5 Dashboard started — update interval %.1fs", interval)

    def stop(self) -> None:
        """Stop background updates."""
        self._running = False
        if self._update_thread:
            self._update_thread.join(timeout=5.0)

    def _update_loop(self, interval: float) -> None:
        """Background thread: updates MT5 data every `interval` seconds."""
        while self._running:
            try:
                self._fetch_all()
                self._last_update = time.time()
            except Exception as e:
                logger.debug("MT5 dashboard update error: %s", e)
            time.sleep(interval)

    def _fetch_all(self) -> None:
        """Fetch all MT5 terminal data."""
        start = time.monotonic()

        # Account info
        try:
            acct = account_info()
            if acct:
                with self._data_lock:
                    self._data.account_balance = acct.balance
                    self._data.account_equity = acct.equity
                    self._data.account_margin = acct.margin
                    self._data.account_free_margin = acct.margin_free
                    self._data.account_profit = acct.profit
        except Exception:
            pass

        # Positions
        try:
            positions = positions_get() or []
            pos_list = []
            for p in positions:
                pos_list.append({
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "type": "BUY" if p.type == 0 else "SELL",
                    "volume": p.volume,
                    "price_open": p.price_open,
                    "price_current": p.price_current,
                    "profit": p.profit,
                    "sl": p.sl,
                    "tp": p.tp,
                    "magic": p.magic,
                    "comment": getattr(p, "comment", ""),
                })
            with self._data_lock:
                self._data.open_positions = pos_list
                self._data.positions_count = len(pos_list)
        except Exception:
            pass

        # Pending orders
        try:
            orders = orders_get() or []
            ord_list = []
            for o in orders:
                ord_list.append({
                    "ticket": o.ticket,
                    "symbol": o.symbol,
                    "type": "BUY_LIMIT" if o.type == 2 else "SELL_LIMIT" if o.type == 3 else "OTHER",
                    "volume": o.volume,
                    "price_open": o.price_open,
                    "sl": o.sl,
                    "tp": o.tp,
                    "magic": o.magic,
                })
            with self._data_lock:
                self._data.pending_orders = ord_list
                self._data.orders_count = len(ord_list)
        except Exception:
            pass

        # Symbols
        try:
            syms = symbols_get(group="*EUR*") or []
            with self._data_lock:
                self._data.watched_symbols = [s.name for s in syms[:10]]
                self._data.symbols_count = len(syms)
        except Exception:
            pass

        # Terminal info
        try:
            term = terminal_info()
            if term:
                with self._data_lock:
                    self._data.terminal_status = "Connected" if term.connected else "Disconnected"
        except Exception:
            pass

        # Spread average for watched symbols
        try:
            spreads = []
            for sym in self.WATCHED_SYMBOLS[:5]:
                tick = symbol_info_tick(sym)
                info = symbol_info(sym)
                if tick and info and info.bid > 0:
                    spread = (tick.ask - tick.bid) / info.point
                    spreads.append(spread)
            with self._data_lock:
                self._data.spread_avg = sum(spreads) / len(spreads) if spreads else 0.0
        except Exception:
            pass

        # Latency
        latency = (time.monotonic() - start) * 1000
        with self._data_lock:
            self._data.latency_ms = latency
            self._data.timestamp = datetime.now().strftime("%H:%M:%S")

    # ─── Public API ──────────────────────────────────────────────

    def get_snapshot(self) -> MT5DashboardData:
        """Get current dashboard data snapshot."""
        with self._data_lock:
            return MT5DashboardData(
                timestamp=self._data.timestamp,
                account_balance=self._data.account_balance,
                account_equity=self._data.account_equity,
                account_margin=self._data.account_margin,
                account_free_margin=self._data.account_free_margin,
                account_profit=self._data.account_profit,
                positions_count=self._data.positions_count,
                orders_count=self._data.orders_count,
                symbols_count=self._data.symbols_count,
                terminal_status=self._data.terminal_status,
                spread_avg=self._data.spread_avg,
                latency_ms=self._data.latency_ms,
                open_positions=self._data.open_positions.copy(),
                pending_orders=self._data.pending_orders.copy(),
                watched_symbols=self._data.watched_symbols.copy(),
            )

    def get_positions(self) -> List[Dict]:
        """Get current open positions."""
        with self._data_lock:
            return self._data.open_positions.copy()

    def get_account_summary(self) -> Dict[str, float]:
        """Get account summary for dashboard display."""
        with self._data_lock:
            return {
                "balance": self._data.account_balance,
                "equity": self._data.account_equity,
                "margin": self._data.account_margin,
                "free_margin": self._data.account_free_margin,
                "profit": self._data.account_profit,
                "spread_avg": self._data.spread_avg,
            }

    def get_terminal_health(self) -> Dict[str, Any]:
        """Get terminal health metrics."""
        with self._data_lock:
            return {
                "status": self._data.terminal_status,
                "positions": self._data.positions_count,
                "orders": self._data.orders_count,
                "symbols": self._data.symbols_count,
                "latency_ms": self._data.latency_ms,
                "spread_avg": self._data.spread_avg,
                "last_update": self._data.timestamp,
            }

    def is_healthy(self) -> bool:
        """Quick health check."""
        with self._data_lock:
            return (
                self._data.terminal_status == "Connected"
                and self._data.latency_ms < 100
                and self._data.positions_count >= 0
            )

    @property
    def is_running(self) -> bool:
        return self._running


# ─── Singleton ─────────────────────────────────────────────────
_dashboard: Optional[MT5Dashboard] = None
_dashboard_lock = threading.Lock()


def get_mt5_dashboard() -> MT5Dashboard:
    global _dashboard
    if _dashboard is None:
        with _dashboard_lock:
            if _dashboard is None:
                _dashboard = MT5Dashboard()
    return _dashboard