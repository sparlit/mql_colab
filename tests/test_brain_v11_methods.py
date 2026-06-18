"""
Tests for brain_v11.py regime classification, method selection, and parameter adaptation.
Run with: pytest tests/test_brain_v11_methods.py -v
"""
import pytest
import numpy as np
import pandas as pd
from tests.conftest import synthetic_df


def generate_trending_data(n=200, direction=1, volatility=0.001):
    np.random.seed(42)
    drift = direction * 0.0001
    close = np.cumsum(np.random.randn(n) * volatility + drift) + 1.10000
    return pd.DataFrame({
        'open': close - 0.0001,
        'high': close + 0.0005,
        'low': close - 0.0005,
        'close': close,
        'tick_volume': np.full(n, 5000.0),
    })


class TestRegimeClassifier:
    def test_classify_returns_dict(self):
        from brain_v11 import RegimeClassifier
        classifier = RegimeClassifier()
        df = synthetic_df(200)
        result = classifier.classify(df, "EURUSD")
        assert isinstance(result, dict)
        assert 'regime' in result

    def test_classify_has_confidence(self):
        from brain_v11 import RegimeClassifier
        classifier = RegimeClassifier()
        df = synthetic_df(200)
        result = classifier.classify(df, "EURUSD")
        assert 'confidence' in result

    def test_uptrend_has_trend_alignment(self):
        from brain_v11 import RegimeClassifier
        classifier = RegimeClassifier()
        df = generate_trending_data(200, direction=1)
        result = classifier.classify(df, "EURUSD")
        assert 'trend_alignment' in result
        assert result['trend_alignment'] > 0

    def test_downtrend_has_negative_alignment(self):
        from brain_v11 import RegimeClassifier
        classifier = RegimeClassifier()
        df = generate_trending_data(200, direction=-1)
        result = classifier.classify(df, "EURUSD")
        assert 'trend_alignment' in result
        assert result['trend_alignment'] < 0

    def test_short_data_returns_unknown(self):
        from brain_v11 import RegimeClassifier
        classifier = RegimeClassifier()
        df = synthetic_df(10)
        result = classifier.classify(df, "EURUSD")
        assert result['regime'] == 'unknown'


class TestMethodSelector:
    def test_select_returns_tuple(self):
        from brain_v11 import MethodSelector
        selector = MethodSelector()
        result = selector.select(
            regime_info={"regime": "strong_uptrend", "trend_strength": 0.8, "volatility": 0.3},
            session="london",
            available_methods=None,
        )
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert len(result) == 3

    def test_select_primary_is_method(self):
        from brain_v11 import MethodSelector
        selector = MethodSelector()
        primary, secondary, scores = selector.select(
            regime_info={"regime": "strong_uptrend", "trend_strength": 0.8, "volatility": 0.3},
            session="london",
            available_methods=None,
        )
        assert primary is not None

    def test_select_has_scores(self):
        from brain_v11 import MethodSelector
        selector = MethodSelector()
        primary, secondary, scores = selector.select(
            regime_info={"regime": "ranging", "trend_strength": 0.1, "volatility": 0.2},
            session="asian",
            available_methods=None,
        )
        assert isinstance(scores, dict)
        assert len(scores) > 0


class TestParameterAdapter:
    def test_adapt_returns_dict(self):
        from brain_v11 import ParameterAdapter
        adapter = ParameterAdapter()
        result = adapter.adapt(
            method="trend_following",
            regime_info={"regime": "strong_uptrend", "volatility": 0.5, "trend_strength": 0.8},
            base_config={"sl_atr_mult": 1.5, "tp_atr_mult": 2.5, "risk_per_trade": 0.01},
        )
        assert isinstance(result, dict)

    def test_adapt_non_empty(self):
        from brain_v11 import ParameterAdapter
        adapter = ParameterAdapter()
        result = adapter.adapt(
            method="trend_following",
            regime_info={"regime": "strong_uptrend", "volatility": 0.5, "trend_strength": 0.8},
            base_config={"sl_atr_mult": 1.5, "tp_atr_mult": 2.5, "risk_per_trade": 0.01},
        )
        assert len(result) > 0

    def test_high_volatility_reduces_risk(self):
        from brain_v11 import ParameterAdapter
        adapter = ParameterAdapter()
        low_vol = adapter.adapt("trend_following", {"regime": "uptrend", "volatility": 0.2, "trend_strength": 0.5}, {"sl_atr_mult": 1.5, "tp_atr_mult": 2.5, "risk_per_trade": 0.01})
        high_vol = adapter.adapt("trend_following", {"regime": "uptrend", "volatility": 0.9, "trend_strength": 0.5}, {"sl_atr_mult": 1.5, "tp_atr_mult": 2.5, "risk_per_trade": 0.01})
        low_risk = low_vol.get("risk_per_trade", 0.01)
        high_risk = high_vol.get("risk_per_trade", 0.01)
        assert high_risk <= low_risk
