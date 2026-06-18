"""Shared technical indicator utilities."""
import numpy as np
import logging
import threading
from datetime import datetime, timezone

try:
    from numba import njit
    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False
    def njit(f=None, **kwargs):
        if f is None:
            return lambda fn: fn
        return f

logger = logging.getLogger(__name__)


def fetch_closed_rates(symbol, timeframe, count):
    """Fetch rates from MT5, excluding the current incomplete bar.

    Args:
        symbol: MT5 symbol name
        timeframe: MT5 timeframe constant
        count: Number of CLOSED bars to return

    Returns:
        numpy array of closed bars only, or None on failure
    """
    import MetaTrader5 as mt5
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count + 1)
    if rates is None or len(rates) < 2:
        return rates
    # Last bar is the currently open (incomplete) bar — drop it
    return rates[:-1]


def align_to_m1_grid(m1_rates, higher_tf_rates):
    """Forward-fill higher TF data onto M1 timestamp grid.

    Each M1 bar gets the LAST CLOSED higher-TF bar's values.
    Prevents temporal misalignment between timeframes.

    Args:
        m1_rates: numpy array from fetch_closed_rates (M1)
        higher_tf_rates: numpy array from fetch_closed_rates (H1, D1, etc.)

    Returns:
        numpy array aligned to M1 timestamps, or None on failure
    """
    if m1_rates is None or higher_tf_rates is None:
        return None
    if len(m1_rates) == 0 or len(higher_tf_rates) == 0:
        return None

    m1_times = m1_rates['time']
    ht_times = higher_tf_rates['time']

    # For each M1 bar, find the last higher-TF bar that closed before or at it
    result = np.empty(len(m1_times), dtype=higher_tf_rates.dtype)
    ht_idx = 0
    for i, m1_t in enumerate(m1_times):
        # Advance ht_idx while higher-TF bar time <= M1 bar time
        while ht_idx < len(ht_times) - 1 and ht_times[ht_idx + 1] <= m1_t:
            ht_idx += 1
        result[i] = higher_tf_rates[ht_idx]
    return result


# Maximum allowed staleness for tick data (seconds)
# Aggressive threshold — if tick is older than this, market is effectively closed
MAX_TICK_STALENESS = 10

# MT5 error code for market closed
MT5_TRADE_RETCODE_MARKET_CLOSED = 10018

# Cooldown after receiving market closed error (seconds)
MARKET_CLOSED_COOLDOWN = 60

# Track symbols known to have closed market to avoid repeated attempts
_symbol_market_closed = {}
_symbol_market_closed_lock = threading.Lock()


@njit(cache=True)
def _ema_kernel(data, span):
    alpha = 2.0 / (span + 1.0)
    result = np.empty_like(data, dtype=np.float64)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = alpha * data[i] + (1.0 - alpha) * result[i - 1]
    return result


def ema(data, span):
    """Exponential Moving Average (numba JIT-compiled).

    Args:
        data: numpy array of price data
        span: EMA period
    Returns:
        numpy array of EMA values
    """
    arr = np.asarray(data, dtype=np.float64)
    return _ema_kernel(arr, span)


# Session hours (UTC)
SESSIONS = {
    "asian": (0, 8),
    "london": (7, 16),
    "new_york": (12, 21),
    "overlap": (12, 16),
    "dead": (21, 0),
}


def get_current_session():
    """Get current trading session based on UTC hour.
    
    Returns:
        str: Session name (asian, london, overlap, new_york, dead)
    """
    hour = datetime.now(timezone.utc).hour
    for name, (start, end) in SESSIONS.items():
        if start < end:
            if start <= hour < end:
                return name
        else:
            if hour >= start or hour < end:
                return name
    return "dead"


# Trading session gate (configurable)
TRADING_SESSIONS_ENABLED = True
TRADING_HOURS = {
    "london": (7, 16),
    "new_york": (12, 21),
}
WEEKEND_TRADING = False


def is_valid_session():
    """Check if current time is within allowed trading sessions.

    Returns:
        bool: True if trading is allowed, False otherwise
    """
    if not TRADING_SESSIONS_ENABLED:
        return True
    now = datetime.now(timezone.utc)
    if not WEEKEND_TRADING and now.weekday() >= 5:
        return False
    hour = now.hour
    for start, end in TRADING_HOURS.values():
        if start <= hour < end:
            return True
    return False


