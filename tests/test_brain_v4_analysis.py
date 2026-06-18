"""
Tests for brain_v4.py Bayesian scoring, entry quality, and false breakout detection.
Run with: pytest tests/test_brain_v4_analysis.py -v
"""
import pytest
import numpy as np
import pandas as pd
from tests.conftest import synthetic_df


class TestBayesianScorer:
    def test_initial_probability(self):
        from brain_v4 import BayesianScorer
        scorer = BayesianScorer()
        prob = scorer.get_probability("test_strategy")
        assert 0.0 <= prob <= 1.0

    def test_winning_beats_losing(self):
        from brain_v4 import BayesianScorer
        scorer = BayesianScorer()
        for _ in range(20):
            scorer.update("winner", True)
            scorer.update("loser", False)
        assert scorer.get_probability("winner") > scorer.get_probability("loser")

    def test_probability_bounds(self):
        from brain_v4 import BayesianScorer
        scorer = BayesianScorer()
        for _ in range(100):
            scorer.update("test_strategy", True)
        prob = scorer.get_probability("test_strategy")
        assert 0.0 <= prob <= 1.0

    def test_get_all_probabilities(self):
        from brain_v4 import BayesianScorer
        scorer = BayesianScorer()
        scorer.update("s1", True)
        scorer.update("s2", False)
        probs = scorer.get_all_probabilities()
        assert isinstance(probs, dict)
        assert "s1" in probs
        assert "s2" in probs


class TestEntryQualityScorer:
    def test_score_returns_dict(self):
        from brain_v4 import EntryQualityScorer
        df = synthetic_df(100)
        result = EntryQualityScorer.score(
            df, direction=1, regime="uptrend", session="london",
            micro=None, zones={}, patterns=[]
        )
        assert isinstance(result, dict)
        assert "total" in result

    def test_score_in_range(self):
        from brain_v4 import EntryQualityScorer
        df = synthetic_df(100)
        result = EntryQualityScorer.score(
            df, direction=1, regime="uptrend", session="london",
            micro=None, zones={}, patterns=[]
        )
        assert 0 <= result["total"] <= 1.0


class TestFalseBreakoutFilter:
    def test_detect_returns_tuple(self):
        from brain_v4 import FalseBreakoutFilter
        df = synthetic_df(100)
        result = FalseBreakoutFilter.detect(df, direction=1)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_detect_returns_bool_and_score(self):
        from brain_v4 import FalseBreakoutFilter
        df = synthetic_df(100)
        is_false, score = FalseBreakoutFilter.detect(df, direction=1)
        assert isinstance(is_false, bool)
        assert isinstance(score, (int, float))

    def test_detect_with_small_data(self):
        from brain_v4 import FalseBreakoutFilter
        df = synthetic_df(10)
        result = FalseBreakoutFilter.detect(df, direction=1)
        assert isinstance(result, tuple)
