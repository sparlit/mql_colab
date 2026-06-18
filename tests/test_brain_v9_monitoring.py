"""
Tests for brain_v9.py TradingProgressTracker and SystemMonitor.
Run with: pytest tests/test_brain_v9_monitoring.py -v
"""
import sys
import types
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime


# ---- Mock config and psutil before importing brain_v9 ----
@pytest.fixture(autouse=True)
def mock_config(monkeypatch):
    cfg = types.ModuleType('config')
    cfg.MAGIC_NUMBER = 99999
    cfg.DATA_DIR = "/tmp/test_data"
    cfg.LOG_DIR = "/tmp/test_logs"
    monkeypatch.setitem(sys.modules, 'config', cfg)
    return cfg


@pytest.fixture
def mock_psutil(monkeypatch):
    """Mock psutil so monitors have data without calling real OS APIs."""
    ps = types.ModuleType('psutil')
    def _cpu_percent(**kwargs):
        if kwargs.get('percpu'):
            return [45.0, 38.0, 52.0, 41.0]
        return 45.0

    ps.cpu_percent = MagicMock(side_effect=_cpu_percent)
    ps.cpu_count = MagicMock(return_value=8)
    ps.cpu_freq = MagicMock(return_value=MagicMock(current=2400, max=3600))
    ps.getloadavg = MagicMock(return_value=(1.0, 1.5, 2.0))
    ps.virtual_memory = MagicMock(return_value=MagicMock(
        total=16 * 1024**3, used=6 * 1024**3, available=10 * 1024**3, percent=37.5
    ))
    ps.swap_memory = MagicMock(return_value=MagicMock(
        total=4 * 1024**3, used=0.5 * 1024**3, percent=12.5
    ))
    ps.disk_partitions = MagicMock(return_value=[])
    ps.boot_time = MagicMock(return_value=0)
    ps.process_iter = MagicMock(return_value=iter([]))
    monkeypatch.setitem(sys.modules, 'psutil', ps)
    return ps


# ==========================================
# TradingProgressTracker
# ==========================================
class TestTradingProgressTracker:
    def test_record_trade_updates_pnl_and_counts(self):
        from brain_v9 import TradingProgressTracker
        tracker = TradingProgressTracker()
        tracker.record_trade(50.0)
        tracker.record_trade(-30.0)
        tracker.record_trade(10.0)
        assert tracker.session_trades == 3
        assert tracker.session_wins == 2
        assert tracker.session_losses == 1
        assert tracker.session_pnl == pytest.approx(30.0)

    def test_record_trade_zero_counted_as_win(self):
        from brain_v9 import TradingProgressTracker
        tracker = TradingProgressTracker()
        tracker.record_trade(0.0)
        assert tracker.session_wins == 1
        assert tracker.session_losses == 0

    def test_update_equity_tracks_peak_and_drawdown(self):
        from brain_v9 import TradingProgressTracker
        tracker = TradingProgressTracker()
        tracker.session_peak_equity = 10000
        tracker.update_equity(10500)
        assert tracker.session_peak_equity == 10500
        assert tracker.session_max_drawdown == 0
        tracker.update_equity(9500)
        assert tracker.session_peak_equity == 10500
        assert tracker.session_max_drawdown == pytest.approx((10500 - 9500) / 10500 * 100, rel=1e-6)

    def test_update_equity_zero_peak_no_division(self):
        from brain_v9 import TradingProgressTracker
        tracker = TradingProgressTracker()
        tracker.update_equity(0)
        assert tracker.session_max_drawdown == 0

    def test_get_progress_returns_expected_keys(self):
        from brain_v9 import TradingProgressTracker
        tracker = TradingProgressTracker()
        progress = tracker.get_progress()
        expected_keys = {
            "session_duration_hours", "session_trades", "session_wins",
            "session_losses", "session_win_rate", "session_pnl",
            "session_max_drawdown", "trades_per_hour", "target_progress",
        }
        assert expected_keys.issubset(progress.keys())
        assert isinstance(progress["target_progress"], dict)
        assert "trades" in progress["target_progress"]
        assert "profit" in progress["target_progress"]

    def test_get_progress_win_rate_calculation(self):
        from brain_v9 import TradingProgressTracker
        tracker = TradingProgressTracker()
        tracker.record_trade(10.0)
        tracker.record_trade(10.0)
        tracker.record_trade(-5.0)
        progress = tracker.get_progress()
        assert progress["session_win_rate"] == pytest.approx(66.7, abs=0.5)

    def test_get_trade_rate_returns_zero_initially(self):
        from brain_v9 import TradingProgressTracker
        tracker = TradingProgressTracker()
        rate = tracker.get_trade_rate()
        assert rate == 0


