"""
Strategy Router — AFX AutoTrader v2
Routes analysis requests to the active strategy based on configured mode.
Thread-safe singleton with dynamic mode switching.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from strategy_base import (
    StrategyMode,
    StrategyMagic,
    BaseStrategy,
    TradeSignal,
    MarketData,
    RiskProfile,
    get_strategy_by_magic,
)
from strategy_swing import SwingStrategy
from strategy_day import DayStrategy
from strategy_carry import CarryStrategy
from strategy_scalp import ScalpStrategy


class StrategyRouter:
    """
    Routes trade analysis to the active strategy.
    Thread-safe, supports dynamic mode switching.

    Usage:
        router = StrategyRouter()
        router.set_mode(StrategyMode.SWING)
        signal = router.analyze(market_data)
    """

    _instance: Optional["StrategyRouter"] = None
    _lock = threading.RLock()

    def __new__(cls) -> "StrategyRouter":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._strategies: dict[int, BaseStrategy] = {}
        self._active_magic: int = int(StrategyMagic.SWING)
        self._active_mode: StrategyMode = StrategyMode.SWING
        self._mode_lock = threading.RLock()

        self._register_all_strategies()
        self._load_mode_from_env()

    def _register_all_strategies(self) -> None:
        self._strategies[int(StrategyMagic.SWING)] = SwingStrategy()
        self._strategies[int(StrategyMagic.DAY)] = DayStrategy()
        self._strategies[int(StrategyMagic.CARRY)] = CarryStrategy()
        self._strategies[int(StrategyMagic.SCALP)] = ScalpStrategy()

    def _load_mode_from_env(self) -> None:
        mode_str = os.getenv("ACTIVE_STRATEGY_MODE", "").upper()
        if mode_str:
            try:
                mode = StrategyMode[mode_str]
                self.set_mode(mode)
            except KeyError:
                pass  # Use default SWING

    def set_mode(self, mode: StrategyMode) -> None:
        """Switch active strategy mode. Thread-safe."""
        magic_map = {
            StrategyMode.SWING: StrategyMagic.SWING,
            StrategyMode.DAY: StrategyMagic.DAY,
            StrategyMode.CARRY: StrategyMagic.CARRY,
            StrategyMode.SCALP: StrategyMagic.SCALP,
        }
        magic = magic_map.get(mode)
        if magic is None:
            raise ValueError(f"Invalid mode: {mode}")

        with self._mode_lock:
            self._active_mode = mode
            self._active_magic = int(magic)

    def get_mode(self) -> StrategyMode:
        """Get current active strategy mode."""
        with self._mode_lock:
            return self._active_mode

    def get_active_strategy(self) -> BaseStrategy:
        """Get the active strategy instance."""
        with self._mode_lock:
            strategy = self._strategies.get(self._active_magic)
            if strategy is None:
                strategy = self._strategies[int(StrategyMagic.SWING)]
            return strategy

    def analyze(self, market_data: MarketData) -> TradeSignal:
        """
        Analyze market data using the active strategy.
        Returns TradeSignal with entry/stop/tp levels.
        """
        strategy = self.get_active_strategy()
        return strategy.analyze(market_data)

    def analyze_all(
        self,
        market_data: MarketData
    ) -> dict[StrategyMode, TradeSignal]:
        """
        Run analysis through ALL strategies (for comparison mode).
        Returns dict of mode -> signal.
        """
        results = {}
        for magic, strategy in self._strategies.items():
            with self._mode_lock:
                mode = StrategyMode(
                    list(StrategyMode)[list(StrategyMagic).index(StrategyMagic(magic))]
                )
            try:
                signal = strategy.analyze(market_data)
                results[mode] = signal
            except Exception as e:
                pass  # Log and continue
        return results

    def update_risk_profile(self, risk_profile: RiskProfile) -> None:
        """Update risk profile on all strategies."""
        for strategy in self._strategies.values():
            strategy.risk_profile = risk_profile

    def get_strategy(self, mode: StrategyMode) -> BaseStrategy:
        """Get a specific strategy by mode."""
        magic_map = {
            StrategyMode.SWING: StrategyMagic.SWING,
            StrategyMode.DAY: StrategyMagic.DAY,
            StrategyMode.CARRY: StrategyMagic.CARRY,
            StrategyMode.SCALP: StrategyMagic.SCALP,
        }
        magic = magic_map.get(mode)
        if magic is None:
            raise ValueError(f"Invalid mode: {mode}")
        return self._strategies.get(int(magic))

    def list_modes(self) -> list[dict]:
        """List all available strategy modes."""
        return [
            {
                "mode": mode.value,
                "magic": int(magic_map[mode]),
                "active": mode == self._active_mode,
            }
            for mode, magic_map in [
                (StrategyMode.SWING, {StrategyMode.SWING: StrategyMagic.SWING}),
                (StrategyMode.DAY, {StrategyMode.DAY: StrategyMagic.DAY}),
                (StrategyMode.CARRY, {StrategyMode.CARRY: StrategyMagic.CARRY}),
                (StrategyMode.SCALP, {StrategyMode.SCALP: StrategyMagic.SCALP}),
            ]
        ]

    def __repr__(self) -> str:
        with self._mode_lock:
            return (
                f"StrategyRouter("
                f"active={self._active_mode.value}, "
                f"magic={self._active_magic})"
            )