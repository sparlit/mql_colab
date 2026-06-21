"""
Swing Trading Strategy — AFX AutoTrader v2
MAGIC_NUMBER: 100001
Holding Period: 1-7 days | Timeframes: H4, D1 | Risk: 1-2% per trade
"""

from __future__ import annotations

import time
from typing import Optional

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
class SwingStrategy(BaseStrategy):
    """
    Swing trading strategy for medium-term moves.
    Identifies swing highs/lows, trend continuations, and reversal patterns.
    Holds positions for 1-7 days.
    """

    MAGIC_NUMBER = int(StrategyMagic.SWING)
    strategy_name = "SWING"
    strategy_version = "v1.0.0"
    preferred_timeframes = ["H4", "D1"]
    default_risk_percent = 0.015  # 1.5%
    max_positions = 5

    # Indicator lookback periods
    EMA_FAST = 50
    EMA_SLOW = 200
    RSI_PERIOD = 14
    BB_PERIOD = 20
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9

    def analyze(self, market_data: MarketData) -> TradeSignal:
        """Generate swing trade signal from market data."""
        self.pre_analyze(market_data)

        indicators = market_data.indicators
        close = market_data.close
        high = market_data.high
        low = market_data.low

        ema50 = indicators.get("ema_50", close)
        ema200 = indicators.get("ema_200", close)
        rsi = indicators.get("rsi_14", 50)
        macd = indicators.get("macd", 0)
        macd_signal = indicators.get("macd_signal", 0)
        bb_upper = indicators.get("bb_upper", close * 1.02)
        bb_lower = indicators.get("bb_lower", close * 0.98)
        bb_width = indicators.get("bb_width", 0.02)

        signal_type = SignalType.HOLD
        confidence = 0.0
        metadata = {}

        # Trend detection
        uptrend = ema50 > ema200
        trend_strength = abs(ema50 - ema200) / close

        # RSI conditions
        rsi_oversold = rsi < 35
        rsi_overbought = rsi > 65
        rsi_neutral = 40 <= rsi <= 60

        # MACD conditions
        macd_bullish = macd > macd_signal
        macd_cross_up = macd > macd_signal and indicators.get("macd_prev", 0) <= indicators.get("macd_signal_prev", 0)

        # Bollinger Band conditions
        bb_expansion = bb_width > 0.03

        # ── BUY Conditions ───────────────────────────────────────
        buy_score = 0
        if uptrend:
            buy_score += 2
        if rsi_oversold:
            buy_score += 2
        if macd_bullish:
            buy_score += 1
        if bb_expansion:
            buy_score += 1

        if buy_score >= 4:
            signal_type = SignalType.BUY
            confidence = min(0.95, 0.5 + (buy_score * 0.1))
            metadata = {
                "reason": "swing_buy",
                "uptrend": uptrend,
                "rsi": rsi,
                "trend_strength": trend_strength,
                "bb_width": bb_width,
            }

        # ── SELL Conditions ───────────────────────────────────────
        sell_score = 0
        if not uptrend:
            sell_score += 2
        if rsi_overbought:
            sell_score += 2
        if not macd_bullish:
            sell_score += 1
        if bb_expansion:
            sell_score += 1

        if sell_score >= 4:
            signal_type = SignalType.SELL
            confidence = min(0.95, 0.5 + (sell_score * 0.1))
            metadata = {
                "reason": "swing_sell",
                "uptrend": uptrend,
                "rsi": rsi,
                "trend_strength": trend_strength,
                "bb_width": bb_width,
            }

        # ── Close conditions ──────────────────────────────────────
        if signal_type == SignalType.HOLD and market_data.metadata.get("has_position"):
            pos = market_data.metadata.get("position_direction")
            pos_magic = market_data.metadata.get("position_magic")
            if pos_magic == self.MAGIC_NUMBER:
                if pos == "BUY" and (rsi_overbought or not uptrend):
                    signal_type = SignalType.CLOSE_BUY
                    confidence = 0.7
                elif pos == "SELL" and (rsi_oversold or uptrend):
                    signal_type = SignalType.CLOSE_SELL
                    confidence = 0.7

        signal = TradeSignal(
            strategy_mode=StrategyMode.SWING,
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
        pip_value = 10.0  # $10 per pip for 1 standard lot on most pairs
        lots = round(risk_amount / (stop_loss_pips * pip_value), 2)
        lots = max(0.01, min(lots, 10.0))  # Clamp to reasonable range
        return PositionSize(
            lots=lots,
            risk_amount=risk_amount,
            risk_percent=risk_profile.risk_percent,
            stop_loss_pips=stop_loss_pips,
            take_profit_pips=stop_loss_pips * 2,  # Target 1:2 R:R
            risk_reward_ratio=2.0,
        )

    def get_stop_loss(
        self,
        signal: TradeSignal,
        entry_price: float,
        direction: SignalType
    ) -> float:
        if direction == SignalType.BUY:
            # Stop below recent swing low or 1.5x ATR
            atr = signal.metadata.get("atr", entry_price * 0.005)
            sl = entry_price - (atr * 1.5)
        else:
            atr = signal.metadata.get("atr", entry_price * 0.005)
            sl = entry_price + (atr * 1.5)
        return round(sl, 5)

    def get_take_profit(
        self,
        signal: TradeSignal,
        entry_price: float,
        direction: SignalType,
        stop_loss: float
    ) -> float:
        risk_pips = abs(entry_price - stop_loss)
        tp_pips = risk_pips * 2.0
        if direction == SignalType.BUY:
            return round(entry_price + tp_pips, 5)
        else:
            return round(entry_price - tp_pips, 5)

    def validate_entry_conditions(self, market_data: MarketData) -> bool:
        indicators = market_data.indicators
        rsi = indicators.get("rsi_14", 50)
        bb_width = indicators.get("bb_width", 0)
        volume = market_data.volume

        if volume <= 0:
            return False
        if bb_width < 0.01:
            return False  # Needs volatility
        if rsi == 0:
            return False  # Indicators not computed

        # No news events during entry
        if market_data.news_event:
            return False

        # Session filter (no trading during quiet Asian for swing)
        if market_data.session == "asian" and market_data.spread > 3.0:
            return False

        return True