"""
Tests for brain_v11.py MethodEngine subclasses, _merge_signals, and record_outcome.
Run with: pytest tests/test_brain_v11_engines.py -v
"""
import sys
import types
import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch
from datetime import datetime


# ---- Mock all external dependencies before importing brain_v11 ----
@pytest.fixture(autouse=True)
def mock_deps(monkeypatch):
    """Set up all mocked dependencies for brain_v11 imports."""
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
    mt5.symbol_info_tick = MagicMock(return_value=None)
    mt5.symbol_info = MagicMock(return_value=None)
    monkeypatch.setitem(sys.modules, 'MetaTrader5', mt5)

    # config mock
    cfg = types.ModuleType('config')
    cfg.MAGIC_NUMBER = 99999
    cfg.MAGIC_SCALPING = 11001
    cfg.MAGIC_DAY_TRADING = 11002
    cfg.MAGIC_SWING = 11003
    cfg.MAGIC_POSITION = 11004
    cfg.MAGIC_TECHNICAL = 11005
    cfg.MAGIC_FUNDAMENTAL = 11006
    cfg.MAGIC_SENTIMENT = 11007
    cfg.MAGIC_TREND = 11008
    cfg.MAGIC_COUNTER_TREND = 11009
    cfg.MAGIC_BREAKOUT = 11010
    cfg.MAGIC_RANGE = 11011
    cfg.MAGIC_TMC = 11012
    monkeypatch.setitem(sys.modules, 'config', cfg)

    # indicators mock
    ind = types.ModuleType('indicators')
    ind.validate_rate_freshness = MagicMock(return_value={"fresh": True})
    ind.fetch_closed_rates = MagicMock(return_value=None)
    ind.align_to_m1_grid = MagicMock(return_value=None)
    ind.is_tradeable_now = MagicMock(return_value={"can_trade": True, "reason": ""})
    ind.get_current_session = MagicMock(return_value="london")
    ind.ema = MagicMock(side_effect=lambda data, span: np.array(data, dtype=float))
    monkeypatch.setitem(sys.modules, 'indicators', ind)

    # alternative_data mock
    alt = types.ModuleType('alternative_data')
    alt.SatelliteDataAnalyzer = MagicMock
    monkeypatch.setitem(sys.modules, 'alternative_data', alt)

    # market_intelligence mock
    mi = types.ModuleType('market_intelligence')
    mi.SentimentFeed = MagicMock
    mi.NewsCalendar = MagicMock
    monkeypatch.setitem(sys.modules, 'market_intelligence', mi)

    # strategies_advanced mock
    sa = types.ModuleType('strategies_advanced')
    sa.MarketMaker = MagicMock
    sa.ArbitrageEngine = MagicMock
    monkeypatch.setitem(sys.modules, 'strategies_advanced', sa)


def _make_engine_df(n=100, trend="up"):
    """Generate a DataFrame with the indicator columns that engines expect."""
    np.random.seed(42)
    drift = 0.0002 if trend == "up" else (-0.0002 if trend == "down" else 0)
    close = np.cumsum(np.random.randn(n) * 0.0005 + drift) + 1.10000
    high = close + 0.001
    low = close - 0.001
    open_ = close + np.random.randn(n) * 0.0001
    volume = np.full(n, 5000.0)
    ema5 = pd.Series(close).ewm(span=5).mean().values
    ema13 = pd.Series(close).ewm(span=13).mean().values
    ema20 = pd.Series(close).ewm(span=20).mean().values
    ema50 = pd.Series(close).ewm(span=50).mean().values
    ema200 = pd.Series(close).ewm(span=200).mean().values if n >= 200 else ema50
    delta = pd.Series(close).diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).values
    bb_ma = pd.Series(close).rolling(20).mean().values
    bb_std = pd.Series(close).rolling(20).std().values
    bb_up = bb_ma + bb_std * 2
    bb_dn = bb_ma - bb_std * 2
    macd_line = pd.Series(close).ewm(span=12).mean() - pd.Series(close).ewm(span=26).mean()
    macd_signal = macd_line.ewm(span=9).mean()
    macd_hist = (macd_line - macd_signal).values
    tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]
    atr = pd.Series(tr).rolling(14).mean().values
    atr_ma = pd.Series(atr).rolling(30).mean().values

    df = pd.DataFrame({
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'tick_volume': volume,
        'MOM': np.random.randn(n),
        'RSI': rsi,
        'EMA5': ema5,
        'EMA13': ema13,
        'EMA20': ema20,
        'EMA50': ema50,
        'EMA200': ema200,
        'BB_UP': bb_up,
        'BB_DN': bb_dn,
        'MACD': macd_line.values,
        'MACD_SIGNAL': macd_signal.values,
        'MACD_HIST': macd_hist,
        'ATR': atr,
        'ATR_MA': atr_ma,
    })
    return df


