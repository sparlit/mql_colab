"""
Position Manager — AFX AutoTrader v2
Unified position sizing, tracking, and management across all 4 strategy modes.

Thread-safe with RLock protection for shared state.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Position:
    ticket: int
    symbol: str
    direction: str  # "BUY" or "SELL"
    lot: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    magic: int
    open_time: int
    strategy_mode: str
    stop_loss: float
    take_profit: float

    @property
    def pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def age_seconds(self) -> int:
        return int(time.time() - self.open_time)


class PositionManager:
    """
    Manages all open positions across strategies.
    Thread-safe with RLock.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._positions: Dict[int, Position] = {}
        self._symbol_index: Dict[str, List[int]] = {}  # symbol -> ticket list
        self._magic_index: Dict[int, List[int]] = {}   # magic -> ticket list

    def open_position(
        self,
        symbol: str,
        direction: str,
        lot: float,
        entry_price: float,
        magic: int,
        ticket: int = 0,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        strategy_mode: str = "SWING",
    ) -> Position:
        """Register a newly opened position."""
        with self._lock:
            pos = Position(
                ticket=ticket or int(time.time() * 1000) % 1000000,
                symbol=symbol,
                direction=direction,
                lot=lot,
                entry_price=entry_price,
                current_price=entry_price,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                magic=magic,
                open_time=int(time.time()),
                strategy_mode=strategy_mode,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
            self._positions[pos.ticket] = pos
            self._symbol_index.setdefault(symbol, []).append(pos.ticket)
            self._magic_index.setdefault(magic, []).append(pos.ticket)
            logger.info("Position opened: %s %s %.2f @ %.5f (ticket=%d, magic=%d)",
                       direction, symbol, lot, entry_price, pos.ticket, magic)
            return pos

    def close_position(self, ticket: int, exit_price: float, pnl: float) -> Optional[Position]:
        """Register a closed position."""
        with self._lock:
            pos = self._positions.pop(ticket, None)
            if pos:
                pos.realized_pnl = pnl
                pos.current_price = exit_price
                # Remove from indices
                if pos.symbol in self._symbol_index:
                    self._symbol_index[pos.symbol] = [
                        t for t in self._symbol_index[pos.symbol] if t != ticket
                    ]
                if pos.magic in self._magic_index:
                    self._magic_index[pos.magic] = [
                        t for t in self._magic_index[pos.magic] if t != ticket
                    ]
                logger.info("Position closed: ticket=%d, PnL=%.2f", ticket, pnl)
            return pos

    def update_prices(self, prices: Dict[str, float]) -> None:
        """Update current prices for all open positions."""
        with self._lock:
            for pos in self._positions.values():
                if pos.symbol in prices:
                    pos.current_price = prices[pos.symbol]

    def get_position(self, ticket: int) -> Optional[Position]:
        with self._lock:
            return self._positions.get(ticket)

    def get_open_positions(self, symbol: str = "") -> List[Position]:
        with self._lock:
            if symbol:
                tickets = self._symbol_index.get(symbol, [])
                return [self._positions[t] for t in tickets if t in self._positions]
            return list(self._positions.values())

    def get_positions_by_magic(self, magic: int) -> List[Position]:
        with self._lock:
            tickets = self._magic_index.get(magic, [])
            return [self._positions[t] for t in tickets if t in self._positions]

    def get_total_exposure(self) -> float:
        with self._lock:
            return sum(abs(pos.lot) for pos in self._positions.values())

    def get_total_pnl(self) -> float:
        with self._lock:
            return sum(pos.realized_pnl + pos.unrealized_pnl for pos in self._positions.values())

    def get_open_count(self) -> int:
        with self._lock:
            return len(self._positions)

    def get_positions_by_strategy(self, strategy_mode: str) -> List[Position]:
        with self._lock:
            return [p for p in self._positions.values() if p.strategy_mode == strategy_mode]

    def sync_with_mt5(self) -> Dict[str, int]:
        """Sync with MT5 — close removed positions, register new ones."""
        from mt5_mcp import positions_get
        with self._lock:
            mt5_tickets = set()
            mt5_positions = positions_get() or []
            for mt5_pos in mt5_positions:
                mt5_tickets.add(mt5_pos.ticket)

            our_tickets = set(self._positions.keys())
            removed = our_tickets - mt5_tickets
            for t in removed:
                self._positions.pop(t, None)

            return {
                "synced": len(mt5_tickets & our_tickets),
                "removed": len(removed),
                "total": len(mt5_tickets),
            }


_position_manager: Optional[PositionManager] = None
_pm_lock = threading.Lock()


def get_position_manager() -> PositionManager:
    global _position_manager
    if _position_manager is None:
        with _pm_lock:
            if _position_manager is None:
                _position_manager = PositionManager()
    return _position_manager