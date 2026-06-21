"""LightGBM gradient boosted model for price direction prediction.

Provides train/predict/save/load with walk-forward validation support
and feature importance tracking.
"""
import os
import json
import logging
import numpy as np
import threading
from config import DATA_DIR

logger = logging.getLogger(__name__)

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False
    logger.warning("lightgbm not installed — ML model disabled")


class LightGBMModel:
    """LightGBM binary classifier for next-bar direction prediction.

    Predicts: 1 (up/buy), -1 (down/sell), 0 (hold).
    Internally uses one-vs-rest with probability calibration.
    """

    def __init__(self, model_path=None):
        self.model_path = model_path or os.path.join(DATA_DIR, "ml_model.json")
        self.model = None
        self.feature_names = []
        self.feature_importance = {}
        self.class_names = {1: "buy", -1: "sell", 0: "hold"}
        self.train_metrics = {}
        self._lock = threading.Lock()

    def train(self, X, y, feature_names=None, params=None, num_boost_round=200,
              valid_fraction=0.15):
        """Train LightGBM model.

        Args:
            X: numpy array (n_samples, n_features)
            y: numpy array (n_samples,) with labels in {-1, 0, 1}
            feature_names: list of feature names
            params: dict of LightGBM parameters (overrides defaults)
            num_boost_round: number of boosting rounds
            valid_fraction: fraction of data to use as validation

        Returns:
            dict with training metrics
        """
        if not HAS_LIGHTGBM:
            return {"error": "lightgbm not installed"}

        if len(X) < 50:
            return {"error": "insufficient training data", "samples": len(X)}

        if feature_names:
            self.feature_names = list(feature_names)

        # Split into train/valid
        n = len(X)
        n_valid = max(int(n * valid_fraction), 10)
        X_train, X_valid = X[:-n_valid], X[-n_valid:]
        y_train, y_valid = y[:-n_valid], y[-n_valid:]

        # LightGBM binary classification: map labels to {0, 1}
        # We train separate models for buy (vs rest) and sell (vs rest)
        # But for simplicity, use multiclass with LabelEncoder
        unique_labels = np.unique(y)
        if len(unique_labels) < 2:
            return {"error": "only one class in labels", "class_counts": {str(unique_labels[0]): len(y)}}

        # Map labels to 0, 1, 2 for LightGBM
        label_map = {}
        for i, label in enumerate(sorted(unique_labels)):
            label_map[int(label)] = i
        y_train_mapped = np.array([label_map[int(v)] for v in y_train], dtype=np.int32)
        y_valid_mapped = np.array([label_map[int(v)] for v in y_valid], dtype=np.int32)

        default_params = {
            "objective": "multiclass",
            "num_class": len(label_map),
            "metric": "multi_logloss",
            "boosting_type": "gbdt",
            "num_leaves": 31,
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "min_child_samples": 20,
            "reg_alpha": 0.1,
            "reg_lambda": 0.1,
            "verbose": -1,
            "n_jobs": -1,
            "seed": 42,
        }
        if params:
            default_params.update(params)

        dtrain = lgb.Dataset(X_train, label=y_train_mapped,
                             feature_name=self.feature_names if self.feature_names else "auto")
        dvalid = lgb.Dataset(X_valid, label=y_valid_mapped,
                             feature_name=self.feature_names if self.feature_names else "auto",
                             reference=dtrain)

        callbacks = [lgb.log_evaluation(period=0)]

        self.model = lgb.train(
            default_params,
            dtrain,
            num_boost_round=num_boost_round,
            valid_sets=[dvalid],
            callbacks=callbacks,
        )

        # Feature importance
        importance = self.model.feature_importance(importance_type="gain")
        if self.feature_names and len(self.feature_names) == len(importance):
            self.feature_importance = dict(zip(self.feature_names, importance.tolist()))
        else:
            self.feature_importance = {f"f{i}": float(importance[i]) for i in range(len(importance))}

        # Validation metrics
        valid_pred = self.model.predict(X_valid)
        valid_pred_indices = np.array([np.argmax(p) for p in valid_pred])
        inverse_map = {v: k for k, v in label_map.items()}
        valid_pred_labels = np.array([inverse_map[idx] for idx in valid_pred_indices])
        accuracy = float(np.mean(valid_pred_labels == y_valid))

        # Per-class accuracy
        class_metrics = {}
        for label_val, label_idx in label_map.items():
            mask = y_valid == label_val
            if mask.sum() > 0:
                class_acc = float(np.mean(valid_pred_labels[mask] == label_val))
                class_metrics[self.class_names.get(label_val, str(label_val))] = {
                    "accuracy": round(class_acc, 4),
                    "count": int(mask.sum()),
                }

        # Inverse label map for prediction
        self._inverse_label_map = {v: k for k, v in label_map.items()}

        self.train_metrics = {
            "samples": len(X_train),
            "valid_samples": len(X_valid),
            "accuracy": round(accuracy, 4),
            "class_metrics": class_metrics,
            "num_boost_round": num_boost_round,
            "n_features": X.shape[1],
            "n_classes": len(label_map),
        }

        logger.info("LightGBM trained: accuracy=%.4f, samples=%d", accuracy, len(X_train))
        return self.train_metrics

    def predict(self, X):
        """Predict class probabilities.

        Args:
            X: numpy array (n_samples, n_features) or (n_features,)

        Returns:
            numpy array of shape (n_samples, 3) with probabilities for [sell, hold, buy]
            or dict with 'action' and 'confidence' for single sample
        """
        if self.model is None:
            return None

        single = False
        if X.ndim == 1:
            X = X.reshape(1, -1)
            single = True

        # Handle NaN — fill with 0
        X = np.nan_to_num(X, nan=0.0)

        # Handle feature count mismatch: pad with zeros or truncate
        model_n_features = self.model.num_feature()
        input_n_features = X.shape[1]
        if input_n_features < model_n_features:
            # Pad with zeros
            pad = np.zeros((X.shape[0], model_n_features - input_n_features), dtype=np.float64)
            X = np.concatenate([X, pad], axis=1)
            logger.debug("Predict: padded features %d -> %d", input_n_features, model_n_features)
        elif input_n_features > model_n_features:
            # Truncate extra features
            X = X[:, :model_n_features]
            logger.debug("Predict: truncated features %d -> %d", input_n_features, model_n_features)

        probs = self.model.predict(X)

        if single:
            p = probs[0]
            inv_map = self._inverse_label_map if hasattr(self, "_inverse_label_map") else {0: 0, 1: 1, 2: -1}
            max_idx = int(np.argmax(p))
            predicted_label = inv_map.get(max_idx, 0)
            confidence = float(p[max_idx])
            action = "buy" if predicted_label == 1 else "sell" if predicted_label == -1 else "hold"
            probs_dict = {}
            for idx, label in inv_map.items():
                name = "buy" if label == 1 else "sell" if label == -1 else "hold"
                probs_dict[name] = round(float(p[idx]), 4)
            return {"action": action, "confidence": round(confidence, 4), "probabilities": probs_dict}

        return probs

    def predict_signal(self, X, min_confidence=0.45):
        """Generate trading signal from prediction.

        Args:
            X: feature vector (1D) or matrix
            min_confidence: minimum confidence to generate a non-hold signal

        Returns:
            dict with 'action' (buy/sell/hold), 'confidence', 'sl_pips', 'tp_pips'
        """
        pred = self.predict(X)
        if pred is None:
            return {"action": "hold", "confidence": 0, "sl_pips": 50, "tp_pips": 100}

        if isinstance(pred, dict):
            action = pred["action"]
            confidence = pred["confidence"]
        else:
            action = "hold"
            confidence = 0

        if confidence < min_confidence or action == "hold":
            return {"action": "hold", "confidence": round(confidence, 4), "sl_pips": 50, "tp_pips": 100}

        return {
            "action": action,
            "confidence": round(confidence, 4),
            "sl_pips": 50,
            "tp_pips": 100,
        }

    def get_feature_importance(self, top_n=15):
        """Get top N features by importance.

        Returns:
            list of (feature_name, importance_value) tuples, sorted descending
        """
        if not self.feature_importance:
            return []
        sorted_features = sorted(self.feature_importance.items(), key=lambda x: x[1], reverse=True)
        return sorted_features[:top_n]

    def save(self, path=None):
        """Save model to disk as JSON (LightGBM native format).

        Also saves metadata (feature names, importance, metrics) alongside.
        """
        save_path = path or self.model_path
        if self.model is None:
            return False

        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # Save LightGBM model
        model_dir = save_path.replace(".json", "")
        self.model.save_model(save_path)

        # Save metadata
        meta = {
            "feature_names": self.feature_names,
            "feature_importance": self.feature_importance,
            "train_metrics": self.train_metrics,
            "inverse_label_map": {str(k): v for k, v in self._inverse_label_map.items()} if hasattr(self, "_inverse_label_map") else {},
            "class_names": {str(k): v for k, v in self.class_names.items()},
        }
        meta_path = save_path.replace(".json", "_meta.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2, default=str)

        logger.info("LightGBM model saved to %s", save_path)
        return True

    def load(self, path=None):
        """Load model from disk.

        Returns:
            True if loaded successfully, False otherwise
        """
        load_path = path or self.model_path
        if not HAS_LIGHTGBM:
            return False
        if not os.path.exists(load_path):
            return False

        try:
            self.model = lgb.Booster(model_file=load_path)

            meta_path = load_path.replace(".json", "_meta.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                self.feature_names = meta.get("feature_names", [])
                self.feature_importance = meta.get("feature_importance", {})
                self.train_metrics = meta.get("train_metrics", {})
                inv_map = meta.get("inverse_label_map", {})
                self._inverse_label_map = {int(k): v for k, v in inv_map.items()} if inv_map else {}
                self.class_names = {int(k): v for k, v in meta.get("class_names", {}).items()}

            logger.info("LightGBM model loaded from %s", load_path)
            return True
        except Exception as e:
            logger.error("Failed to load LightGBM model: %s", e)
            return False

    def is_trained(self):
        """Check if model is loaded and ready for prediction."""
        return self.model is not None


_lightgbm_model = None
_lightgbm_lock = threading.Lock()


def get_lightgbm_model(model_path=None):
    """Get singleton LightGBMModel instance."""
    global _lightgbm_model
    if _lightgbm_model is None:
        with _lightgbm_lock:
            if _lightgbm_model is None:
                _lightgbm_model = LightGBMModel(model_path)
                _lightgbm_model.load()
    return _lightgbm_model
