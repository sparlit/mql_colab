"""
Parallel Executor Module - Centralized ProcessPoolExecutor and ThreadPoolExecutor
Manages CPU-bound (ProcessPool) and I/O-bound (ThreadPool) parallel execution.
"""
import logging
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import Callable, Any, Dict, List, Optional, Tuple
from functools import partial
from config import ANALYSIS_WORKERS, SCANNER_WORKERS, CORRELATION_WORKERS, PROCESS_WORKERS, IO_WORKERS

logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURATION (from config.py - auto-detected)
# ==========================================
PROCESS_TIMEOUT = 30
IO_TIMEOUT = 15


class ParallelExecutor:
    """Centralized parallel execution manager with ProcessPool and ThreadPool pools."""
    
    def __init__(self):
        self._process_pool = None
        self._io_pool = None
        self._analysis_pool = None
        self._scanner_pool = None
        self._correlation_pool = None
        self._lock = threading.RLock()
        self._initialized = False
        self._stats = {
            "process_tasks_submitted": 0,
            "process_tasks_completed": 0,
            "process_tasks_failed": 0,
            "io_tasks_submitted": 0,
            "io_tasks_completed": 0,
            "io_tasks_failed": 0,
            "total_time_ms": 0,
        }
    
    def initialize(self):
        """Initialize all thread/process pools."""
        with self._lock:
            if self._initialized:
                return
            
            self._process_pool = ProcessPoolExecutor(
                max_workers=PROCESS_WORKERS,
                mp_context=None  # Use default spawn context
            )
            self._io_pool = ThreadPoolExecutor(
                max_workers=IO_WORKERS,
                thread_name_prefix="IO"
            )
            self._analysis_pool = ThreadPoolExecutor(
                max_workers=ANALYSIS_WORKERS,
                thread_name_prefix="Analysis"
            )
            self._scanner_pool = ThreadPoolExecutor(
                max_workers=SCANNER_WORKERS,
                thread_name_prefix="Scanner"
            )
            self._correlation_pool = ThreadPoolExecutor(
                max_workers=CORRELATION_WORKERS,
                thread_name_prefix="Correlation"
            )
            
            self._initialized = True
            from config import SYSTEM_TIER, SYSTEM_CPU_COUNT, SYSTEM_MEMORY_GB
            logger.info(
                "ParallelExecutor initialized [%s tier, %d cores, %.0fGB RAM]: "
                "%d process workers, %d IO threads, %d analysis threads, "
                "%d scanner threads, %d correlation threads",
                SYSTEM_TIER, SYSTEM_CPU_COUNT, SYSTEM_MEMORY_GB,
                PROCESS_WORKERS, IO_WORKERS, ANALYSIS_WORKERS,
                SCANNER_WORKERS, CORRELATION_WORKERS
            )
    
    def shutdown(self, wait=True):
        """Shutdown all pools gracefully."""
        with self._lock:
            if not self._initialized:
                return
            
            pools = [
                ("process", self._process_pool),
                ("io", self._io_pool),
                ("analysis", self._analysis_pool),
                ("scanner", self._scanner_pool),
                ("correlation", self._correlation_pool),
            ]
            
            for name, pool in pools:
                if pool:
                    try:
                        pool.shutdown(wait=wait)
                    except Exception as e:
                        logger.error("Error shutting down %s pool: %s", name, e)
            
            self._initialized = False
            logger.info("ParallelExecutor shutdown complete")
    
    # ==========================================
    # PROCESS POOL EXECUTION (CPU-bound)
    # ==========================================
    
    def submit_cpu_task(self, func: Callable, *args, **kwargs) -> Any:
        """Submit a CPU-bound task to the process pool.
        
        Use for: Monte Carlo simulations, indicator calculations,
        correlation matrices, ML training, numerical computations.
        """
        self.initialize()
        with self._lock:
            self._stats["process_tasks_submitted"] += 1
        try:
            future = self._process_pool.submit(func, *args, **kwargs)
            result = future.result(timeout=PROCESS_TIMEOUT)
            with self._lock:
                self._stats["process_tasks_completed"] += 1
            return result
        except Exception as e:
            with self._lock:
                self._stats["process_tasks_failed"] += 1
            logger.error("CPU task failed: %s", e)
            raise
    
    def submit_cpu_tasks_batch(self, func: Callable, tasks: List[Tuple]) -> List[Any]:
        """Submit multiple CPU-bound tasks in parallel.
        
        Args:
            func: Function to execute
            tasks: List of args tuples (each tuple is passed as a single argument to func)
        Returns:
            List of results in order
        """
        self.initialize()
        futures = {}
        results = []
        
        for i, task_args in enumerate(tasks):
            if isinstance(task_args, tuple) and len(task_args) == 2 and isinstance(task_args[1], dict):
                args, kwargs = task_args
            else:
                args = (task_args,)
                kwargs = {}
            
            with self._lock:
                self._stats["process_tasks_submitted"] += 1
            future = self._process_pool.submit(func, *args, **kwargs)
            futures[future] = i
        
        for future in as_completed(futures, timeout=PROCESS_TIMEOUT * 2):
            try:
                result = future.result()
                idx = futures[future]
                results.append((idx, result))
                with self._lock:
                    self._stats["process_tasks_completed"] += 1
            except Exception as e:
                idx = futures[future]
                logger.error("CPU batch task %d failed: %s", idx, e)
                with self._lock:
                    self._stats["process_tasks_failed"] += 1
                results.append((idx, None))
        
        # Sort by original order
        results.sort(key=lambda x: x[0])
        return [r[1] for r in results]
    
    # ==========================================
    # THREAD POOL EXECUTION (I/O-bound)
    # ==========================================
    
    def submit_io_task(self, func: Callable, *args, **kwargs) -> Any:
        """Submit an I/O-bound task to the thread pool.
        
        Use for: MT5 data fetching, file I/O, network requests.
        """
        self.initialize()
        with self._lock:
            self._stats["io_tasks_submitted"] += 1
        try:
            future = self._io_pool.submit(func, *args, **kwargs)
            result = future.result(timeout=IO_TIMEOUT)
            with self._lock:
                self._stats["io_tasks_completed"] += 1
            return result
        except Exception as e:
            with self._lock:
                self._stats["io_tasks_failed"] += 1
            logger.error("IO task failed: %s", e)
            raise
    
    def submit_io_tasks_batch(self, func: Callable, tasks: List[Tuple]) -> List[Any]:
        """Submit multiple I/O-bound tasks in parallel."""
        self.initialize()
        futures = {}
        results = []
        
        for i, task_args in enumerate(tasks):
            if isinstance(task_args, tuple) and len(task_args) == 2:
                args, kwargs = task_args
            else:
                args = (task_args,) if not isinstance(task_args, tuple) else task_args
                kwargs = {}
            
            with self._lock:
                self._stats["io_tasks_submitted"] += 1
            future = self._io_pool.submit(func, *args, **kwargs)
            futures[future] = i
        
        for future in as_completed(futures, timeout=IO_TIMEOUT * 2):
            try:
                result = future.result()
                idx = futures[future]
                results.append((idx, result))
                with self._lock:
                    self._stats["io_tasks_completed"] += 1
            except Exception as e:
                idx = futures[future]
                logger.error("IO batch task %d failed: %s", idx, e)
                with self._lock:
                    self._stats["io_tasks_failed"] += 1
                results.append((idx, None))
        
        results.sort(key=lambda x: x[0])
        return [r[1] for r in results]
    
    # ==========================================
    # SPECIALIZED POOL ACCESS
    # ==========================================
    
    def submit_analysis_task(self, func: Callable, *args, **kwargs) -> Any:
        """Submit to analysis pool (brain analysis tasks)."""
        self.initialize()
        try:
            future = self._analysis_pool.submit(func, *args, **kwargs)
            return future.result(timeout=PROCESS_TIMEOUT)
        except Exception as e:
            logger.error("Analysis task failed: %s", e)
            raise
    
    def submit_scanner_task(self, func: Callable, *args, **kwargs) -> Any:
        """Submit to scanner pool (market scanning tasks)."""
        self.initialize()
        try:
            future = self._scanner_pool.submit(func, *args, **kwargs)
            return future.result(timeout=IO_TIMEOUT)
        except Exception as e:
            logger.error("Scanner task failed: %s", e)
            raise
    
    def submit_correlation_task(self, func: Callable, *args, **kwargs) -> Any:
        """Submit to correlation pool (correlation calculation tasks)."""
        self.initialize()
        try:
            future = self._correlation_pool.submit(func, *args, **kwargs)
            return future.result(timeout=PROCESS_TIMEOUT)
        except Exception as e:
            logger.error("Correlation task failed: %s", e)
            raise
    
    # ==========================================
    # PARALLEL MAP OPERATIONS
    # ==========================================
    
    def parallel_map_cpu(self, func: Callable, items: List[Any]) -> List[Any]:
        """Map function over items using process pool (CPU-bound)."""
        self.initialize()
        futures = {}
        results = [None] * len(items)
        
        for i, item in enumerate(items):
            with self._lock:
                self._stats["process_tasks_submitted"] += 1
            future = self._process_pool.submit(func, item)
            futures[future] = i
        
        for future in as_completed(futures, timeout=PROCESS_TIMEOUT * 2):
            try:
                result = future.result()
                idx = futures[future]
                results[idx] = result
                self._stats["process_tasks_completed"] += 1
            except Exception as e:
                idx = futures[future]
                logger.error("Parallel map item %d failed: %s", idx, e)
                self._stats["process_tasks_failed"] += 1
                results[idx] = None
        
        return results
    
    def parallel_map_io(self, func: Callable, items: List[Any]) -> List[Any]:
        """Map function over items using thread pool (I/O-bound)."""
        self.initialize()
        futures = {}
        results = [None] * len(items)
        
        for i, item in enumerate(items):
            with self._lock:
                self._stats["io_tasks_submitted"] += 1
            future = self._io_pool.submit(func, item)
            futures[future] = i
        
        for future in as_completed(futures, timeout=IO_TIMEOUT * 2):
            try:
                result = future.result()
                idx = futures[future]
                results[idx] = result
                self._stats["io_tasks_completed"] += 1
            except Exception as e:
                idx = futures[future]
                logger.error("Parallel IO map item %d failed: %s", idx, e)
                self._stats["io_tasks_failed"] += 1
                results[idx] = None
        
        return results
    
    # ==========================================
    # STATS
    # ==========================================
    
    def get_stats(self) -> Dict:
        """Get execution statistics."""
        with self._lock:
            return self._stats.copy()
    
    def reset_stats(self):
        """Reset execution statistics."""
        with self._lock:
            self._stats = {
                "process_tasks_submitted": 0,
                "process_tasks_completed": 0,
                "process_tasks_failed": 0,
                "io_tasks_submitted": 0,
                "io_tasks_completed": 0,
                "io_tasks_failed": 0,
                "total_time_ms": 0,
            }


# Global singleton
_executor = None
_executor_lock = threading.Lock()


def get_executor() -> ParallelExecutor:
    """Get the global parallel executor singleton."""
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ParallelExecutor()
    return _executor


def shutdown_executor(wait=True):
    """Shutdown the global executor."""
    global _executor
    if _executor:
        _executor.shutdown(wait=wait)
        _executor = None
