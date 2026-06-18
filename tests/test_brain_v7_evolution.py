"""Tests for brain_v7.py evolution components."""
import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_v7 import (
    StrategyGenome,
    EvolutionEngine,
    PatternMemory,
    PerformanceAdaptor,
    MarketConditionMemory,
    ContinuousImprover,
    PATTERN_MATCH_THRESHOLD,
    POPULATION_SIZE,
)


@pytest.fixture
def genome():
    """A single StrategyGenome."""
    return StrategyGenome()


@pytest.fixture
def engine(tmp_path):
    """EvolutionEngine with mocked file I/O."""
    with patch("brain_v7.DATA_DIR", str(tmp_path)), \
         patch.object(EvolutionEngine, "_load"), \
         patch.object(EvolutionEngine, "_save"):
        e = EvolutionEngine()
        e.population = [StrategyGenome() for _ in range(POPULATION_SIZE)]
        e.generation = 0
        yield e


@pytest.fixture
def memory(tmp_path):
    """PatternMemory with mocked file I/O."""
    with patch("brain_v7.DATA_DIR", str(tmp_path)), \
         patch.object(PatternMemory, "_load"), \
         patch.object(PatternMemory, "_save"):
        m = PatternMemory()
        m.patterns = deque(maxlen=200)
        yield m


class TestStrategyGenome:
    def test_mutate(self, genome):
        original_params = genome.params.copy()
        mutated = genome.mutate(rate=1.0)
        changed = any(mutated.params[k] != original_params[k] for k in original_params)
        assert changed or len(original_params) == 0

    def test_crossover(self, genome):
        other = StrategyGenome()
        child = genome.crossover(other)
        assert child is not None
        assert isinstance(child.params, dict)
        assert len(child.params) == len(genome.params)

    def test_to_dict_from_dict(self, genome):
        genome.fitness = 0.75
        genome.trades = 20
        genome.wins = 15
        d = genome.to_dict()
        restored = StrategyGenome.from_dict(d)
        assert restored.fitness == 0.75
        assert restored.trades == 20
        assert restored.wins == 15
        assert restored.params == genome.params


class TestEvolutionEngine:
    def test_evolve(self, engine):
        for g in engine.population[:3]:
            g.fitness = 0.8
        engine.evolve()
        assert engine.generation == 1
        assert len(engine.population) == POPULATION_SIZE

    def test_get_best_params(self, engine):
        engine.best_genome = StrategyGenome()
        engine.best_genome.fitness = 0.9
        params = engine.get_best_params()
        assert isinstance(params, dict)
        assert "ema_fast" in params
        assert "sl_atr_mult" in params

    def test_record_trade(self, engine):
        engine.record_trade(0, won=True)
        assert engine.population[0].trades == 1
        assert engine.population[0].wins == 1


class TestPatternMemory:
    def test_record_and_find(self, memory):
        snapshot = {"close_pct_change": 0.5, "volatility": 1.2}
        memory.record_pattern(snapshot, outcome=10, confidence=0.8)
        assert len(memory.patterns) == 1
        similar = memory.find_similar(snapshot)
        assert len(similar) > 0

    def test_prediction(self, memory):
        snap1 = {"close_pct_change": 0.3, "volatility": 0.8}
        snap2 = {"close_pct_change": 0.35, "volatility": 0.85}
        memory.record_pattern(snap1, outcome=15, confidence=0.7)
        memory.record_pattern(snap2, outcome=-5, confidence=0.6)
        pred = memory.get_prediction(snap1)
        assert pred is not None
        assert "predicted_direction" in pred
        assert "confidence" in pred

    def test_no_prediction_empty(self, memory):
        pred = memory.get_prediction({"close_pct_change": 0.5})
        assert pred is None


class TestPerformanceAdaptor:
    def test_plateau_detection(self):
        adaptor = PerformanceAdaptor()
        for _ in range(25):
            adaptor.record(0.7, won=True, profit=1.0)
        assert adaptor.detect_plateau() is True

    def test_adaptation_suggestion(self):
        adaptor = PerformanceAdaptor()
        for _ in range(35):
            adaptor.record(0.6, won=False, profit=-10)
        suggestions = adaptor.suggest_adaptation()
        assert suggestions is not None
        assert len(suggestions) > 0


class TestMarketConditionMemory:
    def test_record_and_get_best(self):
        mem = MarketConditionMemory()
        for _ in range(10):
            mem.record("trending", "london", 0.8, "momentum", won=True)
            mem.record("trending", "london", 0.8, "counter", won=False)
        best = mem.get_best_strategy("trending", "london", 0.8)
        assert best is not None
        assert best["strategy"] == "momentum"

    def test_insufficient_data(self):
        mem = MarketConditionMemory()
        mem.record("ranging", "asian", 0.3, "grid", won=True)
        best = mem.get_best_strategy("ranging", "asian", 0.3)
        assert best is None


class TestContinuousImprover:
    def test_improvement_calculation(self):
        improver = ContinuousImprover()
        for _ in range(15):
            improver.record_metrics({"win_rate": 55, "profit_factor": 1.5, "sharpe": 1.0, "expectancy": 10})
        score = improver.calculate_improvement()
        assert isinstance(score, float)

    def test_log_change(self):
        improver = ContinuousImprover()
        improver.log_change("Initial version")
        assert improver.version == 2
        assert len(improver.changelog) == 1