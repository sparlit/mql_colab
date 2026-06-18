"""Tests for brain_v5.py learning components."""
import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_v5 import (
    StrategyAutoWeighter,
    EdgeDecayDetector,
    ParameterOptimizer,
    PositionScalingEngine,
    MIN_TRADES_TO_DISABLE,
    DISABLE_WIN_RATE_THRESHOLD,
    EDGE_DECAY_WINDOW,
    SCALE_IN_CONFIDENCE,
    SCALE_OUT_CONFIDENCE,
    MAX_SCALE_LEVELS,
)


@pytest.fixture
def weighter(tmp_path):
    """StrategyAutoWeighter with mocked file I/O."""
    with patch("brain_v5.DATA_DIR", str(tmp_path)), \
         patch.object(StrategyAutoWeighter, "_load"), \
         patch.object(StrategyAutoWeighter, "_save"):
        w = StrategyAutoWeighter()
        w.performance = {}
        yield w


@pytest.fixture
def detector():
    """EdgeDecayDetector."""
    return EdgeDecayDetector()


@pytest.fixture
def optimizer(tmp_path):
    """ParameterOptimizer with mocked file I/O."""
    with patch("brain_v5.DATA_DIR", str(tmp_path)), \
         patch.object(ParameterOptimizer, "_load"), \
         patch.object(ParameterOptimizer, "_save"):
        o = ParameterOptimizer()
        o.trades_by_regime = {}
        yield o


@pytest.fixture
def scaler():
    """PositionScalingEngine."""
    return PositionScalingEngine()


class TestStrategyAutoWeighter:
    def test_record_and_get_weight(self, weighter):
        for _ in range(20):
            weighter.record("momentum", won=True, profit=10)
        w = weighter.get_weight("momentum")
        assert w > 1.0

        for _ in range(20):
            weighter.record("counter", won=False, profit=-10)
        w_bad = weighter.get_weight("counter")
        assert w_bad < 1.0

    def test_disabled_strategies(self, weighter):
        for _ in range(MIN_TRADES_TO_DISABLE + 5):
            weighter.record("bad_strat", won=False, profit=-5)
        disabled = weighter.get_disabled_strategies()
        assert "bad_strat" in disabled

    def test_weight_bounds(self, weighter):
        for _ in range(100):
            weighter.record("extreme_win", won=True, profit=50)
        w_high = weighter.get_weight("extreme_win")
        assert 1.0 <= w_high <= 1.5

        for _ in range(100):
            weighter.record("extreme_loss", won=False, profit=-50)
        w_low = weighter.get_weight("extreme_loss")
        assert 0.3 <= w_low <= 1.0


class TestEdgeDecayDetector:
    def test_no_decay(self, detector):
        for _ in range(EDGE_DECAY_WINDOW + 10):
            detector.record(0.7, won=True)
        result = detector.detect_decay()
        assert result["decaying"] is False

    def test_decay_detected(self, detector):
        for _ in range(EDGE_DECAY_WINDOW):
            detector.record(0.8, won=True)
        for _ in range(EDGE_DECAY_WINDOW):
            detector.record(0.8, won=False)
        result = detector.detect_decay()
        assert result["decaying"] is True or result["score"] > 0


class TestParameterOptimizer:
    def test_record_and_optimize(self, optimizer):
        for i in range(15):
            optimizer.record("trending", 1.5, 2.5, won=(i % 3 != 0), profit=10 if i % 3 != 0 else -5)
        assert len(optimizer.trades_by_regime["trending"]["trades"]) > 0

    def test_get_optimal_params(self, optimizer):
        for i in range(15):
            optimizer.record("ranging", 1.2, 3.0, won=(i % 2 == 0), profit=8 if i % 2 == 0 else -4)
        result = optimizer.get_optimal_params("ranging")
        assert result is not None
        assert "sl_mult" in result
        assert "tp_mult" in result

    def test_get_optimal_params_insufficient_data(self, optimizer):
        result = optimizer.get_optimal_params("empty_regime")
        assert result is None


class TestPositionScalingEngine:
    def test_should_scale_in(self, scaler):
        position = MagicMock()
        position.ticket = 12345
        position.volume = 0.1
        position.profit = 50
        position.contract_size = 100000
        scale, vol = scaler.should_scale_in(position, 0.9)
        assert scale is True
        assert vol > 0

    def test_should_scale_out(self, scaler):
        position = MagicMock()
        position.ticket = 12345
        position.volume = 0.2
        position.profit = 30
        position.contract_size = 100000
        position.symbol = "EURUSD"
        with patch("brain_v5.mt5") as mock_mt5:
            mock_mt5.symbol_info.return_value.volume_min = 0.01
            mock_mt5.symbol_info.return_value.volume_step = 0.01
            scale, vol = scaler.should_scale_out(position, 0.3)
            assert scale is True
            assert vol > 0

    def test_max_levels(self, scaler):
        position = MagicMock()
        position.ticket = 99999
        position.volume = 0.1
        position.profit = 50
        position.contract_size = 100000
        for _ in range(MAX_SCALE_LEVELS + 1):
            scaler.should_scale_in(position, 0.9)
        scale, vol = scaler.should_scale_in(position, 0.9)
        assert scale is False