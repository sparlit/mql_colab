"""
CPU-Bound Task Functions for ProcessPoolExecutor.
These are standalone functions designed for parallel execution across processes.
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any
from indicators import ema

try:
    from numba import njit
    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False
    def njit(f=None, **kwargs):
        if f is None:
            return lambda fn: fn
        return f


@njit(cache=True)
def _monte_carlo_kernel(win_rate, avg_win, avg_loss, n_trades, n_sims, initial_balance):
    finals = np.empty(n_sims, dtype=np.float64)
    max_dds = np.empty(n_sims, dtype=np.float64)
    for sim in range(n_sims):
        balance = initial_balance
        peak = balance
        max_dd = 0.0
        for t in range(n_trades):
            if np.random.random() < win_rate:
                balance += avg_win
            else:
                balance -= avg_loss
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak if peak > 0.0 else 0.0
            if dd > max_dd:
                max_dd = dd
        finals[sim] = balance
        max_dds[sim] = max_dd
    returns = (finals - initial_balance) / initial_balance
    return returns, max_dds


def calculate_indicators_batch(close_data: np.ndarray) -> Dict[str, np.ndarray]:
    """Calculate all technical indicators for a price series (CPU-bound, GPU-accelerated when available).

    Args:
        close_data: Array of closing prices
    Returns:
        Dictionary of indicator arrays
    """
    # Try GPU-accelerated path first
    try:
        from integration import get_gpu_engine
        gpu = get_gpu_engine()
        if gpu and gpu.gpu_available:
            batch = {"symbol_0": {
                "open": close_data, "high": close_data * 1.001,
                "low": close_data * 0.999, "close": close_data,
                "volume": np.ones_like(close_data),
            }}
            gpu_result = gpu.batch_indicators(batch, ["ema_20", "ema_50", "rsi_14", "macd", "bollinger", "atr_14"])
            sym_data = gpu_result.get("symbol_0", {})
            result = {}
            for span in [5, 8, 13, 21]:
                result[f'EMA{span}'] = ema(close_data, span)
            if "ema_20" in sym_data:
                result['EMA20'] = sym_data["ema_20"]
            if "ema_50" in sym_data:
                result['EMA50'] = sym_data["ema_50"]
            result['EMA200'] = ema(close_data, 200)
            if "rsi_14" in sym_data:
                result['RSI'] = sym_data["rsi_14"]
            else:
                result['RSI'] = _calc_rsi(close_data)
            if "atr_14" in sym_data:
                result['ATR'] = sym_data["atr_14"]
            else:
                result['ATR'] = _calc_atr(close_data)
            if "macd" in sym_data:
                result['MACD'] = sym_data["macd"]
                result['MACD_SIGNAL'] = sym_data.get("macd_signal", np.zeros_like(close_data))
                result['MACD_HIST'] = sym_data.get("macd_hist", np.zeros_like(close_data))
            else:
                result['MACD'] = np.zeros_like(close_data)
                result['MACD_SIGNAL'] = np.zeros_like(close_data)
                result['MACD_HIST'] = np.zeros_like(close_data)
            if "bb_upper" in sym_data:
                result['BB_UP'] = sym_data["bb_upper"]
                result['BB_MA'] = sym_data.get("bb_middle", close_data)
                result['BB_DN'] = sym_data.get("bb_lower", close_data)
            else:
                result['BB_MA'] = pd.Series(close_data).rolling(window=20).mean().values
                bb_std = pd.Series(close_data).rolling(window=20).std().values
                result['BB_UP'] = result['BB_MA'] + (bb_std * 2.0)
                result['BB_DN'] = result['BB_MA'] - (bb_std * 2.0)
            return result
    except Exception:
        pass

    # CPU fallback
    result = {}
    for span in [5, 8, 13, 21, 50, 200]:
        result[f'EMA{span}'] = ema(close_data, span)
    result['RSI'] = _calc_rsi(close_data)
    result['ATR'] = _calc_atr(close_data)
    result['MACD'] = np.zeros_like(close_data)
    result['MACD_SIGNAL'] = np.zeros_like(close_data)
    result['MACD_HIST'] = np.zeros_like(close_data)
    result['BB_MA'] = pd.Series(close_data).rolling(window=20).mean().values
    bb_std = pd.Series(close_data).rolling(window=20).std().values
    result['BB_UP'] = result['BB_MA'] + (bb_std * 2.0)
    result['BB_DN'] = result['BB_MA'] - (bb_std * 2.0)
    return result


def _calc_rsi(close_data):
    delta = np.diff(close_data, prepend=close_data[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(window=14).mean().values
    avg_loss = pd.Series(loss).rolling(window=14).mean().values
    avg_loss = np.where(avg_loss == 0, 1e-10, avg_loss)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_atr(close_data):
    close_diff = np.abs(np.diff(close_data, prepend=close_data[0]))
    return pd.Series(close_diff).rolling(window=14).mean().values


def monte_carlo_simulation(win_rate: float, avg_win: float, avg_loss: float,
                           n_trades: int = 1000, n_simulations: int = 1000,
                           initial_balance: float = 10000.0,
                           parallel: bool = True) -> Dict:
    """Run Monte Carlo trade simulation (CPU-bound, numba JIT-compiled).

    Supports parallel execution by splitting simulations across CPU cores.

    Args:
        win_rate: Probability of winning a trade (0-1)
        avg_win: Average win amount
        avg_loss: Average loss amount
        n_trades: Number of trades per simulation
        n_simulations: Number of Monte Carlo simulations
        initial_balance: Starting balance
        parallel: Split simulations across CPU cores (default True)
    Returns:
        Dictionary with simulation results
    """
    if parallel and n_simulations >= 100:
        import os
        from concurrent.futures import ProcessPoolExecutor, as_completed

        n_workers = min(os.cpu_count() or 4, 8)
        chunk_size = max(1, n_simulations // n_workers)
        chunks = []
        remaining = n_simulations
        for _ in range(n_workers):
            size = min(chunk_size, remaining)
            if size <= 0:
                break
            chunks.append(size)
            remaining -= size

        if len(chunks) > 1:
            all_returns = []
            all_dds = []
            with ProcessPoolExecutor(max_workers=n_workers) as pool:
                futures = {
                    pool.submit(_monte_carlo_kernel, win_rate, avg_win, avg_loss,
                                n_trades, chunk, initial_balance): i
                    for i, chunk in enumerate(chunks)
                }
                for future in as_completed(futures):
                    returns, dds = future.result(timeout=30)
                    all_returns.append(returns)
                    all_dds.append(dds)

            returns = np.concatenate(all_returns)
            dds = np.concatenate(all_dds)
        else:
            returns, dds = _monte_carlo_kernel(
                win_rate, avg_win, avg_loss, n_trades, n_simulations, initial_balance
            )
    else:
        returns, dds = _monte_carlo_kernel(
            win_rate, avg_win, avg_loss, n_trades, n_simulations, initial_balance
        )

    return {
        "mean_return": round(float(np.mean(returns) * 100), 2),
        "median_return": round(float(np.median(returns) * 100), 2),
        "std_return": round(float(np.std(returns) * 100), 2),
        "prob_profit": round(float(np.sum(returns > 0) / len(returns) * 100), 1),
        "var_95": round(float(np.percentile(returns, 5) * 100), 2),
        "cvar_95": round(float(np.mean(returns[returns <= np.percentile(returns, 5)]) * 100), 2) if np.any(returns <= np.percentile(returns, 5)) else 0,
        "max_dd_avg": round(float(np.mean(dds) * 100), 2),
        "max_dd_worst": round(float(np.max(dds) * 100), 2),
        "simulations": len(returns),
        "parallel_workers": len(chunks) if parallel and len(chunks) > 1 else 1,
    }


def calculate_correlation_batch(args: Tuple[np.ndarray, np.ndarray, str, str]) -> Tuple[str, float]:
    """Calculate correlation between two return series (CPU-bound).
    
    Args:
        Tuple of (returns1, returns2, symbol1, symbol2)
    Returns:
        Tuple of (pair_key, correlation_value)
    """
    returns1, returns2, s1, s2 = args
    
    # Ensure same length
    min_len = min(len(returns1), len(returns2))
    r1 = returns1[-min_len:]
    r2 = returns2[-min_len:]
    
    # Remove infs/nans
    mask = np.isfinite(r1) & np.isfinite(r2)
    r1 = r1[mask]
    r2 = r2[mask]
    
    if len(r1) < 20 or np.std(r1) == 0 or np.std(r2) == 0:
        return (f"{s1}_{s2}", 0.0)
    
    corr = np.corrcoef(r1, r2)[0, 1]
    return (f"{s1}_{s2}", round(float(corr), 4))


def calculate_multi_tf_signals(args: Tuple[str, List[int]]) -> Dict[str, int]:
    """Calculate multi-timeframe signals for a symbol (CPU-bound).
    
    Args:
        Tuple of (symbol, list_of_timeframes)
    Returns:
        Dictionary mapping timeframe to signal direction
    """
    try:
        import mt5_mcp as mt5
    except ImportError:
        symbol, timeframes = args
        return {tf: 0 for tf in timeframes}
    
    symbol, timeframes = args
    tf_signals = {}
    
    for tf in timeframes:
        try:
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, 250)
            if rates is None:
                continue
            df = pd.DataFrame(rates)
            
            # Calculate EMAs
            df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()
            df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
            df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
            
            last = df.iloc[-1]
            if last['EMA20'] > last['EMA50'] > last['EMA200']:
                tf_signals[tf] = 1
            elif last['EMA20'] < last['EMA50'] < last['EMA200']:
                tf_signals[tf] = -1
            else:
                tf_signals[tf] = 0
        except Exception:
            tf_signals[tf] = 0
    
    return tf_signals


def calculate_symbol_indicators(symbol_data: Dict) -> Dict:
    """Calculate all indicators for a single symbol (CPU-bound).
    
    Args:
        symbol_data: Dictionary with OHLCV data
    Returns:
        Dictionary with calculated indicators
    """
    close = np.array(symbol_data['close'])
    high = np.array(symbol_data['high'])
    low = np.array(symbol_data['low'])
    volume = np.array(symbol_data['volume'])
    
    result = {}
    
    # EMAs using shared function
    for span in [5, 8, 13, 21, 50, 200]:
        result[f'EMA{span}'] = ema(close, span)
    
    # RSI
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(window=14).mean().values
    avg_loss = pd.Series(loss).rolling(window=14).mean().values
    avg_loss = np.where(avg_loss == 0, 1e-10, avg_loss)
    rs = avg_gain / avg_loss
    result['RSI'] = 100 - (100 / (1 + rs))
    
    # Bollinger Bands
    result['BB_MA'] = pd.Series(close).rolling(window=20).mean().values
    bb_std = pd.Series(close).rolling(window=20).std().values
    result['BB_UP'] = result['BB_MA'] + (bb_std * 2.0)
    result['BB_DN'] = result['BB_MA'] - (bb_std * 2.0)
    
    # ATR
    tr1 = high - low
    tr2 = np.abs(high - np.roll(close, 1))
    tr3 = np.abs(low - np.roll(close, 1))
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    tr[0] = high[0] - low[0]
    result['ATR'] = pd.Series(tr).rolling(window=14).mean().values
    
    # MACD using shared ema function
    result['MACD'] = ema(close, 12) - ema(close, 26)
    result['MACD_SIGNAL'] = pd.Series(result['MACD']).ewm(span=9, adjust=False).mean().values
    result['MACD_HIST'] = result['MACD'] - result['MACD_SIGNAL']
    
    # Stochastic
    lowest = pd.Series(low).rolling(window=14).min().values
    highest = pd.Series(high).rolling(window=14).max().values
    rng = highest - lowest
    rng = np.where(rng == 0, 1, rng)
    result['STOCH_K'] = ((close - lowest) / rng) * 100
    result['STOCH_D'] = pd.Series(result['STOCH_K']).rolling(window=3).mean().values
    
    # Momentum and ROC
    result['MOM'] = close - np.roll(close, 10)
    result['MOM'][:10] = 0
    result['ROC'] = pd.Series(close).pct_change(periods=10).values * 100
    
    # VWAP
    cv = close * volume
    result['VWAP'] = pd.Series(cv).rolling(window=20).sum().values / np.maximum(pd.Series(volume).rolling(window=20).sum().values, 1)
    
    # OBV
    delta_sign = np.sign(np.diff(close, prepend=close[0]))
    result['OBV'] = np.cumsum(delta_sign * volume)
    
    return result


def calculate_portfolio_var(returns: np.ndarray, confidence: float = 0.95) -> Dict:
    """Calculate Value at Risk (CPU-bound).
    
    Args:
        returns: Array of portfolio returns
        confidence: Confidence level (0-1)
    Returns:
        Dictionary with VaR metrics
    """
    sorted_returns = np.sort(returns)
    idx = int(len(sorted_returns) * (1 - confidence))
    var = abs(sorted_returns[idx]) if idx < len(sorted_returns) else 0
    
    tail = sorted_returns[:idx + 1] if idx < len(sorted_returns) else sorted_returns[:1]
    cvar = abs(np.mean(tail)) if len(tail) > 0 else 0
    
    return {
        "var": round(float(var * 100), 4),
        "cvar": round(float(cvar * 100), 4),
        "confidence": confidence,
        "n_returns": len(returns),
    }


def optimize_portfolio_weights(args: Tuple) -> Dict:
    """Optimize portfolio weights using risk parity (CPU-bound).
    
    Args:
        Tuple of (cov_matrix, target_risk_budget)
    Returns:
        Dictionary with optimized weights
    """
    cov_matrix, target_risk = args
    n = cov_matrix.shape[0]
    
    # Simple inverse volatility weighting
    vols = np.sqrt(np.diag(cov_matrix))
    vols = np.where(vols == 0, 1e-10, vols)
    inv_vols = 1.0 / vols
    weights = inv_vols / np.sum(inv_vols)
    
    return {
        "weights": weights.tolist(),
        "expected_risk": float(np.sqrt(weights @ cov_matrix @ weights)),
        "method": "inverse_volatility",
    }


def batch_pattern_detection(args: Tuple) -> List[Dict]:
    """Detect chart patterns for multiple symbols (CPU-bound).
    
    Args:
        Tuple of (symbol_data_list, pattern_type)
    Returns:
        List of pattern detection results
    """
    symbol_data, pattern_type = args
    results = []
    
    for sym_data in symbol_data:
        symbol = sym_data.get('symbol', 'unknown')
        close = np.array(sym_data.get('close', []))
        high = np.array(sym_data.get('high', []))
        low = np.array(sym_data.get('low', []))
        
        if len(close) < 20:
            results.append({"symbol": symbol, "patterns": []})
            continue
        
        patterns = []
        
        # Simple double top/bottom detection
        highs_sorted = np.sort(high[-20:])[::-1]
        lows_sorted = np.sort(low[-20:])
        
        # Check for consolidation
        price_range = (np.max(close[-20:]) - np.min(close[-20:])) / np.mean(close[-20:])
        if price_range < 0.02:  # Less than 2% range
            patterns.append({"type": "consolidation", "strength": min(1.0, 0.02 / price_range)})
        
        # Check for trend
        returns = np.diff(close[-20:]) / close[-21:-1]
        mean_return = np.mean(returns)
        if abs(mean_return) > 0.001:
            trend_strength = min(1.0, abs(mean_return) * 100)
            trend_dir = "up" if mean_return > 0 else "down"
            patterns.append({"type": f"trend_{trend_dir}", "strength": trend_strength})
        
        # Check for breakout potential
        atr = np.mean(np.maximum(high[-14:] - low[-14:], 
                                  np.maximum(np.abs(high[-14:] - np.roll(close[-14:], 1)),
                                            np.abs(low[-14:] - np.roll(close[-14:], 1)))))
        price_volatility = atr / np.mean(close[-14:])
        if price_volatility > 0.01:
            patterns.append({"type": "high_volatility", "strength": min(1.0, price_volatility * 10)})
        
        results.append({"symbol": symbol, "patterns": patterns})
    
    return results
