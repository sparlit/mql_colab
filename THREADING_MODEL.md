# THREADING MODEL — AFX AutoTrader v2
# Design Document v1.0

## Core Principle
**ONLY MT5 communication is async. ALL other processing uses ThreadPoolExecutor or ProcessPoolExecutor.**

This separation ensures:
1. Minimal async surface area (only MT5 I/O)
2. Maximum parallelism for CPU/IO-bound work
3. No GIL contention on MT5 calls
4. Deterministic scheduling via priority queues

---

## THREAD POOL CONFIGURATION

```python
import os
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, PriorityQueue
from typing import Callable, Any
import asyncio

# CPU cores for process pools
CPU_COUNT = os.cpu_count() or 4

# ─── Pool Definitions ──────────────────────────────────────────

MT5_ASYNC_POOL_SIZE = min(8, CPU_COUNT * 2)
ANALYSIS_POOL_SIZE = CPU_COUNT
DECISION_POOL_SIZE = 4
IO_POOL_SIZE = max(8, CPU_COUNT * 2)
MODEL_POOL_SIZE = CPU_COUNT
TRAINING_POOL_SIZE = CPU_COUNT
```

---

## POOL ROLES

### 1. mt5_async_pool (ThreadPool, 4-8 workers)
**SOLE PURPOSE**: Run all MT5 async event loop tasks
- Only ever handles MT5 I/O callbacks
- No business logic here
- Driven by `asyncio.run_in_executor()` wrapping `async_mt5` calls

```python
mt5_async_pool = ThreadPoolExecutor(
    max_workers=MT5_ASYNC_POOL_SIZE,
    thread_name_prefix="mt5_async_",
    initializer=_set_mt5_thread_name
)
```

### 2. analysis_pool (ThreadPool, CPU_count workers)
**PURPOSE**: Feature engineering, indicator calculations, pattern recognition
- All `indicators.py` functions
- `pattern_recognition.py` functions
- `ml_features.py` feature extraction (but NOT model inference)
- CPU-bound but well-released by GIL (numpy, pandas)

```python
analysis_pool = ThreadPoolExecutor(
    max_workers=ANALYSIS_POOL_SIZE,
    thread_name_prefix="analysis_",
    initializer=_set_analysis_thread_name
)
```

### 3. decision_pool (ThreadPool, 4 workers)
**PURPOSE**: Strategy evaluation, risk calculation, position sizing
- `StrategyRouter.analyze()`
- `RiskEngine.calculate_*`
- `PositionManager.calculate_*`
- Critical path — low latency required

```python
decision_pool = ThreadPoolExecutor(
    max_workers=DECISION_POOL_SIZE,
    thread_name_prefix="decision_",
    initializer=_set_decision_thread_name
)
```

### 4. io_pool (ThreadPool, 8-16 workers)
**PURPOSE**: All I/O-bound work except MT5
- Database reads/writes (`magic_database.py`, `settings_db.py`)
- File I/O (`backtest_data.py`, model saves)
- HTTP requests (market data APIs)
- Logging (JSON file writes)

```python
io_pool = ThreadPoolExecutor(
    max_workers=IO_POOL_SIZE,
    thread_name_prefix="io_",
    initializer=_set_io_thread_name
)
```

### 5. model_pool (ProcessPool, CPU_count workers)
**PURPOSE**: ML model inference (CPU-intensive, bypass GIL)
- `ml_model.py` inference calls
- `ml_enhancements.py` feature scoring
- Must be separate process to bypass GIL

```python
model_pool = ProcessPoolExecutor(
    max_workers=MODEL_POOL_SIZE,
    mp_context=multiprocessing.get_context("spawn"),
    initializer=_init_model_process
)
```

### 6. training_pool (ProcessPool, CPU_count workers)
**PURPOSE**: Model training runs (off main thread)
- `train_ml.py` training loops
- `batch_train.py` hyperparameter search
- `walk_forward.py` validation
- Long-running, CPU-intensive

```python
training_pool = ProcessPoolExecutor(
    max_workers=TRAINING_POOL_SIZE,
    mp_context=multiprocessing.get_context("spawn"),
    initializer=_init_training_process
)
```

---

## TASK PRIORITIES

Tasks submitted to all pools use a priority tagging system:

```python
class TaskPriority(IntEnum):
    CRITICAL = 0   # Trade execution, order submission
    HIGH = 1       # Strategy decision, risk calculation
    NORMAL = 2     # Feature engineering, indicators
    LOW = 3        # Database writes, logging
    BACKGROUND = 4 # Model training, batch jobs
```

---

## SUBMISSION API

