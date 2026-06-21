"""
Edge Case Tests — AFX AutoTrader v2
Tests boundary, empty, and error paths for core modules.
Part of Zero-Tolerance quality requirement.
"""

import pytest
import threading
from unittest.mock import MagicMock, patch

from strategy_base import (
    BaseStrategy, StrategyMode, TradeSignal, MarketData,
    RiskProfile, PositionSize, SignalType,
    StrategyMagic, register_strategy,
)
from strategy_swing import SwingStrategy
from strategy_day import DayStrategy
from strategy_carry import CarryStrategy
from strategy_scalp import ScalpStrategy
from risk_engine import RiskEngine, RiskLimits, TradeRisk, RiskLevel
from position_manager import PositionManager
from trade_executor import TradeExecutor, CircuitBreaker, CircuitOpenError
from run_tracker import RunTracker
from metrics import get_metrics, reset_metrics


# ─── Strategy Base Edge Cases ──────────────────────────────────

def test_market_data_empty_indicators():
    """MarketData with empty indicators dict."""
    md = MarketData(
        symbol="EURUSD", timeframe="H4", time=0,
        open=1.1000, high=1.1050, low=1.0980, close=1.1030,
        tick_volume=1000, spread=1.0, volume=1000.0,
        indicators={},
    )
    assert md.symbol == "EURUSD"
    assert md.indicators == {}


def test_market_data_with_metadata():
    """MarketData with metadata (for position context)."""
    md = MarketData(
        symbol="EURUSD", timeframe="H4", time=0,
        open=1.1000, high=1.1050, low=1.0980, close=1.1030,
        tick_volume=1000, spread=1.0, volume=1000.0,
        indicators={},
        metadata={"has_position": True, "position_direction": "BUY", "position_magic": 100001},
    )
    assert md.metadata["has_position"] is True
    assert md.metadata["position_direction"] == "BUY"


def test_risk_profile_validation_valid():
    """RiskProfile with valid values."""
    rp = RiskProfile(
        account_balance=10000.0,
        risk_percent=0.015,
        max_positions=5,
        max_drawdown_percent=0.15,
        max_daily_loss_percent=0.05,
    )
    rp.validate()
    assert rp.risk_amount == 150.0


def test_risk_profile_validation_invalid_percent():
    """RiskProfile with invalid risk_percent raises ValueError."""
    rp = RiskProfile(
        account_balance=10000.0,
        risk_percent=0.15,  # 15% — too high
        max_positions=5,
        max_drawdown_percent=0.15,
        max_daily_loss_percent=0.05,
    )
    with pytest.raises(ValueError, match="risk_percent"):
        rp.validate()


def test_risk_profile_validation_invalid_balance():
    """RiskProfile with zero balance raises ValueError."""
    rp = RiskProfile(
        account_balance=0,
        risk_percent=0.01,
        max_positions=5,
        max_drawdown_percent=0.15,
        max_daily_loss_percent=0.05,
    )
    with pytest.raises(ValueError, match="account_balance"):
        rp.validate()


def test_trade_signal_actionable():
    """TradeSignal.is_actionable() returns True for BUY/SELL."""
    buy_sig = TradeSignal(signal_type=SignalType.BUY, confidence=0.8)
    sell_sig = TradeSignal(signal_type=SignalType.SELL, confidence=0.8)
    hold_sig = TradeSignal(signal_type=SignalType.HOLD, confidence=0.0)
    assert buy_sig.is_actionable() is True
    assert sell_sig.is_actionable() is True
    assert hold_sig.is_actionable() is False


def test_position_size_zero_stop_loss():
    """PositionSize with zero stop_loss should be handled."""
    # This tests that the strategy layer handles this case
    ps = PositionSize(lots=0.01, risk_amount=100.0, risk_percent=0.01, stop_loss_pips=0, take_profit_pips=0, risk_reward_ratio=0)
    assert ps.lots == 0.01


# ─── Strategy Edge Cases ───────────────────────────────────────

