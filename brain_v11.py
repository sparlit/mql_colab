"""
Brain V11 - Autonomous Meta-Brain Orchestrator
Detects market regime and dynamically selects optimal trading method.
Wraps all 10 existing brains plus 11 trading method engines.
"""
import MetaTrader5 as mt5
import numpy as np
import threading
import copy
import logging
from datetime import datetime, timezone
from collections import deque
from enum import Enum
from config import (
    MAGIC_SCALPING, MAGIC_DAY_TRADING, MAGIC_SWING, MAGIC_POSITION,
    MAGIC_TECHNICAL, MAGIC_FUNDAMENTAL, MAGIC_SENTIMENT, MAGIC_TREND,
    MAGIC_COUNTER_TREND, MAGIC_BREAKOUT, MAGIC_RANGE, MAGIC_TMC,
)
from indicators import is_tradeable_now, fetch_closed_rates, get_current_session, ema
from alternative_data import SatelliteDataAnalyzer
from market_intelligence import SentimentFeed
from strategies_advanced import MarketMaker, ArbitrageEngine

logger = logging.getLogger(__name__)

# ==========================================
# TRADING METHODS
# ==========================================
class TradingMethod(Enum):
    SCALPING = "scalping"
    DAY_TRADING = "day_trading"
    SWING_TRADING = "swing_trading"
    POSITION_TRADING = "position_trading"
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    TREND_FOLLOWING = "trend_following"
    COUNTER_TREND = "counter_trend"
    BREAKOUT = "breakout"
    RANGE_TRADING = "range_trading"
    TMC = "tmc"  # Trend Momentum Continuation

# Active methods whitelist (scalping mode)
ACTIVE_METHODS = [TradingMethod.SCALPING, TradingMethod.DAY_TRADING]

# Method configurations
METHOD_CONFIGS = {
    TradingMethod.SCALPING: {
        "timeframes": [mt5.TIMEFRAME_M1, mt5.TIMEFRAME_M5],
        "hold_min": 1, "hold_max": 30,
        "sl_atr_mult": 0.8, "tp_atr_mult": 1.5,
        "min_confidence": 0.70, "max_spread": 10,
        "risk_per_trade": 0.25, "max_positions": 3,
        "description": "M1-M5 momentum/mean-reversion, tight TP/SL",
    },
    TradingMethod.DAY_TRADING: {
        "timeframes": [mt5.TIMEFRAME_M5, mt5.TIMEFRAME_M15, mt5.TIMEFRAME_M1],
        "hold_min": 30, "hold_max": 480,
        "sl_atr_mult": 1.2, "tp_atr_mult": 2.5,
        "min_confidence": 0.60, "max_spread": 15,
        "risk_per_trade": 1.0, "max_positions": 2,
        "description": "M5-H1 breakout/pullback, EOD close",
    },
    TradingMethod.SWING_TRADING: {
        "timeframes": [mt5.TIMEFRAME_H1, mt5.TIMEFRAME_H4, mt5.TIMEFRAME_M15],
        "hold_min": 1440, "hold_max": 10080,
        "sl_atr_mult": 1.5, "tp_atr_mult": 3.0,
        "min_confidence": 0.55, "max_spread": 20,
        "risk_per_trade": 1.5, "max_positions": 2,
        "description": "H1-H4 S/R bounces, trend continuation",
    },
    TradingMethod.POSITION_TRADING: {
        "timeframes": [mt5.TIMEFRAME_H4, mt5.TIMEFRAME_D1],
        "hold_min": 10080, "hold_max": 43200,
        "sl_atr_mult": 2.0, "tp_atr_mult": 4.0,
        "min_confidence": 0.50, "max_spread": 25,
        "risk_per_trade": 2.0, "max_positions": 1,
        "description": "H4-D1 fundamental + trend, wide SL",
    },
    TradingMethod.TECHNICAL: {
        "timeframes": [mt5.TIMEFRAME_M1, mt5.TIMEFRAME_M5, mt5.TIMEFRAME_M15, mt5.TIMEFRAME_H1],
        "hold_min": 5, "hold_max": 1440,
        "sl_atr_mult": 1.5, "tp_atr_mult": 2.5,
        "min_confidence": 0.55, "max_spread": 20,
        "risk_per_trade": 1.0, "max_positions": 3,
        "description": "Indicator-based across timeframes",
    },
    TradingMethod.FUNDAMENTAL: {
        "timeframes": [mt5.TIMEFRAME_H4, mt5.TIMEFRAME_D1],
        "hold_min": 2880, "hold_max": 43200,
        "sl_atr_mult": 2.5, "tp_atr_mult": 5.0,
        "min_confidence": 0.50, "max_spread": 25,
        "risk_per_trade": 2.0, "max_positions": 1,
        "description": "Economic calendar + COT data driven",
    },
    TradingMethod.SENTIMENT: {
        "timeframes": [mt5.TIMEFRAME_M15, mt5.TIMEFRAME_H1],
        "hold_min": 60, "hold_max": 4320,
        "sl_atr_mult": 1.5, "tp_atr_mult": 2.5,
        "min_confidence": 0.55, "max_spread": 20,
        "risk_per_trade": 1.0, "max_positions": 2,
        "description": "News sentiment + positioning analysis",
    },
    TradingMethod.TREND_FOLLOWING: {
        "timeframes": [mt5.TIMEFRAME_H1, mt5.TIMEFRAME_H4, mt5.TIMEFRAME_D1],
        "hold_min": 1440, "hold_max": 43200,
        "sl_atr_mult": 1.8, "tp_atr_mult": 3.5,
        "min_confidence": 0.55, "max_spread": 20,
        "risk_per_trade": 1.5, "max_positions": 2,
        "description": "Moving averages + ADX trend confirmation",
    },
    TradingMethod.COUNTER_TREND: {
        "timeframes": [mt5.TIMEFRAME_M5, mt5.TIMEFRAME_M15, mt5.TIMEFRAME_H1],
        "hold_min": 15, "hold_max": 1440,
        "sl_atr_mult": 1.0, "tp_atr_mult": 2.0,
        "min_confidence": 0.60, "max_spread": 15,
        "risk_per_trade": 0.8, "max_positions": 2,
        "description": "RSI/BB extremes + divergence",
    },
    TradingMethod.BREAKOUT: {
        "timeframes": [mt5.TIMEFRAME_M15, mt5.TIMEFRAME_H1],
        "hold_min": 30, "hold_max": 4320,
        "sl_atr_mult": 1.2, "tp_atr_mult": 2.5,
        "min_confidence": 0.60, "max_spread": 15,
        "risk_per_trade": 1.0, "max_positions": 2,
        "description": "Range breakout + volume confirmation",
    },
    TradingMethod.RANGE_TRADING: {
        "timeframes": [mt5.TIMEFRAME_M5, mt5.TIMEFRAME_M15, mt5.TIMEFRAME_H1],
        "hold_min": 15, "hold_max": 480,
        "sl_atr_mult": 0.8, "tp_atr_mult": 1.5,
        "min_confidence": 0.55, "max_spread": 15,
        "risk_per_trade": 0.8, "max_positions": 3,
        "description": "Bollinger + S/R fade at band edges",
    },
    TradingMethod.TMC: {
        "timeframes": [mt5.TIMEFRAME_M5, mt5.TIMEFRAME_M15, mt5.TIMEFRAME_H1, mt5.TIMEFRAME_H4],
        "hold_min": 60, "hold_max": 14400,
        "sl_atr_mult": 1.5, "tp_atr_mult": 3.0,
        "min_confidence": 0.58, "max_spread": 20,
        "risk_per_trade": 1.2, "max_positions": 2,
        "description": "Trend Momentum Continuation - enter on pullback within confirmed trend with momentum confirmation",
    },
}

