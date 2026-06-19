import MetaTrader5 as mt5

from datetime import datetime
import json
import os
import time as _time
import threading
from collections import deque
import traceback
import logging
from config import DATA_DIR, get_magic_number, magic_belongs_to_brain, is_system_magic
from indicators import is_tradeable_now, validate_tick_freshness, MT5_TRADE_RETCODE_MARKET_CLOSED, mark_symbol_market_closed
from sltp_engine import get_sltp_engine
from execution_optimization import AdvancedExecutor
from brain_v1 import _send_order_with_fallback
from alerts import get_alert_manager

logger = logging.getLogger(__name__)

# Error thresholds
MAX_CONSECUTIVE_ERRORS = 5
ERROR_COOLDOWN = 30
SPREAD_ALERT_THRESHOLD = 50  # Increased from 25 to allow volatile markets
SPREAD_MULTIPLIER = 3.0  # Reject if spread > 3x rolling average
SPREAD_HISTORY_SIZE = 100  # Rolling window for average spread
POSITION_RECONCILE_INTERVAL = 60
ROLLBACK_THRESHOLD = 0.25


class ErrorClassifier:
    CATEGORIES = {
        "connection": ["mt5", "connect", "initialize", "timeout", "socket"],
        "trade": ["order_send", "trade", "retcode", "volume", "price", "filling"],
        "data": ["rates", "copy_rates", "symbol_info", "tick", "data"],
        "calculation": ["divide", "zero", "nan", "inf", "overflow", "index"],
        "memory": ["memory", "allocation", "cache"],
    }

    @staticmethod
    def classify(error_msg):
        msg_lower = str(error_msg).lower()
        for category, keywords in ErrorClassifier.CATEGORIES.items():
            if any(kw in msg_lower for kw in keywords):
                return category
        return "unknown"

    @staticmethod
    def get_severity(category):
        severity = {
            "connection": "critical",
            "trade": "high",
            "data": "medium",
            "calculation": "high",
            "memory": "medium",
            "unknown": "low",
        }
        return severity.get(category, "low")


class ErrorTracker:
    def __init__(self):
        self.errors = deque(maxlen=200)
        self.error_counts = {}
        self.consecutive_errors = 0
        self.last_error_time = 0
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "error_log.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.errors = deque(data.get("errors", [])[-200:], maxlen=200)
                    self.error_counts = data.get("counts", {})
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Error log load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "error_log.json")
        with open(path, "w") as f:
            json.dump({
                "errors": list(self.errors)[-100:],
                "counts": self.error_counts,
            }, f)

    def record(self, error_msg, context="", source="system"):
        category = ErrorClassifier.classify(error_msg)
        severity = ErrorClassifier.get_severity(category)
        entry = {
            "time": datetime.now().isoformat(),
            "msg": str(error_msg)[:500],
            "context": str(context)[:200],
            "source": source,
            "category": category,
            "severity": severity,
        }
        with self._lock:
            self.errors.append(entry)
            self.error_counts[category] = self.error_counts.get(category, 0) + 1
            if severity in ("critical", "high"):
                self.consecutive_errors += 1
            self.last_error_time = _time.time()
        self._save()
        return entry

    def record_success(self):
        with self._lock:
            self.consecutive_errors = 0

    def is_error_storm(self):
        with self._lock:
            return self.consecutive_errors >= MAX_CONSECUTIVE_ERRORS

    def get_error_rate(self, window=300):
        cutoff = _time.time() - window
        with self._lock:
            recent = [e for e in self.errors if _time.time() - _parse_time(e.get("time", "")) < window]
        return len(recent)

    def get_category_summary(self):
        return dict(self.error_counts)


