"""
Tests for brain_v3.py indicator cache, circuit breaker, and data cache.
Run with: pytest tests/test_brain_v3_cache.py -v
"""
import pytest
import numpy as np
import pandas as pd
from tests.conftest import synthetic_df


class TestIndicatorCache:
    def test_compute_indicators_returns_data(self):
        from brain_v3 import IndicatorCache
        cache = IndicatorCache()
        df = synthetic_df(100)
        result = cache.compute_indicators(df)
        assert result is not None, "Should return data"

    def test_compute_indicators_adds_columns(self):
        from brain_v3 import IndicatorCache
        cache = IndicatorCache()
        df = synthetic_df(100)
        result = cache.compute_indicators(df)
        # Should add indicator columns to the dataframe
        assert hasattr(result, 'columns'), "Result should be a DataFrame with columns"

    def test_compute_indicators_has_ema(self):
        from brain_v3 import IndicatorCache
        cache = IndicatorCache()
        df = synthetic_df(100)
        result = cache.compute_indicators(df)
        ema_cols = [c for c in result.columns if 'ema' in c.lower()]
        assert len(ema_cols) > 0, f"No EMA columns found in: {list(result.columns)}"

    def test_compute_indicators_has_rsi(self):
        from brain_v3 import IndicatorCache
        cache = IndicatorCache()
        df = synthetic_df(100)
        result = cache.compute_indicators(df)
        rsi_cols = [c for c in result.columns if 'rsi' in c.lower()]
        assert len(rsi_cols) > 0, f"No RSI columns found in: {list(result.columns)}"

    def test_compute_indicators_different_for_different_data(self):
        from brain_v3 import IndicatorCache
        cache = IndicatorCache()
        df1 = synthetic_df(100, base_price=1.0)
        df2 = synthetic_df(100, base_price=1.5)
        r1 = cache.compute_indicators(df1)
        r2 = cache.compute_indicators(df2)
        # Different data should produce different indicator values
        ema_cols = [c for c in r1.columns if 'ema' in c.lower()]
        if ema_cols:
            col = ema_cols[0]
            assert not r1[col].equals(r2[col]), "Different data should produce different indicators"

    def test_empty_data_handled(self):
        from brain_v3 import IndicatorCache
        cache = IndicatorCache()
        df = synthetic_df(5)
        result = cache.compute_indicators(df)
        assert result is not None, "Should handle small data gracefully"


class TestCircuitBreaker:
    def test_initially_open(self):
        from brain_v3 import CircuitBreaker
        cb = CircuitBreaker()
        assert cb.is_open() is True

    def test_trips_after_consecutive_losses(self):
        from brain_v3 import CircuitBreaker
        cb = CircuitBreaker()
        for _ in range(4):
            cb.record_loss()
        assert cb.is_open() is False

    def test_resets_on_win(self):
        from brain_v3 import CircuitBreaker
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_loss()
        cb.record_win()
        for _ in range(3):
            cb.record_loss()
        assert cb.is_open() is True

    def test_does_not_trip_before_threshold(self):
        from brain_v3 import CircuitBreaker
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_loss()
        assert cb.is_open() is True

    def test_remaining_break_time(self):
        from brain_v3 import CircuitBreaker
        cb = CircuitBreaker()
        for _ in range(4):
            cb.record_loss()
        remaining = cb.remaining_break_time()
        assert remaining > 0


class TestDataCache:
    def test_get_rates_returns_data(self, mock_mt5):
        from brain_v3 import DataCache
        cache = DataCache()
        result = cache.get_rates("EURUSD", 60, 100)
        assert result is not None

    def test_get_rates_caches_result(self, mock_mt5):
        from brain_v3 import DataCache
        cache = DataCache()
        result1 = cache.get_rates("EURUSD", 60, 100)
        result2 = cache.get_rates("EURUSD", 60, 100)
        assert result1 is result2

    def test_get_rates_different_symbols(self, mock_mt5):
        from brain_v3 import DataCache
        cache = DataCache()
        result1 = cache.get_rates("EURUSD", 60, 100)
        result2 = cache.get_rates("GBPUSD", 60, 100)
        assert result1 is not None
        assert result2 is not None
