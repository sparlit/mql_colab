"""Walk-forward validation for backtesting.

Splits historical data into rolling train/test windows, evaluates per-window
metrics, and detects overfitting.
"""
import logging
import numpy as np
import pandas as pd
from ml_enhancements import EventDrivenBacktestEngine, RulesBaseline
from backtest_data import df_to_bars

logger = logging.getLogger(__name__)


def _split_windows(total_bars, train_pct=0.7, n_windows=5):
    """Generate (train_start, train_end, test_start, test_end) indices."""
    window_size = total_bars // n_windows
    windows = []
    for i in range(n_windows):
        w_start = i * window_size
        w_end = min(w_start + window_size, total_bars)
        split = w_start + int((w_end - w_start) * train_pct)
        if split >= w_end - 10:
            continue
        windows.append({
            "train": (w_start, split),
            "test": (split + 1, w_end),
        })
    return windows


def _evaluate_window(signals, bars, initial_balance, pip_value):
    """Run backtest on a single window and return metrics dict."""
    engine = EventDrivenBacktestEngine(
        spread_pips=1.5, slippage_pips=0.5, commission_per_lot=7.0,
    )
    return engine.run(signals, bars, initial_balance=initial_balance, pip_value=pip_value)


def _compute_sharpe_from_trades(trades, risk_free=0.0):
    if len(trades) < 2:
        return 0
    returns = [t["pnl"] for t in trades]
    mean_r = np.mean(returns)
    std_r = np.std(returns)
    if std_r == 0:
        return 0
    return round((mean_r - risk_free) / std_r, 2)


def _max_drawdown_from_equity(equity_curve):
    peak = equity_curve[0]
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    return max_dd * 100


def run_walk_forward(df, initial_balance=10000, pip_value=10.0,
                     train_pct=0.7, n_windows=5, sl_pips=50, tp_pips=100):
    """Run walk-forward validation on a DataFrame of OHLCV data.

    Args:
        df: pd.DataFrame with open, high, low, close columns
        initial_balance: starting capital
        pip_value: pip value per lot
        train_pct: fraction of each window used for training
        n_windows: number of rolling windows
        sl_pips: stop loss in pips
        tp_pips: take profit in pips

    Returns:
        dict with per-window results, aggregate metrics, overfitting flag
    """
    if df is None or len(df) < 200:
        return {"error": "insufficient data", "windows": []}

    bars = df_to_bars(df)
    windows = _split_windows(len(bars), train_pct, n_windows)
    if not windows:
        return {"error": "could not create windows", "windows": []}

    baseline = RulesBaseline()
    window_results = []

    for idx, w in enumerate(windows):
        train_slice = df.iloc[w["train"][0]:w["train"][1] + 1].copy()
        test_slice = df.iloc[w["test"][0]:w["test"][1] + 1].copy()

        train_signals = _generate_signals(baseline, train_slice, sl_pips, tp_pips)
        test_signals = _generate_signals(baseline, test_slice, sl_pips, tp_pips)

        train_bars = df_to_bars(train_slice)
        test_bars = df_to_bars(test_slice)

        train_metrics = _evaluate_window(train_signals, train_bars, initial_balance, pip_value)
        test_metrics = _evaluate_window(test_signals, test_bars, initial_balance, pip_value)

        wr = test_metrics.get("win_rate", 0)
        pf = test_metrics.get("profit_factor", 0)
        dd = test_metrics.get("max_drawdown", 100)
        sharpe = test_metrics.get("sharpe_ratio", 0)

        window_results.append({
            "window": idx + 1,
            "train_bars": len(train_slice),
            "test_bars": len(test_slice),
            "train_trades": train_metrics.get("total_trades", 0),
            "test_trades": test_metrics.get("total_trades", 0),
            "train_return_pct": train_metrics.get("total_return", 0),
            "test_return_pct": test_metrics.get("total_return", 0),
            "train_sharpe": train_metrics.get("sharpe_ratio", 0),
            "test_sharpe": sharpe,
            "test_win_rate": wr,
            "test_profit_factor": pf,
            "test_max_drawdown": dd,
        })

    train_returns = [w["train_return_pct"] for w in window_results]
    test_returns = [w["test_return_pct"] for w in window_results]
    avg_train = np.mean(train_returns) if train_returns else 0
    avg_test = np.mean(test_returns) if test_returns else 0

    overfitting = False
    if avg_train > 0:
        degradation = (avg_train - avg_test) / abs(avg_train) * 100
        overfitting = degradation > 50
    elif avg_test < 0 and avg_train > 0:
        overfitting = True

    avg_sharpe = np.mean([w["test_sharpe"] for w in window_results]) if window_results else 0
    avg_wr = np.mean([w["test_win_rate"] for w in window_results]) if window_results else 0
    avg_pf = np.mean([w["test_profit_factor"] for w in window_results]) if window_results else 0
    avg_dd = np.mean([w["test_max_drawdown"] for w in window_results]) if window_results else 100

    return {
        "n_windows": len(window_results),
        "avg_train_return_pct": round(avg_train, 2),
        "avg_test_return_pct": round(avg_test, 2),
        "avg_test_sharpe": round(avg_sharpe, 2),
        "avg_test_win_rate": round(avg_wr, 1),
        "avg_test_profit_factor": round(avg_pf, 2),
        "avg_test_max_drawdown": round(avg_dd, 2),
        "overfitting_detected": overfitting,
        "windows": window_results,
    }


def _generate_signals(baseline, df, sl_pips, tp_pips):
    """Generate signal list from RulesBaseline for a DataFrame.

    Returns list of signal dicts compatible with EventDrivenBacktestEngine.
    """
    signals = []
    min_bars = 50
    for i in range(len(df)):
        if i < min_bars:
            signals.append({"action": "hold", "confidence": 0, "sl_pips": sl_pips, "tp_pips": tp_pips})
            continue
        window = df.iloc[i - min_bars:i + 1].copy()
        result = baseline.evaluate(window)
        result["sl_pips"] = sl_pips
        result["tp_pips"] = tp_pips
        signals.append(result)
    return signals