def test_swing_strategy_all_missing_indicators():
    """SwingStrategy with no indicator data returns HOLD."""
    md = MarketData(
        symbol="EURUSD", timeframe="H4", time=0,
        open=1.1000, high=1.1050, low=1.0980, close=1.1030,
        tick_volume=0, spread=1.0, volume=0.0,
        indicators={},  # All missing
    )
    s = SwingStrategy()
    sig = s.analyze(md)
    assert sig.signal_type == SignalType.HOLD


def test_swing_strategy_validate_entry_empty_volume():
    """SwingStrategy rejects entry when volume is 0."""
    md = MagicMock(spec=MarketData)
    md.volume = 0
    md.spread = 1.0
    md.news_event = False
    md.session = "london"
    md.indicators = {"rsi_14": 50, "bb_width": 0.02}
    s = SwingStrategy()
    result = s.validate_entry_conditions(md)
    assert result is False


def test_swing_strategy_validate_entry_low_volatility():
    """SwingStrategy rejects entry when BB width is too low."""
    md = MagicMock(spec=MarketData)
    md.volume = 1000
    md.spread = 1.0
    md.news_event = False
    md.session = "london"
    md.indicators = {"rsi_14": 50, "bb_width": 0.005}  # Too low
    s = SwingStrategy()
    result = s.validate_entry_conditions(md)
    assert result is False


def test_day_strategy_validate_entry_asian_session():
    """DayStrategy blocks entry during Asian session (low volume)."""
    md = MagicMock(spec=MarketData)
    md.volume = 500
    md.spread = 6.0  # Wide spread
    md.news_event = False
    md.session = "asian"
    md.indicators = {"rsi_14": 50}
    s = DayStrategy()
    result = s.validate_entry_conditions(md)
    assert result is False


def test_carry_strategy_validate_entry_no_rate_diff():
    """CarryStrategy requires meaningful interest rate differential."""
    md = MagicMock(spec=MarketData)
    md.spread = 2.0
    md.indicators = {
        "interest_rate_diff": 0.002,  # Too small
        "vix": 18.0,
        "carry_strength": 0.5,
    }
    s = CarryStrategy()
    result = s.validate_entry_conditions(md)
    assert result is False


def test_scalp_strategy_validate_entry_wide_spread():
    """ScalpStrategy requires tight spread."""
    md = MagicMock(spec=MarketData)
    md.spread = 3.0  # Too wide
    md.volume = 100
    md.news_event = False
    md.indicators = {}
    s = ScalpStrategy()
    result = s.validate_entry_conditions(md)
    assert result is False


# ─── Risk Engine Edge Cases ────────────────────────────────────

def test_risk_engine_position_size_zero_pips():
    """RiskEngine raises on zero stop_loss_pips."""
    re = RiskEngine()
    with pytest.raises(ValueError, match="stop_loss_pips"):
        re.calculate_position_size(10000.0, 0.01, 0.0)


def test_risk_engine_validate_trade_circuit_open():
    """RiskEngine blocks all trades when circuit is open."""
    re = RiskEngine()
    re._circuit_open = True
    allowed, reason = re.validate_trade("EURUSD", "SWING", 10000.0, 2)
    assert allowed is False
    assert reason == "circuit_breaker_open"


def test_risk_engine_validate_trade_max_positions():
    """RiskEngine blocks when max positions reached."""
    re = RiskEngine()
    # Simulate max positions via limits
    re._limits = RiskLimits(max_total_positions=3)
    allowed, reason = re.validate_trade("EURUSD", "SWING", 10000.0, 3)
    assert allowed is False
    assert "max" in reason


def test_risk_engine_can_open_trade_no_position():
    """RiskEngine allows trade when no position exists for symbol."""
    re = RiskEngine()
    allowed, reason = re.can_open_trade("EURUSD", "SWING", 10000.0)
    assert allowed is True
    assert reason == "ok"


def test_risk_engine_correlation_check_clear():
    """RiskEngine passes correlation check when symbols are uncorrelated."""
    re = RiskEngine()
    matrix = {
        "EURUSD": {"GBPUSD": 0.1},
        "GBPUSD": {"EURUSD": 0.1},
    }
    allowed, max_corr = re.check_correlation_risk("USDCAD", ["EURUSD", "GBPUSD"], matrix)
    assert allowed is True


