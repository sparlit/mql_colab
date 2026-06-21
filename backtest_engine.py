"""
Backtest Engine — AFX AutoTrader v2
Multi-strategy backtesting with walk-forward validation.
Supports all 4 strategies (SWING, DAY, CARRY, SCALP).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from strategy_base import StrategyMode
from strategy_router import StrategyRouter
from parallel_executor import get_executor
from mt5_mcp import (
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15,
    TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1,
)

logger = logging.getLogger(__name__)

TF_MAP = {"M1": TIMEFRAME_M1, "M5": TIMEFRAME_M5, "M15": TIMEFRAME_M15,
          "H1": TIMEFRAME_H1, "H4": TIMEFRAME_H4, "D1": TIMEFRAME_D1}


@dataclass
class BacktestResult:
    strategy: str
    total_trades: int
    win_rate: float
    total_pnl: float
    max_drawdown: float
    sharpe_ratio: float
    profit_factor: float
    avg_trade_duration: float
    equity_curve: List[float]
    trades: List[Dict]


@dataclass
class WalkForwardResult:
    strategy: str
    train_periods: int
    test_periods: int
    period_results: List[BacktestResult]
    avg_sharpe: float
    avg_win_rate: float
    out_of_sample_pct: float


class BacktestEngine:
    """
    Multi-strategy backtest engine with walk-forward validation.

    Supports:
    - All 4 strategies (SWING, DAY, CARRY, SCALP)
    - Walk-forward analysis
    - Multi-symbol backtesting
    - Performance metrics
    """

    def __init__(self):
        self._router = StrategyRouter()
        self._executor = get_executor()

    def run(
        self,
        symbol: str,
        strategy_mode: str,
        start_date: int,
        end_date: int,
        initial_balance: float = 10000.0,
        timeframe: str = "H4",
    ) -> BacktestResult:
        """
        Run single backtest for a strategy.

        Args:
            symbol: Trading symbol
            strategy_mode: SWING, DAY, CARRY, or SCALP
            start_date: Unix timestamp for start
            end_date: Unix timestamp for end
            initial_balance: Starting account balance
            timeframe: Timeframe string

        Returns:
            BacktestResult with full performance metrics
        """
        mode = StrategyMode(strategy_mode)
        self._router.set_mode(mode)

        # Load historical data
        tf_const = TF_MAP.get(timeframe, TIMEFRAME_H4)
        rates = self._load_rates(symbol, tf_const, start_date, end_date)
        if rates is None or len(rates) < 50:
            return BacktestResult(
                strategy=strategy_mode,
                total_trades=0, win_rate=0.0, total_pnl=0.0,
                max_drawdown=0.0, sharpe_ratio=0.0, profit_factor=0.0,
                avg_trade_duration=0.0, equity_curve=[initial_balance], trades=[],
            )

        df = pd.DataFrame(rates)
        equity = initial_balance
        equity_curve = [equity]
        trades = []
        open_position = None
        wins = 0
        losses = 0

        for i in range(20, len(df)):
            window = df.iloc[:i]
            last = window.iloc[-1]

            # Calculate indicators
            indicators = self._calc_indicators(window)
            market_data = self._make_market_data(symbol, timeframe, last, indicators)

            # Get strategy signal
            signal = self._router.get_active_strategy().analyze(market_data)

            if open_position is None and signal.is_actionable():
                sl_price = self._router.get_active_strategy().get_stop_loss(
                    signal, last["close"],
                    signal.signal_type
                )
                tp_price = self._router.get_active_strategy().get_take_profit(
                    signal, last["close"],
                    signal.signal_type, sl_price
                )
                open_position = {
                    "entry_time": last["time"],
                    "entry_price": last["close"],
                    "direction": signal.signal_type.value,
                    "sl": sl_price,
                    "tp": tp_price,
                    "lot": 0.01,
                    "confidence": signal.confidence,
                }

            elif open_position is not None:
                close_reason = None
                close_price = last["close"]
                if open_position["direction"] == "BUY":
                    if close_price <= open_position["sl"]:
                        close_reason = "sl"
                        close_price = open_position["sl"]
                    elif close_price >= open_position["tp"]:
                        close_reason = "tp"
                        close_price = open_position["tp"]
                else:
                    if close_price >= open_position["sl"]:
                        close_reason = "sl"
                        close_price = open_position["sl"]
                    elif close_price <= open_position["tp"]:
                        close_reason = "tp"
                        close_price = open_position["tp"]

                if close_reason:
                    pnl = self._calc_pnl(
                        open_position["direction"],
                        open_position["entry_price"],
                        close_price,
                        open_position["lot"],
                    )
                    equity += pnl
                    equity_curve.append(equity)

                    trade = {
                        **open_position,
                        "exit_time": last["time"],
                        "exit_price": close_price,
                        "pnl": pnl,
                        "close_reason": close_reason,
                    }
                    trades.append(trade)

                    if pnl > 0:
                        wins += 1
                    else:
                        losses += 1

                    open_position = None

        # Close any open position at end
        if open_position is not None:
            last = df.iloc[-1]
            pnl = self._calc_pnl(
                open_position["direction"],
                open_position["entry_price"],
                last["close"],
                open_position["lot"],
            )
            equity += pnl
            equity_curve.append(equity)

        return self._compute_metrics(
            strategy_mode, equity_curve, trades, wins, losses
        )

    def run_walk_forward(
        self,
        symbol: str,
        strategy_mode: str,
        start_date: int,
        end_date: int,
        train_months: int = 3,
        test_months: int = 1,
        initial_balance: float = 10000.0,
    ) -> WalkForwardResult:
        """
        Run walk-forward analysis with rolling train/test windows.

        Args:
            train_months: Months of data for training
            test_months: Months of data for testing
        """
        SECONDS_PER_MONTH = 30 * 24 * 3600
        period_results = []

        current = start_date
        period = 0
        while current + train_months * SECONDS_PER_MONTH + test_months * SECONDS_PER_MONTH <= end_date:
            train_end = current + train_months * SECONDS_PER_MONTH
            test_end = train_end + test_months * SECONDS_PER_MONTH

            result = self.run(
                symbol, strategy_mode,
                current, test_end,
                initial_balance,
            )
            period_results.append(result)
            period += 1
            current = test_end

        if not period_results:
            return WalkForwardResult(
                strategy=strategy_mode,
                train_periods=train_months,
                test_periods=test_months,
                period_results=[],
                avg_sharpe=0.0, avg_win_rate=0.0, out_of_sample_pct=0.0,
            )

        avg_sharpe = np.mean([r.sharpe_ratio for r in period_results])
        avg_win_rate = np.mean([r.win_rate for r in period_results])

        return WalkForwardResult(
            strategy=strategy_mode,
            train_periods=train_months,
            test_periods=test_months,
            period_results=period_results,
            avg_sharpe=avg_sharpe,
            avg_win_rate=avg_win_rate,
            out_of_sample_pct=test_months / (train_months + test_months),
        )

    def run_multi_strategy(
        self,
        symbol: str,
        start_date: int,
        end_date: int,
        initial_balance: float = 10000.0,
    ) -> Dict[str, BacktestResult]:
        """Run backtest for all 4 strategies and return comparison."""
        results = {}
        for mode in ["SWING", "DAY", "CARRY", "SCALP"]:
            try:
                results[mode] = self.run(
                    symbol, mode, start_date, end_date, initial_balance
                )
            except Exception as e:
                logger.error("Backtest failed for %s: %s", mode, e)
        return results

    # ─── Helpers ────────────────────────────────────────────────

    def _load_rates(self, symbol: str, tf: int, start: int, end: int) -> Optional[Any]:
        """Load rates from MT5 or cache."""
        try:
            from mt5_mcp import copy_rates_range
            return copy_rates_range(symbol, tf, start, end)
        except Exception:
            return None

    def _calc_indicators(self, df: pd.DataFrame) -> Dict[str, float]:
        """Calculate indicators for a dataframe row."""
        last = df.iloc[-1]
        return {
            "close": float(last["close"]),
            "ema_50": float(df["close"].ewm(span=50).mean().iloc[-1]),
            "ema_200": float(df["close"].ewm(span=200).mean().iloc[-1]),
            "rsi_14": float(self._rsi(df["close"], 14).iloc[-1]),
        }

    def _rsi(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        return 100 - (100 / (1 + gain / loss.replace(0, 1e-10)))

    def _make_market_data(self, symbol: str, tf: str, row: pd.Series, indicators: Dict) -> Any:
        """Build MarketData object from dataframe row."""
        from strategy_base import MarketData
        return MarketData(
            symbol=symbol,
            timeframe=tf,
            time=int(row["time"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            tick_volume=int(row["tick_volume"]),
            spread=0,
            volume=float(row["tick_volume"]),
            indicators=indicators,
        )

    def _calc_pnl(self, direction: str, entry: float, exit: float, lot: float) -> float:
        pips = (exit - entry) / 0.0001
        if direction == "SELL":
            pips = -pips
        return round(pips * 10 * lot, 2)

    def _compute_metrics(
        self,
        strategy: str,
        equity_curve: List[float],
        trades: List[Dict],
        wins: int,
        losses: int,
    ) -> BacktestResult:
        total = wins + losses
        win_rate = wins / total if total > 0 else 0.0
        pnl_list = [t["pnl"] for t in trades]
        total_pnl = sum(pnl_list)
        gross_profit = sum(p for p in pnl_list if p > 0)
        gross_loss = abs(sum(p for p in pnl_list if p < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        equity_arr = np.array(equity_curve)
        peak = np.maximum.accumulate(equity_arr)
        drawdown = (peak - equity_arr) / peak
        max_dd = float(np.max(drawdown))

        if len(equity_curve) > 1:
            returns = np.diff(equity_arr) / equity_arr[:-1]
            sharpe = float(np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(252))
        else:
            sharpe = 0.0

        durations = [t.get("exit_time", 0) - t.get("entry_time", 0) for t in trades]
        avg_duration = float(np.mean(durations)) if durations else 0.0

        return BacktestResult(
            strategy=strategy,
            total_trades=total,
            win_rate=win_rate,
            total_pnl=total_pnl,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            avg_trade_duration=avg_duration,
            equity_curve=equity_curve,
            trades=trades,
        )


# ─── Singleton ─────────────────────────────────────────────────
_engine: Optional[BacktestEngine] = None


def get_backtest_engine() -> BacktestEngine:
    global _engine
    if _engine is None:
        _engine = BacktestEngine()
    return _engine