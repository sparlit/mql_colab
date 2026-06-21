"""
Brain Engine — AFX AutoTrader v2
Unified brain that consolidates logic from brain_v1 through brain_v11.
Provides strategy-aware analysis with multi-timeframe signal generation.

Brain v1-v11 all merged into this single engine with strategy mode support.
Strategy modes: SWING | DAY | CARRY | SCALP
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from strategy_base import (
    BaseStrategy,
    StrategyMode,
    StrategyMagic,
    SignalType,
    TradeSignal,
    MarketData,
    RiskProfile,
    get_strategy_by_mode,
)
from strategy_router import StrategyRouter
from parallel_executor import get_executor
from async_mt5 import (
    symbol_info_tick,
    symbol_info,
    positions_get,
    account_info,
    order_send,
    copy_rates_from_pos,
)
from indicators import fetch_closed_rates
from mt5_mcp import (
    ORDER_TYPE_BUY,
    ORDER_TYPE_SELL,
    TRADE_ACTION_DEAL,
    ORDER_FILLING_IOC,
    positions_total,
)

logger = logging.getLogger(__name__)

# ─── Magic numbers for system control ─────────────────────────
SYSTEM_MAGICS = {100001, 200002, 300003, 400004}


def is_system_magic(magic: int) -> bool:
    """Check if magic number belongs to AFX AutoTrader."""
    return magic in SYSTEM_MAGICS


# ─── Brain Stats (from brain_v1, unchanged) ─────────────────────
class BrainStats:
    """Trade history and statistics (from brain_v1, extended)."""

    def __init__(self):
        self._trades: List[Dict] = []
        self._equity_curve: List[float] = []
        self._win_count = 0
        self._loss_count = 0

    def record_trade(self, trade_info: Dict) -> None:
        self._trades.append(trade_info)
        if trade_info.get("profit", 0) > 0:
            self._win_count += 1
        else:
            self._loss_count += 1
        equity = self._equity_curve[-1] if self._equity_curve else 10000.0
        self._equity_curve.append(equity + trade_info.get("profit", 0))

    def get_kelly_fraction(self, lookback: int = 100) -> float:
        if not self._trades:
            return 0.01
        recent = self._trades[-lookback:]
        wins = [t["profit"] for t in recent if t.get("profit", 0) > 0]
        losses = [abs(t["profit"]) for t in recent if t.get("profit", 0) < 0]
        if not wins or not losses:
            return 0.01
        win_rate = len(wins) / len(recent)
        avg_win = np.mean(wins)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 0.01
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        kelly = win_rate - ((1 - win_rate) / (avg_win / avg_loss))
        return max(0.01, min(kelly, 0.25))

    @property
    def win_rate(self) -> float:
        total = self._win_count + self._loss_count
        return self._win_count / total if total > 0 else 0.0

    @property
    def equity_curve(self) -> List[float]:
        return self._equity_curve.copy()


# ─── Brain Engine ───────────────────────────────────────────────
class BrainEngine:
    """
    Unified brain for all strategy modes.

    Consolidates SignalAnalyzer, RiskManager, and strategy-aware routing.
    Replaces brain_v1 through brain_v11 with a single consistent interface.

    Usage:
        brain = BrainEngine()
        result = brain.analyze(symbol="EURUSD", timeframe="H4", strategy_mode="SWING")
    """

    def __init__(self):
        self.stats = BrainStats()
        self._router = StrategyRouter()
        self._executor = get_executor()
        self._ai = None
        self._setup_ai()

    def _setup_ai(self) -> None:
        try:
            from ai_client import get_ai_client
            self._ai = get_ai_client()
        except Exception:
            pass

    # ─── Main Entry Point ────────────────────────────────────────

    def analyze(
        self,
        symbol: str,
        timeframe: str = "H4",
        strategy_mode: str = "SWING",
        params: Optional[dict] = None,
        df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        Analyze market and return trade decision.

        Args:
            symbol: Trading symbol (e.g., "EURUSD")
            timeframe: Timeframe string ("M1", "M5", "H1", "H4", "D1")
            strategy_mode: One of SWING, DAY, CARRY, SCALP
            params: Optional override parameters
            df: Optional pre-loaded dataframe

        Returns:
            Dict with action, direction, confidence, lot, signals, etc.
        """
        mode = StrategyMode(strategy_mode)
        self._router.set_mode(mode)
        strategy = self._router.get_active_strategy()

        # Fetch rates if not provided
        if df is None:
            tf_map = {"M1": 1, "M5": 5, "M15": 15, "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769}
            tf_const = tf_map.get(timeframe, 16388)
            rates = fetch_closed_rates(symbol, tf_const, 300)
            if rates is None:
                return {"action": "hold", "reason": "no_data"}
            df = pd.DataFrame(rates)

        # Calculate indicators (runs on analysis pool)
        df = self._calc_indicators(df, params=params)

        # Build MarketData for strategy
        tick = symbol_info(symbol)
        if tick is None:
            tick_bid = tick_ask = df.iloc[-1]["close"]
        else:
            tick_bid = tick.bid
            tick_ask = tick.ask

        market_data = MarketData(
            symbol=symbol,
            timeframe=timeframe,
            time=int(df.iloc[-1]["time"]),
            open=float(df.iloc[-1]["open"]),
            high=float(df.iloc[-1]["high"]),
            low=float(df.iloc[-1]["low"]),
            close=float(df.iloc[-1]["close"]),
            tick_volume=int(df.iloc[-1]["tick_volume"]),
            spread=0,
            volume=float(df.iloc[-1]["tick_volume"]),
            indicators=self._extract_indicators(df),
        )

        # Run strategy analysis
        strategy_signal = strategy.analyze(market_data)

        # If strategy says hold, skip
        if not strategy_signal.is_actionable():
            return {
                "action": "hold",
                "signal_type": strategy_signal.signal_type.value,
                "confidence": strategy_signal.confidence,
                "symbol": symbol,
                "strategy_mode": strategy_mode,
            }

        # Calculate position size
        risk_profile = strategy.risk_profile
        stop_loss_pips = self._calc_stop_loss_pips(strategy_signal, df)
        position_size = strategy.calculate_position_size(strategy_signal, risk_profile, stop_loss_pips)

        # Get SL/TP prices
        direction = strategy_signal.signal_type
        entry_price = tick_ask if direction == SignalType.BUY else tick_bid
        sl_price = strategy.get_stop_loss(strategy_signal, entry_price, direction)
        tp_price = strategy.get_take_profit(strategy_signal, entry_price, direction, sl_price)

        return {
            "action": "trade",
            "signal_type": strategy_signal.signal_type.value,
            "direction": 1 if direction == SignalType.BUY else -1,
            "confidence": strategy_signal.confidence,
            "lot": position_size.lots,
            "entry_price": entry_price,
            "stop_loss": sl_price,
            "take_profit": tp_price,
            "risk_reward": position_size.risk_reward_ratio,
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy_mode": strategy_mode,
            "magic": strategy.MAGIC_NUMBER,
            "signals": strategy_signal.metadata,
        }

    def analyze_multi_tf(
        self,
        symbol: str,
        strategy_mode: str = "SWING",
    ) -> Dict[str, Any]:
        """Multi-timeframe analysis combining H4, D1 for swing signals."""
        timeframes = ["H4", "D1"] if strategy_mode == "SWING" else ["M5", "M15", "H1"]
        results = {}
        for tf in timeframes:
            results[tf] = self.analyze(symbol, timeframe=tf, strategy_mode=strategy_mode)
        return results

    def execute_trade(
        self,
        symbol: str,
        signal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a trade from the analysis result."""
        if signal.get("action") != "trade":
            return {"action": "no_trade", "reason": "signal_hold"}

        direction = signal["direction"]
        request = {
            "action": TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": signal["lot"],
            "type": ORDER_TYPE_BUY if direction == 1 else ORDER_TYPE_SELL,
            "price": signal["entry_price"],
            "sl": signal["stop_loss"],
            "tp": signal["take_profit"],
            "deviation": 10,
            "type_filling": ORDER_FILLING_IOC,
            "magic": signal["magic"],
            "comment": f"AFX_{signal['strategy_mode']}",
        }

        result = order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return {
                "action": "executed",
                "order": result.order,
                "deal": result.deal,
                "retcode": result.retcode,
            }
        return {"action": "failed", "retcode": getattr(result, "retcode", -1)}

    # ─── Indicator Calculation ─────────────────────────────────

    def _calc_indicators(
        self,
        df: pd.DataFrame,
        params: Optional[dict] = None,
    ) -> pd.DataFrame:
        """Calculate all indicators on dataframe."""
        p = params or {}
        df = df.copy()

        # EMA suite
        for span in [5, 8, 13, 21, 50, 200]:
            df[f"ema_{span}"] = df["close"].ewm(span=span, adjust=False).mean()

        # RSI
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        loss = loss.replace(0, 1e-10)
        df["rsi_14"] = 100 - (100 / (1 + gain / loss))

        # Bollinger Bands
        bb_std = df["close"].rolling(20).std()
        df["bb_mid"] = df["close"].rolling(20).mean()
        df["bb_upper"] = df["bb_mid"] + (bb_std * 2)
        df["bb_lower"] = df["bb_mid"] - (bb_std * 2)
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"] * 100

        # ATR
        tr = np.maximum(
            df["high"] - df["low"],
            np.maximum(
                abs(df["high"] - df["close"].shift(1)),
                abs(df["low"] - df["close"].shift(1)),
            )
        )
        df["atr"] = tr.rolling(14).mean()

        # MACD
        df["macd"] = df["close"].ewm(span=12).mean() - df["close"].ewm(span=26).mean()
        df["macd_signal"] = df["macd"].ewm(span=9).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        # Stochastic
        low14 = df["low"].rolling(14).min()
        high14 = df["high"].rolling(14).max()
        df["stoch_k"] = ((df["close"] - low14) / (high14 - low14)) * 100
        df["stoch_d"] = df["stoch_k"].rolling(3).mean()

        # VWAP
        df["vwap"] = (df["close"] * df["tick_volume"]).cumsum() / df["tick_volume"].cumsum()

        # Volume
        df["vol_ma"] = df["tick_volume"].rolling(20).mean()

        # Momentum
        df["mom"] = df["close"] - df["close"].shift(10)

        return df

    def _extract_indicators(self, df: pd.DataFrame) -> Dict[str, float]:
        """Extract latest indicator values as dict."""
        last = df.iloc[-1]
        prev = df.iloc[-2]
        return {
            "ema_5": float(last.get("ema_5", last["close"])),
            "ema_15": float(last.get("ema_21", last["close"])),
            "ema_50": float(last.get("ema_50", last["close"])),
            "ema_200": float(last.get("ema_200", last["close"])),
            "rsi_14": float(last.get("rsi_14", 50)),
            "bb_upper": float(last.get("bb_upper", last["close"] * 1.02)),
            "bb_lower": float(last.get("bb_lower", last["close"] * 0.98)),
            "bb_width": float(last.get("bb_width", 2.0)),
            "macd": float(last.get("macd", 0)),
            "macd_signal": float(last.get("macd_signal", 0)),
            "stoch_k": float(last.get("stoch_k", 50)),
            "stoch_d": float(last.get("stoch_d", 50)),
            "vwap": float(last.get("vwap", last["close"])),
            "atr": float(last.get("atr", last["close"] * 0.005)),
            "volume": float(last.get("tick_volume", 0)),
            "avg_volume": float(last.get("vol_ma", 1)),
            "ema_5_prev": float(prev.get("ema_5", prev["close"])),
            "ema_15_prev": float(prev.get("ema_21", prev["close"])),
            "rsi_14_prev": float(prev.get("rsi_14", 50)),
            "stoch_k_prev": float(prev.get("stoch_k", 50)),
            "stoch_d_prev": float(prev.get("stoch_d", 50)),
        }

    def _calc_stop_loss_pips(self, signal: TradeSignal, df: pd.DataFrame) -> float:
        """Calculate stop loss in pips based on ATR."""
        atr = df.iloc[-1].get("atr", df["close"].std() * 2)
        return float(atr * 1.5)

    # ─── Position Management ─────────────────────────────────────

    def manage_positions(self, symbol: str) -> List[Dict]:
        """Check and manage open positions for symbol."""
        open_positions = positions_get(symbol=symbol) or []
        my_positions = [
            p for p in open_positions
            if is_system_magic(p.magic) and p.symbol == symbol
        ]

        closed = []
        for pos in my_positions:
            sl_hit = self._check_sl(pos)
            tp_hit = self._check_tp(pos)
            if sl_hit or tp_hit:
                closed.append(self._close_position(pos, "sl" if sl_hit else "tp"))
        return closed

    def _check_sl(self, pos) -> bool:
        if pos.sl <= 0:
            return False
        tick = symbol_info_tick(pos.symbol)
        if tick is None:
            return False
        price = tick.bid if pos.type == ORDER_TYPE_BUY else tick.ask
        if pos.type == ORDER_TYPE_BUY and price <= pos.sl:
            return True
        if pos.type == ORDER_TYPE_SELL and price >= pos.sl:
            return True
        return False

    def _check_tp(self, pos) -> bool:
        if pos.tp <= 0:
            return False
        tick = symbol_info_tick(pos.symbol)
        if tick is None:
            return False
        price = tick.bid if pos.type == ORDER_TYPE_BUY else tick.ask
        if pos.type == ORDER_TYPE_BUY and price >= pos.tp:
            return True
        if pos.type == ORDER_TYPE_SELL and price <= pos.tp:
            return True
        return False

    def _close_position(self, pos, reason: str) -> Dict:
        close_type = ORDER_TYPE_SELL if pos.type == ORDER_TYPE_BUY else ORDER_TYPE_BUY
        tick = symbol_info_tick(pos.symbol)
        close_price = tick.bid if pos.type == ORDER_TYPE_BUY else tick.ask if tick else 0

        request = {
            "action": TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": pos.ticket,
            "price": close_price,
            "magic": pos.magic,
            "comment": f"BrainClose_{reason}",
            "type_time": 0,
            "type_filling": ORDER_FILLING_IOC,
        }
        result = order_send(request)
        return {"ticket": pos.ticket, "reason": reason, "result": result}


# ─── Backwards Compatibility ──────────────────────────────────
# Brain class retains the exact interface from brain_v1
# so all existing callers continue to work unchanged.

class Brain(BrainEngine):
    """Legacy Brain class — delegates to BrainEngine."""

    def analyze(self, symbol, timeframe=None, params=None, df=None):
        from mt5_mcp import TIMEFRAME_M1, TIMEFRAME_H4
        tf = timeframe or TIMEFRAME_H4
        return super().analyze(symbol=strymbol, timeframe=self._tf_to_str(tf), strategy_mode="SWING", params=params, df=df)

    def _tf_to_str(self, tf) -> str:
        tf_map = {
            TIMEFRAME_M1: "M1",
            5: "M5",
            15: "M15",
            16385: "H1",
            16388: "H4",
            16408: "D1",
        }
        return tf_map.get(tf, "H4")


# ─── Convenience Factory ───────────────────────────────────────
def get_brain() -> BrainEngine:
    return BrainEngine()