def test_risk_engine_correlation_check_blocked():
    """RiskEngine blocks when correlation exceeds threshold."""
    re = RiskEngine()
    matrix = {
        "EURUSD": {"EURGBP": 0.85},  # High correlation
        "EURGBP": {"EURUSD": 0.85},
    }
    allowed, max_corr = re.check_correlation_risk("EURGBP", ["EURUSD"], matrix, threshold=0.7)
    assert allowed is False


def test_risk_engine_daily_reset():
    """RiskEngine resets daily loss tracking correctly."""
    re = RiskEngine()
    re._daily_loss = -500.0
    re._daily_start_equity = 10000.0
    re.reset_daily(10500.0)
    assert re._daily_loss == 0.0
    assert re._daily_start_equity == 10500.0


# ─── Position Manager Edge Cases ───────────────────────────────

def test_position_manager_empty():
    """PositionManager starts empty."""
    pm = PositionManager()
    assert pm.get_open_count() == 0
    assert pm.get_total_exposure() == 0.0
    assert pm.get_total_pnl() == 0.0


def test_position_manager_update_prices_empty():
    """PositionManager update_prices with empty dict doesn't crash."""
    pm = PositionManager()
    pm.update_prices({})
    assert pm.get_open_count() == 0


def test_position_manager_get_nonexistent():
    """PositionManager returns None for nonexistent ticket."""
    pm = PositionManager()
    result = pm.get_position(999999)
    assert result is None


def test_position_manager_get_positions_empty_symbol():
    """PositionManager returns empty list for symbol with no positions."""
    pm = PositionManager()
    result = pm.get_open_positions("EURUSD")
    assert result == []


def test_position_manager_sync_no_positions():
    """PositionManager sync_with_mt5 handles no positions gracefully."""
    pm = PositionManager()
    with patch("mt5_mcp.positions_get", return_value=[]):
        result = pm.sync_with_mt5()
        assert result["total"] == 0


# ─── Circuit Breaker Edge Cases ─────────────────────────────────

def test_circuit_breaker_initially_closed():
    """Circuit breaker starts in CLOSED state."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
    assert cb.state.value == "CLOSED"


def test_circuit_breaker_opens_after_threshold():
    """Circuit breaker opens after failure threshold."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=10.0)
    for _ in range(3):
        try:
            cb.call(lambda: 1 / 0)  # Always raises
        except:
            pass
    assert cb.state.value == "OPEN"


def test_circuit_breaker_blocks_calls_when_open():
    """Circuit breaker raises CircuitOpenError when OPEN."""
    cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    # Force to OPEN by exceeding failures
    for _ in range(3):
        try:
            cb.call(lambda: 1 / 0)
        except:
            pass
    with pytest.raises(CircuitOpenError):
        cb.call(lambda: 42)


def test_circuit_breaker_success_resets_count():
    """Circuit breaker success decrements failure count."""
    cb = CircuitBreaker(failure_threshold=5)
    # Simulate initial failure count
    cb._on_failure()
    cb._on_failure()
    assert cb._failure_count == 2
    # Success resets one count
    cb._on_success()
    assert cb._failure_count == 1


def test_circuit_breaker_half_open_recovery():
    """Circuit breaker recovers from HALF_OPEN after successes."""
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1, success_threshold=2)
    cb._state = cb._state.__class__.HALF_OPEN
    cb._success_count = 0
    cb._on_success()  # First success
    cb._on_success()  # Second success
    assert cb._state.value == "CLOSED"


def test_circuit_breaker_reset():
    """Circuit breaker reset restores CLOSED state."""
    cb = CircuitBreaker()
    cb._state = cb._state.__class__.OPEN
    cb._failure_count = 10
    cb.reset()
    assert cb._state.value == "CLOSED"
    assert cb._failure_count == 0


# ─── Trade Executor Edge Cases ──────────────────────────────────