# ==========================================
# MethodEngine subclasses
# ==========================================
class TestScalpingEngine:
    def test_generate_signals_returns_list(self):
        from brain_v11 import ScalpingEngine, TradingMethod, METHOD_CONFIGS
        engine = ScalpingEngine(TradingMethod.SCALPING, METHOD_CONFIGS[TradingMethod.SCALPING])
        df = _make_engine_df(100)
        signals = engine.generate_signals(df, {}, {})
        assert isinstance(signals, list)

    def test_generate_signals_empty_df(self):
        from brain_v11 import ScalpingEngine, TradingMethod, METHOD_CONFIGS
        engine = ScalpingEngine(TradingMethod.SCALPING, METHOD_CONFIGS[TradingMethod.SCALPING])
        signals = engine.generate_signals(pd.DataFrame(), {}, {})
        assert signals == []

    def test_generate_signals_short_df(self):
        from brain_v11 import ScalpingEngine, TradingMethod, METHOD_CONFIGS
        engine = ScalpingEngine(TradingMethod.SCALPING, METHOD_CONFIGS[TradingMethod.SCALPING])
        df = _make_engine_df(5)
        signals = engine.generate_signals(df, {}, {})
        assert signals == []


class TestDayTradingEngine:
    def test_generate_signals_returns_list(self):
        from brain_v11 import DayTradingEngine, TradingMethod, METHOD_CONFIGS
        engine = DayTradingEngine(TradingMethod.DAY_TRADING, METHOD_CONFIGS[TradingMethod.DAY_TRADING])
        df = _make_engine_df(100)
        signals = engine.generate_signals(df, {}, {})
        assert isinstance(signals, list)

    def test_generate_signals_empty_df(self):
        from brain_v11 import DayTradingEngine, TradingMethod, METHOD_CONFIGS
        engine = DayTradingEngine(TradingMethod.DAY_TRADING, METHOD_CONFIGS[TradingMethod.DAY_TRADING])
        signals = engine.generate_signals(pd.DataFrame(), {}, {})
        assert signals == []


class TestTrendFollowingEngine:
    def test_generate_signals_returns_list(self):
        from brain_v11 import TrendFollowingEngine, TradingMethod, METHOD_CONFIGS
        engine = TrendFollowingEngine(TradingMethod.TREND_FOLLOWING, METHOD_CONFIGS[TradingMethod.TREND_FOLLOWING])
        df = _make_engine_df(100)
        signals = engine.generate_signals(df, {}, {})
        assert isinstance(signals, list)

    def test_generate_signals_empty_df(self):
        from brain_v11 import TrendFollowingEngine, TradingMethod, METHOD_CONFIGS
        engine = TrendFollowingEngine(TradingMethod.TREND_FOLLOWING, METHOD_CONFIGS[TradingMethod.TREND_FOLLOWING])
        signals = engine.generate_signals(pd.DataFrame(), {}, {})
        assert signals == []


class TestCounterTrendEngine:
    def test_generate_signals_returns_list(self):
        from brain_v11 import CounterTrendEngine, TradingMethod, METHOD_CONFIGS
        engine = CounterTrendEngine(TradingMethod.COUNTER_TREND, METHOD_CONFIGS[TradingMethod.COUNTER_TREND])
        df = _make_engine_df(100)
        signals = engine.generate_signals(df, {}, {})
        assert isinstance(signals, list)

    def test_generate_signals_empty_df(self):
        from brain_v11 import CounterTrendEngine, TradingMethod, METHOD_CONFIGS
        engine = CounterTrendEngine(TradingMethod.COUNTER_TREND, METHOD_CONFIGS[TradingMethod.COUNTER_TREND])
        signals = engine.generate_signals(pd.DataFrame(), {}, {})
        assert signals == []


