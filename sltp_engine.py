"""
SL/TP ENGINE - Advanced Stop Loss & Take Profit System
Designed to defeat SL hunters and maximize risk-adjusted returns.

Features:
1. ATR-based dynamic SL/TP with adaptive multipliers
2. Market structure SL (beyond swing highs/lows)
3. Trailing Stop Loss (TSL) with lock-profit
4. Trailing Take Profit (TTP) - partial close at levels
5. Break-even logic
6. SL hunter avoidance:
   - Place SL beyond key levels
   - Avoid round numbers
   - Account for spread + slippage buffer
   - Time-based volatility adjustment
   - Liquidity zone avoidance
7. Risk-per-trade based position sizing
"""
import numpy as np
import MetaTrader5 as mt5
import time as _time
import threading
import logging

logger = logging.getLogger(__name__)


class SLTPEngine:
    """Advanced SL/TP engine with SL hunter avoidance."""

    def __init__(self):
        self._lock = threading.Lock()

    def calculate_sl_tp(self, symbol, direction, df, config=None):
        """Calculate optimal SL/TP avoiding SL hunters.

        Args:
            symbol: Trading symbol
            direction: 1=BUY, -1=SELL
            df: DataFrame with OHLCV data
            config: Dict with method-specific parameters
        Returns:
            dict with sl, tp, sl_points, tp_points, sl_type, tp_type, reasons
        """
        if df is None or len(df) < 50:
            return {"sl": 0, "tp": 0, "sl_points": 0, "tp_points": 0, "error": "insufficient_data"}

        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if not info or not tick:
            return {"sl": 0, "tp": 0, "sl_points": 0, "tp_points": 0, "error": "no_tick"}

        point = info.point
        digits = info.digits
        spread = info.spread * point
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values

        # Use current tick price as entry (not close[-1] which may be stale)
        current_price = tick.ask if direction == 1 else tick.bid

        # 1. Calculate ATR
        tr = np.maximum(high - low, np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))))
        tr[0] = high[0] - low[0]
        atr = float(np.mean(tr[-14:]))

        # 2. Find market structure (swing highs/lows)
        swing_high, swing_low = self._find_swing_points(high, low, close)

        # 3. Calculate SL hunter buffer
        sl_buffer = self._calculate_sl_hunter_buffer(atr, point, spread)

        # 4. Calculate optimal SL (using current tick price as entry)
        sl_price, sl_type, sl_reason = self._calculate_optimal_sl(
            direction, close, high, low, swing_high, swing_low, atr, point, spread, sl_buffer, config, entry_price=current_price
        )

        # 5. Calculate optimal TP (using current tick price as entry)
        tp_price, tp_type, tp_reason = self._calculate_optimal_tp(
            direction, close, high, low, atr, point, config, entry_price=current_price
        )

        # 6. Calculate points
        sl_points = abs(tick.ask - sl_price) / point if direction == 1 else abs(tick.bid - sl_price) / point
        tp_points = abs(tp_price - tick.ask) / point if direction == 1 else abs(tick.bid - tp_price) / point

        # 7. Validate risk:reward ratio
        if sl_points > 0 and tp_points > 0:
            rr = tp_points / sl_points
            if rr < 1.5:
                # Adjust TP to maintain minimum 1:1.5 RR
                tp_points = sl_points * 1.5
                if direction == 1:
                    tp_price = tick.ask + tp_points * point
                else:
                    tp_price = tick.bid - tp_points * point

        return {
            "sl": round(sl_price, digits),
            "tp": round(tp_price, digits),
            "sl_points": int(sl_points),
            "tp_points": int(tp_points),
            "sl_type": sl_type,
            "tp_type": tp_type,
            "sl_reason": sl_reason,
            "tp_reason": tp_reason,
            "atr": round(atr, 5),
            "rr_ratio": round(tp_points / max(sl_points, 1), 2),
        }

    def _find_swing_points(self, high, low, close, lookback=20):
        """Find swing highs and lows for SL placement."""
        n = len(high)
        if n < lookback:
            return float(high[-1]), float(low[-1])

        # Find swing highs (local maxima)
        swing_highs = []
        for i in range(lookback, n - 1):
            if high[i] > np.max(high[i-lookback:i]) and high[i] > high[i+1]:
                swing_highs.append(float(high[i]))

        # Find swing lows (local minima)
        swing_lows = []
        for i in range(lookback, n - 1):
            if low[i] < np.min(low[i-lookback:i]) and low[i] < low[i+1]:
                swing_lows.append(float(low[i]))

        # Return nearest relevant levels
        swing_high = float(np.max(high[-lookback:])) if not swing_highs else swing_highs[-1]
        swing_low = float(np.min(low[-lookback:])) if not swing_lows else swing_lows[-1]

        return swing_high, swing_low

    def _calculate_sl_hunter_buffer(self, atr, point, spread):
        """Calculate buffer to avoid SL hunters.

        SL hunters typically target:
        - Round numbers (1.10000, 1.20000)
        - Just beyond obvious support/resistance
        - Clustered stop losses around recent highs/lows
        """
        # Base buffer = spread + slippage
        base_buffer = spread + point * 2

        # Add ATR-based buffer for volatility
        atr_buffer = atr * 0.3

        # Total buffer (minimum 2x spread to avoid hunters)
        buffer = max(base_buffer + atr_buffer, spread * 2)

        return buffer

    def _calculate_optimal_sl(self, direction, close, high, low,
                               swing_high, swing_low, atr, point, spread,
                               sl_buffer, config, entry_price=None):
        """Calculate SL placement that avoids SL hunters.

        Strategy:
        1. Base SL = ATR * multiplier
        2. Place beyond nearest swing point
        3. Add buffer for SL hunters
        4. Avoid round numbers
        5. Ensure minimum distance from entry
        """
        atr_mult = 1.5
        if config:
            atr_mult = config.get("sl_atr_mult", 1.5)

        entry = entry_price if entry_price is not None else close[-1]
        atr_sl = atr * atr_mult

        if direction == 1:  # BUY
            # SL below entry
            sl_base = entry - atr_sl

            # Place below nearest swing low
            if swing_low < entry and swing_low > sl_base:
                sl_level = swing_low - sl_buffer
            else:
                sl_level = sl_base - sl_buffer

            # Ensure minimum distance (at least 1.5x spread)
            min_distance = spread * 1.5
            if entry - sl_level < min_distance:
                sl_level = entry - min_distance

            # Avoid round numbers (adjust SL slightly above/below)
            sl_level = self._avoid_round_numbers(sl_level, point, direction)

        else:  # SELL
            # SL above entry
            sl_base = entry + atr_sl

            # Place above nearest swing high
            if swing_high > entry and swing_high < sl_base:
                sl_level = swing_high + sl_buffer
            else:
                sl_level = sl_base + sl_buffer

            # Ensure minimum distance (at least 1.5x spread)
            min_distance = spread * 1.5
            if sl_level - entry < min_distance:
                sl_level = entry + min_distance

            # Avoid round numbers
            sl_level = self._avoid_round_numbers(sl_level, point, direction)

        sl_type = "swing" if abs(swing_low - entry) < atr or abs(swing_high - entry) < atr else "atr"
        sl_reason = f"ATR={atr:.5f} Buffer={sl_buffer:.5f}"

        return sl_level, sl_type, sl_reason

    def _calculate_optimal_tp(self, direction, close, high, low, atr, point, config, entry_price=None):
        """Calculate TP placement with multiple targets."""
        atr_mult = 2.5
        if config:
            atr_mult = config.get("tp_atr_mult", 2.5)

        entry = entry_price if entry_price is not None else close[-1]
        atr_tp = atr * atr_mult

        if direction == 1:  # BUY
            tp_level = entry + atr_tp
        else:  # SELL
            tp_level = entry - atr_tp

        tp_type = "atr"
        tp_reason = f"ATR={atr:.5f} Mult={atr_mult}"

        return tp_level, tp_type, tp_reason

    def _avoid_round_numbers(self, price, point, direction):
        """Adjust SL slightly to avoid round numbers (SL hunter targets)."""
        # Round numbers are at every 0.00100, 0.01000, etc.
        round_levels = [0.00010, 0.00050, 0.00100, 0.00500, 0.01000, 0.05000, 0.10000]

        for rnd in round_levels:
            dist = abs(price - round(price / rnd) * rnd)
            if dist < point * 3:  # Too close to round number
                if direction == 1:  # BUY - SL below, move slightly lower
                    price = price - point * 5
                else:  # SELL - SL above, move slightly higher
                    price = price + point * 5
                break

        return price

    def manage_trailing_stop(self, ticket, symbol, direction, entry_price,
                             current_sl, current_tp, atr, profit_pips,
                             trail_start_pips=30, trail_step_pips=10,
                             break_even_pips=20, break_even_offset_pips=5):
        """Manage trailing stop and break-even logic.

        Args:
            ticket: Position ticket
            symbol: Trading symbol
            direction: 1=BUY, -1=SELL
            entry_price: Entry price
            current_sl: Current stop loss
            current_tp: Current take profit
            atr: Current ATR value
            profit_pips: Current profit in pips
            trail_start_pips: Pips profit to start trailing
            trail_step_pips: Minimum step to move SL
            break_even_pips: Pips profit to move SL to break-even
            break_even_offset_pips: Pips above entry for break-even
        Returns:
            dict with action, new_sl, reason
        """
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if not info or not tick:
            return {"action": "hold", "reason": "no_data"}

        point = info.point
        digits = info.digits

        new_sl = current_sl
        action = "hold"
        reason = ""

        # Current price
        current_price = tick.bid if direction == 1 else tick.ask

        # 1. Break-even logic
        if break_even_pips > 0:
            be_price = entry_price + break_even_offset_pips * point * direction
            if profit_pips >= break_even_pips and current_sl < be_price and direction == 1:
                new_sl = round(be_price, digits)
                action = "modify"
                reason = "break_even"
            elif profit_pips >= break_even_pips and current_sl > be_price and direction == -1:
                new_sl = round(be_price, digits)
                action = "modify"
                reason = "break_even"

        # 2. Trailing stop logic
        if trail_start_pips > 0 and profit_pips >= trail_start_pips:
            # Calculate new trailing SL
            if direction == 1:  # BUY
                trail_sl = current_price - trail_step_pips * point
                if trail_sl > current_sl and trail_sl > entry_price:
                    new_sl = round(trail_sl, digits)
                    action = "modify"
                    reason = "trailing"
            else:  # SELL
                trail_sl = current_price + trail_step_pips * point
                if trail_sl < current_sl and trail_sl < entry_price:
                    new_sl = round(trail_sl, digits)
                    action = "modify"
                    reason = "trailing"

        return {
            "action": action,
            "new_sl": new_sl,
            "reason": reason,
            "profit_pips": profit_pips,
            "current_price": current_price,
        }

    def manage_partial_close(self, ticket, symbol, direction, entry_price, current_sl, current_tp,
                             profit_pips, close_pct=50, min_rr_for_partial=1.0):
        """Manage partial close at 1:1 R:R and breakeven protection.

        When price reaches min_rr_for_partial ratio (default 1:1), close close_pct%
        of the position and move SL to breakeven.

        Args:
            ticket: Position ticket
            symbol: Trading symbol
            direction: 1=BUY, -1=SELL
            entry_price: Entry price
            current_sl: Current stop loss
            current_tp: Current take profit
            profit_pips: Current profit in pips
            close_pct: Percentage of position to close at 1:1 R:R
            min_rr_for_partial: Minimum R:R ratio to trigger partial close
        Returns:
            dict with action, close_volume, new_sl, reason
        """
        info = mt5.symbol_info(symbol)
        if not info:
            return {"action": "hold", "reason": "no_info"}

        point = info.point
        digits = info.digits
        abs_sl_pips = abs(entry_price - current_sl) / point if current_sl > 0 else 0

        if abs_sl_pips <= 0:
            return {"action": "hold", "reason": "no_sl_set"}

        rr_ratio = profit_pips / abs_sl_pips

        if rr_ratio < min_rr_for_partial:
            return {"action": "hold", "reason": f"rr_{rr_ratio:.2f}_below_{min_rr_for_partial}"}

        # Get current position volume
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"action": "hold", "reason": "position_not_found"}
        pos = positions[0]
        close_volume = round(pos.volume * close_pct / 100, 2)
        info_vol = mt5.symbol_info(symbol)
        if info_vol:
            close_volume = max(info_vol.volume_min, min(close_volume, pos.volume))
            close_volume = round(close_volume / info_vol.volume_step) * info_vol.volume_step

        if close_volume < info.volume_min:
            return {"action": "hold", "reason": "volume_too_small"}

        # Move SL to breakeven (entry + small offset)
        be_offset = 5 * point
        if direction == 1:
            new_sl = round(entry_price + be_offset, digits)
        else:
            new_sl = round(entry_price - be_offset, digits)

        return {
            "action": "partial_close",
            "close_volume": round(close_volume, 2),
            "new_sl": new_sl,
            "reason": f"partial_close_at_rr_{rr_ratio:.2f}",
            "rr_ratio": rr_ratio,
        }

    def calculate_partial_close_levels(self, entry_price, tp_price, direction, levels=3):
        """Calculate partial close levels for TTP (Trailing Take Profit).

        Args:
            entry_price: Entry price
            tp_price: Take profit price
            direction: 1=BUY, -1=SELL
            levels: Number of partial close levels
        Returns:
            List of {level, price, percent, action}
        """
        if levels <= 0:
            return []

        total_distance = abs(tp_price - entry_price)
        level_step = total_distance / levels

        close_levels = []
        for i in range(1, levels + 1):
            if direction == 1:  # BUY
                level_price = entry_price + level_step * i
            else:  # SELL
                level_price = entry_price - level_step * i

            # Position size to close at each level
            if i == levels:
                close_percent = 100  # Close all at final level
            elif i == 1:
                close_percent = 30  # Close 30% at first level
            else:
                close_percent = 35  # Close 35% at middle levels

            close_levels.append({
                "level": i,
                "price": round(level_price, 5),
                "percent": close_percent,
                "action": "partial_close" if i < levels else "full_close",
            })

        return close_levels

    def get_status(self):
        """Return engine status for dashboard."""
        return {
            "engine": "SLTP_v2",
            "features": [
                "ATR-based SL/TP",
                "Swing point detection",
                "SL hunter avoidance",
                "Round number avoidance",
                "Trailing stop",
                "Break-even",
                "Partial close levels",
            ]
        }


_sltp_engine = None
_sltp_lock = threading.Lock()


def get_sltp_engine():
    global _sltp_engine
    if _sltp_engine is None:
        with _sltp_lock:
            if _sltp_engine is None:
                _sltp_engine = SLTPEngine()
    return _sltp_engine
