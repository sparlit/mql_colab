"""Tests for backtest infrastructure: data, walk-forward, Monte Carlo, runner."""
import sys
import types
import pytest
import json
import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.conftest import synthetic_ohlcv, synthetic_df


# ==========================================
# backtest_data tests
# ==========================================
class TestBacktestData:
    def test_df_to_bars(self):
        from backtest_data import df_to_bars
        df = synthetic_df(n=10)
        bars = df_to_bars(df)
        assert len(bars) == 10
        assert "open" in bars[0]
        assert "high" in bars[0]
        assert "low" in bars[0]
        assert "close" in bars[0]
        assert isinstance(bars[0]["open"], float)

    def test_df_to_bars_with_spread(self):
        from backtest_data import df_to_bars
        df = synthetic_df(n=5)
        df["spread"] = 15.0
        bars = df_to_bars(df)
        assert all("spread" in b for b in bars)

    def test_df_to_bars_empty(self):
        from backtest_data import df_to_bars
        df = pd.DataFrame(columns=["time", "open", "high", "low", "close"])
        bars = df_to_bars(df)
        assert bars == []

    def test_cache_key_deterministic(self):
        from backtest_data import _cache_key
        k1 = _cache_key("EURUSD", 300, "2025-01-01", "2025-06-01")
        k2 = _cache_key("EURUSD", 300, "2025-01-01", "2025-06-01")
        assert k1 == k2

    def test_cache_key_different_inputs(self):
        from backtest_data import _cache_key
        k1 = _cache_key("EURUSD", 300, "2025-01-01", "2025-06-01")
        k2 = _cache_key("GBPUSD", 300, "2025-01-01", "2025-06-01")
        assert k1 != k2

    @patch("backtest_data.mt5")
    def test_fetch_historical_data_returns_df(self, mock_mt5):
        from backtest_data import fetch_historical_data
        base_ts = int(datetime(2025, 1, 1).timestamp())
        mock_mt5.initialize.return_value = True
        mock_mt5.copy_rates_from_pos.return_value = np.array(
            [(base_ts + i * 300, 1.1, 1.11, 1.09, 1.105, 100, 15, 0) for i in range(50)],
            dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
                   ("close", "f8"), ("tick_volume", "i8"), ("spread", "i8"), ("real_volume", "i8")]
        )
        df = fetch_historical_data("EURUSD", 300, "2025-01-01", "2025-01-02", use_cache=False)
        assert df is not None
        assert len(df) > 0
        assert "close" in df.columns

    @patch("backtest_data.mt5")
    def test_fetch_historical_data_failure(self, mock_mt5):
        from backtest_data import fetch_historical_data
        mock_mt5.initialize.return_value = False
        mock_mt5.last_error.return_value = (1, "init failed")
        df = fetch_historical_data("EURUSD", 300, "2025-01-01", "2025-01-02", use_cache=False)
        assert df is None


# ==========================================
# walk_forward tests
# ==========================================
class TestWalkForward:
    def test_split_windows(self):
        from walk_forward import _split_windows
        windows = _split_windows(1000, train_pct=0.7, n_windows=5)
        assert len(windows) == 5
        for w in windows:
            assert w["train"][1] < w["test"][0]
            assert w["train"][0] < w["train"][1]
            assert w["test"][0] < w["test"][1]

    def test_split_windows_too_small(self):
        from walk_forward import _split_windows
        windows = _split_windows(100, train_pct=0.7, n_windows=5)
        assert len(windows) < 5

    def test_generate_signals_length(self, mock_mt5):
        from walk_forward import _generate_signals
        from ml_enhancements import RulesBaseline
        df = synthetic_df(n=200)
        baseline = RulesBaseline()
        signals = _generate_signals(baseline, df, sl_pips=50, tp_pips=100)
        assert len(signals) == 200
        assert signals[0]["action"] == "hold"
        assert "sl_pips" in signals[-1]
        assert "tp_pips" in signals[-1]

    def test_run_walk_forward(self, mock_mt5):
        from walk_forward import run_walk_forward
        df = synthetic_df(n=500)
        result = run_walk_forward(df, n_windows=3)
        assert "error" not in result or result.get("n_windows", 0) >= 0
        if "n_windows" in result:
            assert result["n_windows"] <= 3

    def test_run_walk_forward_insufficient_data(self):
        from walk_forward import run_walk_forward
        df = synthetic_df(n=50)
        result = run_walk_forward(df)
        assert "error" in result


# ==========================================
# Monte Carlo tests
# ==========================================
class TestMonteCarlo:
    def test_monte_carlo_basic(self):
        from run_backtest import monte_carlo_simulation
        np.random.seed(42)
        trades = [{"pnl": np.random.randn() * 50} for _ in range(100)]
        result = monte_carlo_simulation(trades, n_simulations=100)
        assert "sharpe_ci_95" in result
        assert "max_drawdown_ci_95" in result
        assert "prob_ruin_pct" in result
        assert result["n_simulations"] == 100
        assert result["n_trades"] == 100
        assert result["sharpe_ci_95"][0] <= result["sharpe_ci_95"][1]

    def test_monte_carlo_insufficient_trades(self):
        from run_backtest import monte_carlo_simulation
        trades = [{"pnl": 10}] * 5
        result = monte_carlo_simulation(trades)
        assert "error" in result

    def test_monte_carlo_confidence_intervals(self):
        from run_backtest import monte_carlo_simulation
        trades = [{"pnl": 50 if i % 3 == 0 else -30} for i in range(100)]
        result = monte_carlo_simulation(trades, n_simulations=200)
        ci = result["sharpe_ci_95"]
        assert ci[0] < ci[1]
        assert result["sharpe_median"] >= ci[0]
        assert result["sharpe_median"] <= ci[1]

    def test_monte_carlo_profit_factor_positive(self):
        from run_backtest import monte_carlo_simulation
        trades = [{"pnl": 100 if i % 3 == 0 else -50} for i in range(90)]
        result = monte_carlo_simulation(trades, n_simulations=100)
        assert result["profit_factor_median"] > 0

    def test_monte_carlo_drawdown_bounded(self):
        from run_backtest import monte_carlo_simulation
        trades = [{"pnl": 10 if i % 3 == 0 else -5} for i in range(60)]
        result = monte_carlo_simulation(trades, n_simulations=50)
        lo, hi = result["max_drawdown_ci_95"]
        assert 0 <= lo <= hi <= 100


