"""Backtest runner: orchestrates data fetch, backtest, walk-forward, Monte Carlo.

Fetches real MT5 data, runs RulesBaseline through EventDrivenBacktestEngine,
validates against gate criteria, and saves report to brain_data/backtest_report.json.
"""
import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from config import DATA_DIR
from backtest_data import fetch_historical_data, df_to_bars
from ml_enhancements import RulesBaseline, EventDrivenBacktestEngine
from walk_forward import run_walk_forward
from validation_pipeline import ValidationPipeline, PHASE_CRITERIA

logger = logging.getLogger(__name__)


def monte_carlo_simulation(trades, n_simulations=1000, initial_balance=10000,
                           risk_per_trade=0.01):
    """Monte Carlo simulation on actual trade results.

    Resamples trade P&L with replacement to estimate confidence intervals.

    Args:
        trades: list of dicts with 'pnl' key
        n_simulations: number of resamples
        initial_balance: starting capital
        risk_per_trade: fraction of balance risked per trade

    Returns:
        dict with confidence intervals and probability of ruin
    """
    if not trades or len(trades) < 10:
        return {"error": "insufficient trades for Monte Carlo"}

    pnls = np.array([t["pnl"] for t in trades])
    n_trades = len(pnls)

    sharpe_list = []
    max_dd_list = []
    profit_factor_list = []
    final_balances = []

    for _ in range(n_simulations):
        sampled = np.random.choice(pnls, size=n_trades, replace=True)
        balance = initial_balance
        equity = [balance]
        for pnl in sampled:
            balance += pnl
            equity.append(balance)
        final_balances.append(balance)

        wins = sampled[sampled > 0]
        losses = sampled[sampled < 0]
        gross_profit = np.sum(wins) if len(wins) > 0 else 0
        gross_loss = abs(np.sum(losses)) if len(losses) > 0 else 1
        pf = gross_profit / gross_loss
        profit_factor_list.append(pf)

        mean_r = np.mean(sampled)
        std_r = np.std(sampled)
        sharpe = (mean_r / std_r) if std_r > 0 else 0
        sharpe_list.append(sharpe)

        peak = equity[0]
        max_dd = 0
        for eq in equity:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        max_dd_list.append(max_dd * 100)

    n_ruin = sum(1 for b in final_balances if b < initial_balance * 0.5)
    prob_ruin = round(n_ruin / n_simulations * 100, 2)

    return {
        "n_simulations": n_simulations,
        "n_trades": n_trades,
        "sharpe_ci_95": (
            round(float(np.percentile(sharpe_list, 2.5)), 2),
            round(float(np.percentile(sharpe_list, 97.5)), 2),
        ),
        "sharpe_median": round(float(np.median(sharpe_list)), 2),
        "max_drawdown_ci_95": (
            round(float(np.percentile(max_dd_list, 2.5)), 2),
            round(float(np.percentile(max_dd_list, 97.5)), 2),
        ),
        "max_drawdown_median": round(float(np.median(max_dd_list)), 2),
        "profit_factor_ci_95": (
            round(float(np.percentile(profit_factor_list, 2.5)), 2),
            round(float(np.percentile(profit_factor_list, 97.5)), 2),
        ),
        "profit_factor_median": round(float(np.median(profit_factor_list)), 2),
        "final_balance_median": round(float(np.median(final_balances)), 2),
        "prob_ruin_pct": prob_ruin,
    }


def _generate_signals(df, baseline, sl_pips=50, tp_pips=100):
    """Generate signals from RulesBaseline for each bar in df."""
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


