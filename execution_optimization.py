import MetaTrader5 as mt5
import numpy as np
import time as _time
import threading
import logging
from datetime import datetime
from collections import deque
from config import MAGIC_NUMBER

logger = logging.getLogger(__name__)

# ==========================================
# EXECUTION OPTIMIZATION
# ==========================================


class TWAPExecutor:
    def __init__(self):
        self._lock = threading.Lock()

    def execute_twap(self, symbol, direction, total_volume, duration_seconds=60, slices=5):
        info = mt5.symbol_info(symbol)
        if not info:
            return []
        slice_vol = round(total_volume / slices, 2)
        slice_vol = max(info.volume_min, slice_vol)
        interval = duration_seconds / slices
        results = []
        for i in range(slices):
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                continue
            price = tick.ask if direction == 1 else tick.bid
            order_type = mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL
            request = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
                "volume": slice_vol, "type": order_type, "price": price,
                "magic": MAGIC_NUMBER, "comment": f"TWAP_{i+1}/{slices}",
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            results.append({"slice": i + 1, "success": result.retcode == mt5.TRADE_RETCODE_DONE, "price": price})
            if i < slices - 1:
                _time.sleep(interval)
        return results


class IcebergDetector:
    def __init__(self):
        self.order_history = deque(maxlen=1000)
        self._lock = threading.Lock()

    def detect(self, symbol, lookback=50):
        with self._lock:
            recent = [o for o in self.order_history if o["symbol"] == symbol][-lookback:]
        if len(recent) < 10:
            return []
        volumes = [o["volume"] for o in recent]
        avg_vol = np.mean(volumes)
        std_vol = np.std(volumes)
        icebergs = []
        for order in recent:
            if order["volume"] > avg_vol + 2 * std_vol:
                icebergs.append({
                    "time": order["time"],
                    "side": order["side"],
                    "volume": order["volume"],
                    "avg_multiple": round(order["volume"] / avg_vol, 1),
                })
        return icebergs

    def record_order(self, symbol, side, volume, price):
        with self._lock:
            self.order_history.append({
                "time": datetime.now().isoformat(),
                "symbol": symbol, "side": side,
                "volume": volume, "price": price,
            })


class LatencyOptimizer:
    def __init__(self):
        self.order_templates = {}
        self._lock = threading.Lock()

    def precompute_template(self, symbol, direction):
        info = mt5.symbol_info(symbol)
        if not info:
            return None
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return None
        template = {
            "symbol": symbol,
            "type": mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL,
            "magic": MAGIC_NUMBER,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "point": info.point,
            "digits": info.digits,
            "volume_min": info.volume_min,
            "volume_step": info.volume_step,
        }
        with self._lock:
            self.order_templates[f"{symbol}_{direction}"] = template
        return template

    def execute_fast(self, symbol, direction, volume, sl_points, tp_points):
        template_key = f"{symbol}_{direction}"
        with self._lock:
            template = self.order_templates.get(template_key)
        if not template:
            template = self.precompute_template(symbol, direction)
        if not template:
            return None
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return None
        point = template["point"]
        price = tick.ask if direction == 1 else tick.bid
        sl = price - sl_points * point if direction == 1 else price + sl_points * point
        tp = price + tp_points * point if direction == 1 else price - tp_points * point
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
            "volume": volume, "type": template["type"],
            "price": price, "sl": round(sl, template["digits"]),
            "tp": round(tp, template["digits"]),
            "magic": MAGIC_NUMBER, "comment": "FastExec",
            "type_time": template["type_time"], "type_filling": template["type_filling"],
        }
        return mt5.order_send(request)


class FillRateAnalytics:
    def __init__(self):
        self.fills = deque(maxlen=1000)
        self._lock = threading.Lock()

    def record_fill(self, symbol, expected_price, actual_price, volume, latency_ms):
        slippage = abs(actual_price - expected_price)
        with self._lock:
            self.fills.append({
                "time": datetime.now().isoformat(),
                "symbol": symbol, "expected": expected_price,
                "actual": actual_price, "slippage": slippage,
                "volume": volume, "latency_ms": latency_ms,
            })

    def get_stats(self):
        with self._lock:
            fills = list(self.fills)
        if not fills:
            return {"count": 0, "avg_slippage": 0, "avg_latency": 0, "fill_rate": 0}
        slippages = [f["slippage"] for f in fills]
        latencies = [f["latency_ms"] for f in fills]
        return {
            "count": len(fills),
            "avg_slippage": round(np.mean(slippages), 6),
            "avg_latency": round(np.mean(latencies), 2),
            "max_slippage": round(max(slippages), 6),
            "p95_latency": round(np.percentile(latencies, 95), 2),
        }


class PartialCloseEngine:
    def __init__(self):
        self._lock = threading.Lock()

    def check_partial_close(self, position, tp_levels=None):
        if tp_levels is None:
            tp_levels = [0.3, 0.5, 0.7]
        info = mt5.symbol_info(position.symbol)
        if not info:
            return []
        point = info.point
        if position.type == 0:
            profit_pips = (position.price_current - position.price_open) / point
        else:
            profit_pips = (position.price_open - position.price_current) / point
        total_pips = abs(position.tp - position.price_open) / point if position.tp > 0 else 200
        progress = profit_pips / total_pips if total_pips > 0 else 0
        closes = []
        for level in tp_levels:
            if progress >= level:
                close_vol = round(position.volume * 0.33, 2)
                close_vol = max(info.volume_min, min(close_vol, position.volume))
                closes.append({"level": level, "volume": close_vol})
        return closes


class AdvancedExecutor:
    def __init__(self):
        self.twap = TWAPExecutor()
        self.iceberg = IcebergDetector()
        self.latency = LatencyOptimizer()
        self.fill_analytics = FillRateAnalytics()
        self.partial_close = PartialCloseEngine()

    def execute(self, symbol, direction, volume, sl_points, tp_points):
        start = _time.time()
        result = self.latency.execute_fast(symbol, direction, volume, sl_points, tp_points)
        latency_ms = (_time.time() - start) * 1000
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            tick = mt5.symbol_info_tick(symbol)
            expected = tick.ask if direction == 1 else tick.bid
            self.fill_analytics.record_fill(symbol, expected, result.price, volume, latency_ms)
            self.iceberg.record_order(symbol, "buy" if direction == 1 else "sell", volume, result.price)
        return result


_executor = None
_lock = threading.Lock()


def get_advanced_executor():
    global _executor
    if _executor is None:
        with _lock:
            if _executor is None:
                _executor = AdvancedExecutor()
    return _executor
