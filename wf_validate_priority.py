"""Walk-forward validation on all priority symbols.
Skips evaluation step — runs walk-forward directly on known priority symbols.
"""
import os
import sys
import json
import logging
import time as _time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from config import DATA_DIR

RESULTS_PATH = os.path.join(DATA_DIR, "wf_validation_priority.json")
WF_MAX_WORKERS = 4

PRIORITY_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD", "NZDUSD", "USDCHF",
    "EURGBP", "AUDJPY", "AUDCAD", "EURAUD", "EURCHF", "AUDNZD", "GBPAUD",
    "GBPCAD", "GBPJPY", "CADJPY", "NZDJPY", "CHFJPY", "GBPNZD", "EURJPY", "EURNZD",
    "XAUUSD", "XAGUSD",
    "US500", "US30", "NAS100", "GER40", "UK100", "FRA40", "US2000", "AUS200", "EUSTX50",
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "ADAUSD", "DOTUSD", "LINKUSD", "AVAXUSD", "BNBUSD",
    "US500-F", "NAS100-F", "GER40-F", "FRA40-F", "UK100-F", "EUSTX50-F", "US30-F",
]


def walk_forward_symbol(symbol):
    try:
        from train_ml import run_training_pipeline
        result = run_training_pipeline(
            symbol=symbol, timeframe=5,
            months=6, max_bars=50000, timeout_seconds=300,
        )
        return result
    except Exception as e:
        return {"error": str(e), "symbol": symbol}


def run():
    total = len(PRIORITY_SYMBOLS)
    logger.info("=" * 60)
    logger.info("WALK-FORWARD VALIDATION: %d priority symbols, %d workers", total, WF_MAX_WORKERS)
    logger.info("=" * 60)

    batch_start = _time.time()
    wf_results = []
    done = 0

    with ThreadPoolExecutor(max_workers=WF_MAX_WORKERS, thread_name_prefix="WF") as pool:
        futures = {pool.submit(walk_forward_symbol, s): s for s in PRIORITY_SYMBOLS}
        for future in as_completed(futures):
            done += 1
            symbol = futures[future]
            try:
                wf_result = future.result(timeout=300)
            except Exception as exc:
                wf_result = {"error": str(exc), "symbol": symbol}

            wf_results.append(wf_result)

            elapsed = _time.time() - batch_start
            rate = done / elapsed if elapsed > 0 else 0
            remaining = (total - done) / rate if rate > 0 else 0

            if "error" in wf_result:
                logger.info("  [%d/%d] %s FAILED: %s | ETA=%.0fs",
                            done, total, symbol, wf_result["error"][:40], remaining)
            else:
                acc = wf_result.get("avg_accuracy", 0)
                sharpe = wf_result.get("avg_test_sharpe", 0)
                ret = wf_result.get("avg_test_return_pct", 0)
                wr = wf_result.get("avg_test_win_rate", 0)
                dd = wf_result.get("avg_test_max_drawdown", 0)
                pf = wf_result.get("avg_test_profit_factor", 0)
                trades = wf_result.get("total_trades", 0)
                logger.info("  [%d/%d] %s acc=%.4f sharpe=%.2f ret=%.1f%% wr=%.0f%% dd=%.1f%% pf=%.2f trades=%d | ETA=%.0fs",
                            done, total, symbol, acc, sharpe, ret, wr, dd, pf, trades, remaining)

    successful = [r for r in wf_results if "error" not in r]
    failed = [r for r in wf_results if "error" in r]
    if successful:
        successful.sort(key=lambda r: r.get("avg_accuracy", 0), reverse=True)

    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_time_seconds": round(_time.time() - batch_start, 1),
        "total_symbols": total,
        "walk_forward_successful": len(successful),
        "walk_forward_failed": len(failed),
        "ranking": [
            {
                "rank": i + 1,
                "symbol": r.get("symbol", r.get("data_symbol", "?")),
                "wf_accuracy": r.get("avg_accuracy", 0),
                "wf_sharpe": r.get("avg_test_sharpe", 0),
                "wf_return": r.get("avg_test_return_pct", 0),
                "wf_win_rate": r.get("avg_test_win_rate", 0),
                "wf_max_dd": r.get("avg_test_max_drawdown", 0),
                "wf_profit_factor": r.get("avg_test_profit_factor", 0),
                "total_trades": r.get("total_trades", 0),
                "best_accuracy": r.get("best_accuracy", 0),
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

    logger.info("")
    logger.info("=" * 60)
    logger.info("WALK-FORWARD VALIDATION SUMMARY (Priority Symbols)")
    logger.info("=" * 60)
    logger.info("Total: %d | Success: %d | Failed: %d | Time: %.0fs",
                total, len(successful), len(failed), _time.time() - batch_start)
    logger.info("")
    logger.info("RANKING BY WALK-FORWARD ACCURACY:")
    for entry in summary["ranking"]:
        logger.info(
            "  #%2d %-12s wf_acc=%.4f best_acc=%.4f sharpe=%.2f ret=%.1f%% "
            "wr=%.0f%% dd=%.1f%% pf=%.2f trades=%d",
            entry["rank"], entry["symbol"], entry["wf_accuracy"], entry["best_accuracy"],
            entry["wf_sharpe"], entry["wf_return"], entry["wf_win_rate"],
            entry["wf_max_dd"], entry["wf_profit_factor"], entry["total_trades"],
        )

    if failed:
        logger.info("")
        logger.info("FAILED (%d):", len(failed))
        for f_entry in summary["failed_symbols"]:
            logger.info("  %-12s %s", f_entry["symbol"], f_entry["error"])

    logger.info("=" * 60)
    return summary


if __name__ == "__main__":
    run()
