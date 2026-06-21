"""ML training pipeline: walk-forward LightGBM training on historical data.

Fetches M5 data, engineers features + labels, runs walk-forward training,
evaluates per-window metrics, saves trained model and report.
"""
import os
import json
import logging
import time as _time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from config import DATA_DIR
from backtest_data import fetch_historical_data, df_to_bars
from ml_features import build_dataset, FEATURE_NAMES
from ml_model import LightGBMModel
from ml_enhancements import EventDrivenBacktestEngine

logger = logging.getLogger(__name__)


def _split_walk_forward(n_samples, n_windows=5, train_pct=0.7):
    """Generate walk-forward split indices.

    Returns list of dicts with train/test start/end indices.
    """
    window_size = n_samples // n_windows
    splits = []
    for i in range(n_windows):
        w_start = i * window_size
        w_end = min(w_start + window_size, n_samples)
        split = w_start + int((w_end - w_start) * train_pct)
        if split >= w_end - 50:
            continue
        splits.append({
            "train": (w_start, split),
            "test": (split + 1, w_end),
            "window": i + 1,
        })
    return splits


def _evaluate_signals_on_bars(signals, bars, initial_balance=10000, pip_value=10.0):
    """Run backtest engine on signals and bars."""
    engine = EventDrivenBacktestEngine(
        spread_pips=1.5, slippage_pips=0.5, commission_per_lot=7.0,
    )
    return engine.run(signals, bars, initial_balance=initial_balance, pip_value=pip_value)


def _compute_sharpe(pnls):
    """Compute Sharpe ratio from list of trade P&Ls."""
    if len(pnls) < 2:
        return 0.0
    arr = np.array(pnls)
    mean_r = float(np.mean(arr))
    std_r = float(np.std(arr))
    return round(mean_r / std_r, 2) if std_r > 0 else 0.0


