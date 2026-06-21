"""
Shared test fixtures for brain chain unit tests.
Provides MT5 mock, synthetic data generators, and common test helpers.
"""
import sys
import types
import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock
from datetime import datetime, timedelta


def synthetic_ohlcv(n=300, base_price=1.10000, volatility=0.0005):
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    close = np.cumsum(np.random.randn(n) * volatility) + base_price
    high = close + np.abs(np.random.randn(n)) * volatility * 0.5
    low = close - np.abs(np.random.randn(n)) * volatility * 0.5
    open_ = close + np.random.randn(n) * volatility * 0.3
    volume = np.random.randint(100, 10000, n).astype(float)
    time_vals = [int((datetime.now() - timedelta(minutes=n-i)).timestamp()) for i in range(n)]
    return {
        'time': np.array(time_vals),
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'tick_volume': volume,
        'spread': np.full(n, 15.0),
        'real_volume': np.zeros(n),
    }


def synthetic_df(n=300, base_price=1.10000, volatility=0.0005):
    """Generate synthetic OHLCV DataFrame."""
    return pd.DataFrame(synthetic_ohlcv(n, base_price, volatility))


def synthetic_symbol_info():
    """Generate mock MT5 symbol info."""
    info = MagicMock()
    info.point = 0.00001
    info.digits = 5
    info.trade_contract_size = 100000
    info.volume_min = 0.01
    info.volume_max = 100.0
    info.volume_step = 0.01
    info.trade_mode = 0  # SYMBOL_TRADE_MODE_FULL
    info.visible = True
    info.name = "EURUSD"
    info.path = "Forex\\EURUSD"
    return info


def synthetic_tick(bid=1.10000, ask=1.10015):
    """Generate mock MT5 tick data."""
    tick = MagicMock()
    tick.bid = bid
    tick.ask = ask
    tick.last = bid
    tick.volume = 100
    tick.flags = 0
    tick.time = int(datetime.now().timestamp())
    tick.time_msc = int(datetime.now().timestamp() * 1000)
    return tick


def synthetic_account(equity=10000, balance=10000, margin=2000, margin_free=8000):
    """Generate mock MT5 account info."""
    acct = MagicMock()
    acct.equity = equity
    acct.balance = balance
    acct.margin = margin
    acct.margin_free = margin_free
    acct.profit = 0.0
    acct.leverage = 100
    acct.currency = "USD"
    return acct


def synthetic_order_result(retcode=10009, order=12345, price=1.10000):
    """Generate mock MT5 order result."""
    result = MagicMock()
    result.retcode = retcode
    result.order = order
    result.price = price
    result.volume = 0.1
    result.comment = "Request executed"
    return result


@pytest.fixture
def mock_mt5(monkeypatch):
    """Mock MetaTrader5 module for all brain tests."""
    mock = types.ModuleType('MetaTrader5')

    # Constants
    mock.TIMEFRAME_M1 = 60
    mock.TIMEFRAME_M5 = 300
    mock.TIMEFRAME_M15 = 900
    mock.TIMEFRAME_M30 = 1800
    mock.TIMEFRAME_H1 = 3600
    mock.TIMEFRAME_H4 = 14400
    mock.TIMEFRAME_D1 = 86400
    mock.TIMEFRAME_W1 = 604800
    mock.ORDER_TYPE_BUY = 0
    mock.ORDER_TYPE_SELL = 1
    mock.TRADE_RETCODE_DONE = 10009
    mock.TRADE_RETCODE_PLACED = 10008
    mock.TRADE_ACTION_DEAL = 1
    mock.ORDER_FILLING_IOC = 1
    mock.ORDER_FILLING_FOK = 2
    mock.ORDER_FILLING_RETURN = 0
    mock.ORDER_TIME_GTC = 0
    mock.SYMBOL_TRADE_MODE_FULL = 0
    mock.SYMBOL_TRADE_MODE_CLOSEONLY = 1
    mock.SYMBOL_TRADE_MODE_DISABLED = 2
    mock.DEAL_ENTRY_IN = 0
    mock.DEAL_ENTRY_OUT = 1

    # Mock functions
    mock.initialize = MagicMock(return_value=True)
    mock.shutdown = MagicMock()
    mock.copy_rates_from_pos = MagicMock(side_effect=lambda s, tf, pos, cnt: synthetic_ohlcv(cnt) if cnt > 0 else None)
    mock.symbol_info = MagicMock(side_effect=lambda s: synthetic_symbol_info())
    mock.symbol_info_tick = MagicMock(side_effect=lambda *a, **kw: synthetic_tick())
    mock.account_info = MagicMock(side_effect=lambda: synthetic_account())
    mock.positions_get = MagicMock(return_value=[])
    mock.history_deals_get = MagicMock(return_value=[])
    mock.order_send = MagicMock(side_effect=lambda req: synthetic_order_result())
    mock.last_error = MagicMock(return_value=(0, "No error"))
    mock.terminal_info = MagicMock(return_value=MagicMock(trade_allowed=True))
    mock.symbols_get = MagicMock(return_value=[MagicMock(name="EURUSD"), MagicMock(name="GBPUSD")])

    monkeypatch.setitem(sys.modules, 'MetaTrader5', mock)
    monkeypatch.setitem(sys.modules, 'mt5_mcp', mock)
    return mock


@pytest.fixture
def mock_mt5_no_connection(monkeypatch):
    """Mock MT5 with no connection (returns None for everything)."""
    mock = types.ModuleType('MetaTrader5')
    mock.TIMEFRAME_M1 = 60
    mock.ORDER_TYPE_BUY = 0
    mock.ORDER_TYPE_SELL = 1
    mock.TRADE_RETCODE_DONE = 10009
    mock.SYMBOL_TRADE_MODE_FULL = 0
    mock.DEAL_ENTRY_OUT = 1

    mock.initialize = MagicMock(return_value=False)
    mock.copy_rates_from_pos = MagicMock(return_value=None)
    mock.symbol_info = MagicMock(return_value=None)
    mock.symbol_info_tick = MagicMock(return_value=None)
    mock.account_info = MagicMock(return_value=None)
    mock.positions_get = MagicMock(return_value=None)
    mock.order_send = MagicMock(return_value=None)
    mock.terminal_info = MagicMock(return_value=None)

    monkeypatch.setitem(sys.modules, 'MetaTrader5', mock)
    return mock