class TestBreakoutEngine:
    def test_generate_signals_returns_list(self):
        from brain_v11 import BreakoutEngine, TradingMethod, METHOD_CONFIGS
        engine = BreakoutEngine(TradingMethod.BREAKOUT, METHOD_CONFIGS[TradingMethod.BREAKOUT])
        df = _make_engine_df(100)
        signals = engine.generate_signals(df, {}, {})
        assert isinstance(signals, list)

    def test_generate_signals_empty_df(self):
        from brain_v11 import BreakoutEngine, TradingMethod, METHOD_CONFIGS
        engine = BreakoutEngine(TradingMethod.BREAKOUT, METHOD_CONFIGS[TradingMethod.BREAKOUT])
        signals = engine.generate_signals(pd.DataFrame(), {}, {})
        assert signals == []


class TestRangeTradingEngine:
    def test_generate_signals_returns_list(self):
        from brain_v11 import RangeTradingEngine, TradingMethod, METHOD_CONFIGS
        engine = RangeTradingEngine(TradingMethod.RANGE_TRADING, METHOD_CONFIGS[TradingMethod.RANGE_TRADING])
        df = _make_engine_df(100)
        signals = engine.generate_signals(df, {}, {})
        assert isinstance(signals, list)

    def test_generate_signals_empty_df(self):
        from brain_v11 import RangeTradingEngine, TradingMethod, METHOD_CONFIGS
        engine = RangeTradingEngine(TradingMethod.RANGE_TRADING, METHOD_CONFIGS[TradingMethod.RANGE_TRADING])
        signals = engine.generate_signals(pd.DataFrame(), {}, {})
        assert signals == []


class TestTMCEngine:
    def test_generate_signals_returns_list(self):
        from brain_v11 import TMCEngine, TradingMethod, METHOD_CONFIGS
        engine = TMCEngine(TradingMethod.TMC, METHOD_CONFIGS[TradingMethod.TMC])
        df = _make_engine_df(100, trend="up")
        regime = {"trend_alignment": 0.8}
        signals = engine.generate_signals(df, {}, regime)
        assert isinstance(signals, list)

    def test_generate_signals_no_trend_returns_empty(self):
        from brain_v11 import TMCEngine, TradingMethod, METHOD_CONFIGS
        engine = TMCEngine(TradingMethod.TMC, METHOD_CONFIGS[TradingMethod.TMC])
        df = _make_engine_df(100, trend="flat")
        regime = {"trend_alignment": 0.1}
        signals = engine.generate_signals(df, {}, regime)
        assert signals == []

    def test_generate_signals_empty_df(self):
        from brain_v11 import TMCEngine, TradingMethod, METHOD_CONFIGS
        engine = TMCEngine(TradingMethod.TMC, METHOD_CONFIGS[TradingMethod.TMC])
        signals = engine.generate_signals(pd.DataFrame(), {}, {"trend_alignment": 0.8})
        assert signals == []