def train_lightgbm_walk_forward(df, n_windows=5, train_pct=0.7, num_boost_round=200,
                                 forward_bars=3, threshold_pct=0.01, initial_balance=10000,
                                 pip_value=10.0, sl_pips=None, tp_pips=None, model_path=None,
                                 min_confidence=0.55, use_atr_sltp=True, use_trend_filter=True):
    """Walk-forward train LightGBM model.

    Args:
        df: OHLCV DataFrame (6+ months of M5 data)
        n_windows: number of walk-forward windows
        train_pct: fraction of each window used for training
        num_boost_round: LightGBM boosting rounds
        forward_bars: bars to look forward for target
        threshold_pct: threshold for buy/sell label
        initial_balance: backtest starting capital
        pip_value: pip value per lot
        sl_pips: stop loss pips (None = auto from ATR)
        tp_pips: take profit pips (None = auto from ATR)
        model_path: path to save model (default: brain_data/ml_model.json)
        min_confidence: minimum model confidence to enter trade (0-1)
        use_atr_sltp: use ATR-based dynamic SL/TP instead of fixed
        use_trend_filter: only trade in direction of EMA50/200 trend

    Returns:
        dict with training results, metrics, and saved paths
    """
    if df is None or len(df) < 500:
        return {"error": "insufficient data", "bars": len(df) if df is not None else 0}

    logger.info("Building dataset from %d bars...", len(df))
    X_all, y_all, feature_names = build_dataset(df, forward_bars, threshold_pct)
    logger.info("Dataset: %d samples, %d features, classes=%s",
                len(X_all), len(feature_names), dict(zip(*np.unique(y_all, return_counts=True))))

    if len(X_all) < 200:
        return {"error": "insufficient valid samples", "samples": len(X_all)}

    splits = _split_walk_forward(len(X_all), n_windows, train_pct)
    if not splits:
        return {"error": "could not create walk-forward splits"}

    model_save_path = model_path or os.path.join(DATA_DIR, "ml_model.json")

    window_results = []
    best_accuracy = 0
    best_model = None

    for split in splits:
        w = split["window"]
        train_start, train_end = split["train"]
        test_start, test_end = split["test"]

        X_train = X_all[train_start:train_end + 1]
        y_train = y_all[train_start:train_end + 1]
        X_test = X_all[test_start:test_end + 1]
        y_test = y_all[test_start:test_end + 1]

        logger.info("Window %d: train=%d, test=%d", w, len(X_train), len(X_test))

        model = LightGBMModel()
        metrics = model.train(
            X_train, y_train,
            feature_names=feature_names,
            num_boost_round=num_boost_round,
            valid_fraction=0.15,
        )

        if "error" in metrics:
            logger.warning("Window %d training failed: %s", w, metrics["error"])
            window_results.append({"window": w, "error": metrics["error"]})
            continue

        # Predict on test set
        test_preds = model.predict(X_test)
        if test_preds is None:
            window_results.append({"window": w, "error": "prediction failed"})
            continue

        # Map predictions to labels
        label_map = model._inverse_label_map if hasattr(model, "_inverse_label_map") else {}
        if not label_map:
            window_results.append({"window": w, "error": "no label map"})
            continue

        pred_labels = np.array([label_map.get(np.argmax(p), 0) for p in test_preds])
        test_accuracy = float(np.mean(pred_labels == y_test))

        # Build signals for backtest evaluation
        # Use original DataFrame indices to build bars
        orig_test_start = test_start + (len(df) - len(X_all))
        orig_test_end = test_start + (len(df) - len(X_all)) + len(X_test)

        # Pre-compute ATR and trend for the test slice
        test_slice = df.iloc[orig_test_start:orig_test_end].copy()
        if use_atr_sltp and len(test_slice) >= 20:
            tr = np.maximum(
                test_slice["high"].values - test_slice["low"].values,
                np.maximum(
                    np.abs(test_slice["high"].values - np.roll(test_slice["close"].values, 1)),
                    np.abs(test_slice["low"].values - np.roll(test_slice["close"].values, 1))
                )
            )
            test_slice["_atr14"] = pd.Series(tr).rolling(14).mean().values

        if use_trend_filter and len(test_slice) >= 50:
            test_slice["_ema50"] = test_slice["close"].ewm(span=50).mean().values
            test_slice["_ema200"] = test_slice["close"].ewm(span=min(200, len(test_slice) - 1)).mean().values

        signals = []
        for i in range(len(X_test)):
            pred = pred_labels[i]
            action = "buy" if pred == 1 else "sell" if pred == -1 else "hold"
            confidence = float(np.max(test_preds[i]))

            # Confidence gate: skip low-confidence trades
            if action != "hold" and confidence < min_confidence:
                action = "hold"

            # Trend filter: only trade in direction of EMA alignment
            if use_trend_filter and action != "hold" and len(test_slice) > 0:
                idx_in_slice = min(i, len(test_slice) - 1)
                if "_ema50" in test_slice.columns and "_ema200" in test_slice.columns:
                    ema50_val = test_slice["_ema50"].iloc[idx_in_slice]
                    ema200_val = test_slice["_ema200"].iloc[idx_in_slice]
                    if action == "buy" and ema50_val < ema200_val:
                        action = "hold"  # Counter-trend: suppress
                    elif action == "sell" and ema50_val > ema200_val:
                        action = "hold"  # Counter-trend: suppress

            # Session filter: suppress trades during low-liquidity Asian session
            if action != "hold" and len(test_slice) > 0:
                idx_in_slice = min(i, len(test_slice) - 1)
                if "time" in test_slice.columns:
                    bar_time = test_slice["time"].iloc[idx_in_slice]
                    try:
                        bar_dt = datetime.fromtimestamp(bar_time) if isinstance(bar_time, (int, float)) else bar_time
                        hour = bar_dt.hour
                        # Suppress during Asian low-liquidity: 21:00-01:00 UTC
                        if hour >= 21 or hour < 1:
                            action = "hold"
                    except (OSError, ValueError, TypeError):
                        pass  # Skip filter if time parsing fails

            # ATR-based dynamic SL/TP
            if use_atr_sltp and "_atr14" in test_slice.columns:
                idx_in_slice = min(i, len(test_slice) - 1)
                atr_val = test_slice["_atr14"].iloc[idx_in_slice]
                if atr_val > 0:
                    curr_sl_pips = max(20, round(atr_val * 2.0 / 0.01))  # 2.0x ATR (wider)
                    curr_tp_pips = max(40, round(atr_val * 3.5 / 0.01))  # 3.5x ATR (1.75:1 RR)
                else:
                    curr_sl_pips = sl_pips or 50
                    curr_tp_pips = tp_pips or 100
            else:
                curr_sl_pips = sl_pips or 50
                curr_tp_pips = tp_pips or 100

            signals.append({
                "action": action,
                "confidence": round(confidence, 4),
                "sl_pips": curr_sl_pips,
                "tp_pips": curr_tp_pips,
            })

        # Build bars for this window from original df
        test_slice = df.iloc[orig_test_start:orig_test_end].copy()
        if len(test_slice) < 10:
            window_results.append({"window": w, "error": "test slice too small"})
            continue

        test_bars = df_to_bars(test_slice)
        backtest_result = _evaluate_signals_on_bars(signals, test_bars, initial_balance, pip_value)

        # Infer pip_size from price level
        median_close = float(test_slice["close"].median()) if len(test_slice) > 0 else 1.0
        if median_close > 50:
            _pip_size = 0.01
        elif median_close > 0.5:
            _pip_size = 0.0001
        else:
            _pip_size = 0.00001

        # Collect trade P&Ls for Sharpe
        trades = []
        balance = initial_balance
        positions = []
        for i, bar in enumerate(test_bars):
            if i >= len(signals):
                break
            sig = signals[i]
            high = bar["high"]
            low = bar["low"]
            close = bar["close"]
            spread = bar.get("spread", 1.5)

            closed = []
            for pos in positions:
                if pos["type"] == "BUY":
                    if low <= pos["sl"]:
                        pnl_pips = (pos["sl"] - pos["entry"]) / _pip_size
                        pnl = pnl_pips * pos["lots"] * pip_value - pos["commission"]
                        balance += pnl
                        trades.append(pnl)
                        closed.append(pos)
                    elif high >= pos["tp"]:
                        pnl_pips = (pos["tp"] - pos["entry"]) / _pip_size
                        pnl = pnl_pips * pos["lots"] * pip_value - pos["commission"]
                        balance += pnl
                        trades.append(pnl)
                        closed.append(pos)
                else:
                    if high >= pos["sl"]:
                        pnl_pips = (pos["entry"] - pos["sl"]) / _pip_size
                        pnl = pnl_pips * pos["lots"] * pip_value - pos["commission"]
                        balance += pnl
                        trades.append(pnl)
                        closed.append(pos)
                    elif low <= pos["tp"]:
                        pnl_pips = (pos["entry"] - pos["tp"]) / _pip_size
                        pnl = pnl_pips * pos["lots"] * pip_value - pos["commission"]
                        balance += pnl
                        trades.append(pnl)
                        closed.append(pos)
            for pos in closed:
                positions.remove(pos)

            if sig.get("action") in ("buy", "sell") and len(positions) < 5:
                confidence = sig.get("confidence", 0.5)
                sig_sl = sig.get("sl_pips", 50)
                sig_tp = sig.get("tp_pips", 100)
                risk_amount = balance * 0.01 * min(confidence, 1.0)
                sl_distance_price = sig_sl * _pip_size
                lots = max(0.01, round(risk_amount / (sl_distance_price * pip_value / _pip_size), 2))
                lots = max(0.01, lots)
                spread_cost = spread * pip_value * lots
                commission = 7.0 * lots + spread_cost + 0.5 * pip_value * lots

                if sig["action"] == "buy":
                    entry = close + (spread / 2 * _pip_size)
                    sl = entry - sig_sl * _pip_size
                    tp = entry + sig_tp * _pip_size
                    positions.append({"type": "BUY", "entry": entry, "sl": sl, "tp": tp,
                                      "lots": lots, "commission": commission})
                else:
                    entry = close - (spread / 2 * _pip_size)
                    sl = entry + sig_sl * _pip_size
                    tp = entry - sig_tp * _pip_size
                    positions.append({"type": "SELL", "entry": entry, "sl": sl, "tp": tp,
                                      "lots": lots, "commission": commission})

        window_results.append({
            "window": w,
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "accuracy": round(test_accuracy, 4),
            "sharpe": _compute_sharpe(trades),
            "total_trades": len(trades),
            "total_return_pct": round((balance - initial_balance) / initial_balance * 100, 2),
            "win_rate": round(sum(1 for t in trades if t > 0) / max(len(trades), 1) * 100, 1),
            "max_drawdown": round(backtest_result.get("max_drawdown", 0), 2),
            "profit_factor": backtest_result.get("profit_factor", 0),
        })

        if test_accuracy > best_accuracy:
            best_accuracy = test_accuracy
            best_model = model

    # Save best model
    if best_model is not None:
        best_model.save(model_save_path)
        logger.info("Best model saved to %s (accuracy=%.4f)", model_save_path, best_accuracy)

    # Aggregate metrics
    valid_windows = [w for w in window_results if "error" not in w]
    if valid_windows:
        avg_accuracy = round(float(np.mean([w["accuracy"] for w in valid_windows])), 4)
        avg_sharpe = round(float(np.mean([w["sharpe"] for w in valid_windows])), 2)
        avg_return = round(float(np.mean([w["total_return_pct"] for w in valid_windows])), 2)
        avg_win_rate = round(float(np.mean([w["win_rate"] for w in valid_windows])), 1)
        avg_drawdown = round(float(np.mean([w["max_drawdown"] for w in valid_windows])), 2)
        avg_pf = round(float(np.mean([w["profit_factor"] for w in valid_windows])), 2)
        total_trades = sum(w["total_trades"] for w in valid_windows)
    else:
        avg_accuracy = avg_sharpe = avg_return = avg_win_rate = avg_drawdown = avg_pf = 0
        total_trades = 0

    top_features = best_model.get_feature_importance(top_n=15) if best_model else []

    report = {
        "generated_at": datetime.now().isoformat(),
        "n_windows": len(window_results),
        "valid_windows": len(valid_windows),
        "avg_accuracy": avg_accuracy,
        "avg_test_sharpe": avg_sharpe,
        "avg_test_return_pct": avg_return,
        "avg_test_win_rate": avg_win_rate,
        "avg_test_max_drawdown": avg_drawdown,
        "avg_test_profit_factor": avg_pf,
        "total_trades": total_trades,
        "best_accuracy": best_accuracy,
        "model_saved": model_save_path if best_model else None,
        "feature_names": feature_names,
        "top_features": [{"name": name, "importance": round(imp, 2)} for name, imp in top_features],
        "windows": window_results,
    }

    # Save report
    report_path = os.path.join(DATA_DIR, "ml_training_report.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Training report saved to %s", report_path)

    return report