# ==========================================
# REGIME CLASSIFIER
# ==========================================
class RegimeClassifier:
    def __init__(self):
        self._lock = threading.Lock()
        self.history = deque(maxlen=500)

    def classify(self, df, symbol):
        if df is None or len(df) < 50:
            return {"regime": "unknown", "confidence": 0, "details": {}}

        c = df['close'].values
        h = df['high'].values
        l = df['low'].values

        # Trend strength via ADX proxy
        ema20 = self._ema(c, 20)
        ema50 = self._ema(c, 50)
        ema200 = self._ema(c, 200) if len(c) >= 200 else None

        trend_alignment = 0
        if ema200 is not None:
            if ema20[-1] > ema50[-1] > ema200[-1]:
                trend_alignment = 1.0
            elif ema20[-1] < ema50[-1] < ema200[-1]:
                trend_alignment = -1.0
            elif ema20[-1] > ema50[-1]:
                trend_alignment = 0.5
            elif ema20[-1] < ema50[-1]:
                trend_alignment = -0.5
        else:
            if ema20[-1] > ema50[-1]:
                trend_alignment = 0.5
            elif ema20[-1] < ema50[-1]:
                trend_alignment = -0.5

        # Volatility via ATR
        tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
        tr[0] = h[0] - l[0]
        atr = np.mean(tr[-14:])
        atr_pct = atr / c[-1] * 100 if c[-1] > 0 else 0

        # Range measurement
        high_20 = np.max(h[-20:])
        low_20 = np.min(l[-20:])
        range_pct = (high_20 - low_20) / c[-1] * 100 if c[-1] > 0 else 0

        # Volatility regime
        if atr_pct > 0.15:
            vol_regime = "high"
        elif atr_pct < 0.05:
            vol_regime = "low"
        else:
            vol_regime = "normal"

        # Determine regime
        abs_trend = abs(trend_alignment)
        if abs_trend > 0.7:
            if vol_regime == "high":
                regime = "strong_trend_high_vol"
            else:
                regime = "strong_trend_normal_vol"
            confidence = min(abs_trend * 1.2, 1.0)
        elif abs_trend > 0.3:
            regime = "weak_trend"
            confidence = abs_trend
        elif range_pct < 0.3:
            regime = "tight_range"
            confidence = 0.8
        elif vol_regime == "high":
            regime = "volatile_no_trend"
            confidence = 0.7
        else:
            regime = "choppy"
            confidence = 0.5

        result = {
            "regime": regime,
            "confidence": confidence,
            "trend_alignment": trend_alignment,
            "vol_regime": vol_regime,
            "atr_pct": atr_pct,
            "range_pct": range_pct,
        }
        self.history.append(result)
        return result

    @staticmethod
    def _ema(data, span):
        if len(data) < span:
            return np.full_like(data, np.mean(data), dtype=np.float64)
        return ema(data, span)


