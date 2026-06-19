"""Enhanced feature engineering for ML training pipeline.

Extends FeatureStore with additional features: MACD, BB width, volume profile,
session encoding, ATR ratio, and target variable generation.
"""
import numpy as np
import logging
from datetime import datetime, timezone
from indicators import ema

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    "price_return_1", "price_return_5", "price_return_10",
    "volatility_10", "volatility_20",
    "high_low_range", "close_position",
    "volume_ratio", "momentum_5", "momentum_10",
    "ema_spread", "rsi", "bb_position",
    "atr", "atr_ratio",
    "macd", "macd_signal", "macd_histogram",
    "bb_width", "stoch_k", "stoch_d",
    "session_london", "session_newyork", "session_asian",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "volume_sma_ratio", "price_range_position",
    "consecutive_up", "consecutive_down",
]


def compute_macd(close, fast=12, slow=26, signal_period=9):
    """Compute MACD, signal line, and histogram."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_stochastic(high, low, close, k_period=14, d_period=3):
    """Compute Stochastic %K and %D."""
    n = len(close)
    stoch_k = np.zeros(n)
    for i in range(k_period - 1, n):
        h = np.max(high[i - k_period + 1:i + 1])
        l = np.min(low[i - k_period + 1:i + 1])
        if h != l:
            stoch_k[i] = (close[i] - l) / (h - l) * 100
        else:
            stoch_k[i] = 50.0
    stoch_d = np.zeros(n)
    for i in range(d_period - 1, n):
        stoch_d[i] = np.mean(stoch_k[i - d_period + 1:i + 1])
    return stoch_k, stoch_d


def encode_session(dt):
    """One-hot encode trading session: london, newyork, asian."""
    hour = dt.hour
    london = 1 if 7 <= hour < 16 else 0
    newyork = 1 if 12 <= hour < 21 else 0
    asian = 1 if hour < 8 or hour >= 21 else 0
    return london, newyork, asian


def encode_cyclical(value, max_val):
    """Encode cyclical feature (hour, day of week) as sin/cos pair."""
    sin_val = np.sin(2 * np.pi * value / max_val)
    cos_val = np.cos(2 * np.pi * value / max_val)
    return sin_val, cos_val


def compute_features(df):
    """Compute all ML features from OHLCV DataFrame.

    Returns dict of feature_name -> value, or None if insufficient data.
    """
    if df is None or len(df) < 50:
        return None

    c = df["close"].values.astype(np.float64)
    h = df["high"].values.astype(np.float64)
    l = df["low"].values.astype(np.float64)
    v = df["tick_volume"].values.astype(np.float64) if "tick_volume" in df.columns else np.ones(len(c))
    n = len(c)

    features = {}

    # Price returns
    features["price_return_1"] = (c[-1] - c[-2]) / c[-2] * 100 if c[-2] != 0 else 0
    features["price_return_5"] = (c[-1] - c[-5]) / c[-5] * 100 if n > 5 and c[-5] != 0 else 0
    features["price_return_10"] = (c[-1] - c[-10]) / c[-10] * 100 if n > 10 and c[-10] != 0 else 0

    # Volatility
    features["volatility_10"] = float(np.std(np.diff(c[-10:]) / c[-10:-1]) * 100) if n > 10 else 0
    features["volatility_20"] = float(np.std(np.diff(c[-20:]) / c[-20:-1]) * 100) if n > 20 else 0

    # Price structure
    features["high_low_range"] = (h[-1] - l[-1]) / c[-1] * 100 if c[-1] != 0 else 0
    features["close_position"] = (c[-1] - l[-20]) / (h[-20] - l[-20]) if (h[-20] - l[-20]) > 0 else 0.5

    # Volume
    vol_mean20 = float(np.mean(v[-20:])) if n > 20 else 1
    features["volume_ratio"] = v[-1] / vol_mean20 if vol_mean20 > 0 else 1

    # Volume SMA ratio (volume vs 50-bar average)
    vol_mean50 = float(np.mean(v[-50:])) if n > 50 else vol_mean20
    features["volume_sma_ratio"] = v[-1] / vol_mean50 if vol_mean50 > 0 else 1

    # Momentum
    features["momentum_5"] = c[-1] - c[-5] if n > 5 else 0
    features["momentum_10"] = c[-1] - c[-10] if n > 10 else 0

    # EMA spread
    ema5 = ema(c, 5)
    ema20 = ema(c, 20)
    features["ema_spread"] = (ema5[-1] - ema20[-1]) / c[-1] * 100 if c[-1] != 0 else 0

    # RSI
    delta = np.diff(c, prepend=c[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = float(np.mean(gain[-14:]))
    avg_loss = float(np.mean(loss[-14:]))
    rs = avg_gain / max(avg_loss, 1e-10)
    features["rsi"] = 100 - (100 / (1 + rs))

    # Bollinger Bands position + width
    bb_ma = float(np.mean(c[-20:]))
    bb_std = float(np.std(c[-20:]))
    features["bb_position"] = (c[-1] - (bb_ma - 2 * bb_std)) / (4 * bb_std) if bb_std > 0 else 0.5
    features["bb_width"] = (4 * bb_std) / bb_ma * 100 if bb_ma != 0 else 0

    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr_14 = float(np.mean(tr[-14:]))
    atr_50 = float(np.mean(tr[-50:])) if n > 50 else atr_14
    features["atr"] = atr_14
    features["atr_ratio"] = atr_14 / atr_50 if atr_50 > 0 else 1

    # MACD
    macd_line, signal_line, histogram = compute_macd(c)
    features["macd"] = float(macd_line[-1])
    features["macd_signal"] = float(signal_line[-1])
    features["macd_histogram"] = float(histogram[-1])

    # Stochastic
    stoch_k, stoch_d = compute_stochastic(h, l, c)
    features["stoch_k"] = float(stoch_k[-1])
    features["stoch_d"] = float(stoch_d[-1])

    # Session encoding
    now = datetime.now(timezone.utc)
    london, newyork, asian = encode_session(now)
    features["session_london"] = london
    features["session_newyork"] = newyork
    features["session_asian"] = asian

    # Cyclical time encoding
    hour_sin, hour_cos = encode_cyclical(now.hour, 24)
    dow_sin, dow_cos = encode_cyclical(now.weekday(), 7)
    features["hour_sin"] = hour_sin
    features["hour_cos"] = hour_cos
    features["dow_sin"] = dow_sin
    features["dow_cos"] = dow_cos

    # Price range position (where is price in last 50-bar range)
    if n > 50:
        range_high = float(np.max(h[-50:]))
        range_low = float(np.min(l[-50:]))
        features["price_range_position"] = (c[-1] - range_low) / (range_high - range_low) if (range_high - range_low) > 0 else 0.5
    else:
        features["price_range_position"] = 0.5

    # Consecutive direction
    up_count = 0
    down_count = 0
    for i in range(n - 1, max(n - 11, 0), -1):
        if c[i] > c[i - 1]:
            if down_count > 0:
                break
            up_count += 1
        elif c[i] < c[i - 1]:
            if up_count > 0:
                break
            down_count += 1
        else:
            break
    features["consecutive_up"] = up_count
    features["consecutive_down"] = down_count

    return features


def compute_features_batch(df):
    """Compute features for every bar in a DataFrame.

    Returns numpy array of shape (n_bars, n_features) and feature names list.
    Rows before warmup period (first 50 bars) are filled with NaN.
    """
    n = len(df)
    features_list = []
    for i in range(n):
        if i < 49:
            features_list.append(None)
        else:
            window = df.iloc[max(0, i - 200):i + 1].copy()
            feat = compute_features(window)
            if feat is not None:
                features_list.append(feat)
            else:
                features_list.append(None)

    names = list(FEATURE_NAMES)
    result = np.full((n, len(names)), np.nan, dtype=np.float64)
    for i, feat in enumerate(features_list):
        if feat is not None:
            for j, name in enumerate(names):
                result[i, j] = feat.get(name, 0.0)

    return result, names


def compute_target(df, forward_bars=3, threshold_pct=0.01):
    """Compute target variable: next-bar direction.

    Args:
        df: OHLCV DataFrame
        forward_bars: number of bars to look forward for return
        threshold_pct: minimum return % to label as buy/sell (otherwise hold)

    Returns:
        numpy array of labels: 1 (buy/up), -1 (sell/down), 0 (hold/flat)
    """
    c = df["close"].values.astype(np.float64)
    n = len(c)
    labels = np.zeros(n, dtype=np.int32)

    for i in range(n - forward_bars):
        future_return = (c[i + forward_bars] - c[i]) / c[i] * 100 if c[i] != 0 else 0
        if future_return > threshold_pct:
            labels[i] = 1
        elif future_return < -threshold_pct:
            labels[i] = -1
        else:
            labels[i] = 0

    # Last forward_bars rows have no target
    labels[n - forward_bars:] = 0
    return labels


def build_dataset(df, forward_bars=3, threshold_pct=0.01):
    """Build complete feature matrix + labels from OHLCV DataFrame.

    Returns:
        X: numpy array (n_samples, n_features) — NaN rows filtered out
        y: numpy array (n_samples,) — labels
        feature_names: list of feature names
    """
    X_full, feature_names = compute_features_batch(df)
    y_full = compute_target(df, forward_bars, threshold_pct)

    valid_mask = ~np.isnan(X_full).any(axis=1) & (y_full != 0)
    X = X_full[valid_mask]
    y = y_full[valid_mask]

    return X, y, feature_names
