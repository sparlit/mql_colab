"""Synchronous shim for MetaTrader5 — AFX AutoTrader v2

All functions delegate to async wrappers defined in async_mt5.py and block
until the coroutine completes. Existing code that expects blocking MT5 API
can import `mt5_mcp as mt5` with no source-level changes.

ONLY MT5 communication is async. Everything else uses ThreadPoolExecutor.
"""

from __future__ import annotations

import asyncio
import sys

from async_mt5 import (
    initialize as _initialize,
    shutdown as _shutdown,
    last_error as _last_error,
    account_info as _account_info,
    terminal_info as _terminal_info,
    positions_get as _positions_get,
    position_get as _position_get,
    orders_get as _orders_get,
    order_send as _order_send,
    symbol_info as _symbol_info,
    symbol_info_tick as _symbol_info_tick,
    symbol_info_min as _symbol_info_min,
    symbol_info_max as _symbol_info_max,
    symbol_select as _symbol_select,
    symbols_total as _symbols_total,
    symbol_get as _symbol_get,
    symbols_get as _symbols_get,
    copy_rates_from_pos as _copy_rates_from_pos,
    copy_rates_range as _copy_rates_range,
    copy_ticks_from as _copy_ticks_from,
    copy_ticks_range as _copy_ticks_range,
    copy_rates as _copy_rates,
    history_deals_get as _history_deals_get,
    history_orders_get as _history_orders_get,
    orders_get_total as _orders_get_total,
    positions_total as _positions_total,
)


def _run_sync(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    else:
        return loop.run_until_complete(coro)


# ─── Initialization ────────────────────────────────────────────

def initialize() -> bool:
    return _run_sync(_initialize())


def shutdown() -> bool:
    return _run_sync(_shutdown())


def last_error():
    return _run_sync(_last_error())


# ─── Account ──────────────────────────────────────────────────

def account_info():
    return _run_sync(_account_info())


def terminal_info():
    return _run_sync(_terminal_info())


# ─── Positions ─────────────────────────────────────────────────

def positions_get(group="", ticket=0, symbol=""):
    return _run_sync(_positions_get(group=group, ticket=ticket, symbol=symbol))


def position_get(ticket):
    return _run_sync(_position_get(ticket=ticket))


# ─── Orders ────────────────────────────────────────────────────

def orders_get(group="", ticket=0, symbol=""):
    return _run_sync(_orders_get(group=group, ticket=ticket, symbol=symbol))


def order_send(request):
    return _run_sync(_order_send(request))


# ─── Symbol Info ───────────────────────────────────────────────

def symbol_info(symbol):
    return _run_sync(_symbol_info(symbol))


def symbol_info_tick(symbol):
    return _run_sync(_symbol_info_tick(symbol))


def symbol_info_min(symbol):
    return _run_sync(_symbol_info_min(symbol))


def symbol_info_max(symbol):
    return _run_sync(_symbol_info_max(symbol))


def symbol_select(symbol, select=True):
    return _run_sync(_symbol_select(symbol, select))


def symbols_total():
    return _run_sync(_symbols_total())


def symbol_get(name):
    return _run_sync(_symbol_get(name=name))


def symbols_get(group=""):
    return _run_sync(_symbols_get(group=group))


# ─── Historical Data ───────────────────────────────────────────

def copy_rates_from_pos(symbol, timeframe, start_pos, count):
    return _run_sync(_copy_rates_from_pos(symbol, timeframe, start_pos, count))


def copy_rates_range(symbol, timeframe, date_from, date_to):
    return _run_sync(_copy_rates_range(symbol, timeframe, date_from, date_to))


def copy_ticks_from(symbol, date_from, count, flags=0):
    return _run_sync(_copy_ticks_from(symbol, date_from, count, flags))


def copy_ticks_range(symbol, date_from, date_to, flags=0):
    return _run_sync(_copy_ticks_range(symbol, date_from, date_to, flags))


def copy_rates(symbol, timeframe, start, count):
    return _run_sync(_copy_rates(symbol, timeframe, start, count))


# ─── History ───────────────────────────────────────────────────

def history_deals_get(date_from, date_to, group="", ticket=0):
    return _run_sync(_history_deals_get(date_from, date_to, group=group, ticket=ticket))


def history_orders_get(date_from, date_to, group="", ticket=0):
    return _run_sync(_history_orders_get(date_from, date_to, group=group, ticket=ticket))


def orders_get_total():
    return _run_sync(_orders_get_total())


def positions_total():
    return _run_sync(_positions_total())


# ─── Constant Re-export ────────────────────────────────────────
# Code like `mt5.TIMEFRAME_M1`, `mt5.ORDER_TYPE_BUY`, etc. needs to work
# through this shim. We dynamically copy all non-callable attributes from
# the real MetaTrader5 module so that constants are always in sync.

import MetaTrader5 as _mt5_real

_shim_mod = sys.modules[__name__]

for _name_ in dir(_mt5_real):
    if _name_.startswith("_"):
        continue
    if hasattr(_shim_mod, _name_):
        continue
    _val_ = getattr(_mt5_real, _name_)
    if callable(_val_):
        continue
    setattr(_shim_mod, _name_, _val_)


__all__ = [
    "initialize",
    "shutdown",
    "last_error",
    "account_info",
    "terminal_info",
    "positions_get",
    "position_get",
    "orders_get",
    "order_send",
    "symbol_info",
    "symbol_info_tick",
    "symbol_info_min",
    "symbol_info_max",
    "symbol_select",
    "symbols_total",
    "symbol_get",
    "symbols_get",
    "copy_rates_from_pos",
    "copy_rates_range",
    "copy_ticks_from",
    "copy_ticks_range",
    "copy_rates",
    "history_deals_get",
    "history_orders_get",
    "orders_get_total",
    "positions_total",
]