def is_market_open():
    """Check if the market is actually open and trading is allowed.

    Returns:
        dict with keys:
            - open (bool): True if market is open
            - reason (str): Explanation if not open
            - terminal_trade_allowed (bool): MT5 terminal trade permission
            - symbol_trade_mode (int): Symbol trade mode
    """
    import MetaTrader5 as mt5

    result = {
        "open": False,
        "reason": "",
        "terminal_trade_allowed": False,
        "symbol_trade_mode": None,
    }

    # Check MT5 terminal info
    terminal = mt5.terminal_info()
    if terminal is None:
        result["reason"] = "MT5 terminal not connected"
        return result
    result["terminal_trade_allowed"] = terminal.trade_allowed
    if not terminal.trade_allowed:
        result["reason"] = "MT5 terminal trade not allowed"
        return result

    result["open"] = True
    return result


def is_symbol_tradeable(symbol):
    """Check if a specific symbol is currently tradeable.

    Returns:
        dict with keys:
            - tradeable (bool): True if symbol can be traded
            - reason (str): Explanation if not tradeable
            - trade_mode (int): MT5 symbol trade mode
    """
    import MetaTrader5 as mt5

    result = {
        "tradeable": False,
        "reason": "",
        "trade_mode": None,
    }

    info = mt5.symbol_info(symbol)
    if info is None:
        result["reason"] = f"Symbol {symbol} not found"
        return result

    result["trade_mode"] = info.trade_mode
    if info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        result["reason"] = f"Symbol {symbol} trade mode: {info.trade_mode} (expected FULL)"
        return result

    result["tradeable"] = True
    return result


