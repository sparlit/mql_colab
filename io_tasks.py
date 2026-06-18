"""
I/O-Bound Task Functions for ThreadPoolExecutor.
These are standalone functions designed for parallel I/O execution.
"""
import os
import json
import logging
import pandas as pd
from typing import Dict, List, Tuple, Any, Optional
from config import DATA_DIR

logger = logging.getLogger(__name__)


def fetch_mt5_rates(symbol: str, timeframe: int, count: int = 300) -> Optional[object]:
    """Fetch OHLCV rates from MT5 (I/O-bound).
    
    Args:
        symbol: Trading symbol
        timeframe: MT5 timeframe constant
        count: Number of bars to fetch
    Returns:
        DataFrame with OHLCV data or None
    """
    import MetaTrader5 as mt5
    
    try:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None:
            logger.warning("No rates returned for %s", symbol)
            return None
        return pd.DataFrame(rates)
    except Exception as e:
        logger.error("Failed to fetch rates for %s: %s", symbol, e)
        return None


def fetch_mt5_symbol_info(symbol: str) -> Optional[Dict]:
    """Fetch symbol information from MT5 (I/O-bound).
    
    Args:
        symbol: Trading symbol
    Returns:
        Dictionary with symbol info or None
    """
    import MetaTrader5 as mt5
    
    try:
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        
        return {
            "name": info.name,
            "description": info.description,
            "point": info.point,
            "digits": info.digits,
            "spread": info.spread,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "trade_tick_value": info.trade_tick_value,
            "trade_tick_size": info.trade_tick_size,
            "margin_initial": info.margin_initial,
            "swap_long": info.swap_long,
            "swap_short": info.swap_short,
        }
    except Exception as e:
        logger.error("Failed to fetch symbol info for %s: %s", symbol, e)
        return None


def fetch_multiple_symbols(symbols: List[str]) -> Dict[str, Any]:
    """Fetch symbol info for multiple symbols in parallel (I/O-bound).
    
    Args:
        symbols: List of trading symbols
    Returns:
        Dictionary mapping symbol to its info
    """
    import MetaTrader5 as mt5
    
    results = {}
    for symbol in symbols:
        try:
            info = mt5.symbol_info(symbol)
            if info:
                results[symbol] = {
                    "name": info.name,
                    "point": info.point,
                    "digits": info.digits,
                    "spread": info.spread,
                    "volume_min": info.volume_min,
                    "volume_max": info.volume_max,
                }
        except Exception as e:
            logger.error("Failed to fetch info for %s: %s", symbol, e)
    
    return results


def read_json_file(filepath: str) -> Optional[Dict]:
    """Read and parse a JSON file (I/O-bound).
    
    Args:
        filepath: Path to JSON file
    Returns:
        Parsed JSON data or None
    """
    try:
        if not os.path.exists(filepath):
            return None
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to read JSON file %s: %s", filepath, e)
        return None


def write_json_file(filepath: str, data: Any) -> bool:
    """Write data to a JSON file (I/O-bound).
    
    Args:
        filepath: Path to JSON file
        data: Data to write
    Returns:
        True if successful, False otherwise
    """
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)
        return True
    except Exception as e:
        logger.error("Failed to write JSON file %s: %s", filepath, e)
        return False


def batch_read_json_files(filepaths: List[str]) -> Dict[str, Any]:
    """Read multiple JSON files in parallel (I/O-bound).
    
    Args:
        filepaths: List of file paths to read
    Returns:
        Dictionary mapping filepath to parsed data
    """
    results = {}
    for filepath in filepaths:
        data = read_json_file(filepath)
        if data is not None:
            results[filepath] = data
    return results


def batch_write_json_files(items: List[Tuple[str, Any]]) -> Dict[str, bool]:
    """Write multiple JSON files in parallel (I/O-bound).
    
    Args:
        items: List of (filepath, data) tuples
    Returns:
        Dictionary mapping filepath to success status
    """
    results = {}
    for filepath, data in items:
        results[filepath] = write_json_file(filepath, data)
    return results


def fetch_network_data(url: str, timeout: int = 10) -> Optional[Dict]:
    """Fetch data from a network URL (I/O-bound).
    
    Args:
        url: URL to fetch
        timeout: Request timeout in seconds
    Returns:
        JSON response or None
    """
    try:
        import requests
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except ImportError:
        logger.warning("requests library not available")
        return None
    except Exception as e:
        logger.error("Failed to fetch network data from %s: %s", url, e)
        return None


def batch_fetch_network_data(urls: List[str]) -> Dict[str, Any]:
    """Fetch data from multiple URLs in parallel (I/O-bound).
    
    Args:
        urls: List of URLs to fetch
    Returns:
        Dictionary mapping URL to response data
    """
    results = {}
    for url in urls:
        data = fetch_network_data(url)
        if data is not None:
            results[url] = data
    return results


def save_trade_log(trades: List[Dict], filepath: str) -> bool:
    """Save trades to JSON log file (I/O-bound).
    
    Args:
        trades: List of trade dictionaries
        filepath: Path to save file
    Returns:
        True if successful
    """
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        lock_path = filepath + ".lock"
        try:
            import msvcrt
            _locking = msvcrt.locking
            _LK_LOCK = msvcrt.LK_LOCK
            _LK_UNLCK = msvcrt.LK_UNLCK
        except ImportError:
            import fcntl
            _locking = None
        
        with open(lock_path, "w") as lock_f:
            if _locking:
                _locking(lock_f.fileno(), _LK_LOCK, 1)
            else:
                fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
            try:
                existing = []
                if os.path.exists(filepath):
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            existing = json.load(f)
                    except (json.JSONDecodeError, OSError) as e:
                        existing = []
                        logger.debug("Trade log read failed: %s", e)
                
                existing.extend(trades)
                
                if len(existing) > 10000:
                    existing = existing[-10000:]
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(existing, f, indent=2, default=str)
            finally:
                if _locking:
                    _locking(lock_f.fileno(), _LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
        
        return True
    except Exception as e:
        logger.error("Failed to save trade log: %s", e)
        return False


def load_trade_log(filepath: str) -> List[Dict]:
    """Load trade log from file (I/O-bound).
    
    Args:
        filepath: Path to trade log
    Returns:
        List of trade dictionaries
    """
    try:
        if not os.path.exists(filepath):
            return []
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load trade log: %s", e)
        return []
