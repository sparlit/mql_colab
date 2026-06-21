"""
Tests for ParallelExecutor module.
"""
import pytest
import time
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from parallel_executor import ParallelExecutor, get_executor, shutdown_executor


def simple_cpu_task(args):
    """Simple CPU-bound task for testing. Receives a tuple, returns first element squared."""
    x = args[0] if isinstance(args, tuple) else args
    return x * x


def simple_io_task(x):
    """Simple I/O-bound task for testing."""
    time.sleep(0.01)
    return x + 1


def failing_task(x):
    """Task that always fails."""
    raise ValueError("Test error")


class TestParallelExecutor:
    """Tests for ParallelExecutor class."""
    
    def test_initialization(self):
        """Test that executor initializes correctly and pools are available."""
        executor = get_executor()
        assert executor._initialized
        assert "model" in executor._pools
        assert "io" in executor._pools
    
    def test_singleton_pattern(self):
        """Test that get_executor returns singleton."""
        executor1 = get_executor()
        executor2 = get_executor()
        assert executor1 is executor2
    
    def test_cpu_task_submission(self):
        """Test CPU task submission to process pool."""
        executor = get_executor()
        result = executor.submit_cpu_task(simple_cpu_task, 5)
        assert result == 25
    
    def test_cpu_task_batch(self):
        """Test batch CPU task submission."""
        executor = get_executor()
        tasks = [(i,) for i in range(5)]
        results = executor.submit_cpu_tasks_batch(simple_cpu_task, tasks)
        assert len(results) == 5
        assert results == [0, 1, 4, 9, 16]
    
    def test_io_task_submission(self):
        """Test I/O task submission to thread pool."""
        executor = get_executor()
        result = executor.submit_io_task(simple_io_task, 5)
        assert result == 6
    
    def test_io_task_batch(self):
        """Test batch I/O task submission."""
        executor = get_executor()
        tasks = [(i,) for i in range(5)]
        results = executor.submit_io_tasks_batch(simple_io_task, tasks)
        assert len(results) == 5
        assert results == [1, 2, 3, 4, 5]
    
    def test_parallel_map_cpu(self):
        """Test parallel map on CPU pool."""
        executor = get_executor()
        items = [1, 2, 3, 4, 5]
        results = executor.parallel_map_cpu(simple_cpu_task, items)
        assert results == [1, 4, 9, 16, 25]
    
    def test_parallel_map_io(self):
        """Test parallel map on IO pool."""
        executor = get_executor()
        items = [1, 2, 3, 4, 5]
        results = executor.parallel_map_io(simple_io_task, items)
        assert results == [2, 3, 4, 5, 6]
    
    def test_task_failure_handling(self):
        """Test that task failures are handled gracefully."""
        executor = get_executor()
        with pytest.raises(ValueError):
            executor.submit_cpu_task(failing_task, 5)
    
    def test_stats_tracking(self):
        """Test that statistics are tracked correctly."""
        executor = get_executor()
        executor.reset_stats()

        executor.submit_cpu_task(simple_cpu_task, 5)
        stats = executor.get_stats()

        assert stats["model"]["tasks_submitted"] == 1
        assert stats["model"]["tasks_completed"] == 1
        assert stats["model"]["tasks_failed"] == 0
    
    def test_shutdown(self):
        """Test that executor shuts down cleanly and subsequent calls get fresh instance."""
        executor = get_executor()
        executor.shutdown(wait=True)
        new_executor = get_executor()
        assert new_executor is not executor
        assert not new_executor._shutdown.is_set()
    
    def test_submit_analysis_task(self):
        """Test analysis task submission."""
        executor = get_executor()
        result = executor.submit_analysis_task(simple_cpu_task, 10)
        assert result == 100
    
    def test_submit_scanner_task(self):
        """Test scanner task submission."""
        executor = get_executor()
        result = executor.submit_scanner_task(simple_io_task, 10)
        assert result == 11
    
    def test_submit_correlation_task(self):
        """Test correlation task submission."""
        executor = get_executor()
        result = executor.submit_correlation_task(simple_cpu_task, 15)
        assert result == 225


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
