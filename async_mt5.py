"""Asynchronous wrappers for MetaTrader5 API calls — AFX AutoTrader v2

All MT5 interactions are non-blocking. This module provides async functions
that internally run blocking MT5 calls in a thread-pool executor.

ONLY MT5 communication uses async. All other processing uses
ThreadPoolExecutor/ProcessPoolExecutor in parallel_executor.py.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, List, Optional, Tuple

import MetaTrader5 as mt5

# Dedicated thread pool for MT5 I/O — kept small, MT5 is single-threaded internally
_MT5_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="MT5")


def _run_in_executor(func: Callable[..., Any], *args, **kwargs) -> asyncio.Future:
    """Schedule MT5 call in thread pool. Returns awaitable Future."""
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(_MT5_EXECUTOR, lambda: func(*args, **kwargs))


# ─── Initialization ────────────────────────────────────────────

async def initialize() -> bool:
    """Async mt5.initialize(). Returns True on success."""
    return await _run_in_executor(mt5.initialize)


async def shutdown() -> bool:
    """Async mt5.shutdown(). Returns True on success."""
    return await _run_in_executor(mt5.shutdown)


async def last_error() -> Tuple[int, int]:
    """Async mt5.last_error(). Returns error code tuple."""
    return await _run_in_executor(mt5.last_error)


# ─── Account ───────────────────────────────────────────────────

async def account_info() -> Any:
    """Async mt5.account_info(). Returns account info structure or None."""
    return await _run_in_executor(mt5.account_info)


async def terminal_info() -> Any:
    """Async mt5.terminal_info(). Returns terminal info structure or None."""
    return await _run_in_executor(mt5.terminal_info)


# ─── Positions ─────────────────────────────────────────────────

async def positions_get(
    group: str = "",
    ticket: int = 0,
    symbol: str = "",
) -> Any:
    """Async mt5.positions_get(). Returns open positions matching criteria."""
    return await _run_in_executor(
        lambda: mt5.positions_get(group=group, ticket=ticket, symbol=symbol)
    )


async def position_get(
    ticket: int,
) -> Any:
    """Async mt5.position_get(ticket). Returns single position by ticket."""
    return await _run_in_executor(
        lambda: mt5.position_get(ticket=ticket)
    )


# ─── Orders ────────────────────────────────────────────────────

async def orders_get(
    group: str = "",
    ticket: int = 0,
    symbol: str = "",
) -> Any:
    """Async mt5.orders_get(). Returns pending orders matching criteria."""
    return await _run_in_executor(
        lambda: mt5.orders_get(group=group, ticket=ticket, symbol=symbol)
    )


async def order_send(request: dict) -> Any:
    """Async mt5.order_send(request). Returns trade operation result."""
    return await _run_in_executor(mt5.order_send, request)


# ─── Symbol Info ───────────────────────────────────────────────

async def symbol_info(symbol: str) -> Any:
    """Async mt5.symbol_info(symbol). Returns symbol info structure."""
    return await _run_in_executor(mt5.symbol_info, symbol)


async def symbol_info_tick(symbol: str) -> Any:
    """Async mt5.symbol_info_tick(symbol). Returns latest tick data."""
    return await _run_in_executor(mt5.symbol_info_tick, symbol)


async def symbol_info_min(symbol: str) -> Any:
    """Async mt5.symbol_info_min(symbol). Returns min price info."""
    return await _run_in_executor(mt5.symbol_info_min, symbol)


async def symbol_info_max(symbol: str) -> Any:
    """Async mt5.symbol_info_max(symbol). Returns max price info."""
    return await _run_in_executor(mt5.symbol_info_max, symbol)


async def symbol_select(symbol: str, select: bool = True) -> bool:
    """Async mt5.symbol_select(symbol, select). Adds/removes symbol from Market Watch."""
    return await _run_in_executor(
        lambda: mt5.symbol_select(symbol, select)
    )


async def symbols_total() -> int:
    """Async mt5.symbols_total(). Returns count of symbols in Market Watch."""
    return await _run_in_executor(mt5.symbols_total)


async def symbol_get(
    name: str,
) -> Any:
    """Async mt5.symbol_get(name). Returns symbol by name."""
    return await _run_in_executor(
        lambda: mt5.symbol_get(name=name)
    )


async def symbols_get(
    group: str = "",
) -> Any:
    """Async mt5.symbols_get(group). Returns symbols matching group filter."""
    return await _run_in_executor(
        lambda: mt5.symbols_get(group=group)
    )


# ─── Historical Data ──────────────────────────────────────────

async def copy_rates_from_pos(
    symbol: str,
    timeframe: int,
    start_pos: int,
    count: int,
) -> Any:
    """Async mt5.copy_rates_from_pos(symbol, timeframe, start_pos, count)."""
    return await _run_in_executor(
        lambda: mt5.copy_rates_from_pos(symbol, timeframe, start_pos, count)
    )


async def copy_rates_range(
    symbol: str,
    timeframe: int,
    date_from: int,
    date_to: int,
) -> Any:
    """Async mt5.copy_rates_range(symbol, timeframe, date_from, date_to)."""
    return await _run_in_executor(
        lambda: mt5.copy_rates_range(symbol, timeframe, date_from, date_to)
    )


async def copy_ticks_from(
    symbol: str,
    date_from: int,
    count: int,
    flags: int = 0,
) -> Any:
    """Async mt5.copy_ticks_from(symbol, date_from, count, flags)."""
    return await _run_in_executor(
        lambda: mt5.copy_ticks_from(symbol, date_from, count, flags)
    )


async def copy_ticks_range(
    symbol: str,
    date_from: int,
    date_to: int,
    flags: int = 0,
) -> Any:
    """Async mt5.copy_ticks_range(symbol, date_from, date_to, flags)."""
    return await _run_in_executor(
        lambda: mt5.copy_ticks_range(symbol, date_from, date_to, flags)
    )


async def copy_rates(
    symbol: str,
    timeframe: int,
    start: int,
    count: int,
) -> Any:
    """Async mt5.copy_rates(symbol, timeframe, start, count)."""
    return await _run_in_executor(
        lambda: mt5.copy_rates(symbol, timeframe, start, count)
    )


# ─── History ───────────────────────────────────────────────────

async def history_deals_get(
    date_from: int,
    date_to: int,
    group: str = "",
    ticket: int = 0,
) -> Any:
    """Async mt5.history_deals_get(date_from, date_to, group, ticket)."""
    return await _run_in_executor(
        lambda: mt5.history_deals_get(
            date_from, date_to, group=group, ticket=ticket
        )
    )


async def history_orders_get(
    date_from: int,
    date_to: int,
    group: str = "",
    ticket: int = 0,
) -> Any:
    """Async mt5.history_orders_get(date_from, date_to, group, ticket)."""
    return await _run_in_executor(
        lambda: mt5.history_orders_get(
            date_from, date_to, group=group, ticket=ticket
        )
    )


async def orders_get_total() -> int:
    """Async mt5.orders_get_total()."""
    return await _run_in_executor(mt5.orders_get_total)


async def positions_total() -> int:
    """Async mt5.positions_total()."""
    return await _run_in_executor(mt5.positions_total)


__all__ = [
    # Initialization
    "initialize",
    "shutdown",
    "last_error",
    # Account
    "account_info",
    "terminal_info",
    # Positions
    "positions_get",
    "position_get",
    # Orders
    "orders_get",
    "order_send",
    # Symbol info
    "symbol_info",
    "symbol_info_tick",
    "symbol_info_min",
    "symbol_info_max",
    "symbol_select",
    "symbols_total",
    "symbol_get",
    "symbols_get",
    # Historical data
    "copy_rates_from_pos",
    "copy_rates_range",
    "copy_ticks_from",
    "copy_ticks_range",
    "copy_rates",
    # History
    "history_deals_get",
    "history_orders_get",
    "orders_get_total",
    "positions_total",
]