# ==========================================
# METHOD SELECTOR
# ==========================================
class MethodSelector:
    def __init__(self):
        self._lock = threading.Lock()
        self.performance_history = {m: {"wins": 0, "losses": 0, "pnl": 0} for m in TradingMethod}

    def select(self, regime_info, session, available_methods=None):
        regime = regime_info.get("regime", "unknown")
        vol = regime_info.get("vol_regime", "normal")
        trend = regime_info.get("trend_alignment", 0)

        if available_methods is None:
            available_methods = list(ACTIVE_METHODS)

        # Regime → method mapping
        method_scores = {}
        for method in available_methods:
            score = self._score_method(method, regime, vol, trend, session)
            method_scores[method] = score

        # Sort by score
        sorted_methods = sorted(method_scores.items(), key=lambda x: x[1], reverse=True)

        # Select top method if score > threshold
        if sorted_methods and sorted_methods[0][1] > 0.3:
            primary = sorted_methods[0][0]
            secondary = sorted_methods[1][0] if len(sorted_methods) > 1 and sorted_methods[1][1] > 0.2 else None
            return primary, secondary, method_scores

        return TradingMethod.TECHNICAL, None, method_scores

    def _score_method(self, method, regime, vol, trend, session):
        score = 0.0
        abs_trend = abs(trend)

        if method == TradingMethod.SCALPING:
            score = 0.6
            if vol == "high": score += 0.2
            if session in ["london", "new_york"]: score += 0.15
            if abs_trend < 0.3: score += 0.1
        elif method == TradingMethod.DAY_TRADING:
            score = 0.5
            if abs_trend > 0.3: score += 0.2
            if session in ["london", "new_york"]: score += 0.2
            if vol != "low": score += 0.1
        elif method == TradingMethod.SWING_TRADING:
            score = 0.4
            if abs_trend > 0.5: score += 0.3
            if vol == "normal": score += 0.2
        elif method == TradingMethod.POSITION_TRADING:
            score = 0.3
            if abs_trend > 0.7: score += 0.4
            if vol == "low": score += 0.2
        elif method == TradingMethod.TECHNICAL:
            score = 0.5
            if abs_trend > 0.3: score += 0.15
        elif method == TradingMethod.FUNDAMENTAL:
            score = 0.3
            if abs_trend > 0.5: score += 0.2
        elif method == TradingMethod.SENTIMENT:
            score = 0.4
            if vol == "high": score += 0.2
            if session in ["london", "new_york"]: score += 0.15
        elif method == TradingMethod.TREND_FOLLOWING:
            score = 0.3
            if abs_trend > 0.5: score += 0.4
            if vol != "low": score += 0.1
        elif method == TradingMethod.COUNTER_TREND:
            score = 0.3
            if abs_trend < 0.3: score += 0.3
            if vol == "normal": score += 0.2
        elif method == TradingMethod.BREAKOUT:
            score = 0.4
            if vol == "high": score += 0.3
            if abs_trend > 0.3: score += 0.1
        elif method == TradingMethod.RANGE_TRADING:
            score = 0.4
            if abs_trend < 0.3: score += 0.3
            if vol == "low": score += 0.2
        elif method == TradingMethod.TMC:
            # TMC excels in trending markets with moderate pullbacks
            score = 0.3
            if abs_trend > 0.5: score += 0.35  # Strong trend is ideal
            if vol == "normal": score += 0.15   # Normal volatility preferred
            if vol == "high": score += 0.05     # High vol slightly OK
            if session in ["london", "new_york"]: score += 0.1  # Active sessions
            # TMC specifically needs trend + pullback + momentum - best in weak-to-strong trends
            if 0.5 < abs_trend < 0.9: score += 0.1  # Sweet spot for continuation

        # Performance bonus/penalty
        perf = self.performance_history.get(method, {"wins": 0, "losses": 0})
        total = perf["wins"] + perf["losses"]
        if total >= 5:
            win_rate = perf["wins"] / total
            score *= (0.8 + win_rate * 0.4)

        return max(0, min(score, 1.0))

    def record_outcome(self, method, won, pnl):
        with self._lock:
            if method not in self.performance_history:
                self.performance_history[method] = {"wins": 0, "losses": 0, "pnl": 0}
            if won:
                self.performance_history[method]["wins"] += 1
            else:
                self.performance_history[method]["losses"] += 1
            self.performance_history[method]["pnl"] += pnl


# ==========================================
# PARAMETER ADAPTER
# ==========================================
class ParameterAdapter:
    def adapt(self, method, regime_info, base_config):
        config = METHOD_CONFIGS.get(method, METHOD_CONFIGS[TradingMethod.TECHNICAL]).copy()
        vol = regime_info.get("vol_regime", "normal")
        trend = abs(regime_info.get("trend_alignment", 0))

        # Volatility adjustments
        if vol == "high":
            config["sl_atr_mult"] *= 1.3
            config["tp_atr_mult"] *= 1.2
            config["risk_per_trade"] *= 0.7
        elif vol == "low":
            config["sl_atr_mult"] *= 0.8
            config["tp_atr_mult"] *= 0.8
            config["risk_per_trade"] *= 0.8

        # Trend adjustments
        if method in [TradingMethod.TREND_FOLLOWING, TradingMethod.BREAKOUT]:
            if trend > 0.5:
                config["tp_atr_mult"] *= 1.3
                config["risk_per_trade"] *= 1.1
        elif method in [TradingMethod.COUNTER_TREND, TradingMethod.RANGE_TRADING]:
            if trend < 0.3:
                config["tp_atr_mult"] *= 1.2

        # Session adjustments
        session = self._get_session()
        if session in ["london", "new_york"]:
            config["risk_per_trade"] *= 1.1
        elif session == "dead":
            config["risk_per_trade"] *= 0.5
            config["max_positions"] = 1

        return config

    @staticmethod
    def _get_session():
        return get_current_session()


# ==========================================
# METHOD ENGINES
# ==========================================
class MethodEngine:
    """Base class for method-specific signal generation."""

    def __init__(self, method, config):
        self.method = method
        self.config = config

    def generate_signals(self, df, brain_signals, regime_info, config=None):
        return []


class ScalpingEngine(MethodEngine):
    def generate_signals(self, df, brain_signals, regime_info, config=None):
        signals = []
        if df is None or len(df) < 20:
            return signals

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # Momentum scalp
        if last.get('MOM', 0) > 0 and last.get('RSI', 50) < 65:
            signals.append({"direction": 1, "confidence": 0.6, "type": "momentum"})
        elif last.get('MOM', 0) < 0 and last.get('RSI', 50) > 35:
            signals.append({"direction": -1, "confidence": 0.6, "type": "momentum"})

        # Mean reversion scalp
        bb_pos = (last.get('close', 0) - last.get('BB_DN', 0)) / max(last.get('BB_UP', 1) - last.get('BB_DN', 0), 0.0001)
        if bb_pos < 0.1:
            signals.append({"direction": 1, "confidence": 0.65, "type": "mean_reversion"})
        elif bb_pos > 0.9:
            signals.append({"direction": -1, "confidence": 0.65, "type": "mean_reversion"})

        # EMA crossover
        if prev.get('EMA5', 0) <= prev.get('EMA13', 0) and last.get('EMA5', 0) > last.get('EMA13', 0):
            signals.append({"direction": 1, "confidence": 0.55, "type": "ema_cross"})
        elif prev.get('EMA5', 0) >= prev.get('EMA13', 0) and last.get('EMA5', 0) < last.get('EMA13', 0):
            signals.append({"direction": -1, "confidence": 0.55, "type": "ema_cross"})

        return signals