class MT5HealthMonitor:
    def __init__(self):
        self.health_history = deque(maxlen=50)
        self.last_check = 0
        self.is_healthy = True
        self.reconnect_count = 0
        self._lock = threading.Lock()

    def check_health(self):
        now = _time.time()
        with self._lock:
            if now - self.last_check < 5:
                return self.is_healthy
            self.last_check = now
        try:
            info = mt5.account_info()
            if info is None:
                with self._lock:
                    self.is_healthy = False
                    self.health_history.append({"time": now, "healthy": False, "reason": "no_account_info"})
                return False
            tick = mt5.symbol_info_tick("EURUSD")
            if tick is None:
                with self._lock:
                    self.is_healthy = False
                    self.health_history.append({"time": now, "healthy": False, "reason": "no_tick_data"})
                return False
            with self._lock:
                self.is_healthy = True
                self.health_history.append({"time": now, "healthy": True, "balance": info.balance})
            return True
        except Exception as e:
            with self._lock:
                self.is_healthy = False
                self.health_history.append({"time": now, "healthy": False, "reason": str(e)[:100]})
            return False

    def try_reconnect(self):
        with self._lock:
            try:
                mt5.shutdown()
                _time.sleep(1)
                if mt5.initialize():
                    self.reconnect_count += 1
                    self.is_healthy = True
                    return True
            except Exception as e:
                logger.debug("Health check failed: %s", e)
            return False

    def get_health_score(self):
        if not self.health_history:
            return 1.0
        recent = list(self.health_history)[-10:]
        healthy_count = sum(1 for h in recent if h["healthy"])
        return healthy_count / len(recent)


class TradeValidator:
    def __init__(self):
        self._spread_history = deque(maxlen=SPREAD_HISTORY_SIZE)

    def validate_request(self, request, symbol):
        errors = []
        info = mt5.symbol_info(symbol)
        if info is None:
            errors.append(f"Symbol {symbol} not found")
            return False, errors
        if "volume" in request:
            vol = request["volume"]
            if vol < info.volume_min:
                errors.append(f"Volume {vol} below min {info.volume_min}")
            elif vol > info.volume_max:
                errors.append(f"Volume {vol} above max {info.volume_max}")
            elif vol % info.volume_step != 0:
                errors.append(f"Volume {vol} not aligned to step {info.volume_step}")
        if "price" in request and request["price"] <= 0:
            errors.append(f"Invalid price {request['price']}")
        if "sl" in request and "tp" in request:
            price = request.get("price", 0)
            sl = request.get("sl", 0)
            tp = request.get("tp", 0)
            if request.get("type") == mt5.ORDER_TYPE_BUY:
                if sl > 0 and sl >= price:
                    errors.append("BUY SL above entry")
                if tp > 0 and tp <= price:
                    errors.append("BUY TP below entry")
                if sl > 0 and tp > 0 and sl >= tp:
                    errors.append("BUY SL must be below TP")
            elif request.get("type") == mt5.ORDER_TYPE_SELL:
                if sl > 0 and sl <= price:
                    errors.append("SELL SL below entry")
                if tp > 0 and tp >= price:
                    errors.append("SELL TP above entry")
                if sl > 0 and tp > 0 and sl <= tp:
                    errors.append("SELL SL must be above TP")
            # Check minimum SL/TP distance
            if sl > 0 and price > 0:
                sl_dist = abs(price - sl)
                min_sl_dist = info.point * 50
                if sl_dist < min_sl_dist:
                    errors.append(f"SL too close to entry ({sl_dist:.5f} < {min_sl_dist:.5f})")
            if tp > 0 and price > 0:
                tp_dist = abs(tp - price)
                min_tp_dist = info.point * 30
                if tp_dist < min_tp_dist:
                    errors.append(f"TP too close to entry ({tp_dist:.5f} < {min_tp_dist:.5f})")
        tick = mt5.symbol_info_tick(symbol)
        if tick and "price" in request:
            spread = (tick.ask - tick.bid) / info.point
            self._spread_history.append(spread)
            avg_spread = sum(self._spread_history) / len(self._spread_history) if self._spread_history else spread
            if spread > avg_spread * SPREAD_MULTIPLIER:
                errors.append(f"Spread {spread:.0f}pts exceeds {SPREAD_MULTIPLIER}x average ({avg_spread:.0f}pts)")
            elif spread > SPREAD_ALERT_THRESHOLD:
                errors.append(f"Spread {spread:.0f}pts exceeds alert threshold")
            # Price tolerance: reject if entry price > 10 pips from current tick
            price_tolerance = info.point * 100  # 10 pips
            entry_price = request.get("price", 0)
            if entry_price > 0:
                ref_price = tick.ask if request.get("type") == mt5.ORDER_TYPE_BUY else tick.bid
                if abs(entry_price - ref_price) > price_tolerance:
                    errors.append(f"Price {entry_price:.5f} too far from market {ref_price:.5f} (>{10} pips)")
        return len(errors) == 0, errors


