"""
Strategy Base Framework — AFX AutoTrader v2
Provides abstract base class and shared types for all trading strategies.
Magic numbers are registered here and inherited by each strategy.
"""

from __future__ import annotations

import os
import uuid
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Optional, List, Dict, Any

import numpy as np


# ─── Magic Numbers ────────────────────────────────────────────
class StrategyMagic(IntEnum):
    """Unique magic numbers per strategy. 6 digits, ranges by strategy type."""
    SWING = 100001
    DAY = 200002
    CARRY = 300003
    SCALP = 400004


# ─── Strategy Mode ─────────────────────────────────────────────
class StrategyMode(Enum):
    SWING = "SWING"
    DAY = "DAY"
    CARRY = "CARRY"
    SCALP = "SCALP"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"


# ─── Timeframes ────────────────────────────────────────────────
class Timeframe(Enum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"


# ─── Signal Types ───────────────────────────────────────────────
class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    CLOSE_BUY = "CLOSE_BUY"
    CLOSE_SELL = "CLOSE_SELL"


# ─── Risk Profile ──────────────────────────────────────────────
@dataclass
class RiskProfile:
    """Risk parameters for a single trade."""
    account_balance: float
    risk_percent: float  # e.g., 0.01 = 1%
    max_positions: int
    max_drawdown_percent: float
    max_daily_loss_percent: float

    @property
    def risk_amount(self) -> float:
        return self.account_balance * self.risk_percent

    def validate(self) -> None:
        if not 0 < self.risk_percent <= 0.1:
            raise ValueError(f"risk_percent must be 0-10%, got {self.risk_percent}")
        if not self.account_balance > 0:
            raise ValueError(f"account_balance must be positive, got {self.account_balance}")


# ─── Market Data ───────────────────────────────────────────────
@dataclass
class MarketData:
    """Standardized market data input for strategy analysis."""
    symbol: str
    timeframe: str
    time: int
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    spread: float
    volume: float
    # Optional indicators pre-computed
    indicators: Dict[str, float] = field(default_factory=dict)
    # Additional context
    session: str = ""  # "asian", "london", "new_york"
    news_event: bool = False
    is_holiday: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


# ─── Position Size ─────────────────────────────────────────────
@dataclass
class PositionSize:
    """Calculated position size for a trade."""
    lots: float
    risk_amount: float
    risk_percent: float
    stop_loss_pips: float
    take_profit_pips: float
    risk_reward_ratio: float


# ─── Trade Signal ──────────────────────────────────────────────
@dataclass
class TradeSignal:
    """Output from strategy.analyze() — a trade decision."""
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    strategy_mode: StrategyMode = StrategyMode.SWING
    magic_number: int = 0
    symbol: str = ""
    signal_type: SignalType = SignalType.HOLD
    confidence: float = 0.0  # 0.0 - 1.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    timeframe: str = "H4"
    timestamp: int = field(default_factory=lambda: int(time.time()))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_actionable(self) -> bool:
        return self.signal_type in (SignalType.BUY, SignalType.SELL)


# ─── Trade Result ──────────────────────────────────────────────
@dataclass
class TradeResult:
    """Outcome of a trade for journal and learning."""
    signal_id: str
    magic_number: int
    symbol: str
    entry_price: float
    exit_price: float
    lots: float
    pnl: float
    pnl_percent: float
    duration_seconds: int
    exit_reason: str  # "tp_hit", "sl_hit", "manual", "strategy"
    timestamp: int


# ─── Base Strategy ─────────────────────────────────────────────
class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Each strategy must:
    1. Define its MAGIC_NUMBER (unique per strategy)
    2. Implement analyze() — generate TradeSignal from MarketData
    3. Implement calculate_position_size() — compute lot size
    4. Implement get_stop_loss() / get_take_profit()
    5. Implement validate_entry_conditions()

    Strategy modes are mutually exclusive per execution context.
    Multiple strategies can run in parallel for comparison.
    """

    MAGIC_NUMBER: int = 0  # Must be set by subclass
    strategy_name: str = "BASE"
    strategy_version: str = "v1"

    # Timeframe preferences (override in subclass)
    preferred_timeframes: List[str] = ["H4", "D1"]

    # Risk defaults (override in subclass)
    default_risk_percent: float = 0.01  # 1%
    max_positions: int = 5

    def __init__(self, risk_profile: Optional[RiskProfile] = None):
        if self.MAGIC_NUMBER == 0:
            raise ValueError(f"{self.__class__.__name__} must set MAGIC_NUMBER")
        self._validate_magic_number()
        self.risk_profile = risk_profile or self._default_risk_profile()

    def _validate_magic_number(self) -> None:
        if self.MAGIC_NUMBER <= 0:
            raise ValueError(f"MAGIC_NUMBER must be positive, got {self.MAGIC_NUMBER}")
        if self.MAGIC_NUMBER % 1 != 0:
            raise ValueError(f"MAGIC_NUMBER must be integer")

    def _default_risk_profile(self) -> RiskProfile:
        return RiskProfile(
            account_balance=10000.0,
            risk_percent=self.default_risk_percent,
            max_positions=self.max_positions,
            max_drawdown_percent=0.15,
            max_daily_loss_percent=0.05
        )

    @abstractmethod
    def analyze(self, market_data: MarketData) -> TradeSignal:
        """
        Analyze market data and return a trade signal.
        This is the main entry point for strategy decision-making.

        Args:
            market_data: Standardized market data with indicators

        Returns:
            TradeSignal with signal_type, entry/stop/tp prices, confidence
        """
        ...

    @abstractmethod
    def calculate_position_size(
        self,
        signal: TradeSignal,
        risk_profile: RiskProfile,
        stop_loss_pips: float
    ) -> PositionSize:
        """
        Calculate position size based on risk parameters.

        Args:
            signal: The trade signal from analyze()
            risk_profile: Account risk parameters
            stop_loss_pips: Stop loss distance in pips

        Returns:
            PositionSize with lot size and risk details
        """
        ...

    @abstractmethod
    def get_stop_loss(
        self,
        signal: TradeSignal,
        entry_price: float,
        direction: SignalType
    ) -> float:
        """
        Calculate stop loss price for the signal.

        Args:
            signal: The trade signal
            entry_price: Planned entry price
            direction: BUY or SELL

        Returns:
            Stop loss price
        """
        ...

    @abstractmethod
    def get_take_profit(
        self,
        signal: TradeSignal,
        entry_price: float,
        direction: SignalType,
        stop_loss: float
    ) -> float:
        """
        Calculate take profit price for the signal.

        Args:
            signal: The trade signal
            entry_price: Planned entry price
            direction: BUY or SELL
            stop_loss: Calculated stop loss price

        Returns:
            Take profit price
        """
        ...

    @abstractmethod
    def validate_entry_conditions(self, market_data: MarketData) -> bool:
        """
        Check all pre-conditions before allowing entry.
        Override for strategy-specific entry rules.

        Args:
            market_data: Current market data

        Returns:
            True if entry conditions are met
        """
        ...

    def pre_analyze(self, market_data: MarketData) -> None:
        """
        Hook called before analyze(). Use for setup.
        Default: no-op. Override for custom behavior.
        """
        pass

    def post_analyze(self, signal: TradeSignal) -> TradeSignal:
        """
        Hook called after analyze(). Use for signal post-processing.
        Default: no-op. Override for custom behavior.
        """
        return signal

    def get_risk_profile_for_signal(
        self,
        signal: TradeSignal,
        account_balance: float
    ) -> RiskProfile:
        """
        Get strategy-specific risk profile.
        Override to implement strategy-specific risk rules.
        """
        return self.risk_profile

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"magic={self.MAGIC_NUMBER}, "
            f"name={self.strategy_name}, "
            f"version={self.strategy_version})"
        )


# ─── Strategy Registry ─────────────────────────────────────────
_STRATEGY_REGISTRY: Dict[int, type[BaseStrategy]] = {}


def register_strategy(cls: type[BaseStrategy]) -> type[BaseStrategy]:
    """Class decorator to register strategy in global registry."""
    if cls.MAGIC_NUMBER in _STRATEGY_REGISTRY:
        raise ValueError(
            f"Magic number {cls.MAGIC_NUMBER} already registered to "
            f"{_STRATEGY_REGISTRY[cls.MAGIC_NUMBER].__name__}"
        )
    _STRATEGY_REGISTRY[cls.MAGIC_NUMBER] = cls
    return cls


def get_strategy_by_magic(magic: int) -> Optional[type[BaseStrategy]]:
    """Get strategy class by magic number."""
    return _STRATEGY_REGISTRY.get(magic)


def get_strategy_by_mode(mode: StrategyMode) -> Optional[type[BaseStrategy]]:
    """Get strategy class by mode name."""
    mode_map = {
        StrategyMode.SWING: StrategyMagic.SWING,
        StrategyMode.DAY: StrategyMagic.DAY,
        StrategyMode.CARRY: StrategyMagic.CARRY,
        StrategyMode.SCALP: StrategyMagic.SCALP,
    }
    magic = mode_map.get(mode)
    if magic is None:
        return None
    return _STRATEGY_REGISTRY.get(int(magic))


def list_registered_strategies() -> List[Dict[str, Any]]:
    """List all registered strategies."""
    return [
        {
            "name": cls.strategy_name,
            "magic": cls.MAGIC_NUMBER,
            "version": cls.strategy_version,
        }
        for cls in _STRATEGY_REGISTRY.values()
    ]