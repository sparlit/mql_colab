"""
Tests for brain_v2.py regime detection, candlestick patterns, and adaptive SLTP.
Run with: pytest tests/test_brain_v2_regime.py -v
"""
import pytest
import sys
import numpy as np
import pandas as pd
import importlib
from tests.conftest import synthetic_df


class TestRegimeDetector:
    def test_detect_returns_dict(self):
        from brain_v2 import RegimeDetector
        detector = RegimeDetector()
        df = synthetic_df(200)
        result = detector.detect(df)
        assert isinstance(result, dict)
        assert 'regime' in result

    def test_detect_has_confidence(self):
        from brain_v2 import RegimeDetector
        detector = RegimeDetector()
        df = synthetic_df(200)
        result = detector.detect(df)
        assert 'confidence' in result
        assert 0 <= result['confidence'] <= 1

    def test_short_data_returns_valid_regime(self):
        from brain_v2 import RegimeDetector
        detector = RegimeDetector()
        df = synthetic_df(10)
        result = detector.detect(df)
        assert isinstance(result['regime'], str)

    def test_get_regime_modifier_returns_dict(self):
        from brain_v2 import RegimeDetector
        detector = RegimeDetector()
        result = detector.get_regime_modifier("uptrend")
        assert isinstance(result, dict)


class TestCandlestickPatterns:
    def test_detect_returns_list(self):
        from brain_v2 import CandlestickPatterns
        df = synthetic_df(50)
        result = CandlestickPatterns.detect(df)
        assert isinstance(result, list)


class TestAdaptiveSLTP:
    def _get_sltp(self, mock_mt5):
        """Reload brain_v2 to pick up the mock, then call AdaptiveSLTP."""
        if 'brain_v2' in sys.modules:
            del sys.modules['brain_v2']
        from brain_v2 import AdaptiveSLTP
        df = synthetic_df(100)
        return AdaptiveSLTP.calculate(
            df, direction=1,
            regime_info={"regime": "uptrend"},
            session_mod={"sl_mult": 1.0, "tp_mult": 1.0},
            regime_mod={"sl_mult": 1.0, "tp_mult": 1.0},
            symbol="EURUSD",
        )

    def test_calculate_returns_tuple(self, mock_mt5):
        result = self._get_sltp(mock_mt5)
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert len(result) >= 2, "Should return at least (sl, tp, ...)"

    def test_buy_sl_below_entry(self, mock_mt5):
        result = self._get_sltp(mock_mt5)
        sl = result[0]
        df = synthetic_df(100)
        entry = df['close'].iloc[-1]
        assert sl < entry, "BUY SL should be below entry"

    def test_tp_further_than_sl(self, mock_mt5):
        result = self._get_sltp(mock_mt5)
        sl, tp = result[0], result[1]
        df = synthetic_df(100)
        entry = df['close'].iloc[-1]
        sl_dist = entry - sl
        tp_dist = tp - entry
        assert tp_dist > sl_dist, "TP should be further than SL"
