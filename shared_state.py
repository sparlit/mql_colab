"""Shared state between the trading engine and dashboard.

The SymbolAnalyzer threads write analysis state here.
The dashboard reads it for live display.
"""
import threading
from datetime import datetime

_lock = threading.Lock()
_analysis_state = {}
_symbols = []
_engine_state = None
_brain_chain = None


def set_analysis(symbol, data):
    """Store analysis results for a symbol."""
    with _lock:
        _analysis_state[symbol] = data


def get_analysis(symbol):
    """Get analysis results for a symbol."""
    with _lock:
        return _analysis_state.get(symbol)


def get_all_analysis():
    """Get analysis results for all symbols."""
    with _lock:
        return dict(_analysis_state)


def set_symbols(symbols):
    """Set the list of active symbols."""
    global _symbols
    with _lock:
        _symbols = list(symbols)


def get_symbols():
    """Get the list of active symbols."""
    with _lock:
        return list(_symbols)


def set_engine_state(state):
    """Set the ThreadSafeState reference from the orchestrator."""
    global _engine_state
    _engine_state = state


def get_engine_state():
    """Get the ThreadSafeState reference."""
    return _engine_state


def set_brain_chain(brain):
    """Set the BrainChain reference from the orchestrator.
    The dashboard uses this instead of creating its own brain chain.
    """
    global _brain_chain
    _brain_chain = brain


def get_brain_chain():
    """Get the BrainChain reference from the main app."""
    return _brain_chain