# ==========================================
# _merge_signals
# ==========================================
class TestMergeSignals:
    def _make_brain_decision(self, direction=1, confidence=0.7, action="trade"):
        return {
            "action": action,
            "direction": direction,
            "confidence": confidence,
            "direction_str": "BUY" if direction == 1 else "SELL",
            "signals": {},
            "confidence_adjustments": {},
        }

    def test_merge_with_agreement_increases_confidence(self):
        from brain_v11 import BrainV11, TradingMethod
        mock_v10 = MagicMock()
        v11 = BrainV11(mock_v10)
        brain_decision = self._make_brain_decision(direction=1, confidence=0.6)
        method_signals = [{"direction": 1, "confidence": 0.7, "type": "momentum"}]
        regime_info = {"regime": "strong_trend_normal_vol", "vol_regime": "normal", "trend_alignment": 0.8}
        result = v11._merge_signals(brain_decision, method_signals, regime_info, TradingMethod.SCALPING)
        assert result["confidence"] >= brain_decision["confidence"]

    def test_merge_with_disagreement_decreases_confidence(self):
        from brain_v11 import BrainV11, TradingMethod
        mock_v10 = MagicMock()
        v11 = BrainV11(mock_v10)
        brain_decision = self._make_brain_decision(direction=1, confidence=0.7)
        method_signals = [{"direction": -1, "confidence": 0.8, "type": "momentum"}]
        regime_info = {"regime": "mixed", "vol_regime": "normal", "trend_alignment": 0.1}
        result = v11._merge_signals(brain_decision, method_signals, regime_info, TradingMethod.SCALPING)
        assert result["confidence"] <= brain_decision["confidence"]

    def test_merge_empty_method_signals_keeps_brain(self):
        from brain_v11 import BrainV11, TradingMethod
        mock_v10 = MagicMock()
        v11 = BrainV11(mock_v10)
        brain_decision = self._make_brain_decision(direction=1, confidence=0.75)
        result = v11._merge_signals(brain_decision, [], {}, TradingMethod.TECHNICAL)
        assert result["confidence"] == 0.75
        assert result["action"] == "trade"

    def test_merge_clamps_confidence_to_min(self):
        from brain_v11 import BrainV11, TradingMethod
        mock_v10 = MagicMock()
        v11 = BrainV11(mock_v10)
        brain_decision = self._make_brain_decision(direction=1, confidence=0.1)
        method_signals = [{"direction": -1, "confidence": 0.9, "type": "momentum"}]
        regime_info = {"regime": "mixed", "vol_regime": "normal", "trend_alignment": 0.1}
        result = v11._merge_signals(brain_decision, method_signals, regime_info, TradingMethod.SCALPING)
        assert result["confidence"] >= 0.1

    def test_merge_clamps_confidence_to_max(self):
        from brain_v11 import BrainV11, TradingMethod
        mock_v10 = MagicMock()
        v11 = BrainV11(mock_v10)
        brain_decision = self._make_brain_decision(direction=1, confidence=0.9)
        method_signals = [{"direction": 1, "confidence": 0.95, "type": "momentum"}]
        regime_info = {"regime": "strong_trend_normal_vol", "vol_regime": "normal", "trend_alignment": 0.9}
        result = v11._merge_signals(brain_decision, method_signals, regime_info, TradingMethod.SCALPING)
        assert result["confidence"] <= 0.95


# ==========================================
# record_outcome
# ==========================================
class TestRecordOutcome:
    def test_record_outcome_records_win(self):
        from brain_v11 import MethodSelector, TradingMethod
        selector = MethodSelector()
        selector.record_outcome(TradingMethod.SCALPING, won=True, pnl=50.0)
        perf = selector.performance_history[TradingMethod.SCALPING]
        assert perf["wins"] == 1
        assert perf["pnl"] == 50.0

    def test_record_outcome_records_loss(self):
        from brain_v11 import MethodSelector, TradingMethod
        selector = MethodSelector()
        selector.record_outcome(TradingMethod.DAY_TRADING, won=False, pnl=-30.0)
        perf = selector.performance_history[TradingMethod.DAY_TRADING]
        assert perf["losses"] == 1
        assert perf["pnl"] == -30.0

    def test_record_outcome_affects_future_selection(self):
        from brain_v11 import MethodSelector, TradingMethod
        selector = MethodSelector()
        # Record 10 wins for scalping
        for _ in range(10):
            selector.record_outcome(TradingMethod.SCALPING, won=True, pnl=10.0)
        regime = {"regime": "ranging", "vol_regime": "normal", "trend_alignment": 0.1}
        primary, secondary, scores = selector.select(regime, "london")
        assert scores[TradingMethod.SCALPING] > 0

    def test_record_outcome_unknown_method_still_records(self):
        from brain_v11 import MethodSelector, TradingMethod
        selector = MethodSelector()
        selector.record_outcome(TradingMethod.TECHNICAL, won=True, pnl=25.0)
        perf = selector.performance_history[TradingMethod.TECHNICAL]
        assert perf["wins"] == 1
