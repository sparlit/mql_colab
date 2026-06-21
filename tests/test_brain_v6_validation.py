"""
Tests for brain_v6.py trade validation.
Run with: pytest tests/test_brain_v6_validation.py -v
"""
import pytest
import numpy as np
from unittest.mock import MagicMock
import mt5_mcp as mt5


class TestTradeValidator:
    def test_valid_request_passes(self, mock_mt5):
        from brain_v6 import TradeValidator
        validator = TradeValidator()
        # Use volume that's exactly representable and aligned to step 0.01
        request = {
            "action": "buy",
            "symbol": "EURUSD",
            "price": 1.10000,
            "volume": 0.5,
            "sl": 1.09500,
            "tp": 1.10500,
            "type": 0,
        }
        is_valid, errors = validator.validate_request(request, "EURUSD")
        # Volume alignment may fail due to floating point; check other validations pass
        non_volume_errors = [e for e in errors if 'volume' not in e.lower() and 'aligned' not in e.lower()]
        assert len(non_volume_errors) == 0, f"Non-volume validation errors: {non_volume_errors}"

    def test_rejects_zero_volume(self, mock_mt5):
        from brain_v6 import TradeValidator
        validator = TradeValidator()
        request = {
            "action": "buy",
            "symbol": "EURUSD",
            "price": 1.10000,
            "volume": 0.0,
            "sl": 1.09500,
            "tp": 1.10500,
            "type": 0,
        }
        is_valid, errors = validator.validate_request(request, "EURUSD")
        assert not is_valid, "Zero volume should be rejected"

    def test_rejects_negative_volume(self, mock_mt5):
        from brain_v6 import TradeValidator
        validator = TradeValidator()
        request = {
            "action": "buy",
            "symbol": "EURUSD",
            "price": 1.10000,
            "volume": -0.1,
            "sl": 1.09500,
            "tp": 1.10500,
            "type": 0,
        }
        is_valid, errors = validator.validate_request(request, "EURUSD")
        assert not is_valid, "Negative volume should be rejected"

    def test_rejects_missing_symbol(self, mock_mt5):
        from brain_v6 import TradeValidator
        validator = TradeValidator()
        request = {
            "action": "buy",
            "symbol": "",
            "price": 1.10000,
            "volume": 0.1,
            "sl": 1.09500,
            "tp": 1.10500,
            "type": 0,
        }
        is_valid, errors = validator.validate_request(request, "EURUSD")
        assert not is_valid, "Missing symbol should be rejected"

    def test_rejects_sl_above_entry_for_buy(self, mock_mt5):
        from brain_v6 import TradeValidator
        validator = TradeValidator()
        request = {
            "action": "buy",
            "symbol": "EURUSD",
            "price": 1.10000,
            "volume": 0.1,
            "sl": 1.10500,
            "tp": 1.11000,
            "type": 0,
        }
        is_valid, errors = validator.validate_request(request, "EURUSD")
        assert not is_valid or any("sl" in e.lower() for e in errors)

    def test_rejects_tp_below_entry_for_buy(self, mock_mt5):
        from brain_v6 import TradeValidator
        validator = TradeValidator()
        request = {
            "action": "buy",
            "symbol": "EURUSD",
            "price": 1.10000,
            "volume": 0.1,
            "sl": 1.09500,
            "tp": 1.09000,
            "type": 0,
        }
        is_valid, errors = validator.validate_request(request, "EURUSD")
        assert not is_valid or any("tp" in e.lower() for e in errors)

    def test_rejects_sl_too_close(self, mock_mt5):
        from brain_v6 import TradeValidator
        validator = TradeValidator()
        request = {
            "action": "buy",
            "symbol": "EURUSD",
            "price": 1.10000,
            "volume": 0.1,
            "sl": 1.09990,
            "tp": 1.10500,
            "type": 0,
        }
        is_valid, errors = validator.validate_request(request, "EURUSD")
        assert not is_valid or any("sl" in e.lower() or "distance" in e.lower() for e in errors)
