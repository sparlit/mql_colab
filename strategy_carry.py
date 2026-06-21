"""
Carry Trading Strategy — AFX AutoTrader v2
MAGIC_NUMBER: 300003
Holding Period: 1-4 weeks | Timeframes: D1, W1 | Risk: 2-3% per trade
"""

from __future__ import annotations

from strategy_base import (
    BaseStrategy,
    register_strategy,
    StrategyMode,
    SignalType,
    TradeSignal,
    PositionSize,
    MarketData,
    RiskProfile,
    StrategyMagic,
)


@register_strategy
class CarryStrategy(BaseStrategy):
    """
    Carry trade strategy — profits from interest rate differentials.
    Holds positions for 1-4 weeks, targets EM currencies with high yield.
    Focuses on safe-haven avoidance and roll yield optimization.
    """

    MAGIC_NUMBER = int(StrategyMagic.CARRY)
    strategy_name = "CARRY"
    strategy_version = "v1.0.0"
    preferred_timeframes = ["D1", "W1"]
    default_risk_percent = 0.025  # 2.5%
    max_positions = 3

    def analyze(self, market_data: MarketData) -> TradeSignal:
        self.pre_analyze(market_data)

        indicators = market_data.indicators
        close = market_data.close

        # Carry-specific indicators
        interest_rate_diff = indicators.get("interest_rate_diff", 0)  # Our rate - their rate
        roll_yield = indicators.get("roll_yield", 0.0)  # Expected daily roll
        carry_strength = indicators.get("carry_strength", 0.0)  # Composite carry score
        vix = indicators.get("vix", 15.0)  # Fear gauge

        ema200 = indicators.get("ema_200", close)
        trend = indicators.get("trend", 0)  # 1=up, -1=down, 0=neutral

        # Direction
        uptrend = close > ema200

        signal_type = SignalType.HOLD
        confidence = 0.0
        metadata = {}

        # ── BUY Conditions (long high-yield currency) ───────────────
        # Positive carry: our rate higher than quote currency
        carry_score = 0
        if interest_rate_diff > 0.03:  # >300 pips rate differential
            carry_score += 3
        elif interest_rate_diff > 0.01:
            carry_score += 2
        if roll_yield > 0.0005:  # Positive daily roll
            carry_score += 2
        if uptrend:
            carry_score += 2
        if vix < 20:
            carry_score += 1
        if carry_strength > 0.6:
            carry_score += 2

        if carry_score >= 5:
            signal_type = SignalType.BUY
            confidence = min(0.92, 0.5 + (carry_score * 0.07))
            metadata = {
                "reason": "carry_buy",
                "interest_rate_diff": interest_rate_diff,
                "roll_yield": roll_yield,
                "vix": vix,
                "carry_score": carry_score,
            }

        # ── SELL Conditions (short low-yield / safe-haven) ─────────
        neg_carry_score = 0
        if interest_rate_diff < -0.03:
            neg_carry_score += 3
        elif interest_rate_diff < -0.01:
            neg_carry_score += 2
        if roll_yield < -0.0005:
            neg_carry_score += 2
        if not uptrend:
            neg_carry_score += 2
        if vix > 25:
            neg_carry_score += 2
        if carry_strength < 0.4:
            neg_carry_score += 2

        if neg_carry_score >= 5:
            signal_type = SignalType.SELL
            confidence = min(0.92, 0.5 + (neg_carry_score * 0.07))
            metadata = {
                "reason": "carry_sell",
                "interest_rate_diff": interest_rate_diff,
                "roll_yield": roll_yield,
                "vix": vix,
                "carry_score": neg_carry_score,
            }

        # ── Exit on risk-off events ──────────────────────────────────
        if signal_type == SignalType.HOLD and market_data.metadata.get("has_position"):
            pos = market_data.metadata.get("position_direction")
            pos_magic = market_data.metadata.get("position_magic")
            if pos_magic == self.MAGIC_NUMBER:
                # Exit if VIX spikes (risk-off event)
                if vix > 30:
                    if pos == "BUY":
                        signal_type = SignalType.CLOSE_BUY
                        confidence = 0.85
                    else:
                        signal_type = SignalType.CLOSE_SELL
                        confidence = 0.85

        signal = TradeSignal(
            strategy_mode=StrategyMode.CARRY,
            magic_number=self.MAGIC_NUMBER,
            symbol=market_data.symbol,
            signal_type=signal_type,
            confidence=confidence,
            entry_price=close,
            timeframe=market_data.timeframe,
            metadata=metadata,
        )

        return self.post_analyze(signal)

    def calculate_position_size(
        self,
        signal: TradeSignal,
        risk_profile: RiskProfile,
        stop_loss_pips: float
    ) -> PositionSize:
        if stop_loss_pips <= 0:
            raise ValueError(f"stop_loss_pips must be positive, got {stop_loss_pips}")
        risk_amount = risk_profile.risk_amount
        pip_value = 10.0
        lots = round(risk_amount / (stop_loss_pips * pip_value), 2)
        lots = max(0.01, min(lots, 20.0))  # Larger for carry
        return PositionSize(
            lots=lots,
            risk_amount=risk_amount,
            risk_percent=risk_profile.risk_percent,
            stop_loss_pips=stop_loss_pips,
            take_profit_pips=stop_loss_pips * 3.0,  # Wider TP for carry
            risk_reward_ratio=3.0,
        )

    def get_stop_loss(
        self,
        signal: TradeSignal,
        entry_price: float,
        direction: SignalType
    ) -> float:
        atr = signal.metadata.get("atr", entry_price * 0.008)
        if direction == SignalType.BUY:
            return round(entry_price - (atr * 2.0), 5)
        else:
            return round(entry_price + (atr * 2.0), 5)

    def get_take_profit(
        self,
        signal: TradeSignal,
        entry_price: float,
        direction: SignalType,
        stop_loss: float
    ) -> float:
        risk_pips = abs(entry_price - stop_loss)
        tp_pips = risk_pips * 3.0
        if direction == SignalType.BUY:
            return round(entry_price + tp_pips, 5)
        else:
            return round(entry_price - tp_pips, 5)

    def validate_entry_conditions(self, market_data: MarketData) -> bool:
        indicators = market_data.indicators
        interest_rate_diff = indicators.get("interest_rate_diff", 0)
        vix = indicators.get("vix", 15.0)
        carry_strength = indicators.get("carry_strength", 0.0)

        if abs(interest_rate_diff) < 0.005:
            return False  # Need meaningful rate differential
        if vix > 25:
            return False  # Risk-off environment
        if carry_strength < 0.3:
            return False  # Carry not favorable
        if market_data.spread > 5.0:
            return False  # Wide spread erodes carry

        return True