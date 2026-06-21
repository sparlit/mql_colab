"""
Prometheus Metrics — AFX AutoTrader v2
Entry/exit instrumentation for all critical functions per strategy.
Exposes metrics at /metrics endpoint for Prometheus scraping.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ─── Metric Counters ─────────────────────────────────────────────
_TRADE_COUNTER = 0
_SIGNAL_COUNTER = 0
_ERROR_COUNTER = 0
_CIRCUIT_OPEN_COUNTER = 0
_ORDER_SUCCESS = 0
_ORDER_FAILED = 0
_LATENCY_SUM = 0.0
_LATENCY_COUNT = 0

_METRICS_LOCK = __import__("threading").RLock()


def _inc(name: str, value: int = 1) -> None:
    global _TRADE_COUNTER, _SIGNAL_COUNTER, _ERROR_COUNTER
    global _CIRCUIT_OPEN_COUNTER, _ORDER_SUCCESS, _ORDER_FAILED
    with _METRICS_LOCK:
        if name == "trades":
            _TRADE_COUNTER += value
        elif name == "signals":
            _SIGNAL_COUNTER += value
        elif name == "errors":
            _ERROR_COUNTER += value
        elif name == "circuit_open":
            _CIRCUIT_OPEN_COUNTER += value
        elif name == "order_success":
            _ORDER_SUCCESS += value
        elif name == "order_failed":
            _ORDER_FAILED += value


def _record_latency(latency_ms: float) -> None:
    global _LATENCY_SUM, _LATENCY_COUNT
    with _METRICS_LOCK:
        _LATENCY_SUM += latency_ms
        _LATENCY_COUNT += 1


# ─── Decorator ─────────────────────────────────────────────────
def timed(metric_name: str = ""):
    """Decorator to time function execution and record latency."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as e:
                _inc("errors")
                raise
            finally:
                latency_ms = (time.monotonic() - start) * 1000
                _record_latency(latency_ms)
                if metric_name:
                    logger.debug("%s took %.2fms", metric_name, latency_ms)
        return wrapper
    return decorator


def counted(metric_name: str):
    """Decorator to count function invocations."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            _inc(metric_name)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ─── Metrics Endpoint ─────────────────────────────────────────────

class MetricsCollector(dict):
    """Dict-like metrics container that also exposes object-style API for inc/set_value/observe."""

    def inc(self, name: str, value: int = 1, labels: dict = None) -> None:
        _inc(name, value)

    def set_value(self, name: str, value: float, labels: dict = None) -> None:
        pass

    def observe(self, name: str, value: float, labels: dict = None) -> None:
        pass


_metrics_instance = MetricsCollector()


def get_metrics() -> MetricsCollector:
    """Get current metrics values for Prometheus scraping."""
    with _METRICS_LOCK:
        _metrics_instance.update({
            "trades_total": _TRADE_COUNTER,
            "signals_total": _SIGNAL_COUNTER,
            "errors_total": _ERROR_COUNTER,
            "circuit_open_total": _CIRCUIT_OPEN_COUNTER,
            "orders_success": _ORDER_SUCCESS,
            "orders_failed": _ORDER_FAILED,
            "latency_avg_ms": (_LATENCY_SUM / _LATENCY_COUNT) if _LATENCY_COUNT > 0 else 0,
            "latency_count": _LATENCY_COUNT,
        })
        return _metrics_instance


def metrics_text() -> str:
    """Return Prometheus-formatted metrics text."""
    m = get_metrics()
    return f"""# HELP afx_trades_total Total trade count
# TYPE afx_trades_total counter
afx_trades_total {m["trades_total"]}
# HELP afx_signals_total Total signal count
# TYPE afx_signals_total counter
afx_signals_total {m["signals_total"]}
# HELP afx_errors_total Total error count
# TYPE afx_errors_total counter
afx_errors_total {m["errors_total"]}
# HELP afx_circuit_open_total Circuit breaker opens
# TYPE afx_circuit_open_total counter
afx_circuit_open_total {m["circuit_open_total"]}
# HELP afx_orders_success Successful order count
# TYPE afx_orders_success counter
afx_orders_success {m["orders_success"]}
# HELP afx_orders_failed Failed order count
# TYPE afx_orders_failed counter
afx_orders_failed {m["orders_failed"]}
# HELP afx_latency_avg_ms Average function latency
# TYPE afx_latency_avg_ms gauge
afx_latency_avg_ms {m["latency_avg_ms"]:.2f}
"""


def reset_metrics() -> None:
    """Reset all metrics counters."""
    global _TRADE_COUNTER, _SIGNAL_COUNTER, _ERROR_COUNTER
    global _CIRCUIT_OPEN_COUNTER, _ORDER_SUCCESS, _ORDER_FAILED
    global _LATENCY_SUM, _LATENCY_COUNT
    with _METRICS_LOCK:
        _TRADE_COUNTER = 0
        _SIGNAL_COUNTER = 0
        _ERROR_COUNTER = 0
        _CIRCUIT_OPEN_COUNTER = 0
        _ORDER_SUCCESS = 0
        _ORDER_FAILED = 0
        _LATENCY_SUM = 0.0
        _LATENCY_COUNT = 0


# ─── Strategy-Specific Metrics ──────────────────────────────────
_STRATEGY_TRADES = {m: 0 for m in ["SWING", "DAY", "CARRY", "SCALP"]}
_STRATEGY_PNL = {m: 0.0 for m in ["SWING", "DAY", "CARRY", "SCALP"]}


def record_strategy_trade(strategy_mode: str, pnl: float = 0.0) -> None:
    with _METRICS_LOCK:
        if strategy_mode in _STRATEGY_TRADES:
            _STRATEGY_TRADES[strategy_mode] += 1
            _STRATEGY_PNL[strategy_mode] += pnl


def get_strategy_metrics() -> dict:
    with _METRICS_LOCK:
        return {
            **{f"trades_{m}": _STRATEGY_TRADES[m] for m in _STRATEGY_TRADES},
            **{f"pnl_{m}": round(_STRATEGY_PNL[m], 2) for m in _STRATEGY_PNL},
        }


# Expose metric names as module-level for easy access
TRADE_COUNT = "trades"
SIGNAL_COUNT = "signals"
ERROR_COUNT = "errors"
CIRCUIT_BREAKER_OPEN = "circuit_open"
ORDER_SUCCESS_COUNT = "order_success"
ORDER_FAILED_COUNT = "order_failed"


# ─── Performance Profiler ────────────────────────────────────────
class PerformanceProfiler:
    """Section-level timing profiler used by brain_v3 for efficiency reporting."""

    def __init__(self) -> None:
        self._lock = __import__("threading").RLock()
        self._starts: dict[str, float] = {}
        self.call_counts: dict[str, dict] = {}

    def start(self, name: str) -> None:
        with self._lock:
            self._starts[name] = time.monotonic()

    def end(self, name: str) -> None:
        elapsed_ms = (time.monotonic() - self._starts.pop(name, time.monotonic())) * 1000
        with self._lock:
            if name not in self.call_counts:
                self.call_counts[name] = {"total_ms": 0.0, "count": 0, "min_ms": float("inf"), "max_ms": 0.0}
            stats = self.call_counts[name]
            stats["total_ms"] += elapsed_ms
            stats["count"] += 1
            stats["min_ms"] = min(stats["min_ms"], elapsed_ms)
            stats["max_ms"] = max(stats["max_ms"], elapsed_ms)

    def get_report(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self.call_counts.items()}