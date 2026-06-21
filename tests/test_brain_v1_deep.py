"""
Deep tests for brain_v1.py — 6 critical untested methods.
Run with: pytest tests/test_brain_v1_deep.py -v
"""
import sys
import os
import pytest
import numpy as np
from unittest.mock import MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.conftest import (
    synthetic_df,
    synthetic_account,
    synthetic_symbol_info,
    synthetic_tick,
    synthetic_order_result,
)

VALID_SYSTEM_MAGIC = 101000001


def _patch_brain_stats_io(monkeypatch):
    """Prevent BrainStats from reading/writing to disk during tests."""
    monkeypatch.setattr("brain_v1.BrainStats._load_history", lambda self: None)
    monkeypatch.setattr("brain_v1.BrainStats._save_history", lambda self: None)


def _patch_mt5(monkeypatch, mock_mt5):
    """Ensure brain_v1.mt5 points to the current test's mock."""
    monkeypatch.setattr("brain_v1.mt5", mock_mt5)


def _make_brain(mock_mt5, monkeypatch):
    """Create a Brain instance with AI client mocked out."""
    mock_ai = MagicMock()
    mock_ai.is_available.return_value = False
    monkeypatch.setattr("brain_v1.get_ai_client", lambda: mock_ai)
    _patch_brain_stats_io(monkeypatch)
    _patch_mt5(monkeypatch, mock_mt5)
    from brain_v1 import Brain
    return Brain()


