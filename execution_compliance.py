import MetaTrader5 as mt5
import numpy as np
import json
import os
import time as _time
import threading
import logging
from datetime import datetime
from collections import deque
from config import (
    DATA_DIR, is_system_magic,
)
from magic_database import get_magic_number

logger = logging.getLogger(__name__)

# ==========================================
# EXECUTION & COMPLIANCE
# ==========================================


class SmartOrderRouter:
    def __init__(self):
        self.venue_quality = {}
        self._lock = threading.Lock()

    def route(self, symbol, direction, volume):
        best_venue = "mt5"
        return {"venue": best_venue, "symbol": symbol, "side": "buy" if direction == 1 else "sell", "volume": volume}

    def update_quality(self, venue, fill_rate, avg_latency):
        with self._lock:
            self.venue_quality[venue] = {"fill_rate": fill_rate, "avg_latency": avg_latency}


class DarkPoolDetector:
    def __init__(self):
        self.block_trades = deque(maxlen=1000)
        self._lock = threading.Lock()

    def detect(self, symbol, lookback=50):
        with self._lock:
            recent = [t for t in self.block_trades if t["symbol"] == symbol][-lookback:]
        if len(recent) < 10:
            return {"dark_pool_activity": "unknown", "block_count": len(recent)}
        avg_vol = np.mean([t["volume"] for t in recent])
        large_blocks = [t for t in recent if t["volume"] > avg_vol * 3]
        dark_ratio = len(large_blocks) / max(len(recent), 1)
        return {
            "dark_pool_activity": "high" if dark_ratio > 0.3 else "low",
            "block_count": len(large_blocks),
            "dark_ratio": round(dark_ratio, 3),
        }

    def record_block(self, symbol, side, volume, price):
        with self._lock:
            self.block_trades.append({
                "time": datetime.now().isoformat(),
                "symbol": symbol, "side": side,
                "volume": volume, "price": price,
            })


class PFOFAnalyzer:
    def __init__(self):
        self.flow_data = deque(maxlen=1000)
        self._lock = threading.Lock()

    def analyze_flow(self, symbol, lookback=100):
        with self._lock:
            recent = [f for f in self.flow_data if f["symbol"] == symbol][-lookback:]
        if len(recent) < 10:
            return {"retail_flow": 0, "institutional_flow": 0, "ratio": 1.0}
        retail = sum(1 for f in recent if f["type"] == "retail")
        institutional = sum(1 for f in recent if f["type"] == "institutional")
        total = retail + institutional
        return {
            "retail_flow": round(retail / max(total, 1), 3),
            "institutional_flow": round(institutional / max(total, 1), 3),
            "ratio": round(institutional / max(retail, 1), 2),
        }


class CrossAssetExecutor:
    def __init__(self):
        self._lock = threading.Lock()

    def execute_basket(self, orders):
        results = []
        for order in orders:
            symbol = order["symbol"]
            direction = order["direction"]
            volume = order["volume"]
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                results.append({"symbol": symbol, "success": False, "error": "no tick"})
                continue
            price = tick.ask if direction == 1 else tick.bid
            order_type = mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL
            request = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
                "volume": volume, "type": order_type, "price": price,
                "magic": get_magic_number("v1", "technical", symbol), "comment": "BasketExec",
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            results.append({"symbol": symbol, "success": result.retcode == mt5.TRADE_RETCODE_DONE, "price": price})
        return results


class ContingentOrderManager:
    def __init__(self):
        self.orders = []
        self._lock = threading.Lock()

    def create_contingent(self, primary_symbol, primary_action, primary_volume, contingent_symbol, contingent_action, contingent_volume):
        order = {
            "id": len(self.orders) + 1,
            "primary": {"symbol": primary_symbol, "action": primary_action, "volume": primary_volume, "status": "pending"},
            "contingent": {"symbol": contingent_symbol, "action": contingent_action, "volume": contingent_volume, "status": "waiting"},
            "created": datetime.now().isoformat(),
        }
        with self._lock:
            self.orders.append(order)
        return order

    def check_and_execute(self):
        executed = []
        with self._lock:
            for order in self.orders:
                if order["primary"]["status"] == "pending":
                    sym = order["primary"]["symbol"]
                    tick = mt5.symbol_info_tick(sym)
                    if tick:
                        direction = 1 if order["primary"]["action"] == "buy" else -1
                        price = tick.ask if direction == 1 else tick.bid
                        order_type = mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL
                        request = {
                            "action": mt5.TRADE_ACTION_DEAL, "symbol": sym,
                            "volume": order["primary"]["volume"], "type": order_type,
                            "price": price, "magic": get_magic_number("v1", "technical", sym), "comment": "ContingentPrimary",
                            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
                        }
                        result = mt5.order_send(request)
                        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                            order["primary"]["status"] = "filled"
                            order["contingent"]["status"] = "ready"
                        else:
                            logger.warning("Primary order failed for %s: %s", sym, result)
                    else:
                        logger.debug("No tick for primary symbol %s", sym)
                if order["contingent"]["status"] == "ready":
                    sym = order["contingent"]["symbol"]
                    tick = mt5.symbol_info_tick(sym)
                    if tick:
                        direction = 1 if order["contingent"]["action"] == "buy" else -1
                        price = tick.ask if direction == 1 else tick.bid
                        order_type = mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL
                        request = {
                            "action": mt5.TRADE_ACTION_DEAL, "symbol": sym,
                            "volume": order["contingent"]["volume"], "type": order_type,
                            "price": price, "magic": get_magic_number("v1", "technical", sym), "comment": "Contingent",
                            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
                        }
                        result = mt5.order_send(request)
                        order["contingent"]["status"] = "filled" if result.retcode == mt5.TRADE_RETCODE_DONE else "failed"
                        executed.append(order["id"])
        return executed


