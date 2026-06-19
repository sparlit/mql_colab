"""Tests for LightGBM ML pipeline: features, model, training, integration."""
import sys
import os
import json
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.conftest import synthetic_df
from ml_features import FEATURE_NAMES


# ==========================================
# ml_features tests
# ==========================================
class TestMLFeatures:
    def test_compute_features_returns_dict(self):
        from ml_features import compute_features
        df = synthetic_df(n=200)
        features = compute_features(df)
        assert isinstance(features, dict)
        assert len(features) > 20

    def test_compute_features_insufficient_data(self):
        from ml_features import compute_features
        df = synthetic_df(n=10)
        features = compute_features(df)
        assert features is None

    def test_compute_features_has_all_expected_keys(self):
        from ml_features import compute_features, FEATURE_NAMES
        df = synthetic_df(n=200)
        features = compute_features(df)
        for name in FEATURE_NAMES:
            assert name in features, f"Missing feature: {name}"

    def test_compute_features_no_nan(self):
        from ml_features import compute_features
        df = synthetic_df(n=200)
        features = compute_features(df)
        for k, v in features.items():
            assert not np.isnan(v), f"NaN in feature: {k}"

    def test_compute_target_labels(self):
        from ml_features import compute_target
        df = synthetic_df(n=200)
        labels = compute_target(df, forward_bars=3, threshold_pct=0.01)
        assert len(labels) == 200
        assert set(np.unique(labels)).issubset({-1, 0, 1})
        assert labels[-1] == 0
        assert labels[-2] == 0
        assert labels[-3] == 0

    def test_build_dataset_shapes(self):
        from ml_features import build_dataset
        df = synthetic_df(n=500)
        X, y, names = build_dataset(df, forward_bars=3, threshold_pct=0.01)
        assert X.shape[0] > 0
        assert X.shape[1] == len(names)
        assert y.shape[0] == X.shape[0]
        assert set(np.unique(y)).issubset({-1, 1})

    def test_build_dataset_no_nan(self):
        from ml_features import build_dataset
        df = synthetic_df(n=500)
        X, y, names = build_dataset(df)
        assert not np.isnan(X).any()

    def test_compute_macd(self):
        from ml_features import compute_macd
        close = np.cumsum(np.random.randn(100) * 0.0005) + 1.1
        macd, signal, hist = compute_macd(close)
        assert len(macd) == 100
        assert len(signal) == 100
        assert len(hist) == 100
        assert not np.isnan(macd[-1])

    def test_compute_stochastic(self):
        from ml_features import compute_stochastic
        n = 100
        h = np.random.randn(n) * 0.001 + 1.101
        l = np.random.randn(n) * 0.001 + 1.099
        c = np.random.randn(n) * 0.0005 + 1.1
        k, d = compute_stochastic(h, l, c)
        assert len(k) == n
        assert len(d) == n

    def test_encode_session(self):
        from ml_features import encode_session
        from datetime import datetime, timezone
        dt_london = datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc)
        l, n, a = encode_session(dt_london)
        assert l == 1
        assert n == 0
        assert a == 0

    def test_encode_cyclical(self):
        from ml_features import encode_cyclical
        sin0, cos0 = encode_cyclical(0, 24)
        sin12, cos12 = encode_cyclical(12, 24)
        assert abs(sin0) < 0.01
        assert abs(cos0 - 1.0) < 0.01
        assert abs(sin12) < 0.01
        assert abs(cos12 + 1.0) < 0.01