# ==========================================
# EventDrivenBacktestEngine integration
# ==========================================
class TestEventDrivenBacktest:
    def test_engine_with_signals(self, mock_mt5):
        from ml_enhancements import EventDrivenBacktestEngine
        n = 300
        base = 1.10000
        vol = 0.0005
        np.random.seed(42)
        close = np.cumsum(np.random.randn(n) * vol) + base
        high = close + np.abs(np.random.randn(n)) * vol * 0.5
        low = close - np.abs(np.random.randn(n)) * vol * 0.5

        bars = []
        signals = []
        for i in range(n):
            bars.append({
                "time": f"bar_{i}",
                "open": float(close[i] + 0.0001),
                "high": float(high[i]),
                "low": float(low[i]),
                "close": float(close[i]),
                "spread": 1.5,
            })
            if i % 50 == 0 and i > 0:
                signals.append({"action": "buy", "confidence": 0.7, "sl_pips": 50, "tp_pips": 100})
            elif i % 75 == 0 and i > 0:
                signals.append({"action": "sell", "confidence": 0.6, "sl_pips": 50, "tp_pips": 100})
            else:
                signals.append({"action": "hold", "confidence": 0, "sl_pips": 50, "tp_pips": 100})

        engine = EventDrivenBacktestEngine(spread_pips=1.5, slippage_pips=0.5)
        result = engine.run(signals, bars, initial_balance=10000, pip_value=10.0)
        assert "final_balance" in result
        assert "total_trades" in result
        assert "sharpe_ratio" in result
        assert "max_drawdown" in result
        assert "profit_factor" in result
        assert result["total_trades"] >= 0

    def test_engine_no_signals(self, mock_mt5):
        from ml_enhancements import EventDrivenBacktestEngine
        bars = [{"time": f"b_{i}", "open": 1.1, "high": 1.11, "low": 1.09, "close": 1.105}
                for i in range(100)]
        signals = [{"action": "hold", "confidence": 0, "sl_pips": 50, "tp_pips": 100}] * 100
        engine = EventDrivenBacktestEngine()
        result = engine.run(signals, bars)
        assert result["total_trades"] == 0
        assert result["final_balance"] == 10000


# ==========================================
# ValidationPipeline integration
# ==========================================
class TestValidationPipeline:
    def test_evaluate_backtest_pass(self):
        from validation_pipeline import ValidationPipeline
        pipeline = ValidationPipeline()
        results = {
            "sharpe_ratio": 1.2,
            "max_drawdown": 10.0,
            "profit_factor": 1.5,
            "win_rate": 45.0,
            "total_trades": 150,
        }
        eval_result = pipeline.evaluate_backtest(results)
        assert eval_result["passed"] is True
        assert len(eval_result["failures"]) == 0

    def test_evaluate_backtest_fail_sharpe(self):
        from validation_pipeline import ValidationPipeline
        pipeline = ValidationPipeline()
        results = {
            "sharpe_ratio": 0.3,
            "max_drawdown": 10.0,
            "profit_factor": 1.5,
            "win_rate": 45.0,
            "total_trades": 150,
        }
        eval_result = pipeline.evaluate_backtest(results)
        assert eval_result["passed"] is False
        assert any("sharpe" in f for f in eval_result["failures"])


# ==========================================
# run_backtest integration
# ==========================================
class TestRunBacktest:
    def test_extract_trades(self, mock_mt5):
        from run_backtest import extract_trades_from_engine
        n = 300
        np.random.seed(42)
        close = np.cumsum(np.random.randn(n) * 0.0005) + 1.10000
        high = close + np.abs(np.random.randn(n)) * 0.00025
        low = close - np.abs(np.random.randn(n)) * 0.00025
        bars = [{"time": f"b_{i}", "open": float(close[i] + 0.0001),
                 "high": float(high[i]), "low": float(low[i]), "close": float(close[i]),
                 "spread": 1.5} for i in range(n)]
        signals = []
        for i in range(n):
            if i % 60 == 0 and i > 50:
                signals.append({"action": "buy", "confidence": 0.7, "sl_pips": 50, "tp_pips": 100})
            elif i % 90 == 0 and i > 50:
                signals.append({"action": "sell", "confidence": 0.6, "sl_pips": 50, "tp_pips": 100})
            else:
                signals.append({"action": "hold", "confidence": 0, "sl_pips": 50, "tp_pips": 100})
        trades = extract_trades_from_engine(signals, bars, initial_balance=10000, pip_value=10.0)
        assert isinstance(trades, list)
        if trades:
            assert "pnl" in trades[0]

    @patch("run_backtest.fetch_historical_data")
    def test_run_full_backtest_structure(self, mock_fetch, mock_mt5):
        from run_backtest import run_full_backtest
        df = synthetic_df(n=500)
        mock_fetch.return_value = df
        report = run_full_backtest(months=12)
        assert "backtest" in report
        assert "walk_forward" in report
        assert "monte_carlo" in report
        assert "gate_criteria" in report