class DayTradingEngine(MethodEngine):
    def generate_signals(self, df, brain_signals, regime_info, config=None):
        signals = []
        if df is None or len(df) < 50:
            return signals

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # Breakout of daily range
        high_20 = df['high'].rolling(20).max().iloc[-1]
        low_20 = df['low'].rolling(20).min().iloc[-1]

        if last.get('close', 0) > high_20:
            signals.append({"direction": 1, "confidence": 0.7, "type": "breakout"})
        elif last.get('close', 0) < low_20:
            signals.append({"direction": -1, "confidence": 0.7, "type": "breakout"})

        # Pullback to EMA20
        ema20 = last.get('EMA20', last.get('close', 0))
        if last.get('close', 0) > ema20 and prev.get('close', 0) <= ema20:
            signals.append({"direction": 1, "confidence": 0.6, "type": "pullback"})
        elif last.get('close', 0) < ema20 and prev.get('close', 0) >= ema20:
            signals.append({"direction": -1, "confidence": 0.6, "type": "pullback"})

        # Volume confirmation
        vol_ma = df['tick_volume'].rolling(20).mean().iloc[-1] if 'tick_volume' in df.columns else 1
        if last.get('tick_volume', 0) > vol_ma * 1.5:
            for s in signals:
                s["confidence"] = min(s["confidence"] + 0.1, 0.85)

        return signals


class SwingTradingEngine(MethodEngine):
    def generate_signals(self, df, brain_signals, regime_info, config=None):
        signals = []
        if df is None or len(df) < 100:
            return signals

        last = df.iloc[-1]

        # H4 trend following
        ema50 = last.get('EMA50', last.get('close', 0))
        ema200 = last.get('EMA200', last.get('close', last.get('EMA50', 0)))

        if last.get('close', 0) > ema50 and last.get('close', 0) > ema200:
            signals.append({"direction": 1, "confidence": 0.65, "type": "trend_continuation"})
        elif last.get('close', 0) < ema50 and last.get('close', 0) < ema200:
            signals.append({"direction": -1, "confidence": 0.65, "type": "trend_continuation"})

        # S/R bounce
        bb_pos = (last.get('close', 0) - last.get('BB_DN', 0)) / max(last.get('BB_UP', 1) - last.get('BB_DN', 0), 0.0001)
        if bb_pos < 0.15:
            signals.append({"direction": 1, "confidence": 0.6, "type": "sr_bounce"})
        elif bb_pos > 0.85:
            signals.append({"direction": -1, "confidence": 0.6, "type": "sr_bounce"})

        return signals


class PositionTradingEngine(MethodEngine):
    def generate_signals(self, df, brain_signals, regime_info, config=None):
        signals = []
        if df is None or len(df) < 200:
            return signals

        last = df.iloc[-1]
        ema200 = last.get('EMA200', last.get('close', last.get('EMA50', 0)))

        # Long-term trend
        if last.get('close', 0) > ema200 and last.get('close', 0) > last.get('EMA50', 0):
            signals.append({"direction": 1, "confidence": 0.6, "type": "long_term_trend"})
        elif last.get('close', 0) < ema200 and last.get('close', 0) < last.get('EMA50', 0):
            signals.append({"direction": -1, "confidence": 0.6, "type": "long_term_trend"})

        return signals


class TechnicalEngine(MethodEngine):
    def generate_signals(self, df, brain_signals, regime_info, config=None):
        # Uses existing brain signals directly
        signals = []
        for name, sig in brain_signals.items():
            if sig.get("direction", 0) != 0:
                signals.append({
                    "direction": sig["direction"],
                    "confidence": sig.get("confidence", 0.5),
                    "type": f"technical_{name}"
                })
        return signals


class FundamentalEngine(MethodEngine):
    def __init__(self, method, config):
        super().__init__(method, config)
        self._satellite = SatelliteDataAnalyzer()

    def generate_signals(self, df, brain_signals, regime_info, config=None):
        """Generate fundamental signals using EIA API and macro data.
        
        Integrates with:
        - alternative_data.py SatelliteDataAnalyzer (EIA API)
        - Economic calendar events
        - Interest rate differentials
        """
        signals = []
        
        # Try to get EIA commodity data for forex correlation
        try:
            eia = self._satellite
            oil_data = eia.get_commodity_data("oil")
            if oil_data and oil_data.get("value"):
                # Oil prices affect CAD, NOK, RUB
                oil_change = oil_data.get("value", 0)
                if oil_change > 0:
                    signals.append({"direction": -1, "confidence": 0.5, "type": "oil_bullish"})
                elif oil_change < 0:
                    signals.append({"direction": 1, "confidence": 0.5, "type": "oil_bearish"})
        except Exception as e:
            logger.debug("EIA data unavailable: %s", e)
        
        # Macro trend fallback
        if df is not None and len(df) > 200:
            last = df.iloc[-1]
            ema200 = last.get('EMA200', last.get('close', last.get('EMA50', 0)))
            if last.get('close', 0) > ema200:
                signals.append({"direction": 1, "confidence": 0.55, "type": "macro_trend"})
            elif last.get('close', 0) < ema200:
                signals.append({"direction": -1, "confidence": 0.55, "type": "macro_trend"})
        return signals


