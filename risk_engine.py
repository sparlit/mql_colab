"""
Risk Engine — AFX AutoTrader v2
Unified risk management combining portfolio_risk.py and risk_advanced.py.
Multi-strategy support with portfolio-level and per-trade risk controls.

Handles: position sizing, drawdown protection, correlation risk, tail risk.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ─── Risk Enums ────────────────────────────────────────────────
class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ─── Risk Profile ──────────────────────────────────────────────
@dataclass
class RiskLimits:
    """System-wide risk limits."""
    max_total_risk_percent: float = 0.06      # 6% of account at once
    max_single_trade_percent: float = 0.02   # 2% per trade
    max_drawdown_percent: float = 0.15        # 15% max drawdown
    max_correlation: float = 0.7              # Max correlation between positions
    max_positions_per_strategy: int = 10
    max_total_positions: int = 20
    daily_loss_limit_percent: float = 0.05    # 5% daily loss limit
    max_spread_to_trade: float = 5.0           # Max spread in pips


@dataclass
class TradeRisk:
    """Risk calculation result for a single trade."""
    lot_size: float
    risk_amount: float
    risk_percent: float
    stop_loss_pips: float
    take_profit_pips: float
    risk_reward: float
    kelly_fraction: float
    risk_level: RiskLevel


# ─── Risk Engine ───────────────────────────────────────────────
class RiskEngine:
    """
    Centralized risk management for all strategies.

    Features:
    - Kelly criterion position sizing
    - Portfolio-level risk limits
    - Drawdown circuit breaker
    - Correlation-based position limits
    - Multi-strategy support (Swing, Day, Carry, Scalp)
    """

    def __init__(self, limits: Optional[RiskLimits] = None):
        self._limits = limits or RiskLimits()
        self._equity_peak = 10000.0
        self._daily_loss = 0.0
        self._daily_start_equity = 10000.0
        self._circuit_open = False
        self._open_trades: Dict[str, dict] = {}
        self._trade_history: List[dict] = []
        self._strategy_positions: Dict[str, int] = {
            "SWING": 0, "DAY": 0, "CARRY": 0, "SCALP": 0
        }

    # ─── Position Sizing ─────────────────────────────────────────

    def calculate_position_size(
        self,
        account_balance: float,
        risk_percent: float,
        stop_loss_pips: float,
        strategy_mode: str = "SWING",
    ) -> TradeRisk:
        """
        Calculate position size using Kelly criterion with conservative dampening.

        Args:
            account_balance: Current account balance
            risk_percent: Risk per trade (e.g., 0.015 for 1.5%)
            stop_loss_pips: Stop loss distance in pips
            strategy_mode: SWING, DAY, CARRY, SCALP

        Returns:
            TradeRisk with lot size and risk parameters
        """
        if self._circuit_open:
            raise RuntimeError("Risk circuit breaker is open — trading disabled")

        risk_amount = account_balance * risk_percent
        pip_value = 10.0  # $10 per pip per standard lot

        if stop_loss_pips <= 0:
            raise ValueError(f"stop_loss_pips must be positive, got {stop_loss_pips}")

        lot_size = round(risk_amount / (stop_loss_pips * pip_value), 2)
        lot_size = max(0.01, min(lot_size, self._max_lot_for_strategy(strategy_mode)))

        # Kelly fraction (conservative — use 1/3 Kelly)
        kelly = self._calculate_kelly()
        kelly_fraction = kelly / 3

        # Risk level assessment
        risk_level = self._assess_risk_level(
            account_balance, risk_percent, lot_size
        )

        return TradeRisk(
            lot_size=lot_size,
            risk_amount=risk_amount,
            risk_percent=risk_percent,
            stop_loss_pips=stop_loss_pips,
            take_profit_pips=stop_loss_pips * 2,  # Default 1:2 R:R
            risk_reward=2.0,
            kelly_fraction=kelly_fraction,
            risk_level=risk_level,
        )

    def _max_lot_for_strategy(self, mode: str) -> float:
        limits = {
            "SWING": 10.0,
            "DAY": 5.0,
            "CARRY": 20.0,
            "SCALP": 1.0,
        }
        return limits.get(mode, 10.0)

    def _calculate_kelly(self) -> float:
        """Calculate Kelly criterion fraction from trade history."""
        if len(self._trade_history) < 10:
            return 0.01  # Default conservative

        recent = self._trade_history[-100:]
        wins = [t["profit"] for t in recent if t.get("profit", 0) > 0]
        losses = [abs(t["profit"]) for t in recent if t.get("profit", 0) < 0]

        if not wins or not losses:
            return 0.01

        win_rate = len(wins) / len(recent)
        avg_win = np.mean(wins)
        avg_loss = np.mean(losses)

        if avg_loss == 0:
            return 0.01

        W = win_rate
        R = avg_win / avg_loss
        kelly = (W * R - (1 - W)) / R

        return max(0.01, min(kelly, 0.25))

    def _assess_risk_level(
        self,
        account_balance: float,
        risk_percent: float,
        lot_size: float,
    ) -> RiskLevel:
        """Assess current risk level for the account."""
        # Check total exposure
        total_risk = sum(t.get("risk_amount", 0) for t in self._open_trades.values())
        total_exposure = total_risk + (lot_size * risk_percent * account_balance)

        if total_exposure > account_balance * 0.10:
            return RiskLevel.CRITICAL
        if total_exposure > account_balance * 0.06:
            return RiskLevel.HIGH
        if total_exposure > account_balance * 0.03:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    # ─── Trade Validation ────────────────────────────────────────

    def validate_trade(
        self,
        symbol: str,
        strategy_mode: str,
        account_balance: float,
        current_positions: int,
    ) -> Tuple[bool, str]:
        """
        Validate whether a trade is allowed under current risk constraints.

        Returns:
            (allowed, reason) — if False, reason explains why
        """
        # Circuit breaker check
        if self._circuit_open:
            return False, "circuit_breaker_open"

        # Daily loss limit
        daily_loss_pct = self._daily_loss / self._daily_start_equity
        if daily_loss_pct >= self._limits.daily_loss_limit_percent:
            self._open_circuit("daily_loss_limit_exceeded")
            return False, "daily_loss_limit_exceeded"

        # Max total positions
        if current_positions >= self._limits.max_total_positions:
            return False, "max_positions_reached"

        # Per-strategy position limit
        if self._strategy_positions.get(strategy_mode, 0) >= self._limits.max_positions_per_strategy:
            return False, f"max_{strategy_mode.lower()}_positions"

        # Drawdown check
        current_equity = account_balance + self._daily_loss
        drawdown = (self._equity_peak - current_equity) / self._equity_peak
        if drawdown >= self._limits.max_drawdown_percent:
            self._open_circuit("drawdown_limit_exceeded")
            return False, "drawdown_limit_exceeded"

        return True, "ok"

    def can_open_trade(
        self,
        symbol: str,
        strategy_mode: str,
        account_balance: float,
        spread: float = 0.0,
        news_event: bool = False,
    ) -> Tuple[bool, str]:
        """Extended pre-trade validation."""
        allowed, reason = self.validate_trade(
            symbol, strategy_mode, account_balance,
            len(self._open_trades)
        )
        if not allowed:
            return False, reason

        # Spread check
        if spread > self._limits.max_spread_to_trade:
            return False, f"spread_too_wide_{spread}"

        # News event filter
        if news_event and strategy_mode != "SCALP":
            return False, "news_event_blocked"

        # Symbol already has position
        if symbol in self._open_trades:
            return False, "position_exists"

        return True, "ok"

    # ─── Circuit Breaker ─────────────────────────────────────────

    def _open_circuit(self, reason: str) -> None:
        """Open the risk circuit breaker — blocks all new trades."""
        if not self._circuit_open:
            logger.warning("Risk circuit breaker OPENED: %s", reason)
            self._circuit_open = True

    def reset_circuit(self) -> None:
        """Manually reset circuit breaker (after investigation)."""
        logger.info("Risk circuit breaker reset")
        self._circuit_open = False

    def is_circuit_open(self) -> bool:
        return self._circuit_open

    # ─── Position Tracking ───────────────────────────────────────

    def register_trade(
        self,
        symbol: str,
        strategy_mode: str,
        lot_size: float,
        risk_amount: float,
    ) -> None:
        """Register an open trade for tracking."""
        self._open_trades[symbol] = {
            "strategy_mode": strategy_mode,
            "lot_size": lot_size,
            "risk_amount": risk_amount,
            "opened_at": time.time(),
        }
        self._strategy_positions[strategy_mode] = self._strategy_positions.get(strategy_mode, 0) + 1

    def close_trade(self, symbol: str, profit: float) -> None:
        """Record trade closure and update state."""
        trade = self._open_trades.pop(symbol, None)
        if trade:
            mode = trade["strategy_mode"]
            self._strategy_positions[mode] = max(0, self._strategy_positions.get(mode, 1) - 1)
            self._trade_history.append({
                "profit": profit,
                "mode": mode,
                "timestamp": time.time(),
            })

        # Update daily loss
        self._daily_loss += profit
        if profit > 0:
            # New peak
            current_equity = self._daily_start_equity + self._daily_loss
            self._equity_peak = max(self._equity_peak, current_equity)

    def reset_daily(self, account_balance: float) -> None:
        """Reset daily tracking at trading day boundary."""
        self._daily_loss = 0.0
        self._daily_start_equity = account_balance
        self._equity_peak = account_balance
        logger.info("Daily risk reset — equity: %.2f", account_balance)

    # ─── Correlation Risk ────────────────────────────────────────

    def check_correlation_risk(
        self,
        new_symbol: str,
        existing_symbols: List[str],
        correlation_matrix: Dict[str, Dict[str, float]],
        threshold: float = 0.7,
    ) -> Tuple[bool, float]:
        """
        Check if adding new_symbol would exceed correlation threshold.

        Returns:
            (allowed, max_correlation)
        """
        max_corr = 0.0
        for existing in existing_symbols:
            if existing == new_symbol:
                continue
            corr = correlation_matrix.get(new_symbol, {}).get(existing, 0.0)
            max_corr = max(max_corr, abs(corr))

        if max_corr > threshold:
            return False, max_corr
        return True, max_corr

    # ─── Reporting ───────────────────────────────────────────────

    def get_risk_status(self, account_balance: float) -> dict:
        """Get current risk status for dashboard display."""
        current_equity = account_balance + self._daily_loss
        drawdown = (self._equity_peak - current_equity) / self._equity_peak if self._equity_peak > 0 else 0

        total_exposure = sum(t.get("risk_amount", 0) for t in self._open_trades.values())
        total_risk_pct = total_exposure / account_balance if account_balance > 0 else 0

        return {
            "circuit_open": self._circuit_open,
            "drawdown_percent": round(drawdown * 100, 2),
            "daily_loss_percent": round(abs(self._daily_loss) / self._daily_start_equity * 100, 2)
                                  if self._daily_start_equity > 0 else 0,
            "total_exposure_percent": round(total_risk_pct * 100, 2),
            "open_positions": len(self._open_trades),
            "strategy_positions": self._strategy_positions.copy(),
            "total_risk_amount": total_exposure,
            "equity_peak": self._equity_peak,
            "current_equity": current_equity,
        }


# ─── Singleton ─────────────────────────────────────────────────
_risk_engine: Optional[RiskEngine] = None


def get_risk_engine() -> RiskEngine:
    global _risk_engine
    if _risk_engine is None:
        _risk_engine = RiskEngine()
    return _risk_engine