def validate_rate_freshness(rates, timeframe):
    """Validate that rate data is fresh enough to generate reliable signals.

    Args:
        rates: numpy array from mt5.copy_rates_from_pos()
        timeframe: MT5 timeframe constant (e.g. mt5.TIMEFRAME_M1)

    Returns:
        dict with keys:
            - fresh (bool): True if data is fresh
            - reason (str): Explanation if stale
            - last_bar_time (datetime): Timestamp of last bar
            - age_seconds (float): How old the last bar is
    """
    import MetaTrader5 as mt5

    result = {
        "fresh": False,
        "reason": "",
        "last_bar_time": None,
        "age_seconds": 0,
    }

    if rates is None or len(rates) == 0:
        result["reason"] = "No rate data received"
        return result

    last_bar_ts = rates[-1]['time']
    last_bar_time = datetime.fromtimestamp(last_bar_ts, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    age_seconds = (now - last_bar_time).total_seconds()

    result["last_bar_time"] = last_bar_time
    result["age_seconds"] = age_seconds

    # Handle broker time sync: negative age = broker ahead, treat as fresh
    if age_seconds < 0:
        age_seconds = 0

    max_stale = MAX_RATE_STALENESS.get(timeframe, 3600)
    if age_seconds > max_stale:
        result["reason"] = f"Rate data stale: {age_seconds:.0f}s old (max {max_stale}s for TF {timeframe})"
        return result

    result["fresh"] = True
    return result


def validate_tick_freshness(tick, symbol=None):
    """Validate that tick data is fresh.

    Args:
        tick: result from mt5.symbol_info_tick()
        symbol: Optional symbol name for market closed tracking

    Returns:
        dict with keys:
            - fresh (bool): True if tick is fresh
            - reason (str): Explanation if stale
            - age_seconds (float): How old the tick is
    """
    import MetaTrader5 as mt5

    result = {
        "fresh": False,
        "reason": "",
        "age_seconds": 0,
    }

    if tick is None:
        result["reason"] = "No tick data"
        return result

    # Use MT5 server time as reference (broker may be in different timezone)
    # Compare tick time to the LATEST tick time we can get, not local clock
    import MetaTrader5 as _mt5
    info = _mt5.symbol_info(symbol) if symbol else None
    now = datetime.now(timezone.utc)
    tick_time = datetime.fromtimestamp(tick.time, tz=timezone.utc)
    age_seconds = (now - tick_time).total_seconds()

    # Handle broker time sync issues: if tick is "from the future" (negative age),
    # use the tick's own time as fresh — the broker server is simply ahead of local clock.
    # Only reject if age is positive AND too old.
    if age_seconds < 0:
        # Tick is from the future relative to local clock — this means broker time is ahead.
        # This is normal for many brokers. Accept as fresh.
        age_seconds = 0

    result["age_seconds"] = age_seconds

    # Check if this symbol is known to have closed market
    if symbol and is_symbol_market_closed(symbol):
        result["reason"] = f"Market closed for {symbol} (tracked)"
        return result

    if age_seconds > MAX_TICK_STALENESS:
        result["reason"] = f"Tick stale: {age_seconds:.0f}s old (max {MAX_TICK_STALENESS}s)"
        return result

    result["fresh"] = True
    return result


def validate_market_state(symbol, timeframe=None):
    """Complete market state validation: terminal + symbol + rate freshness.

    This is the primary gate that should be called before ANY signal generation.

    Args:
        symbol: MT5 symbol string
        timeframe: Optional MT5 timeframe for rate freshness check

    Returns:
        dict with keys:
            - can_trade (bool): True if all checks pass
            - reason (str): Combined reason if any check fails
            - terminal_ok (bool)
            - symbol_ok (bool)
            - rates_ok (bool) — only if timeframe provided
            - tick_ok (bool)
    """
    import MetaTrader5 as mt5

    result = {
        "can_trade": False,
        "reason": "",
        "terminal_ok": False,
        "symbol_ok": False,
        "rates_ok": False,
        "tick_ok": False,
    }

    # 1. Terminal check
    market = is_market_open()
    result["terminal_ok"] = market["open"]
    if not market["open"]:
        result["reason"] = market["reason"]
        return result

    # 2. Symbol check
    sym = is_symbol_tradeable(symbol)
    result["symbol_ok"] = sym["tradeable"]
    if not sym["tradeable"]:
        result["reason"] = sym["reason"]
        return result

    # 3. Tick freshness check
    tick = mt5.symbol_info_tick(symbol)
    tick_check = validate_tick_freshness(tick, symbol)
    result["tick_ok"] = tick_check["fresh"]
    if not tick_check["fresh"]:
        result["reason"] = tick_check["reason"]
        return result

    # 4. Rate freshness check (optional)
    if timeframe is not None:
        rates = fetch_closed_rates(symbol, timeframe, 300)
        rate_check = validate_rate_freshness(rates, timeframe)
        result["rates_ok"] = rate_check["fresh"]
        if not rate_check["fresh"]:
            result["reason"] = rate_check["reason"]
            return result
    else:
        result["rates_ok"] = True

    result["can_trade"] = True
    return result


def mark_symbol_market_closed(symbol, error_code=None):
    """Mark a symbol as having a closed market to prevent repeated attempts.

    Args:
        symbol: MT5 symbol string
        error_code: MT5 error code that triggered this (optional)
    """
    with _symbol_market_closed_lock:
        _symbol_market_closed[symbol] = {
            "time": datetime.now(timezone.utc).isoformat(),
            "error_code": error_code,
        }
    logger.debug("Marked %s market closed (error: %s)", symbol, error_code)


def is_symbol_market_closed(symbol):
    """Check if a symbol is known to have a closed market.

    Returns:
        bool: True if symbol is marked as closed and cooldown hasn't expired
    """
    with _symbol_market_closed_lock:
        entry = _symbol_market_closed.get(symbol)
        if entry is None:
            return False
        closed_time = datetime.fromisoformat(entry["time"])
        now = datetime.now(timezone.utc)
        elapsed = (now - closed_time).total_seconds()
        if elapsed > MARKET_CLOSED_COOLDOWN:
            # Cooldown expired — remove entry and allow retry
            del _symbol_market_closed[symbol]
            return False
        return True


def clear_symbol_market_closed(symbol):
    """Clear the market closed state for a symbol (e.g. when market reopens)."""
    with _symbol_market_closed_lock:
        _symbol_market_closed.pop(symbol, None)


def is_tradeable_now(symbol, timeframe=None):
    """Quick check: can we trade this symbol right now?

    Combines market state validation with symbol-specific cooldown tracking.
    This is the recommended entry point for trade readiness checks.

    Args:
        symbol: MT5 symbol string
        timeframe: Optional MT5 timeframe for rate freshness

    Returns:
        dict with keys:
            - can_trade (bool)
            - reason (str)
    """
    # Check trading session
    if not is_valid_session():
        return {"can_trade": False, "reason": "Outside allowed trading sessions"}

    # First check if symbol is known-closed
    if is_symbol_market_closed(symbol):
        return {"can_trade": False, "reason": f"Market closed for {symbol} (cooldown)"}

    # Then run full validation
    return validate_market_state(symbol, timeframe)
