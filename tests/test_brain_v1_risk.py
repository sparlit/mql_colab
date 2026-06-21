"""
Tests for brain_v1.py risk management.
Run with: pytest tests/test_brain_v1_risk.py -v
"""
import pytest
import numpy as np
from unittest.mock import MagicMock
import mt5_mcp as mt5


class TestCanOpenTrade:
    """Tests for RiskManager.can_open_trade."""

    def test_can_open_with_no_positions(self, mock_mt5):
        from brain_v1 import BrainStats, RiskManager
        stats = BrainStats()
        rm = RiskManager(stats)
        ok, reason = rm.can_open_trade("EURUSD", 1)
        assert ok is True, f"Should allow trade: {reason}"

    def test_can_open_blocks_on_drawdown(self, mock_mt5):
        from brain_v1 import BrainStats, RiskManager
        stats = BrainStats()
        stats.current_drawdown = 11.0
        rm = RiskManager(stats)
        ok, reason = rm.can_open_trade("EURUSD", 1)
        assert ok is False, "Should block on drawdown"
        assert "Drawdown" in reason

    def test_can_open_blocks_on_daily_loss(self, mock_mt5):
        from brain_v1 import BrainStats, RiskManager
        stats = BrainStats()
        stats.trades = [{"time": str(__import__('datetime').datetime.now().date()), "profit": -300}]
        rm = RiskManager(stats)
        ok, reason = rm.can_open_trade("EURUSD", 1)
        assert ok is False, "Should block on daily loss"

    def test_can_open_allows_when_all_clear(self, mock_mt5):
        from brain_v1 import BrainStats, RiskManager
        stats = BrainStats()
        rm = RiskManager(stats)
        ok, reason = rm.can_open_trade("EURUSD", 1)
        assert ok is True


class TestShouldCloseEarly:
    """Tests for RiskManager.should_close_early."""

    def test_profitable_trade_not_closed_early(self, mock_mt5):
        from brain_v1 import BrainStats, RiskManager
        stats = BrainStats()
        rm = RiskManager(stats)
        position = MagicMock()
        position.profit = 100.0
        position.volume = 0.1
        position.time = __import__('datetime').datetime.now().timestamp()
        position.magic = 12345
        should, reason = rm.should_close_early(position)
        assert should is False, "Profitable trade should not be closed early"