class PositionReconciler:
    def __init__(self):
        self.known_positions = {}
        self.discrepancies = deque(maxlen=50)
        self.last_reconcile = 0

    def reconcile(self):
        now = _time.time()
        if now - self.last_reconcile < POSITION_RECONCILE_INTERVAL:
            return []
        self.last_reconcile = now
        current = mt5.positions_get()
        current_tickets = {p.ticket: p for p in (current or []) if is_system_magic(p.magic) and magic_belongs_to_brain(p.magic, "v6")}
        issues = []
        for ticket, pos in current_tickets.items():
            if ticket not in self.known_positions:
                self.known_positions[ticket] = {
                    "symbol": pos.symbol, "volume": pos.volume,
                    "open_price": pos.price_open, "open_time": pos.time,
                }
            known = self.known_positions[ticket]
            if abs(pos.volume - known["volume"]) > 0.001:
                issues.append({
                    "ticket": ticket, "type": "volume_mismatch",
                    "expected": known["volume"], "actual": pos.volume,
                })
        for ticket in list(self.known_positions.keys()):
            if ticket not in current_tickets:
                pos_info = self.known_positions.pop(ticket)
                issues.append({
                    "ticket": ticket, "type": "position_closed",
                    "info": pos_info,
                })
        if issues:
            self.discrepancies.extend(issues)
        return issues


class AutoRecovery:
    def __init__(self):
        self.recovery_actions = deque(maxlen=20)
        self.recovery_count = 0

    def handle_error(self, error_category, error_msg):
        actions = []
        if error_category == "connection":
            actions.append("reconnect")
        elif error_category == "trade":
            if "volume" in str(error_msg).lower():
                actions.append("recalculate_lot")
            elif "price" in str(error_msg).lower():
                actions.append("refresh_price")
            elif "filling" in str(error_msg).lower():
                actions.append("change_filling")
        elif error_category == "data":
            actions.append("retry_data_fetch")
        elif error_category == "calculation":
            actions.append("use_fallback_values")
        for action in actions:
            self.recovery_actions.append({
                "time": datetime.now().isoformat(),
                "category": error_category,
                "action": action,
                "error": str(error_msg)[:200],
            })
            self.recovery_count += 1
        return actions