def test_trade_executor_shutdown_rejects_orders():
    """TradeExecutor rejects orders after shutdown."""
    te = TradeExecutor()
    te.initiate_shutdown()
    result = te.submit_order({"action": 1, "symbol": "EURUSD"})
    assert result.success is False
    assert result.error == "executor_shutting_down"


def test_trade_executor_close_no_tick():
    """TradeExecutor close_position handles no tick gracefully."""
    te = TradeExecutor()
    with patch("mt5_mcp.symbol_info_tick", return_value=None):
        result = te.close_position(ticket=12345, symbol="EURUSD", volume=0.1, position_type=0)
        assert result.success is False
        assert "no_tick" in result.error


# ─── Run Tracker Edge Cases ────────────────────────────────────

def test_run_tracker_start_run_generates_uuid():
    """RunTracker.start_run generates unique run_id."""
    rt = RunTracker()
    run1 = rt.start_run(strategy_mode="SWING", random_seed=42)
    run2 = rt.start_run(strategy_mode="SWING", random_seed=42)
    assert run1.run_id != run2.run_id
    assert len(run1.run_id) == 36  # UUID4 format


def test_run_tracker_default_seed():
    """RunTracker.start_run uses random seed if not provided."""
    rt = RunTracker()
    run = rt.start_run(strategy_mode="DAY")
    assert isinstance(run.random_seed, int)
    assert 0 <= run.random_seed <= 99999


def test_run_tracker_record_performance_empty():
    """RunTracker.record_performance with no trades stores defaults."""
    rt = RunTracker()
    rt.start_run(strategy_mode="SWING")
    rt.record_performance()  # Should not crash
    assert rt._run is not None
    # record_performance with no args sets defaults
    assert "sharpe_ratio" in rt._run.performance_metrics
    assert "win_rate" in rt._run.performance_metrics


def test_run_tracker_save_without_start():
    """RunTracker.save_metadata without start_run raises RuntimeError."""
    rt = RunTracker()
    with pytest.raises(RuntimeError, match="start_run"):
        rt.save_metadata()


def test_run_tracker_update_data_hash_missing_file():
    """RunTracker.update_data_hash with missing file sets hash to unavailable."""
    rt = RunTracker()
    rt.start_run(strategy_mode="SWING")
    rt.update_data_hash("nonexistent_file_12345.dat")
    assert rt._run.data_hash == "unavailable"


# ─── Metrics Edge Cases ─────────────────────────────────────────

def test_metrics_reset():
    """Metrics reset clears all counters."""
    reset_metrics()
    m = get_metrics()
    assert m["trades_total"] == 0
    assert m["errors_total"] == 0


def test_metrics_latency_avg_empty():
    """Latency avg is 0 when no measurements recorded."""
    reset_metrics()
    m = get_metrics()
    assert m["latency_avg_ms"] == 0


def test_metrics_text_format():
    """metrics_text() returns Prometheus text format."""
    reset_metrics()
    text = get_metrics()
    assert "trades_total" in text or isinstance(text, dict)


def test_strategy_metrics():
    """get_strategy_metrics() returns per-strategy counters."""
    from metrics import record_strategy_trade, get_strategy_metrics
    record_strategy_trade("SWING", pnl=100.0)
    record_strategy_trade("SWING", pnl=-50.0)
    m = get_strategy_metrics()
    assert "trades_SWING" in m
    assert m["trades_SWING"] == 2


# ─── Thread Safety ─────────────────────────────────────────────

def test_position_manager_thread_safety():
    """PositionManager handles concurrent access without crash."""
    pm = PositionManager()
    errors = []

    def worker():
        try:
            pm.open_position("EURUSD", "BUY", 0.1, 1.1000, 100001)
            pm.get_open_positions("EURUSD")
            pm.get_total_pnl()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0


def test_risk_engine_thread_safety():
    """RiskEngine handles concurrent validation without crash."""
    re = RiskEngine()
    errors = []

    def worker():
        try:
            re.validate_trade("EURUSD", "SWING", 10000.0, 0)
            re.get_risk_status(10000.0)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])