"""Batch training script: train LightGBM on ALL available symbols.

Dynamically fetches all tradable symbols from MT5, groups them by category,
trains each with M5 timeframe using parallel processing, and produces a summary report.
"""
import os
import sys
import json
import logging
import time as _time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

from config import DATA_DIR

BATCH_RESULTS_PATH = os.path.join(DATA_DIR, "batch_results.json")

TIMEFRAME_H1 = 16385
TIMEFRAME_M5 = 5
MIN_BARS_H1 = 5000
MONTHS = 6
MAX_BARS = 50000

# Parallelism config
MAX_WORKERS = min(8, (os.cpu_count() or 4))  # Cap at 8 threads

PRIORITY_GROUPS = [
    ("FOREX MAJORS", ["EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD", "NZDUSD", "USDCHF"]),
    ("FOREX CROSSES", ["EURGBP", "AUDJPY", "AUDCAD", "EURAUD", "EURCHF", "AUDNZD", "GBPAUD", "GBPCAD", "GBPJPY", "CADJPY", "NZDJPY", "CHFJPY", "GBPNZD", "EURJPY", "EURNZD"]),
    ("COMMODITIES", ["XAUUSD", "XAGUSD"]),
    ("INDICES", ["US500", "US30", "NAS100", "GER40", "UK100", "FRA40", "US2000", "AUS200", "EUSTX50"]),
    ("CRYPTO", ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "ADAUSD", "DOTUSD", "LINKUSD", "AVAXUSD", "BNBUSD"]),
    ("FUTURES", ["US500-F", "NAS100-F", "GER40-F", "FRA40-F", "UK100-F", "EUSTX50-F", "US30-F"]),
]


