"""
Trade Executor — AFX AutoTrader v2
Order execution with circuit breaker, retry logic, and graceful shutdown.

Sole async entry point: MT5 communication (via async_mt5).
All other processing: ThreadPoolExecutor (via parallel_executor).
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import asyncio

from async_mt5 import order_send
from mt5_mcp import (
    ORDER_TYPE_BUY, ORDER_TYPE_SELL,
    TRADE_ACTION_DEAL, TRADE_ACTION_SLTP,
    ORDER_FILLING_IOC, ORDER_FILLING_RETURN,
    symbol_info_tick, TRADE_RETCODE_DONE,
)

logger = logging.getLogger(__name__)


# ─── Circuit Breaker ───────────────────────────────────────────
class CircuitState(Enum):
    CLOSED = "CLOSED"   # Normal operation
    OPEN = "OPEN"       # Blocking all calls
    HALF_OPEN = "HALF_OPEN"  # Testing with 1 probe


@dataclass
class CircuitBreaker:
    """Circuit breaker for MT5 order execution."""

    failure_threshold: int = 5       # Failures before opening
    recovery_timeout: float = 30.0   # Seconds before half-open
    success_threshold: int = 2        # Successes to close from half-open
    half_open_max_calls: int = 1     # Max probe calls in half-open

    _state: CircuitState = field(default=CircuitState.CLOSED)
    _failure_count: int = 0
    _success_count: int = 0
    _last_failure_time: float = field(default_factory=time.time)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Execute func through circuit breaker."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    logger.info("Circuit breaker HALF_OPEN")
                else:
                    raise CircuitOpenError("Circuit breaker is OPEN")

            if self._state == CircuitState.HALF_OPEN:
                if self._success_count >= self.half_open_max_calls:
                    raise CircuitOpenError("Circuit breaker half-open limit reached")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    logger.info("Circuit breaker CLOSED (recovered)")
            elif self._state == CircuitState.CLOSED:
                self._failure_count = max(0, self._failure_count - 1)

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("Circuit breaker OPENED from HALF_OPEN")
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning("Circuit breaker OPENED — %d failures", self._failure_count)

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def reset(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


# ─── Execution Result ─────────────────────────────────────────
@dataclass
class ExecutionResult:
    success: bool
    order: int
    deal: int
    retcode: int
    error: str = ""
    retries: int = 0
    latency_ms: float = 0.0


# ─── Trade Executor ────────────────────────────────────────────
class TradeExecutor:
    """
    Centralized trade execution with circuit breaker, retry, and graceful shutdown.

    All order sending goes through this executor. It handles:
    - Circuit breaker (blocks on repeated failures)
    - Retry with exponential backoff
    - Graceful shutdown (no new orders, drain pending)
    - Performance tracking
    """

    def __init__(self, max_retries: int = 3, base_delay: float = 0.5):
        self._cb = CircuitBreaker()
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="trade_exec")
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._pending_orders: List[asyncio.Future] = []
        self._stats = {
            "submitted": 0,
            "executed": 0,
            "failed": 0,
            "retried": 0,
            "circuit_opened": 0,
        }
        self._latencies: List[float] = []

    def submit_order(
        self,
        request: dict,
        retry: bool = True,
    ) -> ExecutionResult:
        """
        Submit a trade order with circuit breaker and retry.

        Args:
            request: MT5 order request dict
            retry: Whether to retry on failure

        Returns:
            ExecutionResult with success status and order details
        """
        if self._shutdown.is_set():
            return ExecutionResult(
                success=False,
                order=0, deal=0, retcode=-1,
                error="executor_shutting_down"
            )

        with self._lock:
            self._stats["submitted"] += 1

        retries = 0
        last_error = ""
        last_retcode = -1

        for attempt in range(self._max_retries if retry else 1):
            start = time.monotonic()
            try:
                result = self._cb.call(self._do_send_order, request)
                latency_ms = (time.monotonic() - start) * 1000

                if result and result.retcode == 1:
                    with self._lock:
                        self._stats["executed"] += 1
                        self._latencies.append(latency_ms)
                    return ExecutionResult(
                        success=True,
                        order=getattr(result, "order", 0),
                        deal=getattr(result, "deal", 0),
                        retcode=result.retcode,
                        retries=retries,
                        latency_ms=latency_ms,
                    )
                else:
                    last_retcode = getattr(result, "retcode", -1)
                    last_error = f"retcode_{last_retcode}"

            except CircuitOpenError:
                with self._lock:
                    self._stats["circuit_opened"] += 1
                logger.warning("Order blocked — circuit breaker open")
                return ExecutionResult(
                    success=False,
                    order=0, deal=0, retcode=-1,
                    error="circuit_open",
                    retries=retries,
                )

            except Exception as e:
                last_error = str(e)
                retries = attempt + 1

            if attempt < self._max_retries - 1:
                delay = self._base_delay * (2 ** attempt)
                logger.info("Order retry %d/%d after %.1fs — %s",
                          attempt + 1, self._max_retries, delay, last_error)
                time.sleep(delay)
                with self._lock:
                    self._stats["retried"] += 1

        with self._lock:
            self._stats["failed"] += 1
        return ExecutionResult(
            success=False,
            order=0, deal=0, retcode=last_retcode,
            error=last_error,
            retries=retries,
        )

    def _do_send_order(self, request: dict) -> Any:
        """Actually send the order via async MT5."""
        return order_send(request)

    def modify_position(
        self,
        ticket: int,
        new_sl: float = 0.0,
        new_tp: float = 0.0,
    ) -> ExecutionResult:
        """Modify stop loss and/or take profit of an existing position."""
        request = {
            "action": TRADE_ACTION_SLTP,
            "position": ticket,
            "sl": new_sl,
            "tp": new_tp,
            "type_time": 0,
            "type_filling": ORDER_FILLING_RETURN,
        }
        return self.submit_order(request, retry=True)

    def close_position(
        self,
        ticket: int,
        symbol: str,
        volume: float,
        position_type: int,
    ) -> ExecutionResult:
        """Close an existing position."""
        tick = symbol_info_tick(symbol)
        if not tick:
            return ExecutionResult(success=False, order=0, deal=0, retcode=-1, error="no_tick")
        price = tick.bid if position_type == ORDER_TYPE_BUY else tick.ask
        close_type = ORDER_TYPE_SELL if position_type == ORDER_TYPE_BUY else ORDER_TYPE_BUY

        request = {
            "action": TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "type_time": 0,
            "type_filling": ORDER_FILLING_IOC,
            "comment": "CloseByExecutor",
        }
        return self.submit_order(request, retry=True)

    # ─── Shutdown ───────────────────────────────────────────────

    def initiate_shutdown(self) -> None:
        """Signal shutdown — no new orders accepted."""
        logger.info("TradeExecutor initiating graceful shutdown")
        self._shutdown.set()

    def wait_for_drain(self, timeout: float = 30.0) -> bool:
        """Wait for all pending orders to complete. Returns True if drained."""
        start = time.monotonic()
        logger.info("TradeExecutor draining — %d pending orders", len(self._pending_orders))
        while self._pending_orders and (time.monotonic() - start) < timeout:
            time.sleep(0.1)
        return len(self._pending_orders) == 0

    # ─── Stats ──────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "circuit_state": self._cb.state.value,
                "avg_latency_ms": sum(self._latencies) / len(self._latencies) if self._latencies else 0,
                "p95_latency_ms": sorted(self._latencies)[int(len(self._latencies) * 0.95)]
                                  if len(self._latencies) > 10 else 0,
            }

    def reset_circuit(self) -> None:
        """Manually reset circuit breaker."""
        self._cb.reset()
        logger.info("Circuit breaker manually reset")


# ─── Singleton ─────────────────────────────────────────────────
_executor: Optional[TradeExecutor] = None
_executor_lock = threading.Lock()


def get_trade_executor() -> TradeExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = TradeExecutor()
    return _executor


def shutdown_trade_executor() -> None:
    global _executor
    if _executor:
        _executor.initiate_shutdown()
        _executor = None