class BrainV6:
    def __init__(self, brain_v5):
        self.v5 = brain_v5
        self.error_tracker = ErrorTracker()
        self.health_monitor = MT5HealthMonitor()
        self.validator = TradeValidator()
        self.reconciler = PositionReconciler()
        self.recovery = AutoRecovery()
        self._last_health_check = 0
        self._advanced_executor = None
        self._order_results = deque(maxlen=20)
        self._rejection_pause_until = 0
        try:
            self._advanced_executor = AdvancedExecutor()
        except Exception:
            pass

    def _track_order_result(self, success, reason=""):
        self._order_results.append({"ok": success, "reason": reason, "time": _time.time()})

    def _is_rejection_rate_high(self):
        if len(self._order_results) < 10:
            return False
        recent = list(self._order_results)[-10:]
        rejects = sum(1 for r in recent if not r["ok"])
        rate = rejects / len(recent)
        return rate > 0.5

    def _check_rejection_pause(self):
        if _time.time() < self._rejection_pause_until:
            return True
        return False

    def safe_analyze(self, symbol, timeframe=mt5.TIMEFRAME_M1, params=None, df=None):
        # Health check
        now = _time.time()
        if now - self._last_health_check > 10:
            healthy = self.health_monitor.check_health()
            if not healthy:
                logger.warning("MT5 unhealthy, attempting reconnect...")
                if self.health_monitor.try_reconnect():
                    logger.info("Reconnected successfully")
                else:
                    logger.warning("Reconnect failed, waiting...")
                    try:
                        get_alert_manager().alert_mt5_disconnect("Reconnect failed")
                    except Exception:
                        pass
                    return {"action": "hold", "confidence": 0, "reason": "MT5 disconnected"}
            self._last_health_check = now

        # Error storm check with exponential backoff
        if self.error_tracker.is_error_storm():
            backoff_mult = min(self.error_tracker.consecutive_errors / MAX_CONSECUTIVE_ERRORS, 4.0)
            effective_cooldown = ERROR_COOLDOWN * backoff_mult
            remaining = effective_cooldown - (_time.time() - self.error_tracker.last_error_time)
            if remaining > 0:
                logger.warning("Error storm cooldown (%.0fs, backoff=%.1fx)", remaining, backoff_mult)
                return {"action": "hold", "confidence": 0, "reason": f"Error storm cooldown ({remaining:.0f}s)"}

        # Reconcile positions
        issues = self.reconciler.reconcile()
        if issues:
            for issue in issues:
                logger.warning("Position issue: %s ticket %s", issue['type'], issue.get('ticket', '?'))

        # Safe analysis with error catching
        try:
            decision = self.v5.analyze(symbol, timeframe, params=params, df=df)
            self.error_tracker.record_success()
            return decision
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            tb = traceback.format_exc()
            self.error_tracker.record(error_msg, context=f"analyze({symbol})", source="brain_v6")
            logger.error("Error in analysis: %s", error_msg)
            categories = self.recovery.handle_error(
                ErrorClassifier.classify(error_msg), error_msg
            )
            logger.warning("Recovery actions: %s", categories)
            return {"action": "hold", "confidence": 0, "reason": f"Analysis error: {error_msg[:100]}"}

    def safe_execute(self, decision, symbol):
        if decision.get("action") != "trade":
            return False

        if self._check_rejection_pause():
            logger.warning("Rejection rate pause active — skipping execution")
            return False

        # Full market state check — includes symbol-specific cooldown tracking
        tradeable = is_tradeable_now(symbol)
        if not tradeable["can_trade"]:
            logger.warning("Cannot trade %s: %s", symbol, tradeable['reason'])
            self.error_tracker.record(f"Trade blocked: {tradeable['reason']}", source="brain_v6")
            self._track_order_result(False, f"blocked: {tradeable['reason']}")
            return False

        # Validate request before sending
        direction = decision.get("direction", 0)
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            self.error_tracker.record("No tick data for execution", source="brain_v6")
            self._track_order_result(False, "no tick data")
            return False

        # Validate tick freshness — reject if data is stale
        tick_check = validate_tick_freshness(tick, symbol)
        if not tick_check["fresh"]:
            logger.warning("Stale tick for %s: %s", symbol, tick_check['reason'])
            self.error_tracker.record(f"Stale tick: {tick_check['reason']}", source="brain_v6")
            self._track_order_result(False, f"stale tick: {tick_check['reason']}")
            return False

        info = mt5.symbol_info(symbol)
        if not info:
            self.error_tracker.record(f"Symbol {symbol} not found", source="brain_v6")
            self._track_order_result(False, f"symbol {symbol} not found")
            return False

        # Check if market is open
        if info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            logger.warning("Market closed for %s (trade_mode=%s)", symbol, info.trade_mode)
            self.error_tracker.record(f"Market closed for {symbol}", source="brain_v6")
            self._track_order_result(False, f"market closed: {symbol}")
            return False

        price = tick.ask if direction == 1 else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": decision.get("lot", 0.01),
            "type": mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": decision.get("sl", 0),
            "tp": decision.get("tp", 0),
              "magic": decision.get("magic", get_magic_number("v6", "technical", decision.get("symbol", "EURUSD"))),
            "comment": f"BV6:{decision.get('confidence', 0):.2f}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Auto-fix SL/TP if zero — use SLTP engine for optimal placement
        if request["sl"] == 0 or request["tp"] == 0:
            try:
                rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 200)
                if rates is not None and len(rates) >= 50:
                    import pandas as pd
                    df = pd.DataFrame(rates)
                    sltp_result = get_sltp_engine().calculate_sl_tp(symbol, direction, df)
                    if request["sl"] == 0 and sltp_result.get("sl", 0) != 0:
                        request["sl"] = sltp_result["sl"]
                        logger.info("SLTP engine SL to %s", request['sl'])
                    if request["tp"] == 0 and sltp_result.get("tp", 0) != 0:
                        request["tp"] = sltp_result["tp"]
                        logger.info("SLTP engine TP to %s", request['tp'])
            except Exception as e:
                logger.warning('SLTP calculation failed: %s', e)
            # Hardcoded fallback if SLTP engine failed
            if request["sl"] == 0 or request["tp"] == 0:
                if tick and info:
                    point = info.point
                    price = tick.ask if direction == 1 else tick.bid
                    if request["sl"] == 0:
                        request["sl"] = round(price - 100 * point, info.digits) if direction == 1 else round(price + 100 * point, info.digits)
                        logger.info("Fallback SL to %s", request['sl'])
                    if request["tp"] == 0:
                        request["tp"] = round(price + 200 * point, info.digits) if direction == 1 else round(price - 200 * point, info.digits)
                        logger.info("Fallback TP to %s", request['tp'])

        valid, errors = self.validator.validate_request(request, symbol)
        if not valid:
            for err in errors:
                self.error_tracker.record(f"Validation: {err}", context=f"execute({symbol})", source="brain_v6")
                logger.warning("Validation error: %s", err)

            # Auto-fix common issues
            if any("volume" in e.lower() for e in errors):
                if info:
                    request["volume"] = max(info.volume_min, min(request["volume"], info.volume_max))
                    request["volume"] = round(request["volume"] / info.volume_step) * info.volume_step
                    logger.info("Auto-fixed volume to %s", request['volume'])

            if any("price" in e.lower() for e in errors):
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    request["price"] = tick.ask if direction == 1 else tick.bid
                    logger.info("Auto-refreshed price to %s", request['price'])

            valid_after_fix, _ = self.validator.validate_request(request, symbol)
            if not valid_after_fix:
                self._track_order_result(False, "validation failed after auto-fix")
                return False

        # Execute with error handling
        try:
            logger.debug("Sending order: symbol=%s, volume=%s, price=%s, type=%s, sl=%s, tp=%s", request.get('symbol'), request.get('volume'), request.get('price'), request.get('type'), request.get('sl'), request.get('tp'))
            
            if self._advanced_executor:
                exec_start = _time.time()
                result = self._advanced_executor.execute(symbol, direction, request.get("volume", 0.01), decision.get("sl_points", 100), decision.get("tp_points", 200))
                exec_time = (_time.time() - exec_start) * 1000
            else:
                exec_start = _time.time()
                result = _send_order_with_fallback(request)
                exec_time = (_time.time() - exec_start) * 1000

            if result is None:
                error_msg = f"Trade failed: order_send returned None (last_error: {mt5.last_error()})"
                self.error_tracker.record(error_msg, context=f"execute({symbol})", source="brain_v6")
                self._track_order_result(False, error_msg)
                logger.warning("%s", error_msg)
                return False

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                error_msg = f"Trade error: {result.comment} (code: {result.retcode})"
                self.error_tracker.record(error_msg, context=f"execute({symbol})", source="brain_v6")
                self._track_order_result(False, error_msg)
                logger.warning("%s", error_msg)
                # Handle market closed error — mark symbol and prevent retries
                if result.retcode == MT5_TRADE_RETCODE_MARKET_CLOSED:
                    mark_symbol_market_closed(symbol, result.retcode)
                    logger.warning("Market closed for %s — added to cooldown", symbol)
                    return False

                # Try recovery for other errors
                recovery = self.recovery.handle_error("trade", error_msg)
                if "refresh_price" in recovery:
                    tick = mt5.symbol_info_tick(symbol)
                    if tick:
                        request["price"] = tick.ask if direction == 1 else tick.bid
                        result2 = _send_order_with_fallback(request)
                        if result2 is not None and result2.retcode == mt5.TRADE_RETCODE_DONE:
                            self.error_tracker.record_success()
                            self._track_order_result(True)
                            return True
                        # Check if retry also hit market closed
                        if result2 and result2.retcode == MT5_TRADE_RETCODE_MARKET_CLOSED:
                            mark_symbol_market_closed(symbol, result2.retcode)
                            logger.warning("Market closed for %s on retry — added to cooldown", symbol)
                elif "recalculate_lot" in recovery:
                    if info:
                        request["volume"] = max(info.volume_min, min(request["volume"], info.volume_max))
                        request["volume"] = round(request["volume"] / info.volume_step) * info.volume_step
                        result2 = _send_order_with_fallback(request)
                        if result2 is not None and result2.retcode == mt5.TRADE_RETCODE_DONE:
                            self.error_tracker.record_success()
                            self._track_order_result(True)
                            return True
                elif "change_filling" in recovery:
                    request["type_filling"] = mt5.ORDER_FILLING_FOK
                    result2 = _send_order_with_fallback(request)
                    if result2 is not None and result2.retcode == mt5.TRADE_RETCODE_DONE:
                        self.error_tracker.record_success()
                        self._track_order_result(True)
                        return True
                self._track_order_result(False, "recovery failed")
                return False

            self.error_tracker.record_success()
            self._track_order_result(True)
            if self._is_rejection_rate_high():
                self._rejection_pause_until = _time.time() + 300
                logger.warning("Rejection rate > 50%% in last 10 orders — pausing 5min")
            logger.info("Executed in %.0fms | Conf: %.3f", exec_time, decision.get('confidence', 0))
            return True

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            self.error_tracker.record(error_msg, context=f"execute({symbol})", source="brain_v6")
            self._track_order_result(False, error_msg)
            logger.error("Execution error: %s", error_msg)
            return False

    def manage_positions(self, symbol):
        try:
            self.v5.manage_positions(symbol)
        except Exception as e:
            self.error_tracker.record(f"Position mgmt error: {e}", source="brain_v6")

    def record_trade_result(self, *args, **kwargs):
        try:
            self.v5.record_trade_outcome(*args, **kwargs)
        except Exception as e:
            self.error_tracker.record(f"Record error: {e}", source="brain_v6")

    def get_dashboard_data(self):
        data = self.v5.get_dashboard_data()
        data["v6"] = {
            "error_count": len(self.error_tracker.errors),
            "consecutive_errors": self.error_tracker.consecutive_errors,
            "error_storm": self.error_tracker.is_error_storm(),
            "error_categories": self.error_tracker.get_category_summary(),
            "health_score": self.health_monitor.get_health_score(),
            "reconnect_count": self.health_monitor.reconnect_count,
            "recovery_count": self.recovery.recovery_count,
            "position_issues": len(self.reconciler.discrepancies),
        }
        return data

    def print_status(self):
        self.v5.print_status()
        v6 = self.get_dashboard_data().get("v6", {})
        logger.info("BRAIN V6 — ERROR FIXING & SELF-CORRECTION")
        logger.info("  Health Score: %.0f%% | Reconnects: %d", v6.get('health_score', 1) * 100, v6.get('reconnect_count', 0))
        logger.info("  Errors: %d total | Consecutive: %d | Storm: %s", v6.get('error_count', 0), v6.get('consecutive_errors', 0), 'YES' if v6.get('error_storm') else 'NO')
        cats = v6.get('error_categories', {})
        if cats:
            logger.info("  Error Categories: %s", ', '.join(f'{k}:{v}' for k, v in cats.items()))
        logger.info("  Recoveries: %d | Position Issues: %d", v6.get('recovery_count', 0), v6.get('position_issues', 0))


def _parse_time(time_str):
    try:
        dt = datetime.fromisoformat(time_str)
        return dt.timestamp()
    except (ValueError, TypeError) as e:
        logger.debug("Time parse failed: %s", e)
        return 0
