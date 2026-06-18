"""
Tests for brain_v10.py CorrelationAnalyzer and MarketRegimeDetector.
Run with: pytest tests/test_brain_v10_mtf.py -v
"""
import sys
import types
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime


# ---- Mock all external dependencies before importing brain_v10 ----
@pytest.fixture(autouse=True)
def mock_deps(monkeypatch):
    """Set up all mocked dependencies for brain_v10 imports."""
    # MT5 mock
    mt5 = types.ModuleType('MetaTrader5')
    mt5.TIMEFRAME_M1 = 60
    mt5.TIMEFRAME_M5 = 300
    mt5.TIMEFRAME_M15 = 900
    mt5.TIMEFRAME_M30 = 1800
    mt5.TIMEFRAME_H1 = 3600
    mt5.TIMEFRAME_H4 = 14400
    mt5.TIMEFRAME_D1 = 86400
    mt5.copy_rates_from_pos = MagicMock(return_value=None)
    monkeypatch.setitem(sys.modules, 'MetaTrader5', mt5)

    # config mock
    cfg = types.ModuleType('config')
    cfg.MAGIC_NUMBER = 99999
    cfg.DATA_DIR = "/tmp/test_data"
    cfg.CORRELATION_GROUPS = {
        "eurusd_group": {"symbols": ["EURUSD", "GBPUSD"]},
    }
    monkeypatch.setitem(sys.modules, 'config', cfg)

    # ai_client mock
    ai = types.ModuleType('ai_client')
    ai.get_ai_client = MagicMock(return_value=MagicMock(is_available=lambda: False))
    monkeypatch.setitem(sys.modules, 'ai_client', ai)

    # indicators mock
    ind = types.ModuleType('indicators')
    ind.validate_rate_freshness = MagicMock(return_value={"fresh": True})
    ind.ema = MagicMock(side_effect=lambda data, span: np.array(data, dtype=float))
    ind.fetch_closed_rates = MagicMock(return_value=None)
    ind.align_to_m1_grid = MagicMock(return_value=None)
    ind.is_tradeable_now = MagicMock(return_value={"can_trade": True, "reason": ""})
    ind.get_current_session = MagicMock(return_value="london")
    monkeypatch.setitem(sys.modules, 'indicators', ind)

    # order_flow mock
    of = types.ModuleType('order_flow')
    of.OrderFlowAnalyzer = MagicMock
    monkeypatch.setitem(sys.modules, 'order_flow', of)

    # market_intelligence mock
    mi = types.ModuleType('market_intelligence')
    mi.NewsCalendar = MagicMock
    mi.SentimentFeed = MagicMock
    monkeypatch.setitem(sys.modules, 'market_intelligence', mi)

    # institutional_analytics mock
    ia = types.ModuleType('institutional_analytics')
    ia.OrderBookHeatmap = MagicMock
    ia.VolumeProfile = MagicMock
    monkeypatch.setitem(sys.modules, 'institutional_analytics', ia)

    # microstructure mock
    micro = types.ModuleType('microstructure')
    micro.LatencyArbitrage = MagicMock
    micro.MarketImpactModel = MagicMock
    monkeypatch.setitem(sys.modules, 'microstructure', micro)

    # providers mock
    prov = types.ModuleType('providers')
    prov.SignalProvider = MagicMock
    monkeypatch.setitem(sys.modules, 'providers', prov)


# ==========================================
# CorrelationAnalyzer
# ==========================================
class TestCorrelationAnalyzer:
    def test_get_regime_empty_cache_returns_unknown(self):
        from brain_v10 import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        regime = analyzer.get_regime()
        assert regime == "unknown"

    def test_get_regime_high_positive_returns_risk_on(self):
        from brain_v10 import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        analyzer.correlation_cache = {"EURUSD_GBPUSD": 0.8, "EURUSD_USDJPY": 0.75}
        regime = analyzer.get_regime()
        assert regime == "risk_on"

    def test_get_regime_negative_returns_divergent(self):
        from brain_v10 import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        analyzer.correlation_cache = {"EURUSD_GBPUSD": -0.5, "EURUSD_USDJPY": -0.4}
        regime = analyzer.get_regime()
        assert regime == "divergent"

    def test_get_regime_moderate_returns_moderate(self):
        from brain_v10 import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        analyzer.correlation_cache = {"EURUSD_GBPUSD": 0.5, "EURUSD_USDJPY": 0.45}
        regime = analyzer.get_regime()
        assert regime == "moderate"

    def test_get_regime_low_positive_returns_mixed(self):
        from brain_v10 import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        analyzer.correlation_cache = {"EURUSD_GBPUSD": 0.2, "EURUSD_USDJPY": 0.1}
        regime = analyzer.get_regime()
        assert regime == "mixed"

    def test_get_pair_correlation_returns_cached_value(self):
        from brain_v10 import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        analyzer.correlation_cache = {"EURUSD_GBPUSD": 0.72}
        corr = analyzer.get_pair_correlation("EURUSD", "GBPUSD")
        assert corr == 0.72

    def test_get_pair_correlation_missing_returns_zero(self):
        from brain_v10 import CorrelationAnalyzer
        analyzer = CorrelationAnalyzer()
        corr = analyzer.get_pair_correlation("EURUSD", "USDJPY")
        assert corr == 0