class TradeReporter:
    def __init__(self):
        self._lock = threading.Lock()
        os.makedirs(DATA_DIR, exist_ok=True)

    def generate_mifid_report(self, trades):
        report = {
            "report_type": "MiFID_II",
            "generated": datetime.now().isoformat(),
            "total_trades": len(trades),
            "trades": [],
        }
        for trade in trades:
            report["trades"].append({
                "time": trade.get("time", ""),
                "symbol": trade.get("symbol", ""),
                "side": trade.get("side", ""),
                "volume": trade.get("volume", 0),
                "price": trade.get("price", 0),
                "venue": "MT5",
                "algorithm": "SCALPER_PRO",
                "commission": trade.get("commission", 0),
            })
        path = os.path.join(DATA_DIR, f"mifid_report_{datetime.now().strftime('%Y%m%d')}.json")
        with open(path, "w") as f:
            json.dump(report, f, indent=2)
        return report

    def generate_audit_trail(self, trades):
        trail = []
        for trade in trades:
            trail.append({
                "event": trade.get("event", "trade"),
                "time": trade.get("time", ""),
                "details": trade,
            })
        path = os.path.join(DATA_DIR, f"audit_trail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(path, "w") as f:
            json.dump(trail, f, indent=2, default=str)
        return trail


class PositionLimitMonitor:
    def __init__(self):
        self.limits = {}
        self._lock = threading.Lock()

    def set_limit(self, symbol, max_volume, max_positions):
        with self._lock:
            self.limits[symbol] = {"max_volume": max_volume, "max_positions": max_positions}

    def check_limits(self, symbol):
        positions = mt5.positions_get()
        my_pos = [p for p in (positions or []) if is_system_magic(p.magic) and p.symbol == symbol]
        total_volume = sum(p.volume for p in my_pos)
        limit = self.limits.get(symbol, {"max_volume": 100, "max_positions": 10})
        return {
            "volume_ok": total_volume < limit["max_volume"],
            "positions_ok": len(my_pos) < limit["max_positions"],
            "current_volume": total_volume,
            "current_positions": len(my_pos),
            "limits": limit,
        }


class WashTradeDetector:
    def __init__(self):
        self.recent_trades = deque(maxlen=500)
        self._lock = threading.Lock()

    def record(self, symbol, direction, volume, price):
        with self._lock:
            self.recent_trades.append({
                "time": _time.time(),
                "symbol": symbol, "direction": direction,
                "volume": volume, "price": price,
            })

    def detect_wash(self, symbol, lookback=50):
        with self._lock:
            recent = [t for t in self.recent_trades if t["symbol"] == symbol][-lookback:]
        if len(recent) < 4:
            return {"wash_trade": False}
        for i in range(len(recent) - 1):
            if (recent[i]["direction"] != recent[i+1]["direction"] and
                abs(recent[i]["price"] - recent[i+1]["price"]) / recent[i]["price"] < 0.0005 and
                abs(recent[i]["time"] - recent[i+1]["time"]) < 5):
                return {"wash_trade": True, "details": "Opposite trades at similar prices within 5 seconds"}
        return {"wash_trade": False}


_router = None
_dark_pool = None
_pfof = None
_cross_asset = None
_contingent = None
_reporter = None
_limits = None
_wash = None
_lock = threading.Lock()


def get_smart_router():
    global _router
    if _router is None:
        with _lock:
            if _router is None:
                _router = SmartOrderRouter()
    return _router


def get_dark_pool_detector():
    global _dark_pool
    if _dark_pool is None:
        with _lock:
            if _dark_pool is None:
                _dark_pool = DarkPoolDetector()
    return _dark_pool


def get_pfof_analyzer():
    global _pfof
    if _pfof is None:
        with _lock:
            if _pfof is None:
                _pfof = PFOFAnalyzer()
    return _pfof


def get_cross_asset_executor():
    global _cross_asset
    if _cross_asset is None:
        with _lock:
            if _cross_asset is None:
                _cross_asset = CrossAssetExecutor()
    return _cross_asset


def get_contingent_manager():
    global _contingent
    if _contingent is None:
        with _lock:
            if _contingent is None:
                _contingent = ContingentOrderManager()
    return _contingent


def get_trade_reporter():
    global _reporter
    if _reporter is None:
        with _lock:
            if _reporter is None:
                _reporter = TradeReporter()
    return _reporter


def get_position_limits():
    global _limits
    if _limits is None:
        with _lock:
            if _limits is None:
                _limits = PositionLimitMonitor()
    return _limits


def get_wash_detector():
    global _wash
    if _wash is None:
        with _lock:
            if _wash is None:
                _wash = WashTradeDetector()
    return _wash