class SentimentEngine(MethodEngine):
    def __init__(self, method, config):
        super().__init__(method, config)
        self._sentiment = SentimentFeed()

    def generate_signals(self, df, brain_signals, regime_info, config=None):
        """Generate sentiment signals using market intelligence data.
        
        Integrates with:
        - market_intelligence.py SentimentFeed (Myfxbook)
        - order_flow.py OrderFlowAnalyzer
        - Volume imbalance analysis
        """
        signals = []
        
        # Try to get retail sentiment from Myfxbook
        try:
            sentiment = self._sentiment
            symbol = regime_info.get("symbol", "EURUSD") if regime_info else "EURUSD"
            sentiment_data = sentiment.get_sentiment(symbol)
            if sentiment_data:
                bullish = sentiment_data.get("bullish", 50)
                bearish = sentiment_data.get("bearish", 50)
                if bullish > bearish * 1.2:
                    signals.append({"direction": 1, "confidence": 0.55, "type": "retail_sentiment"})
                elif bearish > bullish * 1.2:
                    signals.append({"direction": -1, "confidence": 0.55, "type": "retail_sentiment"})
        except Exception as e:
            logger.debug("Sentiment data unavailable: %s", e)
        
        # Volume imbalance fallback
        if df is not None and len(df) > 20:
            vol_buy = df['tick_volume'].iloc[-10:].sum() if 'tick_volume' in df.columns else 0
            vol_sell = df['tick_volume'].iloc[-20:-10].sum() if 'tick_volume' in df.columns else 0
            if vol_buy > vol_sell * 1.2:
                signals.append({"direction": 1, "confidence": 0.55, "type": "sentiment_volume"})
            elif vol_sell > vol_buy * 1.2:
                signals.append({"direction": -1, "confidence": 0.55, "type": "sentiment_volume"})
        return signals


class TrendFollowingEngine(MethodEngine):
    def generate_signals(self, df, brain_signals, regime_info, config=None):
        signals = []
        if df is None or len(df) < 50:
            return signals

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # ADX-based trend strength
        ema20 = last.get('EMA20', last.get('close', 0))
        ema50 = last.get('EMA50', last.get('close', 0))
        ema200 = last.get('EMA200', last.get('close', last.get('EMA50', 0)))

        # Trend alignment
        if ema20 > ema50 > ema200:
            signals.append({"direction": 1, "confidence": 0.7, "type": "trend_alignment"})
        elif ema20 < ema50 < ema200:
            signals.append({"direction": -1, "confidence": 0.7, "type": "trend_alignment"})

        # MACD confirmation
        macd = last.get('MACD', 0)
        macd_signal = last.get('MACD_SIGNAL', 0)
        prev_macd = prev.get('MACD', 0)
        prev_macd_signal = prev.get('MACD_SIGNAL', 0)

        if macd > macd_signal and prev_macd <= prev_macd_signal:
            signals.append({"direction": 1, "confidence": 0.6, "type": "macd_cross"})
        elif macd < macd_signal and prev_macd >= prev_macd_signal:
            signals.append({"direction": -1, "confidence": 0.6, "type": "macd_cross"})

        # ADX filter
        atr = last.get('ATR', 0)
        atr_ma = last.get('ATR_MA', 0)
        if atr > 0 and atr_ma > 0 and atr > atr_ma * 1.2:
            for s in signals:
                s["confidence"] = min(s["confidence"] + 0.1, 0.85)

        return signals


class CounterTrendEngine(MethodEngine):
    def generate_signals(self, df, brain_signals, regime_info, config=None):
        signals = []
        if df is None or len(df) < 20:
            return signals

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # RSI extreme reversal
        rsi = last.get('RSI', 50)
        if rsi < 25:
            signals.append({"direction": 1, "confidence": 0.65, "type": "rsi_extreme"})
        elif rsi > 75:
            signals.append({"direction": -1, "confidence": 0.65, "type": "rsi_extreme"})
        elif rsi < 35 and last.get('close', 0) > prev.get('close', 0):
            signals.append({"direction": 1, "confidence": 0.55, "type": "rsi_bounce"})
        elif rsi > 65 and last.get('close', 0) < prev.get('close', 0):
            signals.append({"direction": -1, "confidence": 0.55, "type": "rsi_bounce"})

        # Bollinger band fade
        bb_pos = (last.get('close', 0) - last.get('BB_DN', 0)) / max(last.get('BB_UP', 1) - last.get('BB_DN', 0), 0.0001)
        if bb_pos < 0.05:
            signals.append({"direction": 1, "confidence": 0.6, "type": "bb_fade"})
        elif bb_pos > 0.95:
            signals.append({"direction": -1, "confidence": 0.6, "type": "bb_fade"})

        # Divergence (RSI vs price)
        if len(df) > 10:
            price_higher = df['close'].iloc[-1] > df['close'].iloc[-5]
            has_rsi = 'RSI' in df.columns
            rsi_lower = df['RSI'].iloc[-1] < df['RSI'].iloc[-5] if has_rsi else False
            if price_higher and rsi_lower:
                signals.append({"direction": -1, "confidence": 0.6, "type": "bearish_divergence"})
            elif not price_higher and not rsi_lower and has_rsi and df['close'].iloc[-1] < df['close'].iloc[-5] and df['RSI'].iloc[-1] > df['RSI'].iloc[-5]:
                signals.append({"direction": 1, "confidence": 0.6, "type": "bullish_divergence"})

        return signals


