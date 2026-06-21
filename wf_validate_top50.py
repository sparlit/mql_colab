"""Walk-forward validation on top 50 symbols by ML accuracy.
Parallel evaluation + parallel walk-forward.
"""
import os
import sys
import json
import logging
import time as _time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import glob

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from config import DATA_DIR

TOP_N = 50
TIMEFRAME = 5
MONTHS = 6
MAX_BARS = 20000
WF_MAX_WORKERS = 4
EVAL_MAX_WORKERS = 6
RESULTS_PATH = os.path.join(DATA_DIR, "wf_validation_top50.json")


def find_all_models():
    pattern = os.path.join(DATA_DIR, "ml_model_*.json")
    files = glob.glob(pattern)
    models = []
    for f in files:
        basename = os.path.basename(f)
        if "_meta" in basename:
            continue
        symbol = basename.replace("ml_model_", "").replace(".json", "")
        models.append({"symbol": symbol, "path": f})
    return models


def quick_evaluate(symbol):
    try:
        from backtest_data import fetch_historical_data
        from ml_features import build_dataset
        from ml_model import LightGBMModel

        model_path = os.path.join(DATA_DIR, f"ml_model_{symbol}.json")
        if not os.path.exists(model_path):
            return None

        model = LightGBMModel()
        if not model.load(model_path):
            return None

        end_date = datetime.now()
        start_date = end_date - timedelta(days=MONTHS * 30)
        df = fetch_historical_data(symbol, TIMEFRAME, start_date, end_date,
                                   use_cache=True, max_bars=MAX_BARS)
        if df is None or len(df) < 500:
            return None

        X, y, feature_names = build_dataset(df, forward_bars=3, threshold_pct=0.01)
        if len(X) < 100:
            return None

        eval_start = int(len(X) * 0.7)
        X_eval = X[eval_start:]
        y_eval = y[eval_start:]

        preds = model.predict(X_eval)
        if preds is None:
            return None

        label_map = model._inverse_label_map if hasattr(model, "_inverse_label_map") else {}
        if not label_map:
            return None

        pred_labels = np.array([label_map.get(np.argmax(p), 0) for p in preds])
        accuracy = float(np.mean(pred_labels == y_eval))

        return {
            "symbol": symbol,
            "accuracy": round(accuracy, 4),
            "eval_samples": len(X_eval),
            "total_samples": len(X),
        }
    except Exception:
        return None


def walk_forward_symbol(symbol):
    try:
        from train_ml import run_training_pipeline
        result = run_training_pipeline(
            symbol=symbol, timeframe=TIMEFRAME,
            months=MONTHS, max_bars=50000, timeout_seconds=300,
        )
        return result
    except Exception as e:
        return {"error": str(e), "symbol": symbol}


