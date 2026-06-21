"""
Scalping Strategy — AFX AutoTrader v2
MAGIC_NUMBER: 400004
Holding Period: seconds to minutes | Timeframes: M1, M5 | Risk: 0.1-0.25% per trade
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
class ScalpStrategy(BaseStrategy):
    """
    Ultra-low latency scalping strategy.
    Exploits micro price movements, orderflow, and Level 2 data.
    All positions are short-term, tight spread required.
    """

    MAGIC_NUMBER = int(StrategyMagic.SCALP)
    strategy_name = "SCALP"
    strategy_version = "v1.0.0"
    preferred_timeframes = ["M1", "M5"]
    default_risk_percent = 0.002  # 0.2%
    max_positions = 20

    EMA_FAST = 5
    EMA_SLOW = 15

    def analyze(self, market_data: MarketData) -> TradeSignal:
        self.pre_analyze(market_data)

        indicators = market_data.indicators
        close = market_data.close

        ema5 = indicators.get("ema_5", close)
        ema15 = indicators.get("ema_15", close)
        ema5_prev = indicators.get("ema_5_prev", close)
        ema15_prev = indicators.get("ema_15_prev", close)
        rsi = indicators.get("rsi_14", 50)
        rsi_prev = indicators.get("rsi_14_prev", 50)
        stochastic_k = indicators.get("stoch_k", 50)
        stochastic_d = indicators.get("stoch_d", 50)
        spread = market_data.spread
        volume = market_data.volume

        # EMA conditions
        ema_bullish = ema5 > ema15
        ema_bullish_cross = ema5 > ema15 and ema5_prev <= ema15_prev
        ema_bearish_cross = ema5 < ema15 and ema5_prev >= ema15_prev

        # Stochastic conditions
        stoch_oversold = stochastic_k < 20
        stoch_overbought = stochastic_k > 80
        stoch_bullish_cross = stochastic_k > stochastic_d and indicators.get("stoch_k_prev", 0) <= indicators.get("stoch_d_prev", 0)
        stoch_bearish_cross = stochastic_k < stochastic_d and indicators.get("stoch_k_prev", 0) >= indicators.get("stoch_d_prev", 0)

        # RSI conditions
        rsi_bullish_cross = rsi > 50 and rsi_prev <= 50
        rsi_bearish_cross = rsi < 50 and rsi_prev >= 50

        signal_type = SignalType.HOLD
        confidence = 0.0
        metadata = {}

        # ── BUY Conditions ───────────────────────────────────────
        buy_score = 0
        if ema_bullish:
            buy_score += 2
        if ema_bullish_cross:
            buy_score += 3
        if stoch_oversold and stoch_bullish_cross:
            buy_score += 2
        if rsi_bullish_cross:
            buy_score += 1

        if buy_score >= 4:
            signal_type = SignalType.BUY
            confidence = min(0.88, 0.4 + (buy_score * 0.1))
            metadata = {
                "reason": "scalp_buy",
                "ema_cross": ema_bullish_cross,
                "stoch_cross": stoch_bullish_cross,
                "spread": spread,
            }

        # ── SELL Conditions ───────────────────────────────────────
        sell_score = 0
        if not ema_bullish:
            sell_score += 2
        if ema_bearish_cross:
            sell_score += 3
        if stoch_overbought and stoch_bearish_cross:
            sell_score += 2
        if rsi_bearish_cross:
            sell_score += 1

        if sell_score >= 4:
            signal_type = SignalType.SELL
            confidence = min(0.88, 0.4 + (sell_score * 0.1))
            metadata = {
                "reason": "scalp_sell",
                "ema_cross": ema_bearish_cross,
                "stoch_cross": stoch_bearish_cross,
                "spread": spread,
            }

        # ── Close conditions ──────────────────────────────────────
        if signal_type == SignalType.HOLD and market_data.metadata.get("has_position"):
            pos = market_data.metadata.get("position_direction")
            pos_magic = market_data.metadata.get("position_magic")
            if pos_magic == self.MAGIC_NUMBER:
                if pos == "BUY" and rsi > 70:
                    signal_type = SignalType.CLOSE_BUY
                    confidence = 0.75
                elif pos == "SELL" and rsi < 30:
                    signal_type = SignalType.CLOSE_SELL
                    confidence = 0.75

        signal = TradeSignal(
            strategy_mode=StrategyMode.SCALP,
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
        lots = max(0.01, min(lots, 1.0))  # Tight risk, small lots
        return PositionSize(
            lots=lots,
            risk_amount=risk_amount,
            risk_percent=risk_profile.risk_percent,
            stop_loss_pips=stop_loss_pips,
            take_profit_pips=stop_loss_pips * 1.0,  # 1:1 for scalping
            risk_reward_ratio=1.0,
        )

    def get_stop_loss(
        self,
        signal: TradeSignal,
        entry_price: float,
        direction: SignalType
    ) -> float:
        # Very tight stops for scalping
        if direction == SignalType.BUY:
            return round(entry_price - 0.00030, 5)  # 3 pip SL
        else:
            return round(entry_price + 0.00030, 5)

    def get_take_profit(
        self,
        signal: TradeSignal,
        entry_price: float,
        direction: SignalType,
        stop_loss: float
    ) -> float:
        risk_pips = abs(entry_price - stop_loss)
        tp_pips = risk_pips  # 1:1 R:R
        if direction == SignalType.BUY:
            return round(entry_price + tp_pips, 5)
        else:
            return round(entry_price - tp_pips, 5)

    def validate_entry_conditions(self, market_data: MarketData) -> bool:
        spread = market_data.spread
        volume = market_data.volume

        if spread > 2.0:  # Tight spread required for scalping
            return False
        if volume < 10:  # Need liquidity
            return False
        if market_data.news_event:
            return False

        return True