# ==========================================
# ml_model tests
# ==========================================
class TestLightGBMModel:
    def test_import(self):
        from ml_model import LightGBMModel, HAS_LIGHTGBM
        assert HAS_LIGHTGBM is True

    def test_train_and_predict(self):
        from ml_model import LightGBMModel
        np.random.seed(42)
        n = 500
        X = np.random.randn(n, 10)
        y = (X[:, 0] + X[:, 1] * 0.5 > 0).astype(int) * 2 - 1
        y[np.abs(X[:, 2]) < 0.3] = 0

        model = LightGBMModel()
        metrics = model.train(X, y, num_boost_round=50)
        assert "error" not in metrics
        assert "accuracy" in metrics
        assert metrics["accuracy"] > 0.3

    def test_predict_returns_dict(self):
        from ml_model import LightGBMModel
        np.random.seed(42)
        n = 500
        X = np.random.randn(n, 10)
        y = (X[:, 0] > 0).astype(int) * 2 - 1
        y[np.abs(X[:, 2]) < 0.3] = 0

        model = LightGBMModel()
        model.train(X, y, num_boost_round=50)
        pred = model.predict(X[0])
        assert isinstance(pred, dict)
        assert "action" in pred
        assert "confidence" in pred
        assert pred["action"] in ("buy", "sell", "hold")

    def test_predict_signal(self):
        from ml_model import LightGBMModel
        np.random.seed(42)
        n = 500
        X = np.random.randn(n, 10)
        y = (X[:, 0] > 0).astype(int) * 2 - 1
        y[np.abs(X[:, 2]) < 0.3] = 0

        model = LightGBMModel()
        model.train(X, y, num_boost_round=50)
        signal = model.predict_signal(X[0])
        assert "action" in signal
        assert "sl_pips" in signal
        assert "tp_pips" in signal

    def test_save_and_load(self, tmp_path):
        from ml_model import LightGBMModel
        np.random.seed(42)
        n = 500
        X = np.random.randn(n, 10)
        y = (X[:, 0] > 0).astype(int) * 2 - 1
        y[np.abs(X[:, 2]) < 0.3] = 0

        model = LightGBMModel()
        model.train(X, y, num_boost_round=50, feature_names=[f"f{i}" for i in range(10)])

        save_path = str(tmp_path / "test_model.json")
        model.save(save_path)
        assert os.path.exists(save_path)
        assert os.path.exists(save_path.replace(".json", "_meta.json"))

        model2 = LightGBMModel(model_path=save_path)
        loaded = model2.load(save_path)
        assert loaded is True
        assert model2.is_trained()

    def test_feature_importance(self):
        from ml_model import LightGBMModel
        np.random.seed(42)
        n = 500
        X = np.random.randn(n, 10)
        y = (X[:, 0] > 0).astype(int) * 2 - 1

        model = LightGBMModel()
        model.train(X, y, num_boost_round=50, feature_names=[f"f{i}" for i in range(10)])
        importance = model.get_feature_importance(top_n=5)
        assert len(importance) == 5
        assert importance[0][1] >= importance[-1][1]

    def test_train_insufficient_data(self):
        from ml_model import LightGBMModel
        X = np.random.randn(10, 5)
        y = np.array([1, -1] * 5)
        model = LightGBMModel()
        result = model.train(X, y)
        assert "error" in result

    def test_predict_without_training(self):
        from ml_model import LightGBMModel
        model = LightGBMModel()
        pred = model.predict(np.zeros(10))
        assert pred is None


# ==========================================
# train_ml tests
# ==========================================
class TestTrainML:
    def test_train_lightgbm_walk_forward(self):
        from train_ml import train_lightgbm_walk_forward
        df = synthetic_df(n=600)
        result = train_lightgbm_walk_forward(
            df, n_windows=2, num_boost_round=30, forward_bars=3, threshold_pct=0.01,
        )
        if "error" not in result:
            assert result["valid_windows"] >= 1
            assert "avg_accuracy" in result
            assert "avg_test_sharpe" in result
            assert "windows" in result

    def test_train_returns_error_on_small_data(self):
        from train_ml import train_lightgbm_walk_forward
        df = synthetic_df(n=50)
        result = train_lightgbm_walk_forward(df)
        assert "error" in result

    def test_split_walk_forward(self):
        from train_ml import _split_walk_forward
        splits = _split_walk_forward(1000, n_windows=5, train_pct=0.7)
        assert len(splits) >= 3
        for s in splits:
            assert s["train"][1] < s["test"][0]
            assert s["train"][0] < s["train"][1]

    def test_compute_sharpe(self):
        from train_ml import _compute_sharpe
        assert _compute_sharpe([]) == 0.0
        assert _compute_sharpe([10]) == 0.0
        sharpe = _compute_sharpe([100, -50, 80, -30, 60])
        assert isinstance(sharpe, float)


# ==========================================
# run_backtest LGBM integration tests
# ==========================================
class TestRunBacktestLGBM:
    def test_generate_lgbm_signals_length(self, mock_mt5):
        from run_backtest import _generate_lgbm_signals
        from ml_model import LightGBMModel
        np.random.seed(42)
        n = 200
        X = np.random.randn(500, len(FEATURE_NAMES))
        y = np.random.choice([-1, 0, 1], size=500)
        model = LightGBMModel()
        model.train(X, y, feature_names=FEATURE_NAMES, num_boost_round=20)

        df = synthetic_df(n=n)
        signals = _generate_lgbm_signals(df, model, sl_pips=50, tp_pips=100, progress_interval=0)
        assert len(signals) == n
        assert "action" in signals[-1]

    @patch("run_backtest.fetch_historical_data")
    def test_run_full_backtest_includes_lgbm(self, mock_fetch, mock_mt5):
        from run_backtest import run_full_backtest
        df = synthetic_df(n=500)
        mock_fetch.return_value = df
        report = run_full_backtest(months=12)
        assert "backtest" in report
        assert "lgbm_skipped" in report or "lgbm_backtest" in report