def run():
    models = find_all_models()
    logger.info("Found %d trained models", len(models))

    # Step 1: Parallel evaluation
    logger.info("=" * 60)
    logger.info("STEP 1: Quick accuracy evaluation (%d workers)", EVAL_MAX_WORKERS)
    logger.info("=" * 60)

    evaluations = []
    done = 0
    batch_start = _time.time()

    with ThreadPoolExecutor(max_workers=EVAL_MAX_WORKERS, thread_name_prefix="Eval") as pool:
        futures = {pool.submit(quick_evaluate, m["symbol"]): m["symbol"] for m in models}
        for future in as_completed(futures):
            done += 1
            if done % 100 == 0:
                elapsed = _time.time() - batch_start
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (len(models) - done) / rate if rate > 0 else 0
                logger.info("  Evaluated %d/%d (%.0f%%) | %.1f sym/s | ETA=%.0fs",
                            done, len(models), 100 * done / len(models), rate, remaining)
            result = future.result()
            if result:
                evaluations.append(result)

    logger.info("Evaluated %d/%d models in %.0fs", len(evaluations), len(models),
                _time.time() - batch_start)

    # Step 2: Rank and select top 50
    evaluations.sort(key=lambda x: x["accuracy"], reverse=True)
    top50 = evaluations[:TOP_N]

    logger.info("")
    logger.info("=" * 60)
    logger.info("TOP 50 SYMBOLS BY ACCURACY:")
    logger.info("=" * 60)
    for i, e in enumerate(top50):
        logger.info("  #%2d %-12s acc=%.4f samples=%d",
                     i + 1, e["symbol"], e["accuracy"], e["eval_samples"])

    # Step 3: Parallel walk-forward
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 2: Walk-forward validation (%d workers)", WF_MAX_WORKERS)
    logger.info("=" * 60)

    wf_results = []
    done_wf = 0
    wf_start = _time.time()

    with ThreadPoolExecutor(max_workers=WF_MAX_WORKERS, thread_name_prefix="WF") as pool:
        futures = {}
        for e in top50:
            f = pool.submit(walk_forward_symbol, e["symbol"])
            futures[f] = e

        for future in as_completed(futures):
            done_wf += 1
            e = futures[future]
            symbol = e["symbol"]
            try:
                wf_result = future.result(timeout=300)
            except Exception as exc:
                wf_result = {"error": str(exc), "symbol": symbol}

            wf_result["pre_accuracy"] = e["accuracy"]
            wf_result["pre_eval_samples"] = e["eval_samples"]
            wf_results.append(wf_result)

            elapsed = _time.time() - wf_start
            rate = done_wf / elapsed if elapsed > 0 else 0
            remaining = (len(top50) - done_wf) / rate if rate > 0 else 0

            if "error" in wf_result:
                logger.info("  [%d/%d] %s FAILED: %s | ETA=%.0fs",
                            done_wf, len(top50), symbol, wf_result["error"][:40], remaining)
            else:
                acc = wf_result.get("avg_accuracy", 0)
                sharpe = wf_result.get("avg_test_sharpe", 0)
                logger.info("  [%d/%d] %s acc=%.4f sharpe=%.2f | ETA=%.0fs",
                            done_wf, len(top50), symbol, acc, sharpe, remaining)

    # Step 4: Aggregate
    successful = [r for r in wf_results if "error" not in r]
    failed = [r for r in wf_results if "error" in r]
    if successful:
        successful.sort(key=lambda r: r.get("avg_accuracy", 0), reverse=True)

    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_time_seconds": round(_time.time() - batch_start, 1),
        "top_n": TOP_N,
        "total_evaluated": len(evaluations),
        "walk_forward_successful": len(successful),
        "walk_forward_failed": len(failed),
        "ranking": [
            {
                "rank": i + 1,
                "symbol": r.get("symbol", r.get("data_symbol", "?")),
                "pre_accuracy": r.get("pre_accuracy", 0),
                "wf_accuracy": r.get("avg_accuracy", 0),
                "wf_sharpe": r.get("avg_test_sharpe", 0),
                "wf_return": r.get("avg_test_return_pct", 0),
                "wf_win_rate": r.get("avg_test_win_rate", 0),
                "wf_max_dd": r.get("avg_test_max_drawdown", 0),
                "wf_profit_factor": r.get("avg_test_profit_factor", 0),
                "total_trades": r.get("total_trades", 0),
            }
            for i, r in enumerate(successful)
        ],
        "failed_symbols": [
            {"symbol": r.get("symbol", "?"), "error": r.get("error", "")[:80]}
            for r in failed
        ],
        "all_results": wf_results,
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info("")
    logger.info("Results saved to %s", RESULTS_PATH)

    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("WALK-FORWARD VALIDATION SUMMARY (Top %d)", TOP_N)
    logger.info("=" * 60)
    logger.info("Evaluated: %d | WF Success: %d | WF Failed: %d | Time: %.0fs",
                len(evaluations), len(successful), len(failed),
                _time.time() - batch_start)
    logger.info("")
    logger.info("RANKING BY WALK-FORWARD ACCURACY:")
    for entry in summary["ranking"][:30]:
        logger.info(
            "  #%2d %-12s pre=%.4f wf=%.4f sharpe=%.2f ret=%.1f%% "
            "wr=%.0f%% dd=%.1f%% pf=%.2f trades=%d",
            entry["rank"], entry["symbol"], entry["pre_accuracy"],
            entry["wf_accuracy"], entry["wf_sharpe"], entry["wf_return"],
            entry["wf_win_rate"], entry["wf_max_dd"], entry["wf_profit_factor"],
            entry["total_trades"],
        )

    if failed:
        logger.info("")
        logger.info("FAILED (%d):", len(failed))
        for f_entry in summary["failed_symbols"][:10]:
            logger.info("  %-12s %s", f_entry["symbol"], f_entry["error"])

    logger.info("=" * 60)
    return summary


if __name__ == "__main__":
    run()