def _classify_symbol(name):
    n = name.upper()
    if any(c in n for c in ['XAU', 'XAG', 'XPT', 'XPD', 'OIL', 'NATGAS', 'COPPER', 'WHEAT', 'CORN', 'SUGAR', 'COFFEE', 'COCOA', 'COTTON']):
        return 'COMMODITIES'
    if any(c in n for c in ['BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'DOT', 'LINK', 'AVAX', 'BNB', 'UNI', 'SHIB', 'PEPE', 'DOGE', 'LTC', 'XLM', 'NEAR', 'ATOM', 'APT', 'ARB', 'OP']):
        return 'CRYPTO'
    if any(c in n for c in ['US500', 'US30', 'NAS100', 'GER40', 'UK100', 'FRA40', 'JPN225', 'US2000', 'AUS200', 'HK50', 'EUSTX50', 'CHINAH', 'EU50', 'SPA35', 'SUI30', 'NETH25', 'ITA40', 'POL20', 'SWI20', '-F']):
        return 'INDICES'
    if any(c in n for c in ['DJI', 'SPX', 'NDX', 'RUT', 'VIX']):
        return 'INDICES'
    return 'FOREX'


def fetch_all_tradeable_symbols(max_spread=50):
    """Query MT5 for all visible symbols with spread <= max_spread."""
    import mt5_mcp as mt5
    if not mt5.initialize():
        logger.error("MT5 init failed: %s", mt5.last_error())
        return {}

    symbols = mt5.symbols_get()
    visible = [s for s in symbols if s.visible]

    raw = {}
    for s in visible:
        info = mt5.symbol_info(s.name)
        if not info:
            continue
        tick = mt5.symbol_info_tick(s.name)
        if not tick or tick.ask <= 0 or tick.bid <= 0:
            continue
        spread = (tick.ask - tick.bid) / info.point
        if spread <= max_spread:
            cat = _classify_symbol(s.name)
            if cat not in raw:
                raw[cat] = []
            raw[cat].append(s.name)

    for cat in raw:
        raw[cat].sort()

    mt5.shutdown()

    priority_syms = set()
    for _, syms in PRIORITY_GROUPS:
        priority_syms.update(syms)

    forex = sorted([s for s in raw.get('FOREX', []) if s not in priority_syms])
    commodities = sorted([s for s in raw.get('COMMODITIES', []) if s not in priority_syms])
    crypto = sorted([s for s in raw.get('CRYPTO', []) if s not in priority_syms])
    indices = sorted([s for s in raw.get('INDICES', []) if s not in priority_syms])

    result = []
    for name, syms in PRIORITY_GROUPS:
        result.append((name, syms))
    if forex:
        result.append(("FOREX OTHER", forex))
    if commodities:
        result.append(("COMMODITIES OTHER", commodities))
    if crypto:
        result.append(("CRYPTO OTHER", crypto))
    if indices:
        result.append(("INDICES OTHER", indices))

    total = sum(len(syms) for _, syms in result)
    logger.info("Fetched %d tradeable symbols from MT5", total)
    for name, syms in result:
        logger.info("  %s: %d symbols", name, len(syms))

    return result


def _fetch_bar_count(symbol, timeframe, months=6, max_bars=50000):
    try:
        from backtest_data import fetch_historical_data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=months * 30)
        df = fetch_historical_data(
            symbol, timeframe, start_date, end_date,
            use_cache=True, max_bars=max_bars,
        )
        if df is not None:
            return df, len(df)
        return None, 0
    except Exception as e:
        logger.debug("Fetch failed for %s tf=%d: %s", symbol, timeframe, e)
        return None, 0


def _rename_model_for_symbol(symbol):
    default_model = os.path.join(DATA_DIR, "ml_model.json")
    default_meta = os.path.join(DATA_DIR, "ml_model_meta.json")
    symbol_model = os.path.join(DATA_DIR, f"ml_model_{symbol}.json")
    symbol_meta = os.path.join(DATA_DIR, f"ml_model_{symbol}_meta.json")

    if os.path.exists(default_model):
        if os.path.exists(symbol_model):
            os.remove(symbol_model)
        os.rename(default_model, symbol_model)

    if os.path.exists(default_meta):
        if os.path.exists(symbol_meta):
            os.remove(symbol_meta)
        os.rename(default_meta, symbol_meta)


def train_symbol(symbol, group_name, skip_existing=True):
    existing_model = os.path.join(DATA_DIR, f"ml_model_{symbol}.json")
    if skip_existing and os.path.exists(existing_model):
        return {"symbol": symbol, "group": group_name, "skipped": True}

    from train_ml import run_training_pipeline

    df, bars = _fetch_bar_count(symbol, TIMEFRAME_H1, MONTHS, MAX_BARS)

    if bars >= MIN_BARS_H1:
        result = run_training_pipeline(
            symbol=symbol, timeframe=TIMEFRAME_H1,
            months=MONTHS, max_bars=MAX_BARS,
        )
        result["timeframe_used"] = "H1"
        result["timeframe_value"] = TIMEFRAME_H1
    else:
        result = run_training_pipeline(
            symbol=symbol, timeframe=TIMEFRAME_M5,
            months=MONTHS, max_bars=MAX_BARS,
        )
        result["timeframe_used"] = "M5"
        result["timeframe_value"] = TIMEFRAME_M5

    _rename_model_for_symbol(symbol)

    result["symbol"] = symbol
    result["group"] = group_name
    result["trained_at"] = datetime.now().isoformat()
    return result


class _ProgressTracker:
    """Thread-safe progress tracker for parallel training."""

    def __init__(self, total):
        self.total = total
        self.done = 0
        self.successful = 0
        self.failed = 0
        self.skipped = 0
        self._lock = threading.Lock()
        self._start = _time.time()

    def record(self, result):
        with self._lock:
            self.done += 1
            if result.get("skipped"):
                self.skipped += 1
            elif "error" in result:
                self.failed += 1
            else:
                self.successful += 1
            elapsed = _time.time() - self._start
            rate = self.done / elapsed if elapsed > 0 else 0
            remaining = (self.total - self.done) / rate if rate > 0 else 0
            if self.done % 10 == 0 or self.done == self.total:
                logger.info(
                    "  Progress: %d/%d (%.0f%%) | OK=%d skip=%d fail=%d | ETA=%.0fs",
                    self.done, self.total, 100 * self.done / self.total,
                    self.successful, self.skipped, self.failed, remaining,
                )


def run_batch_training(groups=None, max_workers=None):
    if groups is None:
        groups = fetch_all_tradeable_symbols()
    if max_workers is None:
        max_workers = MAX_WORKERS

    # Flatten all symbols with group info
    all_symbols = []
    for group_name, symbols in groups:
        for symbol in symbols:
            all_symbols.append((symbol, group_name))

    total_symbols = len(all_symbols)
    logger.info("=" * 60)
    logger.info("BATCH TRAINING: %d symbols, %d workers (parallel)", total_symbols, max_workers)
    logger.info("=" * 60)

    os.makedirs(DATA_DIR, exist_ok=True)
    batch_start = _time.time()
    all_results = [None] * total_symbols
    progress = _ProgressTracker(total_symbols)

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Train") as pool:
        future_to_idx = {}
        for idx, (symbol, group_name) in enumerate(all_symbols):
            future = pool.submit(train_symbol, symbol, group_name)
            future_to_idx[future] = idx

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            symbol, group_name = all_symbols[idx]
            try:
                result = future.result(timeout=600)
            except Exception as e:
                logger.error("  %s EXCEPTION: %s", symbol, e)
                result = {
                    "symbol": symbol,
                    "group": group_name,
                    "error": str(e),
                    "trained_at": datetime.now().isoformat(),
                }
            all_results[idx] = result
            progress.record(result)

            # Log per-symbol result
            if result.get("skipped"):
                pass  # Skip logging for already-trained
            elif "error" in result:
                logger.warning("  %s FAILED — %s", symbol, result["error"])
            else:
                avg_acc = result.get("avg_accuracy", 0)
                logger.info("  %s DONE — accuracy=%.4f tf=%s", symbol, avg_acc, result.get("timeframe_used", "?"))

    elapsed = _time.time() - batch_start

    # Build summary
    successful = [r for r in all_results if r and "error" not in r and not r.get("skipped")]
    skipped = [r for r in all_results if r and r.get("skipped")]
    failed = [r for r in all_results if r and "error" in r]
    successful.sort(key=lambda r: r.get("avg_accuracy", 0), reverse=True)

    best_per_group = {}
    for r in successful:
        grp = r.get("group", "")
        if grp not in best_per_group or r.get("avg_accuracy", 0) > best_per_group[grp].get("avg_accuracy", 0):
            best_per_group[grp] = r

    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_time_seconds": round(elapsed, 1),
        "total_symbols": total_symbols,
        "max_workers": max_workers,
        "successful": len(successful),
        "skipped": len(skipped),
        "failed": len(failed),
        "symbols_per_second": round(total_symbols / elapsed, 2) if elapsed > 0 else 0,
        "ranking_by_accuracy": [
            {
                "rank": i + 1,
                "symbol": r["symbol"],
                "group": r.get("group", ""),
                "accuracy": r.get("avg_accuracy", 0),
                "sharpe": r.get("avg_test_sharpe", 0),
                "return_pct": r.get("avg_test_return_pct", 0),
                "win_rate": r.get("avg_test_win_rate", 0),
                "timeframe": r.get("timeframe_used", "unknown"),
                "profit_factor": r.get("avg_test_profit_factor", 0),
            }
            for i, r in enumerate(successful)
        ],
        "best_per_group": {
            grp: {
                "symbol": r["symbol"],
                "accuracy": r.get("avg_accuracy", 0),
                "sharpe": r.get("avg_test_sharpe", 0),
                "timeframe": r.get("timeframe_used", "unknown"),
            }
            for grp, r in best_per_group.items()
        },
        "failed_symbols": [
            {"symbol": r["symbol"], "group": r.get("group", ""), "error": r.get("error", "")}
            for r in failed
        ],
        "all_results": all_results,
    }

    with open(BATCH_RESULTS_PATH, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    logger.info("")
    logger.info("Batch results saved to %s", BATCH_RESULTS_PATH)

    logger.info("")
    logger.info("=" * 60)
    logger.info("BATCH TRAINING SUMMARY (parallel, %d workers)", max_workers)
    logger.info("=" * 60)
    logger.info("Total: %d | Success: %d | Skipped: %d | Failed: %d | Time: %.0fs (%.1f sym/s)",
                total_symbols, len(successful), len(skipped), len(failed),
                elapsed, total_symbols / elapsed if elapsed > 0 else 0)
    logger.info("")
    logger.info("RANKING BY ACCURACY:")
    for entry in summary["ranking_by_accuracy"][:50]:
        logger.info(
            "  #%d %-8s %-16s acc=%.4f sharpe=%.2f ret=%.1f%% wr=%.0f%% pf=%.2f tf=%s",
            entry["rank"], entry["symbol"], entry["group"],
            entry["accuracy"], entry["sharpe"], entry["return_pct"],
            entry["win_rate"], entry["profit_factor"], entry["timeframe"],
        )
    logger.info("")
    logger.info("BEST MODEL PER GROUP:")
    for grp, info in summary["best_per_group"].items():
        logger.info("  %-16s -> %-8s acc=%.4f sharpe=%.2f tf=%s",
                     grp, info["symbol"], info["accuracy"], info["sharpe"], info["timeframe"])
    if failed:
        logger.info("")
        logger.info("FAILED SYMBOLS:")
        for f_entry in summary["failed_symbols"]:
            logger.info("  %-8s [%s] — %s", f_entry["symbol"], f_entry["group"], f_entry["error"])

    logger.info("=" * 60)
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Batch train ML models for all symbols")
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel workers")
    parser.add_argument("--priority-only", action="store_true", help="Train only priority 49 symbols")
    args = parser.parse_args()

    groups = None
    if args.priority_only:
        groups = PRIORITY_GROUPS

    run_batch_training(groups=groups, max_workers=args.workers)
