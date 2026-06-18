"""
Unit tests for shared utilities and SLTP engine.
Run with: pytest tests/test_utils.py -v
"""
import pytest
import numpy as np
from indicators import ema, get_current_session


class TestEMA:
    """Tests for the shared EMA function."""
    
    def test_ema_basic(self):
        """Test EMA with simple data."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = ema(data, 3)
        assert len(result) == 5
        assert result[0] == 1.0  # First value should be unchanged
    
    def test_ema_constant(self):
        """Test EMA with constant data."""
        data = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
        result = ema(data, 3)
        assert all(abs(v - 5.0) < 0.001 for v in result)
    
    def test_ema_single_value(self):
        """Test EMA with single value."""
        data = np.array([10.0])
        result = ema(data, 5)
        assert len(result) == 1
        assert result[0] == 10.0


class TestSessionDetection:
    """Tests for session detection."""
    
    def test_get_current_session_returns_string(self):
        """Test that get_current_session returns a valid session name."""
        session = get_current_session()
        assert session in ["asian", "london", "overlap", "new_york", "dead"]
    
    def test_session_is_always_valid(self):
        """Test that session is always one of the valid values."""
        for _ in range(10):
            session = get_current_session()
            assert session in ["asian", "london", "overlap", "new_york", "dead"]


class TestSLTPEngine:
    """Tests for the SLTP engine (requires MT5 mock)."""
    
    def test_sltp_import(self):
        """Test that SLTP engine can be imported."""
        try:
            from sltp_engine import SLTPEngine, get_sltp_engine
            assert SLTPEngine is not None
            assert get_sltp_engine is not None
        except ImportError:
            pytest.skip("SLTP engine not available")
    
    def test_partial_close_levels(self):
        """Test partial close level calculation."""
        try:
            from sltp_engine import SLTPEngine
            engine = SLTPEngine()
            levels = engine.calculate_partial_close_levels(
                entry_price=1.1000, tp_price=1.1100, direction=1, levels=3
            )
            assert len(levels) == 3
            assert levels[0]["percent"] == 30  # First level closes 30%
            assert levels[-1]["percent"] == 100  # Last level closes 100%
        except ImportError:
            pytest.skip("SLTP engine not available")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
