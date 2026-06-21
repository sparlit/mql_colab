"""
Day Trading Strategy — AFX AutoTrader v2
MAGIC_NUMBER: 200002
Holding Period: Intraday (0-24h) | Timeframes: M5, M15, H1 | Risk: 0.5-1% per trade
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
class DayStrategy(BaseStrategy):
    """
    Intraday trading strategy.
    Trades VWAP breakouts, EMA crosses, and RSI extremes on lower timeframes.
    All positions closed by end of trading day.
    """

    MAGIC_NUMBER = int(StrategyMagic.DAY)
    strategy_name = "DAY"
    strategy_version = "v1.0.0"
    preferred_timeframes = ["M5", "M15", "H1"]
    default_risk_percent = 0.008  # 0.8%
    max_positions = 10

    EMA_FAST = 9
    EMA_SLOW = 21
    RSI_PERIOD = 14

    def analyze(self, market_data: MarketData) -> TradeSignal:
        self.pre_analyze(market_data)

        indicators = market_data.indicators
        close = market_data.close
        high = market_data.high
        low = market_data.low

        ema9 = indicators.get("ema_9", close)
        ema21 = indicators.get("ema_21", close)
        ema9_prev = indicators.get("ema_9_prev", close)
        ema21_prev = indicators.get("ema_21_prev", close)
        rsi = indicators.get("rsi_14", 50)
        vwap = indicators.get("vwap", close)
        volume = market_data.volume
        avg_volume = indicators.get("avg_volume", volume or 1)

        # EMA cross detection
        ema_bullish_cross = ema9 > ema21 and ema9_prev <= ema21_prev
        ema_bearish_cross = ema9 < ema21 and ema9_prev >= ema21_prev
        ema_trending_up = ema9 > ema21
        ema_trending_down = ema9 < ema21

        # VWAP conditions
        above_vwap = close > vwap
        below_vwap = close < vwap

        # Volume condition
        volume_surge = volume > (avg_volume * 1.5)

        # RSI conditions
        rsi_oversold = rsi < 35
        rsi_overbought = rsi > 65
        rsi_extreme = rsi < 30 or rsi > 70

        signal_type = SignalType.HOLD
        confidence = 0.0
        metadata = {}

        # ── BUY Conditions ───────────────────────────────────────
        buy_score = 0
        if ema_trending_up:
            buy_score += 2
        if ema_bullish_cross:
            buy_score += 3
        if above_vwap:
            buy_score += 1
        if volume_surge:
            buy_score += 2
        if rsi_oversold:
            buy_score += 1

        if buy_score >= 3:
            signal_type = SignalType.BUY
            confidence = min(0.90, 0.4 + (buy_score * 0.08))
            metadata = {
                "reason": "day_buy",
                "ema_cross": ema_bullish_cross,
                "above_vwap": above_vwap,
                "volume_surge": volume_surge,
                "rsi": rsi,
            }

        # ── SELL Conditions ───────────────────────────────────────
        sell_score = 0
        if ema_trending_down:
            sell_score += 2
        if ema_bearish_cross:
            sell_score += 3
        if below_vwap:
            sell_score += 1
        if volume_surge:
            sell_score += 2
        if rsi_overbought:
            sell_score += 1

        if sell_score >= 3:
            signal_type = SignalType.SELL
            confidence = min(0.90, 0.4 + (sell_score * 0.08))
            metadata = {
                "reason": "day_sell",
                "ema_cross": ema_bearish_cross,
                "below_vwap": below_vwap,
                "volume_surge": volume_surge,
                "rsi": rsi,
            }

        # ── Close conditions (end of day / opposite signal) ────────
        if signal_type == SignalType.HOLD and market_data.metadata.get("has_position"):
            pos = market_data.metadata.get("position_direction")
            pos_magic = market_data.metadata.get("position_magic")
            if pos_magic == self.MAGIC_NUMBER:
                # Time-based close for intraday
                hour = market_data.metadata.get("hour", 0)
                is_close_of_day = hour >= 16  # 4PM close

                if is_close_of_day:
                    if pos == "BUY":
                        signal_type = SignalType.CLOSE_BUY
                        confidence = 0.8
                    else:
                        signal_type = SignalType.CLOSE_SELL
                        confidence = 0.8

        signal = TradeSignal(
            strategy_mode=StrategyMode.DAY,
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
        lots = max(0.01, min(lots, 5.0))
        return PositionSize(
            lots=lots,
            risk_amount=risk_amount,
            risk_percent=risk_profile.risk_percent,
            stop_loss_pips=stop_loss_pips,
            take_profit_pips=stop_loss_pips * 1.5,
            risk_reward_ratio=1.5,
        )

    def get_stop_loss(
        self,
        signal: TradeSignal,
        entry_price: float,
        direction: SignalType
    ) -> float:
        atr = signal.metadata.get("atr", entry_price * 0.003)
        if direction == SignalType.BUY:
            return round(entry_price - (atr * 1.2), 5)
        else:
            return round(entry_price + (atr * 1.2), 5)

    def get_take_profit(
        self,
        signal: TradeSignal,
        entry_price: float,
        direction: SignalType,
        stop_loss: float
    ) -> float:
        risk_pips = abs(entry_price - stop_loss)
        tp_pips = risk_pips * 1.5
        if direction == SignalType.BUY:
            return round(entry_price + tp_pips, 5)
        else:
            return round(entry_price - tp_pips, 5)

    def validate_entry_conditions(self, market_data: MarketData) -> bool:
        indicators = market_data.indicators
        rsi = indicators.get("rsi_14", 50)
        volume = market_data.volume
        spread = market_data.spread

        if volume <= 0 or spread > 5.0:
            return False
        if market_data.news_event:
            return False
        # Intraday: no trading during low volume periods
        if market_data.session == "asian":
            return False

        return True