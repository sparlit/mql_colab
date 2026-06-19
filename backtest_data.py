"""Historical data fetcher for backtesting with disk caching.

Fetches OHLCV and tick data from MT5, caches to brain_data/backtest_cache/.
"""
import os
import json
import hashlib
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

import MetaTrader5 as mt5
from config import DATA_DIR, MT5_TIMEFRAMES

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(DATA_DIR, "backtest_cache")


def _cache_key(symbol, timeframe, start_date, end_date):
    raw = f"{symbol}_{timeframe}_{start_date}_{end_date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cache_path(symbol, timeframe, start_date, end_date, suffix="ohlcv"):
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _cache_key(symbol, timeframe, start_date, end_date)
    return os.path.join(CACHE_DIR, f"{symbol}_{timeframe}_{key}_{suffix}.npz")


def _parse_date(d):
    if isinstance(d, str):
        return datetime.strptime(d, "%Y-%m-%d")
    return d


def fetch_historical_data(symbol, timeframe, start_date, end_date, use_cache=True,
                          max_bars=50000, progress_callback=None):
    """Fetch OHLCV bars from MT5 for a date range.

    Args:
        symbol: MT5 symbol (e.g. 'EURUSD')
        timeframe: MT5 timeframe constant (e.g. 300 for M5)
        start_date: 'YYYY-MM-DD' string or datetime
        end_date: 'YYYY-MM-DD' string or datetime
        use_cache: if True, check disk cache first
        max_bars: maximum number of bars to fetch (prevents memory issues)
        progress_callback: optional callable(fetched_bars, total_bars) for progress

    Returns:
        pd.DataFrame with columns: time, open, high, low, close, tick_volume, spread
        None on failure
    """
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)

    if use_cache:
        cached = _load_cache(symbol, timeframe, start_dt, end_dt, "ohlcv")
        if cached is not None:
            logger.debug("Cache hit: %s %s %s-%s", symbol, timeframe, start_date, end_date)
            return cached

    if not mt5.initialize():
        logger.error("MT5 initialize failed: %s", mt5.last_error())
        return None

    tf_seconds = timeframe
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    bars_needed = min(max(1, (end_ts - start_ts) // tf_seconds + 1), max_bars)

    all_rates = []
    chunk_size = 50000
    remaining = bars_needed
    
    while remaining > 0:
        fetch_count = min(remaining, chunk_size)
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, fetch_count)
        if rates is None or len(rates) == 0:
            if all_rates:
                break
            logger.error("MT5 copy_rates_from_pos failed: %s", mt5.last_error())
            return None
        all_rates.extend(rates)
        remaining -= len(rates)
        if progress_callback:
            progress_callback(len(all_rates), bars_needed)
        if len(rates) < fetch_count:
            break
    
    if not all_rates:
        return None
    
    rates = np.array(all_rates, dtype=rates.dtype if all_rates else None)

    df = pd.DataFrame(rates)
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df[(df["time"] >= start_dt) & (df["time"] <= end_dt)]
    df = df.reset_index(drop=True)

    if use_cache and len(df) > 0:
        _save_cache(symbol, timeframe, start_dt, end_dt, df, "ohlcv")

    return df


def fetch_multi_timeframe(symbol, timeframes, start_date, end_date, use_cache=True):
    """Fetch data for multiple timeframes simultaneously.

    Args:
        symbol: MT5 symbol
        timeframes: list of MT5 timeframe constants
        start_date, end_date: date range
        use_cache: disk caching

    Returns:
        dict mapping timeframe -> pd.DataFrame
    """
    result = {}
    for tf in timeframes:
        df = fetch_historical_data(symbol, tf, start_date, end_date, use_cache=use_cache)
        if df is not None and len(df) > 0:
            result[tf] = df
        else:
            logger.warning("No data for %s tf=%s", symbol, tf)
    return result


def fetch_tick_data(symbol, start_date, end_date, use_cache=True):
    """Fetch tick data for tick-level backtesting.

    Args:
        symbol: MT5 symbol
        start_date, end_date: date range

    Returns:
        pd.DataFrame with columns: time, bid, ask, volume
        None on failure
    """
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)

    if use_cache:
        cached = _load_cache(symbol, 0, start_dt, end_dt, "tick")
        if cached is not None:
            return cached

    if not mt5.initialize():
        logger.error("MT5 initialize failed: %s", mt5.last_error())
        return None

    ticks = mt5.copy_ticks_range(symbol, start_dt, end_dt, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        logger.error("MT5 copy_ticks_range failed: %s", mt5.last_error())
        return None

    df = pd.DataFrame(ticks)
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df[["time", "bid", "ask", "volume_real"]].rename(columns={"volume_real": "volume"})
    df = df.reset_index(drop=True)

    if use_cache and len(df) > 0:
        _save_cache(symbol, 0, start_dt, end_dt, df, "tick")

    return df


def df_to_bars(df):
    """Convert DataFrame to list of bar dicts for EventDrivenBacktestEngine.

    Args:
        df: pd.DataFrame with open, high, low, close columns

    Returns:
        list of dicts with 'time', 'open', 'high', 'low', 'close', 'spread'
    """
    bars = []
    for _, row in df.iterrows():
        bar = {
            "time": str(row.get("time", "")),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
        if "spread" in df.columns:
            bar["spread"] = float(row["spread"])
        bars.append(bar)
    return bars


def _load_cache(symbol, timeframe, start_dt, end_dt, suffix):
    path = _cache_path(symbol, timeframe, start_dt, end_dt, suffix)
    if not os.path.exists(path):
        return None
    try:
        data = np.load(path, allow_pickle=True)
        columns = list(data.files)
        records = {}
        for col in columns:
            records[col] = data[col]
        df = pd.DataFrame(records)
        if "time" in df.columns and df["time"].dtype.kind == "M":
            pass
        elif "time" in df.columns:
            try:
                df["time"] = pd.to_datetime(df["time"], unit="s")
            except Exception:
                pass
        return df
    except Exception as e:
        logger.debug("Cache load failed: %s", e)
        return None


def _save_cache(symbol, timeframe, start_dt, end_dt, df, suffix):
    try:
        path = _cache_path(symbol, timeframe, start_dt, end_dt, suffix)
        save_df = df.copy()
        if "time" in save_df.columns and hasattr(save_df["time"].iloc[0], "timestamp"):
            save_df["time"] = save_df["time"].apply(lambda x: x.timestamp())
        save_dict = {col: save_df[col].values for col in save_df.columns}
        np.savez_compressed(path, **save_dict)
    except Exception as e:
        logger.debug("Cache save failed: %s", e)