def run_full_backtest(symbol="EURUSD", timeframe=None, months=12,
                      initial_balance=10000, pip_value=10.0,
                      sl_pips=50, tp_pips=100):
    if timeframe is None:
        import MetaTrader5 as mt5
        timeframe = mt5.TIMEFRAME_M5
    """Run complete backtest pipeline.

    1. Fetch historical data from MT5
    2. Run RulesBaseline through EventDrivenBacktestEngine
    3. Run walk-forward validation
    4. Run Monte Carlo simulation
    5. Check against validation_pipeline gate criteria
    6. Save report to brain_data/backtest_report.json

    Returns:
        dict with full report
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)

    logger.info("Fetching %s data: %s to %s (M5)", symbol, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
    df = fetch_historical_data(symbol, timeframe, start_date, end_date, use_cache=True)
    if df is None or len(df) < 200:
        return {"error": "Failed to fetch sufficient data", "bars": len(df) if df is not None else 0}

    logger.info("Fetched %d bars", len(df))

    bars = df_to_bars(df)
    baseline = RulesBaseline()
    signals = _generate_signals(df, baseline, sl_pips, tp_pips)

    engine = EventDrivenBacktestEngine(
        spread_pips=1.5, slippage_pips=0.5, commission_per_lot=7.0,
    )
    backtest_results = engine.run(signals, bars, initial_balance=initial_balance, pip_value=pip_value)
    logger.info("Backtest: %d trades, Sharpe=%.2f, DD=%.1f%%, PF=%.2f",
                backtest_results["total_trades"], backtest_results["sharpe_ratio"],
                backtest_results["max_drawdown"], backtest_results["profit_factor"])

    walk_forward_results = run_walk_forward(
        df, initial_balance=initial_balance, pip_value=pip_value,
        train_pct=0.7, n_windows=5, sl_pips=sl_pips, tp_pips=tp_pips,
    )

    mc_trades = extract_trades_from_engine(signals, bars, initial_balance=initial_balance, pip_value=pip_value)
    mc_results = monte_carlo_simulation(mc_trades, n_simulations=1000, initial_balance=initial_balance)

    pipeline = ValidationPipeline()
    gate_result = pipeline.evaluate_backtest(backtest_results)

    report = {
        "generated_at": datetime.now().isoformat(),
        "symbol": symbol,
        "timeframe": timeframe,
        "months": months,
        "bars": len(df),
        "backtest": backtest_results,
        "walk_forward": walk_forward_results,
        "monte_carlo": mc_results,
        "gate_criteria": gate_result,
    }

    report_path = os.path.join(DATA_DIR, "backtest_report.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Report saved to %s", report_path)

    return report


def extract_trades_from_engine(signals, bars, initial_balance=10000, pip_value=10.0):
    """Extract individual trade P&L for Monte Carlo from a backtest run.

    Runs the engine and captures trade-level results.
    """
    engine = EventDrivenBacktestEngine(
        spread_pips=1.5, slippage_pips=0.5, commission_per_lot=7.0,
    )
    balance = initial_balance
    equity_curve = [balance]
    trades = []
    positions = []

    for i, bar in enumerate(bars):
        if i >= len(signals):
            break
        signal = signals[i]
        high = bar["high"]
        low = bar["low"]
        close = bar["close"]
        spread = bar.get("spread", 1.5)

        closed_positions = []
        for pos in positions:
            if pos["type"] == "BUY":
                if low <= pos["sl"]:
                    pnl = (pos["sl"] - pos["entry"]) * pos["lots"] * pip_value - pos["commission"]
                    balance += pnl
                    trades.append({"pnl": pnl, "bars_held": i - pos["open_bar"]})
                    closed_positions.append(pos)
                elif high >= pos["tp"]:
                    pnl = (pos["tp"] - pos["entry"]) * pos["lots"] * pip_value - pos["commission"]
                    balance += pnl
                    trades.append({"pnl": pnl, "bars_held": i - pos["open_bar"]})
                    closed_positions.append(pos)
            else:
                if high >= pos["sl"]:
                    pnl = (pos["entry"] - pos["sl"]) * pos["lots"] * pip_value - pos["commission"]
                    balance += pnl
                    trades.append({"pnl": pnl, "bars_held": i - pos["open_bar"]})
                    closed_positions.append(pos)
                elif low <= pos["tp"]:
                    pnl = (pos["entry"] - pos["tp"]) * pos["lots"] * pip_value - pos["commission"]
                    balance += pnl
                    trades.append({"pnl": pnl, "bars_held": i - pos["open_bar"]})
                    closed_positions.append(pos)
        for pos in closed_positions:
            positions.remove(pos)

        if signal.get("action") in ("buy", "sell") and len(positions) < 5:
            sl_pips_val = signal.get("sl_pips", 50)
            tp_pips_val = signal.get("tp_pips", 100)
            confidence = signal.get("confidence", 0.5)
            risk_amount = balance * 0.01 * min(confidence, 1.0)
            sl_distance = sl_pips_val * pip_value
            lots = max(0.01, round(risk_amount / sl_distance, 2))
            spread_cost = spread * pip_value * lots
            slippage_cost = 0.5 * pip_value * lots
            commission = 7.0 * lots + spread_cost + slippage_cost

            if signal["action"] == "buy":
                entry = close + (spread / 2 * pip_value / lots)
                sl = entry - sl_pips_val * pip_value / lots
                tp = entry + tp_pips_val * pip_value / lots
                positions.append({"type": "BUY", "entry": entry, "sl": sl, "tp": tp,
                                  "lots": lots, "commission": commission, "open_bar": i})
            else:
                entry = close - (spread / 2 * pip_value / lots)
                sl = entry + sl_pips_val * pip_value / lots
                tp = entry - tp_pips_val * pip_value / lots
                positions.append({"type": "SELL", "entry": entry, "sl": sl, "tp": tp,
                                  "lots": lots, "commission": commission, "open_bar": i})

    return trades


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    report = run_full_backtest()
    print(json.dumps(report, indent=2, default=str))