class BreakoutEngine(MethodEngine):
    def generate_signals(self, df, brain_signals, regime_info, config=None):
        signals = []
        if df is None or len(df) < 30:
            return signals

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # Range breakout
        high_20 = df['high'].rolling(20).max().iloc[-1]
        low_20 = df['low'].rolling(20).min().iloc[-1]
        range_size = high_20 - low_20

        if last.get('close', 0) > high_20 and prev.get('close', 0) <= high_20:
            # Volume confirmation
            vol_ratio = last.get('tick_volume', 0) / max(df['tick_volume'].rolling(20).mean().iloc[-1], 1) if 'tick_volume' in df.columns else 1.0
            conf = 0.7 if vol_ratio > 1.3 else 0.55
            signals.append({"direction": 1, "confidence": conf, "type": "range_breakout"})
        elif last.get('close', 0) < low_20 and prev.get('close', 0) >= low_20:
            vol_ratio = last.get('tick_volume', 0) / max(df['tick_volume'].rolling(20).mean().iloc[-1], 1) if 'tick_volume' in df.columns else 1.0
            conf = 0.7 if vol_ratio > 1.3 else 0.55
            signals.append({"direction": -1, "confidence": conf, "type": "range_breakout"})

        # Volatility breakout
        atr = last.get('ATR', 0)
        atr_ma = last.get('ATR_MA', 0)
        if atr > 0 and atr_ma > 0 and atr > atr_ma * 1.5:
            if last.get('close', 0) > prev.get('close', 0):
                signals.append({"direction": 1, "confidence": 0.6, "type": "vol_breakout"})
            else:
                signals.append({"direction": -1, "confidence": 0.6, "type": "vol_breakout"})

        return signals


class RangeTradingEngine(MethodEngine):
    def generate_signals(self, df, brain_signals, regime_info, config=None):
        signals = []
        if df is None or len(df) < 30:
            return signals

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # Bollinger band fade
        bb_pos = (last.get('close', 0) - last.get('BB_DN', 0)) / max(last.get('BB_UP', 1) - last.get('BB_DN', 0), 0.0001)

        if bb_pos < 0.1 and last.get('close', 0) > prev.get('close', 0):
            signals.append({"direction": 1, "confidence": 0.65, "type": "bb_fade"})
        elif bb_pos > 0.9 and last.get('close', 0) < prev.get('close', 0):
            signals.append({"direction": -1, "confidence": 0.65, "type": "bb_fade"})

        # S/R fade
        high_20 = df['high'].rolling(20).max().iloc[-1]
        low_20 = df['low'].rolling(20).min().iloc[-1]
        mid = (high_20 + low_20) / 2

        if last.get('close', 0) > high_20 * 0.98 and last.get('close', 0) < prev.get('close', 0):
            signals.append({"direction": -1, "confidence": 0.55, "type": "sr_fade"})
        elif last.get('close', 0) < low_20 * 1.02 and last.get('close', 0) > prev.get('close', 0):
            signals.append({"direction": 1, "confidence": 0.55, "type": "sr_fade"})

        return signals


class TMCEngine(MethodEngine):
    """Trend Momentum Continuation - enters on pullback within confirmed trend with momentum confirmation."""

    def generate_signals(self, df, brain_signals, regime_info, config=None):
        signals = []
        if df is None or len(df) < 50:
            return signals

        last = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3] if len(df) > 3 else prev

        # === STEP 1: Confirm Strong Trend ===
        ema20 = last.get('EMA20', last.get('close', 0))
        ema50 = last.get('EMA50', last.get('close', 0))
        ema200 = last.get('EMA200', last.get('close', last.get('EMA50', 0)))

        trend_strength = regime_info.get("trend_alignment", 0)
        abs_trend = abs(trend_strength)

        if abs_trend < 0.5:
            return signals  # No strong trend, TMC not applicable

        # === STEP 2: Detect Pullback/Consolidation ===
        # Price pulled back from recent swing
        high_20 = df['high'].rolling(20).max().iloc[-1]
        low_20 = df['low'].rolling(20).min().iloc[-1]
        mid = (high_20 + low_20) / 2

        # Pullback detection: price moved against trend then started recovering
        if trend_strength > 0:  # Uptrend
            # Pullback = price dipped below EMA20 but stayed above EMA50
            pullback = (last.get('close', 0) < ema20 and last.get('close', 0) > ema50)
            # Or price touched lower Bollinger band area
            bb_pos = (last.get('close', 0) - last.get('BB_DN', 0)) / max(last.get('BB_UP', 1) - last.get('BB_DN', 0), 0.0001)
            pullback = pullback or (bb_pos < 0.3)
        else:  # Downtrend
            pullback = (last.get('close', 0) > ema20 and last.get('close', 0) < ema50)
            bb_pos = (last.get('close', 0) - last.get('BB_DN', 0)) / max(last.get('BB_UP', 1) - last.get('BB_DN', 0), 0.0001)
            pullback = pullback or (bb_pos > 0.7)

        if not pullback:
            return signals  # No pullback detected

        # === STEP 3: Momentum Confirmation ===
        # RSI turning back toward trend
        rsi = last.get('RSI', 50)
        prev_rsi = prev.get('RSI', 50)

        # MACD histogram turning
        macd_hist = last.get('MACD_HIST', 0)
        prev_macd_hist = prev.get('MACD_HIST', 0)

        # EMA alignment re-establishing
        ema_bullish = ema20 > ema50
        ema_bearish = ema20 < ema50

        momentum_score = 0
        if trend_strength > 0:
            # Uptrend: need bullish momentum
            if rsi > prev_rsi and rsi < 65:  # RSI turning up but not overbought
                momentum_score += 0.3
            if macd_hist > prev_macd_hist:  # MACD histogram expanding
                momentum_score += 0.3
            if ema_bullish:  # EMA alignment
                momentum_score += 0.2
            if last.get('close', 0) > prev.get('close', 0):  # Price closing higher
                momentum_score += 0.2
        else:
            # Downtrend: need bearish momentum
            if rsi < prev_rsi and rsi > 35:  # RSI turning down but not oversold
                momentum_score += 0.3
            if macd_hist < prev_macd_hist:  # MACD histogram contracting
                momentum_score += 0.3
            if ema_bearish:
                momentum_score += 0.2
            if last.get('close', 0) < prev.get('close', 0):
                momentum_score += 0.2

        if momentum_score < 0.4:
            return signals  # Not enough momentum confirmation

        # === STEP 4: Volume Confirmation ===
        vol_ma = df['tick_volume'].rolling(20).mean().iloc[-1] if 'tick_volume' in df.columns else 1
        vol_ratio = last.get('tick_volume', 0) / max(vol_ma, 1)
        vol_boost = 1.1 if vol_ratio > 1.2 else 1.0

        # === STEP 5: Generate Signal ===
        confidence = (abs_trend * 0.4 + momentum_score * 0.4 + 0.2) * vol_boost
        confidence = min(confidence, 0.9)

        if trend_strength > 0:
            signals.append({
                "direction": 1,
                "confidence": confidence,
                "type": "tmc_bullish_continuation",
                "momentum_score": momentum_score,
                "trend_strength": trend_strength,
                "pullback_confirmed": True,
            })
        elif trend_strength < 0:
            signals.append({
                "direction": -1,
                "confidence": confidence,
                "type": "tmc_bearish_continuation",
                "momentum_score": momentum_score,
                "trend_strength": trend_strength,
                "pullback_confirmed": True,
            })

        return signals