# ==========================================
# SystemMonitor
# ==========================================
class TestSystemMonitor:
    def test_get_health_score_returns_value_between_0_100(self, mock_psutil):
        from brain_v9 import SystemMonitor
        monitor = SystemMonitor()
        score = monitor.get_health_score()
        assert 0 <= score <= 100

    def test_full_check_returns_dict_with_all_metrics(self, mock_psutil):
        from brain_v9 import SystemMonitor
        monitor = SystemMonitor()
        result = monitor.full_check()
        assert isinstance(result, dict)
        assert "cpu" in result
        assert "memory" in result
        assert "processes" in result
        assert "disk" in result
        assert "system_info" in result
        assert "timestamp" in result

    def test_full_check_cpu_has_overall(self, mock_psutil):
        from brain_v9 import SystemMonitor
        monitor = SystemMonitor()
        result = monitor.full_check()
        assert "overall" in result["cpu"]

    def test_full_check_memory_has_percent(self, mock_psutil):
        from brain_v9 import SystemMonitor
        monitor = SystemMonitor()
        result = monitor.full_check()
        assert "percent" in result["memory"]

    def test_get_alerts_returns_list(self, mock_psutil):
        from brain_v9 import SystemMonitor
        monitor = SystemMonitor()
        alerts = monitor.get_alerts()
        assert isinstance(alerts, list)

    def test_log_system_adds_entry(self, mock_psutil):
        from brain_v9 import SystemMonitor
        monitor = SystemMonitor()
        entry = monitor.log_system("test", "test message")
        assert entry["category"] == "test"
        assert entry["message"] == "test message"

    def test_health_score_full_when_no_load(self, mock_psutil):
        from brain_v9 import SystemMonitor
        monitor = SystemMonitor()
        # Manually set low averages
        monitor.cpu.usage_history.clear()
        monitor.memory.usage_history.clear()
        monitor.disk_usage = {}
        score = monitor.get_health_score()
        assert score == 100

    def test_check_alerts_triggers_on_high_cpu(self, mock_psutil):
        from brain_v9 import SystemMonitor
        monitor = SystemMonitor()
        cpu_data = {"overall": 95.0}
        mem_data = {"percent": 30.0}
        disk_data = {}
        monitor._check_alerts(cpu_data, mem_data, disk_data)
        alerts = monitor.get_alerts()
        assert len(alerts) > 0
        assert alerts[-1]["type"] == "cpu_high"

    def test_check_alerts_triggers_on_high_memory(self, mock_psutil):
        from brain_v9 import SystemMonitor
        monitor = SystemMonitor()
        cpu_data = {"overall": 30.0}
        mem_data = {"percent": 90.0}
        disk_data = {}
        monitor._check_alerts(cpu_data, mem_data, disk_data)
        alerts = monitor.get_alerts()
        assert any(a["type"] == "memory_high" for a in alerts)

    def test_check_alerts_triggers_on_high_disk(self, mock_psutil):
        from brain_v9 import SystemMonitor
        monitor = SystemMonitor()
        cpu_data = {"overall": 30.0}
        mem_data = {"percent": 30.0}
        disk_data = {"C:\\": {"percent": 95.0}}
        monitor._check_alerts(cpu_data, mem_data, disk_data)
        alerts = monitor.get_alerts()
        assert any(a["type"] == "disk_high" for a in alerts)
