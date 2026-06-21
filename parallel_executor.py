"""
Parallel Executor — AFX AutoTrader v2
Centralized ThreadPoolExecutor and ProcessPoolExecutor management.
Supports ALL strategy runtypes with deterministic priority scheduling.

Threading Model:
- ONLY MT5 I/O is async (via async_mt5, NOT this module)
- ALL other processing uses these pools
- ProcessPool: CPU-bound (ML, numerical computation)
- ThreadPool: I/O-bound + CPU-light (indicators, decisions, DB)
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
import atexit
from concurrent.futures import (
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    Future,
    as_completed,
    wait,
)
from dataclasses import dataclass, field
from enum import IntEnum, Enum as _Enum
from functools import partial
from typing import Callable, Any, Dict, Iterable, List, Optional, Tuple, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ─── CPU Detection ─────────────────────────────────────────────
CPU_COUNT = os.cpu_count() or 4

# ─── Pool Sizes ────────────────────────────────────────────────
MT5_ASYNC_WORKERS = min(8, CPU_COUNT * 2)
ANALYSIS_WORKERS = CPU_COUNT
DECISION_WORKERS = 4
IO_WORKERS = max(8, CPU_COUNT * 2)
MODEL_WORKERS = CPU_COUNT
TRAINING_WORKERS = CPU_COUNT
SCANNER_WORKERS = 4
CORRELATION_WORKERS = 2

# ─── Timeouts ─────────────────────────────────────────────────
PROCESS_TIMEOUT = 30
IO_TIMEOUT = 15
DECISION_TIMEOUT = 5
MODEL_TIMEOUT = 10

# ─── Task Priorities ───────────────────────────────────────────
class TaskPriority(IntEnum):
    CRITICAL = 0   # Trade execution, circuit breaker
    HIGH = 1       # Strategy decision, risk calculation
    NORMAL = 2     # Feature engineering, indicators
    LOW = 3        # Database writes, logging
    BACKGROUND = 4  # Model training, batch jobs


# ─── Run Types ─────────────────────────────────────────────────
class RunType(_Enum):
    SYMBOL_SCAN = "symbol_scan"
    INDICATOR_CALC = "indicator_calc"
    STRATEGY_ANALYZE = "strategy_analyze"
    RISK_CALC = "risk_calc"
    ML_INFERENCE = "ml_inference"
    ML_TRAINING = "ml_training"
    DB_WRITE = "db_write"
    DB_READ = "db_read"
    ORDER_SUBMIT = "order_submit"
    BACKTEST = "backtest"
    FEATURE_EXTRACT = "feature_extract"




def _process_worker(fn: Callable[..., T], args: tuple, kwargs: dict) -> Tuple[Any, float]:
    """Picklable worker for ProcessPool. Returns (result, elapsed_ms) or re-raises."""
    start = time.monotonic()
    result = fn(*args, **kwargs)
    elapsed_ms = (time.monotonic() - start) * 1000
    return (result, elapsed_ms)


# ─── Task ──────────────────────────────────────────────────────
@dataclass
class Task:
    """Internal task representation with priority and run type."""
    fn: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    run_type: RunType = RunType.INDICATOR_CALC
    timeout: float = 30.0
    task_id: str = ""

    def __lt__(self, other: "Task") -> bool:
        return (self.priority, self.task_id) < (other.priority, other.task_id)


# ─── Executor Stats ────────────────────────────────────────────
@dataclass
class ExecutorStats:
    tasks_submitted: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_time_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "tasks_submitted": self.tasks_submitted,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "total_time_ms": self.total_time_ms,
        }


# ─── Parallel Executor ─────────────────────────────────────────
class ParallelExecutor:
    """
    Unified parallel execution engine.

    Pools:
    - decision_pool: Strategy evaluation, risk calc (ThreadPool, 4 workers)
    - analysis_pool: Indicators, patterns (ThreadPool, CPU_count workers)
    - io_pool: DB, HTTP, file I/O (ThreadPool, 8-16 workers)
    - model_pool: ML inference (ProcessPool, CPU_count workers)
    - training_pool: ML training (ProcessPool, CPU_count workers)
    - mt5_async_pool: MT5 I/O ONLY (ThreadPool, 4-8 workers)

    Submission:
        executor.submit(fn, *args, pool="analysis", priority=NORMAL)
        executor.submit_cpu(fn, *args)    # → model_pool
        executor.submit_io(fn, *args)    # → io_pool
        executor.submit_decision(fn, *args)  # → decision_pool
    """

    _instance: Optional["ParallelExecutor"] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "ParallelExecutor":
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._pools: Dict[str, Any] = {}
        self._pool_stats: Dict[str, ExecutorStats] = {}
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._setup_complete = False

        self._setup_pools()
        self._register_signal_handlers()

    def _setup_pools(self) -> None:
        """Initialize all thread and process pools."""
        with self._lock:
            # Thread pools
            self._pools["decision"] = ThreadPoolExecutor(
                max_workers=DECISION_WORKERS,
                thread_name_prefix="decision_",
            )
            self._pool_stats["decision"] = ExecutorStats()

            self._pools["analysis"] = ThreadPoolExecutor(
                max_workers=ANALYSIS_WORKERS,
                thread_name_prefix="analysis_",
            )
            self._pool_stats["analysis"] = ExecutorStats()

            self._pools["io"] = ThreadPoolExecutor(
                max_workers=IO_WORKERS,
                thread_name_prefix="io_",
            )
            self._pool_stats["io"] = ExecutorStats()

            self._pools["scanner"] = ThreadPoolExecutor(
                max_workers=SCANNER_WORKERS,
                thread_name_prefix="scanner_",
            )
            self._pool_stats["scanner"] = ExecutorStats()

            self._pools["correlation"] = ThreadPoolExecutor(
                max_workers=CORRELATION_WORKERS,
                thread_name_prefix="correlation_",
            )
            self._pool_stats["correlation"] = ExecutorStats()

            # Process pools (bypass GIL for CPU-bound work)
            self._pools["model"] = ProcessPoolExecutor(
                max_workers=MODEL_WORKERS,
                mp_context=None,
            )
            self._pool_stats["model"] = ExecutorStats()

            self._pools["training"] = ProcessPoolExecutor(
                max_workers=TRAINING_WORKERS,
                mp_context=None,
            )
            self._pool_stats["training"] = ExecutorStats()

            self._pools["mt5_async"] = ThreadPoolExecutor(
                max_workers=MT5_ASYNC_WORKERS,
                thread_name_prefix="mt5_async_",
            )
            self._pool_stats["mt5_async"] = ExecutorStats()

            self._setup_complete = True
            logger.info(
                "ParallelExecutor initialized: %d CPU cores, "
                "decision=%d, analysis=%d, io=%d, model=%d, training=%d",
                CPU_COUNT, DECISION_WORKERS, ANALYSIS_WORKERS,
                IO_WORKERS, MODEL_WORKERS, TRAINING_WORKERS
            )

    def _register_signal_handlers(self) -> None:
        """Register SIGTERM/SIGINT handlers for graceful shutdown."""

        def _sigterm_handler(signum, frame):
            logger.info(f"ParallelExecutor received SIGTERM ({signum})")
            self.shutdown(wait=True, timeout=30.0)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)

        def _sigint_handler(signum, frame):
            logger.info(f"ParallelExecutor received SIGINT ({signum})")
            self.shutdown(wait=True, timeout=30.0)
            signal.signal(signal.SIGINT, signal.SIG_DFL)

        signal.signal(signal.SIGTERM, _sigterm_handler)
        signal.signal(signal.SIGINT, _sigint_handler)
        atexit.register(lambda: self.shutdown(wait=True, timeout=30.0))

    # ─── Generic Submit ─────────────────────────────────────────

    def submit(
        self,
        fn: Callable[..., T],
        *args,
        pool: str = "analysis",
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: Optional[float] = None,
        **kwargs
    ) -> Future[T]:
        """
        Generic submit to specified pool.

        Pools: decision | analysis | io | scanner | correlation | model | training | mt5_async
        """
        if self._shutdown.is_set():
            raise RuntimeError("Executor is shutting down")

        pool_executor = self._pools.get(pool)
        if pool_executor is None:
            raise ValueError(f"Unknown pool: {pool}. Valid: {list(self._pools.keys())}")

        timeout_map = {
            "model": MODEL_TIMEOUT,
            "training": PROCESS_TIMEOUT,
            "decision": DECISION_TIMEOUT,
        }

        is_process_pool = pool in {"model", "training"}

        if is_process_pool:
            with self._lock:
                self._pool_stats[pool].tasks_submitted += 1
            future = pool_executor.submit(_process_worker, fn, args, kwargs)
            return future
        else:
            def _wrapped():
                start = time.monotonic()
                try:
                    return fn(*args, **kwargs)
                finally:
                    elapsed_ms = (time.monotonic() - start) * 1000
                    with self._lock:
                        self._pool_stats[pool].tasks_submitted += 1
                        self._pool_stats[pool].tasks_completed += 1
                        self._pool_stats[pool].total_time_ms += elapsed_ms

            with self._lock:
                self._pool_stats[pool].tasks_submitted += 1

            return pool_executor.submit(_wrapped)

    def submit_and_wait(
        self,
        fn: Callable[..., T],
        *args,
        pool: str = "analysis",
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: Optional[float] = None,
        **kwargs
    ) -> T:
        """Submit and wait for result."""
        future = self.submit(fn, *args, pool=pool, priority=priority, timeout=timeout, **kwargs)
        return future.result(timeout=timeout)

    # ─── Specialized Submits ────────────────────────────────────

    def submit_decision(
        self,
        fn: Callable[..., T],
        *args,
        timeout: float = DECISION_TIMEOUT,
        **kwargs
    ) -> Future[T]:
        """Submit to decision pool (strategy, risk, position)."""
        return self.submit(fn, *args, pool="decision", priority=TaskPriority.HIGH, timeout=timeout, **kwargs)

    def submit_analysis(
        self,
        fn: Callable[..., T],
        *args,
        timeout: float = PROCESS_TIMEOUT,
        **kwargs
    ) -> Future[T]:
        """Submit to analysis pool (indicators, patterns, features)."""
        return self.submit(fn, *args, pool="analysis", priority=TaskPriority.NORMAL, timeout=timeout, **kwargs)

    def submit_io(
        self,
        fn: Callable[..., T],
        *args,
        timeout: float = IO_TIMEOUT,
        **kwargs
    ) -> Future[T]:
        """Submit to I/O pool (DB, HTTP, file)."""
        return self.submit(fn, *args, pool="io", priority=TaskPriority.LOW, timeout=timeout, **kwargs)

    def submit_cpu(
        self,
        fn: Callable[..., T],
        *args,
        timeout: float = MODEL_TIMEOUT,
        **kwargs
    ) -> Future[T]:
        """Submit to process pool for ML inference."""
        return self.submit(fn, *args, pool="model", priority=TaskPriority.NORMAL, timeout=timeout, **kwargs)

    def submit_training(
        self,
        fn: Callable[..., T],
        *args,
        timeout: float = PROCESS_TIMEOUT * 10,
        **kwargs
    ) -> Future[T]:
        """Submit to training pool (model training, off main thread)."""
        return self.submit(fn, *args, pool="training", priority=TaskPriority.BACKGROUND, timeout=timeout, **kwargs)

    def submit_mt5_async(
        self,
        fn: Callable[..., T],
        *args,
        timeout: float = IO_TIMEOUT,
        **kwargs
    ) -> Future[T]:
        """Submit to MT5 async pool (ONLY async I/O, NOT business logic)."""
        return self.submit(fn, *args, pool="mt5_async", priority=TaskPriority.CRITICAL, timeout=timeout, **kwargs)

    # ─── Backward Compat: legacy brain_v1/brain_v2 callers ────────
    # These provide the old blocking-style API (sync return, not Future)
    # so Brain.analyze and test fixtures work without modification.

    def submit_analysis_task(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        future = self.submit_analysis(fn, *args, **kwargs)
        result = future.result(timeout=PROCESS_TIMEOUT)
        if isinstance(result, tuple) and len(result) == 2:
            result = result[0]
        return result

    def submit_cpu_task(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        future = self.submit_cpu(fn, *args, **kwargs)
        result = future.result(timeout=MODEL_TIMEOUT)
        if isinstance(result, tuple) and len(result) == 2:
            result, elapsed_ms = result
            with self._lock:
                self._pool_stats["model"].tasks_completed += 1
                self._pool_stats["model"].total_time_ms += elapsed_ms
        return result

    def submit_io_task(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        return self.submit_io(fn, *args, **kwargs).result(timeout=IO_TIMEOUT)

    def submit_scanner_task(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        return self.submit(fn, *args, pool="scanner", **kwargs).result(timeout=IO_TIMEOUT)

    def submit_correlation_task(self, fn: Callable[..., Any], *args, **kwargs) -> Any:
        return self.submit(fn, *args, pool="correlation", **kwargs).result(timeout=IO_TIMEOUT)

    def submit_cpu_tasks_batch(self, fn: Callable[..., Any], tasks: list) -> list:
        results = []
        for task in tasks:
            args = task[0] if isinstance(task, tuple) else task
            result = self.submit_cpu_task(fn, args)
            results.append(result)
        return results

    def submit_io_tasks_batch(self, fn: Callable[..., Any], tasks: list) -> list:
        return self.map_io(
            lambda item: fn(*item[0], **item[1] if len(item) > 1 else {}),
            [(t,) for t in tasks],
        )

    def parallel_map_cpu(self, fn: Callable[..., Any], items: Iterable[Any]) -> list:
        return self.map_cpu(fn, items)

    def parallel_map_io(self, fn: Callable[..., Any], items: Iterable[Any]) -> list:
        return self.map_io(fn, items)

    # ─── Batch Operations ────────────────────────────────────────

    def map(
        self,
        fn: Callable[[Any], T],
        items: Iterable[Any],
        pool: str = "analysis",
        timeout_per_item: float = 30.0,
    ) -> List[T]:
        """Map function over items using specified pool."""
        results: List[Optional[T]] = [None] * len(items) if hasattr(items, "__len__") else []
        items_list = list(items)
        futures: Dict[Future, int] = {}
        is_process_pool = pool in {"model", "training"}

        for i, item in enumerate(items_list):
            future = self.submit(fn, item, pool=pool, timeout=timeout_per_item)
            futures[future] = i

        for future in as_completed(futures, timeout=len(items_list) * timeout_per_item):
            i = futures[future]
            try:
                result = future.result(timeout=timeout_per_item)
                if is_process_pool:
                    result, elapsed_ms = result
                    with self._lock:
                        self._pool_stats[pool].tasks_completed += 1
                        self._pool_stats[pool].total_time_ms += elapsed_ms
                results[i] = result
            except Exception as e:
                logger.error("map item %d failed: %s", i, e)
                results[i] = None

        return results

    def map_cpu(
        self,
        fn: Callable[[Any], T],
        items: Iterable[Any],
        timeout_per_item: float = MODEL_TIMEOUT,
    ) -> List[T]:
        """Map over CPU process pool."""
        return self.map(fn, items, pool="model", timeout_per_item=timeout_per_item)

    def map_io(
        self,
        fn: Callable[[Any], T],
        items: Iterable[Any],
        timeout_per_item: float = IO_TIMEOUT,
    ) -> List[T]:
        """Map over I/O thread pool."""
        return self.map(fn, items, pool="io", timeout_per_item=timeout_per_item)

    def map_decision(
        self,
        fn: Callable[[Any], T],
        items: Iterable[Any],
        timeout_per_item: float = DECISION_TIMEOUT,
    ) -> List[T]:
        """Map over decision thread pool."""
        return self.map(fn, items, pool="decision", timeout_per_item=timeout_per_item)

    # ─── Strategy-Specific Operations ───────────────────────────

    def analyze_symbol(
        self,
        symbol: str,
        brain_analyze_fn: Callable,
        strategy_analyze_fn: Callable,
        risk_calc_fn: Callable,
        market_data: Any,
    ) -> dict:
        """
        Full analysis pipeline for one symbol using decision pool.
        Runs brain → strategy → risk in sequence on decision pool.

        Returns dict with brain_analysis, signal, risk params.
        """
        def _pipeline():
            brain_result = brain_analyze_fn(market_data)
            signal = strategy_analyze_fn(market_data)
            risk_params = risk_calc_fn(signal, market_data)
            return {
                "brain": brain_result,
                "signal": signal,
                "risk": risk_params,
                "symbol": symbol,
            }

        future = self.submit_decision(_pipeline)
        return future.result(timeout=DECISION_TIMEOUT * 3)

    def run_indicators_parallel(
        self,
        indicator_fns: List[Callable],
        market_data: Any,
    ) -> List[Any]:
        """
        Run multiple indicator functions in parallel on analysis pool.
        Returns list of results in same order as indicator_fns.
        """
        def _run_one(fn):
            return fn(market_data)

        return self.map(_run_one, indicator_fns, pool="analysis", timeout_per_item=5.0)

    # ─── Shutdown ────────────────────────────────────────────────

    def shutdown(self, wait: bool = True, timeout: float = 30.0) -> None:
        """Graceful shutdown of all pools, suppress logging errors during interpreter exit."""
        # Disable logger to avoid errors when handlers are closed
        logger.disabled = True

        if self._shutdown.is_set():
            return
        self._shutdown.set()

        try:
            logger.info("ParallelExecutor shutting down (wait=%s, timeout=%s)", wait, timeout)
        except Exception:
            pass
        start = time.monotonic()

        for name, pool in self._pools.items():
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                try:
                    logger.warning("Shutdown timeout exceeded, forcing pool %s shutdown", name)
                except Exception:
                    pass
                pool.shutdown(wait=False, cancel_futures=True)
            else:
                pool.shutdown(wait=wait and remaining > 0, cancel_futures=True)

        self._setup_complete = False
        ParallelExecutor._instance = None
        try:
            logger.info("ParallelExecutor shutdown complete")
        except Exception:
            pass

    def is_shutting_down(self) -> bool:
        return self._shutdown.is_set()

    # ─── Stats ──────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, dict]:
        """Get stats for all pools."""
        with self._lock:
            return {name: stats.to_dict() for name, stats in self._pool_stats.items()}

    def get_pool_status(self) -> Dict[str, bool]:
        """Check which pools are healthy."""
        return {name: self._setup_complete and not self._shutdown.is_set()
                for name in self._pools}

    def reset_stats(self) -> None:
        """Reset all stats counters."""
        with self._lock:
            for stats in self._pool_stats.values():
                stats.tasks_submitted = 0
                stats.tasks_completed = 0
                stats.tasks_failed = 0
                stats.total_time_ms = 0.0


# ─── Backwards Compatibility Aliases ──────────────────────────
# These map old method names to new ones for compatibility
class _CompatWrapper:
    """Backwards compatibility wrapper."""

    def __init__(self, executor: ParallelExecutor):
        self._ex = executor

    def submit_cpu_task(self, func, *args, **kwargs):
        return self._ex.submit_cpu(func, *args, **kwargs)

    def submit_cpu_tasks_batch(self, func, tasks):
        return self._ex.map_cpu(lambda t: func(*t[0], **(t[1] if len(t) > 1 else {})),
                                [(t,) for t in tasks])

    def submit_io_task(self, func, *args, **kwargs):
        return self._ex.submit_io(func, *args, **kwargs)

    def submit_io_tasks_batch(self, func, tasks):
        return self._ex.map_io(lambda t: func(*t[0], **(t[1] if len(t) > 1 else {})),
                                [(t,) for t in tasks])

    def submit_analysis_task(self, func, *args, **kwargs):
        return self._ex.submit_analysis(func, *args, **kwargs)

    def submit_scanner_task(self, func, *args, **kwargs):
        return self._ex.submit(func, *args, pool="scanner", **kwargs)

    def submit_correlation_task(self, func, *args, **kwargs):
        return self._ex.submit(func, *args, pool="correlation", **kwargs)

    def parallel_map_cpu(self, func, items):
        return self._ex.map_cpu(func, items)

    def parallel_map_io(self, func, items):
        return self._ex.map_io(func, items)

    def get_stats(self):
        return self._ex.get_stats()

    def shutdown(self, wait=True):
        self._ex.shutdown(wait=wait)


# ─── Global Singleton ──────────────────────────────────────────
_executor: Optional[ParallelExecutor] = None
_executor_lock = threading.Lock()


def get_executor() -> ParallelExecutor:
    """Get the global parallel executor singleton."""
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ParallelExecutor()
    elif _executor._shutdown.is_set():
        _executor = None
        with _executor_lock:
            if _executor is None:
                _executor = ParallelExecutor()
    return _executor


def shutdown_executor(wait: bool = True, timeout: float = 30.0) -> None:
    """Shutdown the global executor."""
    global _executor
    if _executor:
        _executor.shutdown(wait=wait, timeout=timeout)
        _executor = None