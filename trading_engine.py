"""High‑performance trading engine with ultra‑low latency pipeline.

The engine overlaps async MT5 I/O with parallel CPU work so that there is
almost no idle time between stages. This satisfies the requirement that
*the response time between each section be as low as possible while still
maintaining stable communication*.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import async_mt5
import mt5_mcp as mt5
from parallel_executor import get_executor

# Existing Brain components – they already use the ParallelExecutor for
# heavy‑weight signal calculations.
from brain_v1 import SignalAnalyzer, BrainStats, RiskManager

logger = logging.getLogger(__name__)


def _run_coroutine(coro):
    """Run a coroutine in a fresh event loop (used for legacy blocking API)."""
    return asyncio.run(coro)


class TradingEngine:
    """Core orchestration class.

    Public API:
        * ``execute`` – synchronous façade for legacy callers.
        * ``async_execute`` – coroutine that runs the ultra‑low‑latency pipeline.
    """

    def __init__(self) -> None:
        self._executor = get_executor()
        self._stats = BrainStats()               # persistent trade history
        self._analyzer = SignalAnalyzer()        # signal‑generation component
        self._risk = RiskManager(self._stats)       # risk management

    # ---------------------------------------------------------------------
    # Legacy blocking façade
    # ---------------------------------------------------------------------
    def execute(
        self,
        symbol: str,
        timeframe: int,
        params: Optional[dict] = None,
        df: Optional[Any] = None,
    ) -> Dict:
        """Synchronous wrapper that runs the async pipeline and returns its result."""
        return _run_coroutine(
            self.async_execute(symbol, timeframe, params, df)
        )

    # ---------------------------------------------------------------------
    # Async pipeline – fully overlapped I/O and CPU work
    # ---------------------------------------------------------------------
    async def async_execute(
        self,
        symbol: str,
        timeframe: int,
        params: Optional[dict] = None,
        df: Optional[Any] = None,
    ) -> Dict:
        """Execute a single trading decision with minimal latency.

        Steps (run in parallel where possible):
        1️⃣ Fetch latest tick (async MT5 I/O).
        2️⃣ Generate all signals (CPU‑bound, run in thread pool).
        3️⃣ Compute risk / Kelly fraction (CPU‑bound, separate thread).
        4️⃣ Decision logic (pure Python, negligible time).
        5️⃣ Place order (async MT5 I/O).
        6️⃣ Record trade synchronously (fast I/O).
        """
        loop = asyncio.get_event_loop()

        # --------------------------
        # 1️⃣ Async tick fetch
        # --------------------------
        tick_task = loop.create_task(async_mt5.symbol_info_tick(symbol))

        # --------------------------
        # 2️⃣ Parallel signal generation
        # --------------------------
        signals_future = loop.run_in_executor(
            None,
            lambda: self._analyzer.calculate_all_signals(
                symbol, timeframe, params, df
            ),
        )

        # Wait for both to finish as soon as possible
        tick = await tick_task
        signals_result = await signals_future

        if not tick:
            logger.warning("No tick data for %s – aborting execution", symbol)
            return {"action": "hold", "reason": "no_tick"}

        signals = signals_result["signals"]
        df_used = signals_result["df"]  # retained for possible downstream use

        # --------------------------
        # 3️⃣ Risk / Kelly fraction (run in separate thread while we do decision logic)
        # --------------------------
        risk_future = loop.run_in_executor(
            None,
            lambda: self._stats.get_kelly_fraction(lookback=100),
        )

        # --------------------------
        # 4️⃣ Decision logic (pure Python – executes immediately)
        # --------------------------
        weighted_buy = weighted_sell = total_weight = 0.0
        active_signals: List[str] = []

        for name, sig in signals.items():
            weight = self._analyzer.STRATEGY_WEIGHTS.get(name, 1.0)  # type: ignore[attr-defined]
            if sig["direction"] == 1:
                weighted_buy += sig["confidence"] * weight
                active_signals.append(f"+{name}({sig['confidence']:.2f})")
            elif sig["direction"] == -1:
                weighted_sell += sig["confidence"] * weight
                active_signals.append(f"-{name}({sig['confidence']:.2f})")
            total_weight += weight

        buy_score = weighted_buy / total_weight if total_weight else 0.0
        sell_score = weighted_sell / total_weight if total_weight else 0.0
        net_score = buy_score - sell_score
        confidence = abs(net_score)
        direction = (
            1 if net_score > 0 else -1 if net_score < 0 else 0
        )

        # Retrieve risk result (await if not ready yet)
        kelly_fraction = await risk_future
        lot = max(0.01, round(kelly_fraction * 0.1, 2))

        # --------------------------
        # 5️⃣ Async order placement (only if we have a valid signal)
        # --------------------------
        if direction == 0 or confidence < 0.5:
            logger.info("No actionable signal for %s – holding", symbol)
            return {
                "action": "hold",
                "direction": direction,
                "confidence": confidence,
                "buy_score": buy_score,
                "sell_score": sell_score,
                "signals": signals,
                "active": active_signals,
            }

        ok, reason = self._risk.can_open_trade(symbol, direction)
        if not ok:
            return {"action": "blocked", "reason": reason}

        sl, tp, _, _ = self._risk.calculate_dynamic_sl_tp(symbol, direction, df_used)
        if sl is None or tp is None:
            sl = tick.ask - 0.001 if direction == 1 else tick.bid + 0.001
            tp = tick.ask + 0.002 if direction == 1 else tick.bid - 0.002

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if direction == 1 else tick.bid,
            "deviation": 10,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "magic": 123456,
            "comment": "AutoTrader",
            "sl": sl,
            "tp": tp,
        }

        order_result = await async_mt5.order_send(request)

        # --------------------------
        # 6️⃣ Record trade (fast synchronous I/O)
        # --------------------------
        if order_result and order_result.retcode == mt5.TRADE_RETCODE_DONE:
            trade_info = {
                "ticket": order_result.order,
                "symbol": symbol,
                "direction": direction,
                "lot": lot,
                "price": request["price"],
                "profit": 0.0,
                "time": asyncio.get_event_loop().time(),
                "strategy": "combined",
            }
            self._stats.record_trade(trade_info)
            logger.info("Trade executed: %s", trade_info)
            return {
                "action": "trade",
                "direction": direction,
                "confidence": confidence,
                "lot": lot,
                "sl": sl,
                "tp": tp,
                "buy_score": buy_score,
                "sell_score": sell_score,
                "signals": signals,
                "active": active_signals,
                "trade": trade_info,
            }

        logger.warning(
            "Order failed for %s – retcode %s",
            symbol,
            getattr(order_result, "retcode", None),
        )
        return {
            "action": "failed",
            "reason": "order_failed",
            "sl": sl,
            "tp": tp,
            "signals": signals,
            "active": active_signals,
        }

    # ---------------------------------------------------------------------
    # Convenience async helpers (optional for external callers)
    # ---------------------------------------------------------------------
    async def async_get_account(self) -> Any:
        """Thin wrapper around ``async_mt5.account_info``."""
        return await async_mt5.account_info()

    async def async_get_positions(self) -> Any:
        """Thin wrapper around ``async_mt5.positions_get``."""
        return await async_mt5.positions_get()