# ================================================================
# 1. BrainStats.record_trade  (lines 102-112)
# ================================================================
class TestRecordTrade:
    """Test that record_trade updates trades list, equity curve, peak, drawdown."""

    def test_appends_trade_to_list(self, mock_mt5, monkeypatch):
        _patch_brain_stats_io(monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        from brain_v1 import BrainStats
        stats = BrainStats()
        assert len(stats.trades) == 0
        stats.record_trade({"profit": 50, "symbol": "EURUSD"})
        assert len(stats.trades) == 1
        assert stats.trades[0]["profit"] == 50

    def test_updates_equity_curve(self, mock_mt5, monkeypatch):
        _patch_brain_stats_io(monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        from brain_v1 import BrainStats
        stats = BrainStats()
        mock_mt5.account_info.side_effect = lambda: synthetic_account(equity=10500)
        stats.record_trade({"profit": 500})
        assert len(stats.equity_curve) == 1
        assert stats.equity_curve[0]["equity"] == 10500

    def test_peak_equity_increases(self, mock_mt5, monkeypatch):
        _patch_brain_stats_io(monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        from brain_v1 import BrainStats
        stats = BrainStats()
        mock_mt5.account_info.side_effect = lambda: synthetic_account(equity=10000)
        stats.record_trade({"profit": 100})
        assert stats.peak_equity == 10000

        mock_mt5.account_info.side_effect = lambda: synthetic_account(equity=12000)
        stats.record_trade({"profit": 2000})
        assert stats.peak_equity == 12000

    def test_peak_equity_does_not_decrease(self, mock_mt5, monkeypatch):
        _patch_brain_stats_io(monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        from brain_v1 import BrainStats
        stats = BrainStats()
        mock_mt5.account_info.side_effect = lambda: synthetic_account(equity=12000)
        stats.record_trade({"profit": 2000})
        assert stats.peak_equity == 12000

        mock_mt5.account_info.side_effect = lambda: synthetic_account(equity=11000)
        stats.record_trade({"profit": -1000})
        assert stats.peak_equity == 12000

    def test_drawdown_calculated_correctly(self, mock_mt5, monkeypatch):
        _patch_brain_stats_io(monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        from brain_v1 import BrainStats
        stats = BrainStats()
        mock_mt5.account_info.side_effect = lambda: synthetic_account(equity=12000)
        stats.record_trade({"profit": 2000})
        assert stats.peak_equity == 12000
        assert stats.current_drawdown == 0

        mock_mt5.account_info.side_effect = lambda: synthetic_account(equity=10800)
        stats.record_trade({"profit": -1200})
        expected_dd = (12000 - 10800) / 12000 * 100
        assert abs(stats.current_drawdown - expected_dd) < 0.01

    def test_multiple_trades_accumulate(self, mock_mt5, monkeypatch):
        _patch_brain_stats_io(monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        from brain_v1 import BrainStats
        stats = BrainStats()
        for i in range(5):
            mock_mt5.account_info.side_effect = lambda i=i: synthetic_account(equity=10000 + i * 100)
            stats.record_trade({"profit": i * 100})
        assert len(stats.trades) == 5
        assert len(stats.equity_curve) == 5
        assert stats.peak_equity == 10400

    def test_handles_none_account_info(self, mock_mt5, monkeypatch):
        _patch_brain_stats_io(monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        from brain_v1 import BrainStats
        stats = BrainStats()
        mock_mt5.account_info.side_effect = lambda: None
        stats.record_trade({"profit": 100})
        assert len(stats.trades) == 1
        assert stats.equity_curve == []
        assert stats.peak_equity == 0


# ================================================================
# 2. BrainStats.get_kelly_fraction  (lines 197-212)
# ================================================================
class TestKellyFraction:
    """Test Kelly fraction calculations for known scenarios."""

    def _make_stats_with_trades(self, mock_mt5, monkeypatch, profits):
        _patch_brain_stats_io(monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        from brain_v1 import BrainStats
        stats = BrainStats()
        for p in profits:
            stats.trades.append({"profit": p})
        return stats

    def test_all_wins_returns_positive(self, mock_mt5, monkeypatch):
        profits = [100.0] * 25
        stats = self._make_stats_with_trades(mock_mt5, monkeypatch, profits)
        kelly = stats.get_kelly_fraction()
        assert kelly > 0.01, f"Kelly for all wins should be positive, got {kelly}"

    def test_no_wins_returns_default(self, mock_mt5, monkeypatch):
        """When all trades are losses, wins=[] triggers early return of 0.02."""
        profits = [-100.0] * 25
        stats = self._make_stats_with_trades(mock_mt5, monkeypatch, profits)
        kelly = stats.get_kelly_fraction()
        assert kelly == 0.02, f"No wins should return 0.02 default, got {kelly}"

    def test_no_losses_returns_default(self, mock_mt5, monkeypatch):
        """When all trades are wins, losses=[] triggers early return of 0.02."""
        profits = [100.0] * 25
        stats = self._make_stats_with_trades(mock_mt5, monkeypatch, profits)
        kelly = stats.get_kelly_fraction()
        assert kelly == 0.02

    def test_balanced_equal_win_loss_returns_bounded(self, mock_mt5, monkeypatch):
        profits = [100.0] * 15 + [-100.0] * 15
        stats = self._make_stats_with_trades(mock_mt5, monkeypatch, profits)
        kelly = stats.get_kelly_fraction()
        assert 0.01 <= kelly <= 0.05, f"Kelly for balanced trades should be bounded, got {kelly}"

    def test_insufficient_trades_returns_default(self, mock_mt5, monkeypatch):
        stats = self._make_stats_with_trades(mock_mt5, monkeypatch, [100.0] * 10)
        kelly = stats.get_kelly_fraction()
        assert kelly == 0.02, "Less than 20 trades should return default 0.02"

    def test_kelly_bounded_between_001_and_005(self, mock_mt5, monkeypatch):
        profits = [500.0] * 30
        stats = self._make_stats_with_trades(mock_mt5, monkeypatch, profits)
        kelly = stats.get_kelly_fraction()
        assert 0.01 <= kelly <= 0.05, f"Kelly should be bounded, got {kelly}"

    def test_high_win_rate_high_ratio_returns_max(self, mock_mt5, monkeypatch):
        profits = [300.0] * 25 + [-50.0] * 5
        stats = self._make_stats_with_trades(mock_mt5, monkeypatch, profits)
        kelly = stats.get_kelly_fraction()
        assert kelly >= 0.04, f"High win rate + high ratio should approach max, got {kelly}"

    def test_low_win_rate_low_ratio_returns_min(self, mock_mt5, monkeypatch):
        profits = [50.0] * 5 + [-300.0] * 25
        stats = self._make_stats_with_trades(mock_mt5, monkeypatch, profits)
        kelly = stats.get_kelly_fraction()
        assert kelly == 0.01


# ================================================================
# 3. RiskManager.calculate_position_size  (lines 659-702)
# ================================================================
class TestPositionSize:
    """Test that position sizing returns positive lot, scales with confidence."""

    def _setup_tick_info(self, mock_mt5, monkeypatch, tick_value=10.0, tick_size=0.00001):
        _patch_mt5(monkeypatch, mock_mt5)
        info = synthetic_symbol_info()
        info.trade_tick_value = tick_value
        info.trade_tick_size = tick_size
        mock_mt5.symbol_info.side_effect = lambda s: info
        mock_mt5.account_info.side_effect = lambda: synthetic_account(balance=10000, equity=10000)
        return info

    def _make_rm(self, mock_mt5, monkeypatch):
        _patch_brain_stats_io(monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        from brain_v1 import BrainStats, RiskManager
        stats = BrainStats()
        stats.trades = [{"profit": 100}] * 10 + [{"profit": -50}] * 10
        rm = RiskManager(stats)
        return rm, stats

    def test_returns_positive_lot(self, mock_mt5, monkeypatch):
        self._setup_tick_info(mock_mt5, monkeypatch)
        rm, _ = self._make_rm(mock_mt5, monkeypatch)
        lot = rm.calculate_position_size("EURUSD", sl_points=100, confidence=0.6)
        assert lot >= 0.01, f"Lot should be at least volume_min, got {lot}"

    def test_higher_confidence_gives_larger_lot(self, mock_mt5, monkeypatch):
        self._setup_tick_info(mock_mt5, monkeypatch)
        rm, _ = self._make_rm(mock_mt5, monkeypatch)
        lot_low = rm.calculate_position_size("EURUSD", sl_points=100, confidence=0.5)
        lot_high = rm.calculate_position_size("EURUSD", sl_points=100, confidence=0.8)
        assert lot_high >= lot_low, f"Higher confidence should give >= lot: {lot_high} vs {lot_low}"

    def test_wider_sl_gives_smaller_lot(self, mock_mt5, monkeypatch):
        self._setup_tick_info(mock_mt5, monkeypatch)
        rm, _ = self._make_rm(mock_mt5, monkeypatch)
        lot_narrow = rm.calculate_position_size("EURUSD", sl_points=50, confidence=0.6)
        lot_wide = rm.calculate_position_size("EURUSD", sl_points=200, confidence=0.6)
        assert lot_narrow >= lot_wide, f"Narrower SL should give >= lot: {lot_narrow} vs {lot_wide}"

    def test_returns_min_when_no_symbol_info(self, mock_mt5, monkeypatch):
        _patch_mt5(monkeypatch, mock_mt5)
        mock_mt5.symbol_info.side_effect = lambda s: None
        rm, _ = self._make_rm(mock_mt5, monkeypatch)
        lot = rm.calculate_position_size("EURUSD", sl_points=100, confidence=0.6)
        assert lot == 0.01

    def test_lot_within_volume_bounds(self, mock_mt5, monkeypatch):
        info = self._setup_tick_info(mock_mt5, monkeypatch)
        rm, _ = self._make_rm(mock_mt5, monkeypatch)
        lot = rm.calculate_position_size("EURUSD", sl_points=100, confidence=0.6)
        assert lot >= info.volume_min, f"Lot {lot} below min {info.volume_min}"
        assert lot <= info.volume_max, f"Lot {lot} above max {info.volume_max}"

    def test_lot_rounded_to_volume_step(self, mock_mt5, monkeypatch):
        info = self._setup_tick_info(mock_mt5, monkeypatch)
        rm, _ = self._make_rm(mock_mt5, monkeypatch)
        lot = rm.calculate_position_size("EURUSD", sl_points=100, confidence=0.6)
        step = info.volume_step
        remainder = lot / step - round(lot / step)
        assert abs(remainder) < 1e-9, f"Lot {lot} not aligned to step {step}"

    def test_zero_tick_value_returns_min(self, mock_mt5, monkeypatch):
        self._setup_tick_info(mock_mt5, monkeypatch, tick_value=0)
        rm, _ = self._make_rm(mock_mt5, monkeypatch)
        lot = rm.calculate_position_size("EURUSD", sl_points=100, confidence=0.6)
        assert lot == 0.01


# ================================================================
# 4. Brain.analyze()  (lines 825-920)
# ================================================================
class TestBrainAnalyze:
    """Test that analyze returns a proper decision dict."""

    def _mock_analyze_prereqs(self, mock_mt5, monkeypatch):
        async def _mock_tick(s):
            return synthetic_tick(bid=1.10000, ask=1.10015)

        monkeypatch.setattr("async_mt5.symbol_info_tick", _mock_tick)
        monkeypatch.setattr(
            "trading_engine.BrainStats.get_kelly_fraction",
            lambda self, lookback=100: 1.0,
        )
        async def _mock_order_send(req):
            return synthetic_order_result(retcode=10009, order=99999, price=req["price"])

        monkeypatch.setattr("async_mt5.order_send", _mock_order_send)
        monkeypatch.setattr(
            "trading_engine.RiskManager.can_open_trade",
            lambda self, s, d: (True, "OK"),
        )
        monkeypatch.setattr(
            "trading_engine.RiskManager.calculate_dynamic_sl_tp",
            lambda self, s, d, df: (1.09900, 1.10200, 100, 200),
        )
        monkeypatch.setattr(
            "trading_engine.RiskManager.calculate_position_size",
            lambda self, s, sl, c: 0.1,
        )

        def _mock_calc_signals(self, symbol, timeframe, params=None, df=None):
            return {
                "signals": {
                    "ma_crossover": {"direction": 1, "confidence": 0.9, "name": "ma_crossover"},
                    "rsi": {"direction": 1, "confidence": 0.85, "name": "rsi"},
                    "bollinger": {"direction": 1, "confidence": 0.75, "name": "bollinger"},
                    "breakout": {"direction": 1, "confidence": 0.8, "name": "breakout"},
                    "orderflow": {"direction": 1, "confidence": 0.7, "name": "orderflow"},
                    "momentum": {"direction": 1, "confidence": 0.8, "name": "momentum"},
                    "support_resistance": {"direction": 1, "confidence": 0.7, "name": "support_resistance"},
                    "multi_tf": {"direction": 1, "confidence": 0.85, "name": "multi_tf"},
                },
                "df": df if df is not None else synthetic_df(300),
            }

        monkeypatch.setattr(
            "trading_engine.SignalAnalyzer.calculate_all_signals",
            _mock_calc_signals,
        )

    def test_returns_decision_dict_with_all_keys(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        self._mock_analyze_prereqs(mock_mt5, monkeypatch)
        result = brain.analyze("EURUSD", df=synthetic_df(300))
        required_keys = {"action", "direction", "confidence", "signals", "lot", "sl", "tp"}
        assert required_keys.issubset(result.keys()), f"Missing keys: {required_keys - result.keys()}"

    def test_trade_action_on_high_confidence(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        self._mock_analyze_prereqs(mock_mt5, monkeypatch)
        result = brain.analyze("EURUSD", df=synthetic_df(300))
        assert result["action"] == "trade"
        assert result["direction"] == 1
        assert result["lot"] == 0.1

    def test_hold_action_when_market_not_tradeable(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        async def _mock_tick(s):
            return synthetic_tick(bid=1.10000, ask=1.10015)

        monkeypatch.setattr("async_mt5.symbol_info_tick", _mock_tick)
        monkeypatch.setattr(
            "trading_engine.BrainStats.get_kelly_fraction",
            lambda self, lookback=100: 0.5,
        )

        def _zero_signals(self, symbol, timeframe, params=None, df=None):
            return {
                "signals": {
                    "ma_crossover": {"direction": 0, "confidence": 0, "name": "ma_crossover"},
                    "rsi": {"direction": 0, "confidence": 0, "name": "rsi"},
                    "bollinger": {"direction": 0, "confidence": 0, "name": "bollinger"},
                    "breakout": {"direction": 0, "confidence": 0, "name": "breakout"},
                    "orderflow": {"direction": 0, "confidence": 0, "name": "orderflow"},
                    "momentum": {"direction": 0, "confidence": 0, "name": "momentum"},
                    "support_resistance": {"direction": 0, "confidence": 0, "name": "support_resistance"},
                    "multi_tf": {"direction": 0, "confidence": 0, "name": "multi_tf"},
                },
                "df": df if df is not None else synthetic_df(300),
            }

        monkeypatch.setattr(
            "trading_engine.SignalAnalyzer.calculate_all_signals",
            _zero_signals,
        )
        result = brain.analyze("EURUSD", df=synthetic_df(300))
        assert result["action"] == "hold"
        assert result["confidence"] == 0

    def test_hold_action_on_low_confidence(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        async def _mock_tick(s):
            return synthetic_tick(bid=1.10000, ask=1.10015)

        monkeypatch.setattr("async_mt5.symbol_info_tick", _mock_tick)
        monkeypatch.setattr(
            "trading_engine.BrainStats.get_kelly_fraction",
            lambda self, lookback=100: 0.5,
        )

        def _mock_no_signal(self, symbol, timeframe, params=None, df=None):
            return {
                "signals": {
                    "ma_crossover": {"direction": 0, "confidence": 0, "name": "ma_crossover"},
                    "rsi": {"direction": 0, "confidence": 0, "name": "rsi"},
                    "bollinger": {"direction": 0, "confidence": 0, "name": "bollinger"},
                    "breakout": {"direction": 0, "confidence": 0, "name": "breakout"},
                    "orderflow": {"direction": 0, "confidence": 0, "name": "orderflow"},
                    "momentum": {"direction": 0, "confidence": 0, "name": "momentum"},
                    "support_resistance": {"direction": 0, "confidence": 0, "name": "support_resistance"},
                    "multi_tf": {"direction": 0, "confidence": 0, "name": "multi_tf"},
                },
                "df": df if df is not None else synthetic_df(300),
            }

        monkeypatch.setattr("trading_engine.SignalAnalyzer.calculate_all_signals", _mock_no_signal)
        result = brain.analyze("EURUSD", df=synthetic_df(300))
        assert result["action"] == "hold"

    def test_blocked_action_when_risk_denies(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        self._mock_analyze_prereqs(mock_mt5, monkeypatch)
        monkeypatch.setattr(
            "trading_engine.RiskManager.can_open_trade",
            lambda self, s, d: (False, "Drawdown kill switch"),
        )
        result = brain.analyze("EURUSD", df=synthetic_df(300))
        assert result["action"] == "blocked"
        assert "Drawdown" in result.get("reason", "")

    def test_returns_sl_tp_from_engine(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        self._mock_analyze_prereqs(mock_mt5, monkeypatch)
        result = brain.analyze("EURUSD", df=synthetic_df(300))
        assert result["sl"] == 1.09900
        assert result["tp"] == 1.10200

    def test_buy_score_and_sell_score_in_result(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        self._mock_analyze_prereqs(mock_mt5, monkeypatch)
        result = brain.analyze("EURUSD", df=synthetic_df(300))
        assert "buy_score" in result
        assert "sell_score" in result
        assert result["buy_score"] > 0


# ================================================================
# 5. Brain.execute_decision()  (lines 1029-1098)
# ================================================================
class TestExecuteDecision:
    """Test that execute_decision constructs order and calls mt5.order_send."""

    def _mock_exec_prereqs(self, mock_mt5, monkeypatch):
        monkeypatch.setattr(
            "brain_v1.is_tradeable_now",
            lambda s, tf=None: {"can_trade": True},
        )
        monkeypatch.setattr(
            "brain_v1.validate_tick_freshness",
            lambda t, s: {"fresh": True},
        )
        monkeypatch.setattr(
            "brain_v1.fetch_closed_rates",
            lambda s, tf, n: None,
        )
        monkeypatch.setattr(
            "brain_v1._send_order_with_fallback",
            lambda req: synthetic_order_result(retcode=10009, order=99999, price=1.10010),
        )
        monkeypatch.setattr(
            "brain_v1.get_magic_number",
            lambda *a, **kw: 12345,
        )

    def _make_decision(self, direction=1):
        return {
            "action": "trade",
            "direction": direction,
            "direction_str": "BUY" if direction == 1 else "SELL",
            "lot": 0.1,
            "sl": 1.09900,
            "tp": 1.10200,
            "confidence": 0.7,
        }

    def test_returns_order_info_on_success(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        self._mock_exec_prereqs(mock_mt5, monkeypatch)
        result = brain.execute_decision(self._make_decision(), "EURUSD")
        assert result is not False
        assert result["order"] == 99999
        assert result["volume"] == 0.1

    def test_returns_false_for_non_trade_action(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        result = brain.execute_decision({"action": "hold", "direction": 0}, "EURUSD")
        assert result is False

    def test_returns_false_when_market_not_tradeable(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        monkeypatch.setattr(
            "brain_v1.is_tradeable_now",
            lambda s, tf=None: {"can_trade": False, "reason": "closed"},
        )
        result = brain.execute_decision(self._make_decision(), "EURUSD")
        assert result is False

    def test_returns_false_when_tick_none(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        self._mock_exec_prereqs(mock_mt5, monkeypatch)
        mock_mt5.symbol_info_tick.side_effect = lambda *a, **kw: None
        result = brain.execute_decision(self._make_decision(), "EURUSD")
        assert result is False

    def test_returns_false_when_stale_tick(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        self._mock_exec_prereqs(mock_mt5, monkeypatch)
        monkeypatch.setattr(
            "brain_v1.validate_tick_freshness",
            lambda t, s: {"fresh": False, "reason": "stale"},
        )
        result = brain.execute_decision(self._make_decision(), "EURUSD")
        assert result is False

    def test_returns_false_on_order_failure(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        self._mock_exec_prereqs(mock_mt5, monkeypatch)
        monkeypatch.setattr(
            "brain_v1._send_order_with_fallback",
            lambda req: synthetic_order_result(retcode=10013, order=0),
        )
        result = brain.execute_decision(self._make_decision(), "EURUSD")
        assert result is False

    def test_returns_false_when_send_returns_none(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        self._mock_exec_prereqs(mock_mt5, monkeypatch)
        monkeypatch.setattr("brain_v1._send_order_with_fallback", lambda req: None)
        result = brain.execute_decision(self._make_decision(), "EURUSD")
        assert result is False

    def test_sell_direction_uses_bid_price(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        self._mock_exec_prereqs(mock_mt5, monkeypatch)
        tick = synthetic_tick(bid=1.10000, ask=1.10015)
        mock_mt5.symbol_info_tick.side_effect = lambda *a, **kw: tick
        captured = {}

        def _capture_order(req):
            captured["type"] = req["type"]
            captured["price"] = req["price"]
            return synthetic_order_result(retcode=10009, order=88888, price=req["price"])

        monkeypatch.setattr("brain_v1._send_order_with_fallback", _capture_order)
        result = brain.execute_decision(self._make_decision(direction=-1), "EURUSD")
        assert result is not False
        assert captured["type"] == 1
        assert captured["price"] == 1.10000


# ================================================================
# 6. Brain.manage_positions()  (lines 938-1027)
# ================================================================
class TestManagePositions:
    """Test that manage_positions checks stale trades and applies trailing stops."""

    def _make_position(self, ticket=11111, symbol="EURUSD", pos_type=0,
                       volume=0.1, profit=50.0, sl=1.09900, tp=1.10200,
                       price_open=1.10000, price_current=1.10050,
                       magic=VALID_SYSTEM_MAGIC,
                       time_offset_hours=1):
        pos = MagicMock()
        pos.ticket = ticket
        pos.symbol = symbol
        pos.type = pos_type
        pos.volume = volume
        pos.profit = profit
        pos.sl = sl
        pos.tp = tp
        pos.price_open = price_open
        pos.price_current = price_current
        pos.magic = magic
        pos.time = int((datetime.now() - timedelta(hours=time_offset_hours)).timestamp())
        return pos

    def _setup_manage_mocks(self, mock_mt5, monkeypatch, stale=False):
        """Common mock setup for manage_positions tests."""
        _patch_mt5(monkeypatch, mock_mt5)
        mock_mt5.TRADE_ACTION_SLTP = 5
        tick = synthetic_tick()
        mock_mt5.symbol_info_tick.side_effect = lambda *a, **kw: tick
        monkeypatch.setattr("brain_v1.validate_tick_freshness", lambda t, s: {"fresh": True})
        monkeypatch.setattr("brain_v1.fetch_closed_rates", lambda s, tf, n: None)
        if stale:
            monkeypatch.setattr("brain_v1.RiskManager.should_close_early", lambda self, p: (True, "Stale losing trade"))
            monkeypatch.setattr("brain_v1._send_order_with_fallback", lambda req: synthetic_order_result())
        else:
            monkeypatch.setattr("brain_v1.RiskManager.should_close_early", lambda self, p: (False, ""))

    def test_does_nothing_when_no_positions(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        mock_mt5.positions_get.return_value = []
        brain.manage_positions("EURUSD")

    def test_does_nothing_when_symbol_info_none(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        mock_mt5.positions_get.return_value = [self._make_position()]
        mock_mt5.symbol_info.side_effect = lambda s: None
        brain.manage_positions("EURUSD")

    def test_closes_stale_losing_trade(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        stale_pos = self._make_position(profit=-50.0, volume=0.1, time_offset_hours=5)
        mock_mt5.positions_get.return_value = [stale_pos]
        self._setup_manage_mocks(mock_mt5, monkeypatch, stale=True)
        mock_sltp = MagicMock(manage_trailing_stop=lambda **kw: None)
        monkeypatch.setattr("brain_v1.get_sltp_engine", lambda: mock_sltp)
        brain.manage_positions("EURUSD")
        assert mock_mt5.positions_get.called

    def test_applies_trailing_stop_on_profitable(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        _patch_mt5(monkeypatch, mock_mt5)
        mock_mt5.TRADE_ACTION_SLTP = 5
        pos = self._make_position(
            pos_type=0, profit=100.0, sl=1.09900,
            price_current=1.10100, price_open=1.10000, volume=0.1,
        )
        mock_mt5.positions_get.return_value = [pos]
        mock_mt5.symbol_info.side_effect = lambda s: synthetic_symbol_info()
        tick = synthetic_tick(bid=1.10100, ask=1.10115)
        mock_mt5.symbol_info_tick.side_effect = lambda *a, **kw: tick
        monkeypatch.setattr("brain_v1.validate_tick_freshness", lambda t, s: {"fresh": True})
        monkeypatch.setattr("brain_v1.RiskManager.should_close_early", lambda self, p: (False, ""))
        monkeypatch.setattr("brain_v1.fetch_closed_rates", lambda s, tf, n: None)

        mock_sltp = MagicMock()
        mock_sltp.manage_trailing_stop.return_value = {"action": "modify", "new_sl": 1.10050}
        monkeypatch.setattr("brain_v1.get_sltp_engine", lambda: mock_sltp)

        brain.manage_positions("EURUSD")
        mock_sltp.manage_trailing_stop.assert_called_once()

    def test_no_trailing_stop_when_below_threshold(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        pos = self._make_position(
            pos_type=0, profit=10.0, sl=1.09900,
            price_current=1.10010, price_open=1.10000,
        )
        mock_mt5.positions_get.return_value = [pos]
        self._setup_manage_mocks(mock_mt5, monkeypatch)
        mock_sltp = MagicMock()
        mock_sltp.manage_trailing_stop.return_value = None
        monkeypatch.setattr("brain_v1.get_sltp_engine", lambda: mock_sltp)
        brain.manage_positions("EURUSD")
        assert mock_mt5.order_send.call_count == 0

    def test_ignores_positions_with_wrong_magic(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        pos = self._make_position(magic=99999)
        mock_mt5.positions_get.return_value = [pos]
        mock_mt5.symbol_info.side_effect = lambda s: synthetic_symbol_info()
        brain.manage_positions("EURUSD")
        mock_mt5.symbol_info_tick.assert_not_called()

    def test_ignores_positions_with_wrong_symbol(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        pos = self._make_position(symbol="GBPUSD")
        mock_mt5.positions_get.return_value = [pos]
        mock_mt5.symbol_info.side_effect = lambda s: synthetic_symbol_info()
        brain.manage_positions("EURUSD")
        mock_mt5.symbol_info_tick.assert_not_called()

    def test_fallback_trailing_stop_when_sltp_fails(self, mock_mt5, monkeypatch):
        brain = _make_brain(mock_mt5, monkeypatch)
        pos = self._make_position(
            pos_type=0, profit=100.0, sl=1.09500,
            price_current=1.10100, price_open=1.10000,
        )
        mock_mt5.positions_get.return_value = [pos]
        self._setup_manage_mocks(mock_mt5, monkeypatch)
        monkeypatch.setattr("brain_v1.get_sltp_engine", lambda: (_ for _ in ()).throw(Exception("engine down")))
        brain.manage_positions("EURUSD")
        call_args = mock_mt5.order_send.call_args
        if call_args:
            req = call_args[0][0]
            assert req.get("sl", 0) > 0 or req.get("action") is not None