# ==========================================
# MarketRegimeDetector
# ==========================================
class TestMarketRegimeDetector:
    def _make_mtf_result(self, trend="UP", volatility="NORMAL"):
        return {"EURUSD": {"H1": {"trend": trend, "volatility": volatility}}}

    def test_detect_returns_regime_and_confidence(self):
        from brain_v10 import MarketRegimeDetector
        detector = MarketRegimeDetector()
        mtf = self._make_mtf_result(trend="UP", volatility="NORMAL")
        result = detector.detect(mtf, {})
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_detect_has_valid_regime_string(self):
        from brain_v10 import MarketRegimeDetector
        detector = MarketRegimeDetector()
        mtf = self._make_mtf_result(trend="STRONG_UP", volatility="HIGH")
        regime, conf = detector.detect(mtf, {"EURUSD_GBPUSD": 0.8})
        assert regime in {"trending_correlated", "trending_divergent", "ranging", "volatile", "mixed", "unknown"}
        assert isinstance(conf, float)

    def test_detect_empty_mtf_returns_unknown(self):
        from brain_v10 import MarketRegimeDetector
        detector = MarketRegimeDetector()
        regime, conf = detector.detect({}, {})
        assert regime == "unknown"
        assert conf == 0

    def test_detect_strong_trend_with_high_corr_gives_trending_correlated(self):
        from brain_v10 import MarketRegimeDetector
        detector = MarketRegimeDetector()
        # Build result with many trending timeframes
        mtf = {}
        for sym in ["EURUSD", "GBPUSD", "USDJPY"]:
            mtf[sym] = {
                "M5": {"trend": "UP", "volatility": "NORMAL"},
                "H1": {"trend": "STRONG_UP", "volatility": "HIGH"},
                "H4": {"trend": "UP", "volatility": "NORMAL"},
            }
        correlations = {"EURUSD_GBPUSD": 0.8, "EURUSD_USDJPY": 0.7}
        regime, conf = detector.detect(mtf, correlations)
        assert regime == "trending_correlated"
        assert conf > 0

    def test_detect_range_dominant_gives_ranging(self):
        from brain_v10 import MarketRegimeDetector
        detector = MarketRegimeDetector()
        mtf = {}
        for sym in ["EURUSD", "GBPUSD"]:
            mtf[sym] = {
                "M5": {"trend": "RANGING", "volatility": "LOW"},
                "H1": {"trend": "RANGING", "volatility": "NORMAL"},
                "H4": {"trend": "RANGING", "volatility": "LOW"},
            }
        regime, conf = detector.detect(mtf, {})
        assert regime == "ranging"
        assert conf > 0

    def test_detect_high_volatility_gives_volatile(self):
        from brain_v10 import MarketRegimeDetector
        detector = MarketRegimeDetector()
        # Need trend_pct < 0.6, range_pct < 0.6, vol_high_pct > 0.5
        # 6 entries: 3 trend + 3 range, all HIGH vol → volatile
        mtf = {
            "EURUSD": {
                "M5": {"trend": "UP", "volatility": "HIGH"},
                "H1": {"trend": "RANGING", "volatility": "HIGH"},
            },
            "GBPUSD": {
                "M5": {"trend": "DOWN", "volatility": "HIGH"},
                "H1": {"trend": "RANGING", "volatility": "HIGH"},
            },
            "USDJPY": {
                "M5": {"trend": "UP", "volatility": "HIGH"},
                "H1": {"trend": "RANGING", "volatility": "HIGH"},
            },
        }
        regime, conf = detector.detect(mtf, {})
        assert regime == "volatile"
        assert conf > 0

    def test_detect_updates_history(self):
        from brain_v10 import MarketRegimeDetector
        detector = MarketRegimeDetector()
        mtf = self._make_mtf_result()
        detector.detect(mtf, {})
        assert len(detector.regime_history) > 0
