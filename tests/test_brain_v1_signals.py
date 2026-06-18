"""
Tests for brain_v1.py signal generation.
Run with: pytest tests/test_brain_v1_signals.py -v
"""
import pytest
import numpy as np
import pandas as pd
from tests.conftest import synthetic_df


class TestCalcIndicators:
    def test_calc_indicators_modifies_df(self, mock_mt5):
        from brain_v1 import SignalAnalyzer
        analyzer = SignalAnalyzer()
        df = synthetic_df(100)
        original_cols = set(df.columns)
        analyzer._calc_indicators(df)
        new_cols = set(df.columns) - original_cols
        assert len(new_cols) > 0, f"No new columns added"

    def test_calc_indicators_adds_ema(self, mock_mt5):
        from brain_v1 import SignalAnalyzer
        analyzer = SignalAnalyzer()
        df = synthetic_df(100)
        analyzer._calc_indicators(df)
        ema_cols = [c for c in df.columns if 'ema' in c.lower()]
        assert len(ema_cols) > 0

    def test_calc_indicators_adds_rsi(self, mock_mt5):
        from brain_v1 import SignalAnalyzer
        analyzer = SignalAnalyzer()
        df = synthetic_df(100)
        analyzer._calc_indicators(df)
        rsi_cols = [c for c in df.columns if 'rsi' in c.lower()]
        assert len(rsi_cols) > 0


class TestSignalMA:
    def test_signal_ma_returns_dict(self, mock_mt5):
        from brain_v1 import SignalAnalyzer
        analyzer = SignalAnalyzer()
        df = synthetic_df(100)
        analyzer._calc_indicators(df)
        result = analyzer._signal_ma(df)
        assert isinstance(result, dict)
        assert 'direction' in result
        assert 'confidence' in result


class TestSignalRSI:
    def test_signal_rsi_returns_dict(self, mock_mt5):
        from brain_v1 import SignalAnalyzer
        analyzer = SignalAnalyzer()
        df = synthetic_df(100)
        analyzer._calc_indicators(df)
        result = analyzer._signal_rsi(df)
        assert isinstance(result, dict)
        assert 'direction' in result


class TestSignalBB:
    def test_signal_bb_returns_dict(self, mock_mt5):
        from brain_v1 import SignalAnalyzer
        analyzer = SignalAnalyzer()
        df = synthetic_df(100)
        analyzer._calc_indicators(df)
        result = analyzer._signal_bb(df)
        assert isinstance(result, dict)
        assert 'direction' in result


class TestSignalBreakout:
    def test_signal_breakout_returns_dict(self, mock_mt5):
        from brain_v1 import SignalAnalyzer
        analyzer = SignalAnalyzer()
        df = synthetic_df(100)
        analyzer._calc_indicators(df)
        result = analyzer._signal_breakout(df)
        assert isinstance(result, dict)
        assert 'direction' in result


class TestSignalMomentum:
    def test_signal_momentum_returns_dict(self, mock_mt5):
        from brain_v1 import SignalAnalyzer
        analyzer = SignalAnalyzer()
        df = synthetic_df(100)
        analyzer._calc_indicators(df)
        result = analyzer._signal_momentum(df)
        assert isinstance(result, dict)
        assert 'direction' in result


class TestSignalOrderflow:
    def test_signal_orderflow_returns_dict(self, mock_mt5):
        from brain_v1 import SignalAnalyzer
        analyzer = SignalAnalyzer()
        df = synthetic_df(100)
        analyzer._calc_indicators(df)
        result = analyzer._signal_orderflow(df)
        assert isinstance(result, dict)
        assert 'direction' in result


class TestSignalSR:
    def test_signal_sr_returns_dict(self, mock_mt5):
        from brain_v1 import SignalAnalyzer
        analyzer = SignalAnalyzer()
        df = synthetic_df(100)
        analyzer._calc_indicators(df)
        result = analyzer._signal_sr(df, "EURUSD")
        assert isinstance(result, dict)
        assert 'direction' in result
