"""Tests for brain_v8.py recording components."""
import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_v8 import (
    TradeJournal,
    ActivityLogger,
    ErrorDocumentation,
    DecisionAuditTrail,
    ReportGenerator,
    MAX_JOURNAL_ENTRIES,
    MAX_ACTIVITY_LOG,
)


@pytest.fixture
def journal(tmp_path):
    """TradeJournal with mocked file I/O."""
    with patch("brain_v8.DATA_DIR", str(tmp_path)), \
         patch.object(TradeJournal, "_load"), \
         patch.object(TradeJournal, "_save"):
        j = TradeJournal()
        j.entries = deque(maxlen=MAX_JOURNAL_ENTRIES)
        yield j


@pytest.fixture
def activity(tmp_path):
    """ActivityLogger with mocked file I/O."""
    with patch("brain_v8.DATA_DIR", str(tmp_path)), \
         patch.object(ActivityLogger, "_load"), \
         patch.object(ActivityLogger, "_save"):
        a = ActivityLogger()
        a.activities = deque(maxlen=MAX_ACTIVITY_LOG)
        yield a


@pytest.fixture
def error_doc(tmp_path):
    """ErrorDocumentation with mocked file I/O."""
    with patch("brain_v8.DATA_DIR", str(tmp_path)), \
         patch.object(ErrorDocumentation, "_load"), \
         patch.object(ErrorDocumentation, "_save"):
        e = ErrorDocumentation()
        e.errors = deque(maxlen=500)
        yield e


@pytest.fixture
def audit(tmp_path):
    """DecisionAuditTrail with mocked file I/O."""
    with patch("brain_v8.DATA_DIR", str(tmp_path)), \
         patch.object(DecisionAuditTrail, "_load"), \
         patch.object(DecisionAuditTrail, "_save"):
        a = DecisionAuditTrail()
        a.trail = deque(maxlen=1000)
        yield a


class TestTradeJournal:
    def test_record_open(self, journal):
        entry = journal.record_open(
            ticket=12345, symbol="EURUSD", direction=1, lot=0.1,
            price=1.10000, sl=1.09500, tp=1.10500, confidence=0.75,
            signals=["ema", "rsi"], regime="trending", session="london",
            brain_versions={"v1": "8strat"}
        )
        assert entry["ticket"] == 12345
        assert entry["status"] == "open"
        assert entry["direction"] == "BUY"

    def test_record_close(self, journal):
        journal.record_open(
            ticket=99999, symbol="GBPUSD", direction=-1, lot=0.05,
            price=1.25000, sl=1.25500, tp=1.24500, confidence=0.6,
            signals=["bb"], regime="ranging", session="newyork",
            brain_versions={"v1": "8strat"}
        )
        with patch("brain_v8.mt5") as mock_mt5:
            info = MagicMock()
            info.point = 0.0001
            mock_mt5.symbol_info.return_value = info
            closed = journal.record_close(99999, close_price=1.24800, profit=10, reason="tp")
        assert closed is not None
        assert closed["status"] == "closed"
        assert closed["profit"] == 10

    def test_get_stats(self, journal):
        for i in range(5):
            journal.entries.append({
                "ticket": i, "status": "closed", "profit": 10 if i % 2 == 0 else -5
            })
        stats = journal.get_stats()
        assert "total_trades" in stats
        assert "win_rate" in stats
        assert "profit_factor" in stats


class TestActivityLogger:
    def test_log_and_get_recent(self, activity):
        activity.log("system", "System started", level="info")
        activity.log("trade", "Trade opened", level="info")
        recent = activity.get_recent(n=5)
        assert len(recent) == 2
        assert recent[0]["category"] == "system"
        assert recent[1]["category"] == "trade"

    def test_filter_by_category(self, activity):
        activity.log("trade", "Trade 1")
        activity.log("system", "System event")
        activity.log("trade", "Trade 2")
        trades = activity.get_recent(category="trade")
        assert len(trades) == 2

    def test_summary(self, activity):
        activity.log("trade", "T1")
        activity.log("error", "E1", level="error")
        summary = activity.get_summary()
        assert summary["total"] == 2
        assert "trade" in summary["categories"]


class TestErrorDocumentation:
    def test_document_dedup(self, error_doc):
        error_doc.document("Connection timeout", "network", "MT5 connection")
        e2 = error_doc.document("Connection timeout", "network", "MT5 connection")
        assert e2["occurrences"] == 2
        assert len(error_doc.errors) == 1

    def test_different_errors(self, error_doc):
        error_doc.document("Error A", "type_a", "context_a")
        error_doc.document("Error B", "type_b", "context_b")
        assert len(error_doc.errors) == 2

    def test_get_frequent(self, error_doc):
        error_doc.document("Recurring error", "test", "ctx")
        error_doc.document("Recurring error", "test", "ctx")
        error_doc.document("Recurring error", "test", "ctx")
        frequent = error_doc.get_frequent(min_occurrences=2)
        assert len(frequent) == 1
        assert frequent[0]["occurrences"] == 3


class TestDecisionAuditTrail:
    def test_record_and_get_recent(self, audit):
        decision = {"action": "trade", "confidence": 0.8, "direction": 1}
        audit.record(decision, "EURUSD")
        recent = audit.get_recent()
        assert len(recent) == 1
        assert recent[0]["symbol"] == "EURUSD"

    def test_decision_stats(self, audit):
        for _ in range(3):
            audit.record({"action": "trade", "confidence": 0.7}, "EURUSD")
        audit.record({"action": "wait", "confidence": 0}, "GBPUSD")
        stats = audit.get_decision_stats()
        assert stats["total_decisions"] == 4
        assert "trade" in stats["action_breakdown"]