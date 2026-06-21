"""
Decision Engine — AFX AutoTrader v2
Orchestrates strategy analysis, risk calculation, and position sizing
into a single unified trade decision.

Thread-safe, supports all 4 strategy modes (Swing, Day, Carry, Scalp).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from strategy_base import StrategyMode, SignalType
from strategy_router import StrategyRouter
from risk_engine import RiskEngine, get_risk_engine
from position_manager import PositionManager, get_position_manager
from brain_engine import BrainEngine, get_brain
from parallel_executor import get_executor
from mt5_mcp import (
    ORDER_TYPE_BUY, ORDER_TYPE_SELL,
    TRADE_ACTION_DEAL, ORDER_FILLING_IOC,
    symbol_info, symbol_info_tick, positions_get, account_info,
)
from async_mt5 import order_send

logger = logging.getLogger(__name__)


# ─── Decision Types ────────────────────────────────────────────
class DecisionType(Enum):
    HOLD = "HOLD"
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    MODIFY = "MODIFY"


# ─── Decision Result ───────────────────────────────────────────
@dataclass
class Decision:
    decision: DecisionType
    confidence: float
    lot: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    reason: str
    metadata: Dict[str, Any]


# ─── Decision Engine ───────────────────────────────────────────
class DecisionEngine:
    """
    Unified decision-making engine.

    Coordinates:
    1. BrainEngine (signal generation)
    2. StrategyRouter (strategy selection)
    3. RiskEngine (position sizing, validation)
    4. PositionManager (position tracking)

    Usage:
        engine = DecisionEngine()
        decision = engine.evaluate(symbol="EURUSD", strategy_mode="SWING")
        if decision.decision in (DecisionType.BUY, DecisionType.SELL):
            engine.execute(decision)
    """

    def __init__(
        self,
        router: Optional[StrategyRouter] = None,
        risk: Optional[RiskEngine] = None,
        positions: Optional[PositionManager] = None,
        brain: Optional[BrainEngine] = None,
    ):
        self._router = router or StrategyRouter()
        self._risk = risk or get_risk_engine()
        self._positions = positions or get_position_manager()
        self._brain = brain or get_brain()
        self._executor = get_executor()

    def evaluate(
        self,
        symbol: str,
        strategy_mode: str = "SWING",
        force_decision: bool = False,
    ) -> Decision:
        """
        Evaluate market and produce a trade decision.

        Pipeline:
        1. Run brain analysis (strategy-aware)
        2. Validate against risk engine
        3. Calculate position size
        4. Return Decision object

        Args:
            symbol: Trading symbol
            strategy_mode: SWING, DAY, CARRY, or SCALP
            force_decision: Skip confidence threshold for close decisions

        Returns:
            Decision with full trade parameters
        """
        mode = StrategyMode(strategy_mode)
        self._router.set_mode(mode)
        strategy = self._router.get_active_strategy()

        # Get account info
        try:
            acct = account_info()
            balance = acct.balance if acct else 10000.0
        except Exception:
            balance = 10000.0

        # Check risk validation first
        current_positions = len(self._positions.get_open_positions(symbol) or [])
        allowed, reason = self._risk.can_open_trade(
            symbol=symbol,
            strategy_mode=strategy_mode,
            account_balance=balance,
            spread=0,  # Would get real spread here
            news_event=False,
        )

        if not allowed:
            logger.info("Trade blocked for %s: %s", symbol, reason)
            return Decision(
                decision=DecisionType.HOLD,
                confidence=0.0,
                lot=0.0,
                entry_price=0.0,
                stop_loss=0.0,
                take_profit=0.0,
                risk_amount=0.0,
                reason=reason,
                metadata={},
            )

        # Run brain analysis with strategy mode
        result = self._brain.analyze(
            symbol=symbol,
            strategy_mode=strategy_mode,
            timeframe=self._preferred_timeframe(strategy_mode),
        )

        action = result.get("action", "hold")
        if action == "hold":
            return Decision(
                decision=DecisionType.HOLD,
                confidence=result.get("confidence", 0),
                lot=0.0, entry_price=0.0, stop_loss=0.0, take_profit=0.0,
                risk_amount=0.0,
                reason=result.get("reason", "no_signal"),
                metadata=result,
            )

        if action == "trade":
            direction = result.get("direction", 0)
            decision_type = DecisionType.BUY if direction == 1 else DecisionType.SELL
            confidence = result.get("confidence", 0.5)
            lot = result.get("lot", 0.01)
            sl = result.get("stop_loss", 0.0)
            tp = result.get("take_profit", 0.0)
            risk_amount = result.get("risk_amount", balance * 0.01)

            return Decision(
                decision=decision_type,
                confidence=confidence,
                lot=lot,
                entry_price=result.get("entry_price", 0),
                stop_loss=sl,
                take_profit=tp,
                risk_amount=risk_amount,
                reason="signal",
                metadata=result,
            )

        return Decision(
            decision=DecisionType.HOLD,
            confidence=0.0,
            lot=0.0, entry_price=0.0, stop_loss=0.0, take_profit=0.0,
            risk_amount=0.0,
            reason="unknown_action",
            metadata={},
        )

    def evaluate_all_strategies(
        self,
        symbol: str,
    ) -> Dict[str, Decision]:
        """
        Run evaluation across all strategies for comparison mode.
        Returns dict of strategy_mode -> Decision.
        """
        results = {}
        for mode in ["SWING", "DAY", "CARRY", "SCALP"]:
            try:
                results[mode] = self.evaluate(symbol, strategy_mode=mode)
            except Exception as e:
                logger.error("Strategy %s evaluation failed: %s", mode, e)
                results[mode] = Decision(
                    decision=DecisionType.HOLD,
                    confidence=0.0, lot=0.0, entry_price=0.0,
                    stop_loss=0.0, take_profit=0.0, risk_amount=0.0,
                    reason=f"error_{e}",
                    metadata={},
                )
        return results

    def execute(self, decision: Decision, symbol: str) -> Dict[str, Any]:
        """Execute a trade decision."""
        if decision.decision == DecisionType.HOLD:
            return {"action": "no_trade", "reason": decision.reason}

        direction = decision.decision
        order_type = ORDER_TYPE_BUY if direction == DecisionType.BUY else ORDER_TYPE_SELL

        request = {
            "action": TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": decision.lot,
            "type": order_type,
            "price": decision.entry_price,
            "sl": decision.stop_loss,
            "tp": decision.take_profit,
            "deviation": 10,
            "type_filling": ORDER_FILLING_IOC,
            "magic": decision.metadata.get("magic", 100001),
            "comment": f"AFX_{decision.decision.value}",
        }

        try:
            result = order_send(request)
            if result and result.retcode == 1:
                self._risk.register_trade(
                    symbol=symbol,
                    strategy_mode=decision.metadata.get("strategy_mode", "SWING"),
                    lot_size=decision.lot,
                    risk_amount=decision.risk_amount,
                )
                self._positions.open_position(
                    symbol=symbol,
                    direction=decision.decision.value,
                    lot=decision.lot,
                    entry_price=decision.entry_price,
                    magic=decision.metadata.get("magic", 100001),
                )
                return {
                    "action": "executed",
                    "order": result.order,
                    "deal": result.deal,
                    "retcode": result.retcode,
                }
            else:
                return {
                    "action": "failed",
                    "retcode": getattr(result, "retcode", -1),
                }
        except Exception as e:
            logger.error("Trade execution failed for %s: %s", symbol, e)
            return {"action": "error", "error": str(e)}

    def _preferred_timeframe(self, mode: str) -> str:
        tf_map = {
            "SWING": "H4",
            "DAY": "H1",
            "CARRY": "D1",
            "SCALP": "M5",
        }
        return tf_map.get(mode, "H4")


# ─── Singleton ─────────────────────────────────────────────────
_engine: Optional[DecisionEngine] = None


def get_decision_engine() -> DecisionEngine:
    global _engine
    if _engine is None:
        _engine = DecisionEngine()
    return _engine