```python
from functools import partial

class ParallelExecutor:
    """Unified submission interface for all thread/process pools."""

    def submit(
        self,
        fn: Callable[..., T],
        *args: Any,
        pool: str = "analysis",  # analysis | decision | io | model | training
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: float | None = None,
        **kwargs
    ) -> Future[T]:
        """
        Submit task to specified pool with priority.
        Returns concurrent.futures.Future for result retrieval.
        """
        ...

    def submit_mt5_async(
        self,
        coro: Coroutine,
        timeout: float = 30.0
    ) -> Any:
        """
        Submit async MT5 coroutine to the async event loop.
        This is the ONLY async entry point.
        """
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(mt5_async_pool, coro)

    def map(
        self,
        fn: Callable[..., T],
        items: Iterable[Any],
        pool: str = "analysis",
        priority: TaskPriority = TaskPriority.NORMAL
    ) -> list[T]:
        """Map function over items using specified pool."""
        ...
```

---

## SHARED STATE ACCESS RULES

All shared state (positions, risk limits, brain weights) is accessed through:
- Thread-safe `dataclasses` with `threading.Lock`
- Or `multiprocessing.Manager()` for process-safe access
- No raw global state modifications

```python
from threading import RLock
from dataclasses import dataclass, field

@dataclass
class SharedState:
    _lock: RLock = field(default_factory=RLock)

    @property
    def lock(self) -> RLock:
        return self._lock

    def update_positions(self, positions: list[Position]) -> None:
        with self._lock:
            self._positions = positions
```

---

## LIFECYCLE MANAGEMENT

```python
class ThreadPoolManager:
    """Manages lifecycle of all thread/process pools."""

    def __init__(self):
        self.pools: dict[str, Executor] = {}
        self._shutdown = threading.Event()
        self._setup_pools()

    def _setup_pools(self):
        self.pools["mt5_async"] = mt5_async_pool
        self.pools["analysis"] = analysis_pool
        self.pools["decision"] = decision_pool
        self.pools["io"] = io_pool
        self.pools["model"] = model_pool
        self.pools["training"] = training_pool

    def shutdown(self, wait: bool = True, timeout: float = 30.0):
        """
        Graceful shutdown of all pools.
        Sets shutdown flag, cancels pending tasks, waits for completion.
        """
        self._shutdown.set()

        for name, pool in self.pools.items():
            pool.shutdown(wait=wait, cancel_futures=True)

        if wait:
            self._wait_for_completion(timeout)

    def _wait_for_completion(self, timeout: float):
        """Wait for all in-flight tasks to complete."""
        import time
        start = time.monotonic()
        for name, pool in self.pools.items():
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                break
            pool.shutdown(wait=True, cancel_futures=False)

    def is_shutting_down(self) -> bool:
        return self._shutdown.is_set()
```

---

## SIGNAL HANDLING

```python
import signal
import atexit

def _setup_signal_handlers(manager: ThreadPoolManager):
    """Register signal handlers for graceful shutdown."""

    def sigterm_handler(signum, frame):
        logger.info(f"Received SIGTERM ({signum}), initiating graceful shutdown")
        manager.shutdown(wait=True, timeout=30.0)
        sys.exit(0)

    def sigint_handler(signum, frame):
        logger.info(f"Received SIGINT ({signum}), initiating graceful shutdown")
        manager.shutdown(wait=True, timeout=30.0)
        sys.exit(0)

    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGINT, sigint_handler)
    atexit.register(lambda: manager.shutdown(wait=True, timeout=30.0))
```

---

## CONCURRENCY LIMITS

| Operation | Max Concurrent | Pool |
|-----------|----------------|------|
| MT5 symbol subscribe | 50 | mt5_async |
| MT5 order submit | 8 | mt5_async |
| Strategy evaluate per symbol | 4 | decision |
| Risk calculate per signal | 10 | decision |
| Indicator calculate per bar | CPU_count | analysis |
| ML inference per tick | CPU_count | model |
| DB writes | 16 | io |
| HTTP requests | 20 | io |

---

## ERROR HANDLING IN POOLS

```python
from concurrent.futures import Future
import traceback

def _handle_future_error(future: Future, task_name: str) -> None:
    """Centralized error handler for pool task failures."""
    exc = future.exception()
    if exc:
        logger.error(
            f"Task {task_name} failed",
            extra={
                "error": str(exc),
                "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
                "task": task_name
            }
        )
        if isinstance(exc, CriticalError):
            # Trigger circuit breaker, alert dashboards
            circuit_breaker.open()
            notify_dashboards_critical(exc)
```

---

## TICK-to-DECISION PIPELINE

```
MT5 Tick (async callback)
  │
  ▼
mt5_async_pool receives tick
  │
  ▼
analysis_pool: indicators, patterns, ML features (parallel, 4 workers)
  │
  ▼
decision_pool: StrategyRouter.analyze() → RiskEngine → PositionManager
  │
  ▼
Result returned (Future) — total target: <50ms p99
```

---

*This document defines the threading model. All pool usage must conform to these specifications.*