def run_training_pipeline(symbol="EURUSD", timeframe=None, months=6, max_bars=50000, timeout_seconds=600):
    """Full ML training pipeline.

    1. Fetch 6+ months of M5 data
    2. Engineer features + labels
    3. Walk-forward train LightGBM
    4. Evaluate on test windows
    5. Save trained model + report

    Args:
        symbol: MT5 symbol (default: EURUSD)
        months: months of history (default: 6)
        max_bars: max bars to fetch (default: 50000)
        timeout_seconds: hard timeout (default: 600s)

    Returns:
        dict with full training report
    """
    import mt5_mcp as mt5
    pipeline_start = _time.time()

    logger.info("=== ML Training Pipeline ===")
    logger.info("Symbol: %s, Months: %d, Max bars: %d", symbol, months, max_bars)

    # 1. Fetch data
    if timeframe is None:
        timeframe = mt5.TIMEFRAME_M5
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)

    logger.info("Fetching %s data: %s to %s", symbol,
                start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
    df = fetch_historical_data(symbol, timeframe, start_date, end_date, use_cache=True,
                               max_bars=max_bars)
    if df is None or len(df) < 500:
        return {"error": "Failed to fetch sufficient data", "bars": len(df) if df is not None else 0}

    logger.info("Fetched %d bars", len(df))

    elapsed = _time.time() - pipeline_start
    if elapsed > timeout_seconds:
        return {"error": f"Timeout after data fetch ({elapsed:.0f}s)"}

    # 2-4. Walk-forward training with improved strategy
    result = train_lightgbm_walk_forward(
        df, n_windows=5, train_pct=0.7, num_boost_round=200,
        forward_bars=3, threshold_pct=0.01,
        min_confidence=0.65, use_atr_sltp=True, use_trend_filter=True,
    )

    result["data_bars"] = len(df)
    result["data_symbol"] = symbol
    result["data_months"] = months
    result["pipeline_time_seconds"] = round(_time.time() - pipeline_start, 1)

    logger.info("Pipeline complete: avg_accuracy=%.4f, avg_sharpe=%.2f",
                result.get("avg_accuracy", 0), result.get("avg_test_sharpe", 0))
    return result


if __name__ == "__main__":
    import sys
    import time as _time
    logging.basicConfig(level=logging.INFO)

    # Parse simple args: symbol and timeframe
    symbol = "EURUSD"
    timeframe = None
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--symbol" and i + 1 < len(sys.argv) - 1:
            symbol = sys.argv[i + 2]
        elif arg == "--timeframe" and i + 1 < len(sys.argv) - 1:
            timeframe = int(sys.argv[i + 2])

    logger.info("=== ML Training Pipeline: standalone run ===")
    result = run_training_pipeline(symbol=symbol, timeframe=timeframe, months=6, max_bars=50000, timeout_seconds=600)
    print(json.dumps(result, indent=2, default=str))

    if "error" not in result:
        logger.info("Training succeeded!")
    else:
        logger.error("Training failed: %s", result["error"])