# Method engine registry
METHOD_ENGINES = {
    TradingMethod.SCALPING: ScalpingEngine,
    TradingMethod.DAY_TRADING: DayTradingEngine,
    TradingMethod.SWING_TRADING: SwingTradingEngine,
    TradingMethod.POSITION_TRADING: PositionTradingEngine,
    TradingMethod.TECHNICAL: TechnicalEngine,
    TradingMethod.FUNDAMENTAL: FundamentalEngine,
    TradingMethod.SENTIMENT: SentimentEngine,
    TradingMethod.TREND_FOLLOWING: TrendFollowingEngine,
    TradingMethod.COUNTER_TREND: CounterTrendEngine,
    TradingMethod.BREAKOUT: BreakoutEngine,
    TradingMethod.RANGE_TRADING: RangeTradingEngine,
    TradingMethod.TMC: TMCEngine,
}


# ==========================================
# META-BRAIN V11
# ==========================================
class BrainV11:
    """
    Autonomous Meta-Brain Orchestrator.

    Detects market regime, selects optimal trading method,
    adapts parameters, and dispatches to specialized engines.
    Wraps the existing brain chain (V1-V10) for signal generation.
    """

    def __init__(self, brain_v10):
        self.v10 = brain_v10
        self.classifier = RegimeClassifier()
        self.selector = MethodSelector()
        self.adapter = ParameterAdapter()
        self.method_engines = {m: e(m, METHOD_CONFIGS.get(m, {})) for m, e in METHOD_ENGINES.items()}
        self._lock = threading.Lock()
        self.current_method = TradingMethod.TECHNICAL
        self.current_config = METHOD_CONFIGS[TradingMethod.TECHNICAL]
        self.regime_history = deque(maxlen=100)
        self.method_history = deque(maxlen=100)
        self._market_maker = None
        self._arbitrage = None
        try:
            self._market_maker = MarketMaker()
            self._arbitrage = ArbitrageEngine()
        except Exception:
            pass

    def analyze(self, symbol, timeframe=mt5.TIMEFRAME_M1):
        # === MARKET STATE GATE ===
        # Validate market is open, symbol is tradeable, data is fresh
        # before ANY signal generation. This prevents hallucinated signals
        # from stale/closed-market data.
        tradeable = is_tradeable_now(symbol, timeframe)
        if not tradeable["can_trade"]:
                logger.debug("V11 market gate: %s — %s", symbol, tradeable["reason"])
                return {
                    "action": "hold",
                    "direction": 0,
                    "confidence": 0,
                    "reason": f"market_closed: {tradeable['reason']}",
                    "signals": {},
                    "active": [],
                    "v11": {
                        "method": self.current_method.value,
                        "secondary_method": None,
                        "regime": {},
                        "config": self.current_config,
                        "method_signals": [],
                        "method_scores": {},
                        "market_gate": tradeable,
                    },
                }

        # Get data for regime classification
        rates = fetch_closed_rates(symbol, timeframe, 300)
        df = None
        if rates is not None and len(rates) > 0:
            import pandas as pd
            df = pd.DataFrame(rates)

        # Classify regime
        regime_info = self.classifier.classify(df, symbol)
        self.regime_history.append(regime_info)

        # Select method
        primary_method, secondary_method, scores = self.selector.select(regime_info, self._get_session())
        adapted_config = self.adapter.adapt(primary_method, regime_info, METHOD_CONFIGS.get(primary_method, {}))
        with self._lock:
            self.current_method = primary_method
            self.current_config = adapted_config

        # Get brain signals from existing V10 chain
        brain_decision = self.v10.analyze(symbol, timeframe, df=df)

        # Generate method-specific signals
        engine = self.method_engines.get(primary_method)
        method_signals = []
        if engine:
            local_config = dict(self.current_config)
            method_signals = engine.generate_signals(df, brain_decision.get("signals", {}), regime_info, config=local_config)

        # Merge brain signals with method signals
        merged = self._merge_signals(brain_decision, method_signals, regime_info, primary_method, df, symbol)

        # Add V11 metadata
        merged["v11"] = {
            "method": primary_method.value,
            "secondary_method": secondary_method.value if secondary_method else None,
            "regime": regime_info,
            "config": self.current_config,
            "method_signals": method_signals,
            "method_scores": {m.value: round(s, 3) for m, s in scores.items()},
        }

        # Record for learning
        self.method_history.append({
            "method": primary_method,
            "regime": regime_info.get("regime"),
            "time": datetime.now().isoformat(),
        })

        # Advanced strategy intelligence
        if self._market_maker and df is not None and len(df) > 0:
            try:
                last_price = float(df['close'].iloc[-1])
                volatility = float(df.get('ATR', pd.Series([0])).iloc[-1]) / last_price if 'ATR' in df.columns and last_price > 0 else 0.01
                quotes = self._market_maker.calculate_quotes(symbol, last_price, volatility)
                if quotes:
                    merged.setdefault("v11_advanced", {})["market_maker"] = quotes
            except Exception:
                pass

        if self._arbitrage:
            try:
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    arb_data = {symbol: {"bid": tick.bid, "ask": tick.ask}}
                    for other_sym in ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]:
                        if other_sym != symbol:
                            other_tick = mt5.symbol_info_tick(other_sym)
                            if other_tick:
                                arb_data[other_sym] = {"bid": other_tick.bid, "ask": other_tick.ask}
                    opps = self._arbitrage.check_triangular(arb_data)
                    if opps:
                        merged.setdefault("v11_advanced", {})["arbitrage"] = opps
            except Exception:
                pass

        return merged

    def _merge_signals(self, brain_decision, method_signals, regime_info, primary_method, df=None, symbol=None):
        """Merge brain chain signals with method-specific signals.
        
        Aggregates all additive confidence_adjustments from the brain chain
        (V2/V3/V4/V5/V7/V10) and applies them once to the base confidence.
        """
        config = METHOD_CONFIGS.get(primary_method, METHOD_CONFIGS[TradingMethod.TECHNICAL])

        # Start with brain decision
        result = copy.deepcopy(brain_decision)

        # Aggregate ALL adjustments from brain chain into a single additive pass
        base = result.get("confidence", 0)
        adjs = result.get("confidence_adjustments", {})
        total_adj = sum(adjs.values())
        final = max(0.1, min(base + total_adj, 0.98))
        result["confidence"] = final
        result["confidence_adjustments"] = adjs
        result["confidence_total_adjustment"] = round(total_adj, 4)

        if not method_signals:
            return result

        # Aggregate method signals
        buy_conf = 0
        sell_conf = 0
        for sig in method_signals:
            if sig["direction"] == 1:
                buy_conf += sig["confidence"]
            elif sig["direction"] == -1:
                sell_conf += sig["confidence"]

        method_direction = 1 if buy_conf > sell_conf else (-1 if sell_conf > buy_conf else 0)
        method_confidence = max(buy_conf, sell_conf) / max(len(method_signals), 1)

        # Combine with brain signals using additive approach
        brain_direction = result.get("direction", 0)
        brain_confidence = result.get("confidence", 0)

        if method_direction == brain_direction and method_direction != 0:
            # Agreement - additive boost
            method_adj = (method_confidence - brain_confidence) * 0.15  # max +15%
            combined_confidence = brain_confidence + max(method_adj, 0)
        elif method_direction != 0 and brain_direction != 0:
            # Disagreement - additive penalty
            method_adj = -abs(method_confidence - brain_confidence) * 0.20  # max -20%
            combined_confidence = brain_confidence + method_adj
        else:
            combined_confidence = max(brain_confidence, method_confidence)

        combined_confidence = max(0.1, min(combined_confidence, 0.95))

        # Apply method-specific confidence threshold
        if combined_confidence < config.get("min_confidence", 0.55):
            result["action"] = "hold"
        else:
            result["action"] = "trade"
            result["direction"] = method_direction if method_direction != 0 else brain_direction
            result["direction_str"] = "BUY" if result["direction"] == 1 else "SELL"
            result["confidence"] = combined_confidence

        # Apply method-specific SL/TP
        atr = df.iloc[-1].get('ATR', 0) if df is not None else 0
        if atr > 0:
            info = mt5.symbol_info(symbol)
            if info:
                point = info.point
                sl_pts = max(int(atr / point * config.get("sl_atr_mult", 1.5)), 50)
                tp_pts = int(atr / point * config.get("tp_atr_mult", 2.5))
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    if result["direction"] == 1:
                        result["sl"] = tick.ask - sl_pts * point
                        result["tp"] = tick.ask + tp_pts * point
                    else:
                        result["sl"] = tick.bid + sl_pts * point
                        result["tp"] = tick.bid - tp_pts * point
                    result["sl_points"] = sl_pts
                    result["tp_points"] = tp_pts

        result["method"] = primary_method.value
        # Set method-specific magic number
        method_to_magic = {
            TradingMethod.SCALPING: MAGIC_SCALPING,
            TradingMethod.DAY_TRADING: MAGIC_DAY_TRADING,
            TradingMethod.SWING_TRADING: MAGIC_SWING,
            TradingMethod.POSITION_TRADING: MAGIC_POSITION,
            TradingMethod.TECHNICAL: MAGIC_TECHNICAL,
            TradingMethod.FUNDAMENTAL: MAGIC_FUNDAMENTAL,
            TradingMethod.SENTIMENT: MAGIC_SENTIMENT,
            TradingMethod.TREND_FOLLOWING: MAGIC_TREND,
            TradingMethod.COUNTER_TREND: MAGIC_COUNTER_TREND,
            TradingMethod.BREAKOUT: MAGIC_BREAKOUT,
            TradingMethod.RANGE_TRADING: MAGIC_RANGE,
            TradingMethod.TMC: MAGIC_TMC,
        }
        result["magic"] = method_to_magic[primary_method]
        result["method_signals"] = method_signals
        return result

    def _get_session(self):
        return get_current_session()

    def record_trade_outcome(self, method, won, pnl):
        self.selector.record_outcome(method, won, pnl)

    def execute_decision(self, decision, symbol):
        return self.v10.execute_decision(decision, symbol)

    def get_status(self):
        return {
            "current_method": self.current_method.value,
            "config": self.current_config,
            "recent_regimes": list(self.regime_history)[-5:],
            "recent_methods": [m["method"].value for m in list(self.method_history)[-5:]],
            "method_performance": self.selector.performance_history,
        }
