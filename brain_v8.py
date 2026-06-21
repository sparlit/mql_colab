import mt5_mcp as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os
import time as _time
from collections import deque
import threading
import logging
from config import DATA_DIR
from data_analytics import get_tick_db, get_realtime_pnl

logger = logging.getLogger(__name__)

# Retention
MAX_JOURNAL_ENTRIES = 2000
MAX_ACTIVITY_LOG = 5000
MAX_DECISION_LOG = 1000
MAX_ERROR_LOG = 500
DAILY_REPORT_HOUR = 0


class TradeJournal:
    def __init__(self):
        self.entries = deque(maxlen=MAX_JOURNAL_ENTRIES)
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "trade_journal_v8.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.entries = deque(data.get("entries", [])[-MAX_JOURNAL_ENTRIES:], maxlen=MAX_JOURNAL_ENTRIES)
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Journal load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "trade_journal_v8.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"entries": list(self.entries)}, f)
        if os.path.exists(path):
            os.replace(tmp, path)
        else:
            os.rename(tmp, path)

    def record_open(self, ticket, symbol, direction, lot, price, sl, tp, confidence, signals, regime, session, brain_versions):
        entry = {
            "ticket": ticket,
            "symbol": symbol,
            "direction": "BUY" if direction == 1 else "SELL",
            "lot": lot,
            "open_price": price,
            "sl": sl,
            "tp": tp,
            "open_time": datetime.now().isoformat(),
            "confidence": confidence,
            "signals": signals,
            "regime": regime,
            "session": session,
            "brain_versions": brain_versions,
            "status": "open",
            "close_price": None,
            "close_time": None,
            "profit": None,
            "pips": None,
            "duration": None,
            "close_reason": None,
            "notes": [],
        }
        with self._lock:
            self.entries.append(entry)
            self._save()
        return entry

    def record_close(self, ticket, close_price, profit, reason=""):
        result = None
        with self._lock:
            for entry in reversed(self.entries):
                if entry["ticket"] == ticket and entry["status"] == "open":
                    entry["close_price"] = close_price
                    entry["close_time"] = datetime.now().isoformat()
                    entry["profit"] = profit
                    entry["status"] = "closed"
                    entry["close_reason"] = reason
                    open_time = datetime.fromisoformat(entry["open_time"])
                    entry["duration"] = str(datetime.now() - open_time)
                    info = mt5.symbol_info(entry["symbol"])
                    if info and entry["open_price"] > 0:
                        point = info.point
                        if entry["direction"] == "BUY":
                            entry["points"] = round((close_price - entry["open_price"]) / point, 1)
                        else:
                            entry["points"] = round((entry["open_price"] - close_price) / point, 1)
                    result = entry
                    break
        if result:
            with self._save_lock:
                self._save()
        return result

    def add_note(self, ticket, note):
        with self._lock:
            for entry in reversed(self.entries):
                if entry["ticket"] == ticket:
                    entry["notes"].append({
                        "time": datetime.now().isoformat(),
                        "note": note,
                    })
                    break
            else:
                return False
        with self._save_lock:
            self._save()
        return True

    def get_recent(self, n=20):
        with self._lock:
            return list(self.entries)[-n:]

    def get_open(self):
        with self._lock:
            return [e for e in self.entries if e["status"] == "open"]

    def get_closed(self):
        with self._lock:
            return [e for e in self.entries if e["status"] == "closed"]

    def get_stats(self):
        with self._lock:
            closed = [e for e in self.entries if e["status"] == "closed"]
        if not closed:
            return {}
        wins = [e for e in closed if e.get("profit") is not None and e.get("profit") > 0]
        losses = [e for e in closed if e.get("profit") is not None and e.get("profit") < 0]
        total_profit = sum(e.get("profit", 0) for e in closed)
        avg_win = np.mean([e["profit"] for e in wins]) if wins else 0
        avg_loss = abs(np.mean([e["profit"] for e in losses])) if losses else 0
        return {
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(closed) * 100,
            "total_profit": round(total_profit, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(avg_win / avg_loss, 2) if avg_loss > 0 else 100.0,
            "best_trade": max(closed, key=lambda e: e.get("profit", 0)),
            "worst_trade": min(closed, key=lambda e: e.get("profit", 0)),
        }


class ActivityLogger:
    def __init__(self):
        self.activities = deque(maxlen=MAX_ACTIVITY_LOG)
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "activity_log.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.activities = deque(data.get("activities", [])[-MAX_ACTIVITY_LOG:], maxlen=MAX_ACTIVITY_LOG)
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Activity log load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "activity_log.json")
        with open(path, "w") as f:
            json.dump({"activities": list(self.activities)[-500:]}, f)

    def log(self, category, message, level="info", data=None):
        entry = {
            "time": datetime.now().isoformat(),
            "category": category,
            "message": message,
            "level": level,
            "data": data,
        }
        with self._lock:
            self.activities.append(entry)
        if level in ("error", "critical"):
            self._save()
        return entry

    def get_recent(self, n=50, category=None, level=None):
        with self._lock:
            entries = list(self.activities)
        if category:
            entries = [e for e in entries if e["category"] == category]
        if level:
            entries = [e for e in entries if e["level"] == level]
        return entries[-n:]

    def get_summary(self):
        categories = {}
        levels = {}
        with self._lock:
            activities_snapshot = list(self.activities)
        for e in activities_snapshot:
            cat = e["category"]
            lev = e["level"]
            categories[cat] = categories.get(cat, 0) + 1
            levels[lev] = levels.get(lev, 0) + 1
        return {"categories": categories, "levels": levels, "total": len(activities_snapshot)}


class DecisionAuditTrail:
    def __init__(self):
        self.trail = deque(maxlen=MAX_DECISION_LOG)
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "decision_audit.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.trail = deque(data.get("decisions", [])[-MAX_DECISION_LOG:], maxlen=MAX_DECISION_LOG)
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Decision audit load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "decision_audit.json")
        with open(path, "w") as f:
            json.dump({"decisions": list(self.trail)[-300:]}, f)

    def record(self, decision, symbol):
        entry = {
            "time": datetime.now().isoformat(),
            "symbol": symbol,
            "action": decision.get("action", "unknown"),
            "direction": decision.get("direction_str", decision.get("direction", "")),
            "confidence": decision.get("confidence", 0),
            "lot": decision.get("lot", 0),
            "sl": decision.get("sl_points", 0),
            "tp": decision.get("tp_points", 0),
            "reason": decision.get("reason", ""),
            "active_signals": decision.get("active", []),
            "v2_regime": decision.get("v2_analysis", {}).get("regime", ""),
            "v2_session": decision.get("v2_analysis", {}).get("session", ""),
        }
        with self._lock:
            self.trail.append(entry)
            trail_len = len(self.trail)
        if trail_len % 50 == 0:
            self._save()

    def get_recent(self, n=20):
        with self._lock:
            return list(self.trail)[-n:]

    def get_decision_stats(self):
        with self._lock:
            if not self.trail:
                return {}
            actions = {}
            for d in self.trail:
                a = d.get("action", "unknown")
                actions[a] = actions.get(a, 0) + 1
            confs = [d.get("confidence", 0) for d in self.trail if d.get("action") == "trade"]
            trail_len = len(self.trail)
        return {
            "total_decisions": trail_len,
            "action_breakdown": actions,
            "avg_trade_confidence": np.mean(confs) if confs else 0,
        }


class ErrorDocumentation:
    def __init__(self):
        self.errors = deque(maxlen=MAX_ERROR_LOG)
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        path = os.path.join(DATA_DIR, "error_docs.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.errors = deque(data.get("errors", [])[-MAX_ERROR_LOG:], maxlen=MAX_ERROR_LOG)
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Error docs load failed: %s", e)

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "error_docs.json")
        with open(path, "w") as f:
            json.dump({"errors": list(self.errors)[-200:]}, f)

    def document(self, error_msg, category, context, resolution=""):
        entry = {
            "time": datetime.now().isoformat(),
            "message": str(error_msg)[:1000],
            "category": category,
            "context": str(context)[:500],
            "resolution": resolution,
            "occurrences": 1,
        }
        with self._lock:
            for existing in self.errors:
                if existing["message"] == entry["message"] and existing["category"] == category:
                    existing["occurrences"] += 1
                    existing["last_seen"] = entry["time"]
                    self._save()
                    return existing
            self.errors.append(entry)
        self._save()
        return entry

    def get_by_category(self, category):
        with self._lock:
            return [e for e in self.errors if e["category"] == category]

    def get_frequent(self, min_occurrences=2):
        with self._lock:
            return [e for e in self.errors if e.get("occurrences", 1) >= min_occurrences]


class ReportGenerator:
    def __init__(self, journal, activity, audit, errors):
        self.journal = journal
        self.activity = activity
        self.audit = audit
        self.errors = errors

    def daily_report(self):
        today = datetime.now().date()
        closed_today = [e for e in self.journal.get_closed()
                       if e.get("close_time", "")[:10] == str(today)]
        if not closed_today:
            return {"date": str(today), "trades": 0, "message": "No trades today"}

        wins = [e for e in closed_today if e.get("profit") is not None and e.get("profit") > 0]
        losses = [e for e in closed_today if e.get("profit") is not None and e.get("profit") < 0]
        total_profit = sum(e.get("profit", 0) for e in closed_today)
        with self.activity._lock:
            activities_today = [a for a in self.activity.activities if a.get("time", "")[:10] == str(today)]
        with self.errors._lock:
            errors_today = [e for e in self.errors.errors if e.get("time", "")[:10] == str(today)]

        report = {
            "date": str(today),
            "trades": len(closed_today),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(closed_today) * 100 if closed_today else 0,
            "total_profit": round(total_profit, 2),
            "best_trade": max(closed_today, key=lambda e: e.get("profit", 0)) if closed_today else None,
            "worst_trade": min(closed_today, key=lambda e: e.get("profit", 0)) if closed_today else None,
            "activities": len(activities_today),
            "errors": len(errors_today),
            "avg_confidence": np.mean([e.get("confidence", 0) for e in closed_today]),
            "regimes_traded": list(set(e.get("regime", "") for e in closed_today)),
            "sessions_traded": list(set(e.get("session", "") for e in closed_today)),
        }
        return report

    def performance_summary(self, days=30):
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        closed = [e for e in self.journal.get_closed() if e.get("close_time", "") >= cutoff[:10]]
        if not closed:
            return {"period": f"Last {days} days", "trades": 0}

        daily_pnl = {}
        for e in closed:
            day = e.get("close_time", "")[:10]
            daily_pnl[day] = daily_pnl.get(day, 0) + (e.get("profit") or 0)

        return {
            "period": f"Last {days} days",
            "total_trades": len(closed),
            "total_profit": round(sum(daily_pnl.values()), 2),
            "profitable_days": sum(1 for v in daily_pnl.values() if v > 0),
            "total_days": len(daily_pnl),
            "best_day": max(daily_pnl.values()) if daily_pnl else 0,
            "worst_day": min(daily_pnl.values()) if daily_pnl else 0,
            "avg_daily_pnl": round(np.mean(list(daily_pnl.values())), 2),
        }

    def export_journal(self, filepath=None):
        if filepath is None:
            filepath = os.path.join(DATA_DIR, f"journal_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with self.journal._lock:
            journal_snapshot = list(self.journal.entries)
        data = {
            "export_time": datetime.now().isoformat(),
            "stats": self.journal.get_stats(),
            "journal": journal_snapshot,
            "activity_summary": self.activity.get_summary(),
            "decision_stats": self.audit.get_decision_stats(),
            "frequent_errors": self.errors.get_frequent(),
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)
        return filepath


class BrainV8:
    def __init__(self, brain_v7):
        self.v7 = brain_v7
        self.journal = TradeJournal()
        self.activity = ActivityLogger()
        self.audit = DecisionAuditTrail()
        self.error_doc = ErrorDocumentation()
        self.reporter = ReportGenerator(self.journal, self.activity, self.audit, self.error_doc)
        self._last_daily_report = None
        self._tick_db = None
        self._pnl_tracker = None
        try:
            self._tick_db = get_tick_db()
            self._pnl_tracker = get_realtime_pnl()
        except Exception:
            pass

    def analyze(self, symbol, timeframe=mt5.TIMEFRAME_M1, df=None):
        self.activity.log("analysis", f"Starting analysis for {symbol}", data={"timeframe": timeframe})
        if self._tick_db:
            try:
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    self._tick_db.record_tick(symbol, tick)
            except Exception:
                pass
        if self._pnl_tracker:
            try:
                self._pnl_tracker.record()
            except Exception:
                pass

        decision = self.v7.analyze(symbol, timeframe, df=df)

        self.audit.record(decision, symbol)

        if decision.get("action") == "trade":
            self.activity.log("trade_signal", f"Signal: {decision.get('direction_str', '')} {symbol} conf={decision.get('confidence', 0):.3f}",
                            level="info", data={"confidence": decision.get("confidence"), "lot": decision.get("lot")})

        # Daily report check
        now = datetime.now()
        if self._last_daily_report != now.date() and now.hour >= DAILY_REPORT_HOUR:
            report = self.reporter.daily_report()
            if report.get("trades", 0) > 0:
                self.activity.log("report", f"Daily report: {report['trades']} trades, PnL ${report.get('total_profit', 0):.2f}")
            self._last_daily_report = now.date()

        return decision

    def record_trade_open(self, ticket, symbol, direction, lot, price, sl, tp, confidence, signals, regime, session):
        brain_versions = {
            "v1": "8strat", "v2": "regime", "v3": "cache",
            "v4": "bayesian", "v5": "evolution", "v6": "safety",
            "v7": "learning", "v8": "recording",
        }
        entry = self.journal.record_open(
            ticket, symbol, direction, lot, price, sl, tp,
            confidence, signals, regime, session, brain_versions
        )
        self.activity.log("trade_open", f"OPENED {direction} {lot} {symbol} @ {price}",
                         level="info", data={"ticket": ticket, "confidence": confidence})
        return entry

    def record_trade_close(self, ticket, close_price, profit, reason=""):
        entry = self.journal.record_close(ticket, close_price, profit, reason)
        if entry:
            level = "info" if profit >= 0 else "warning"
            self.activity.log("trade_close",
                            f"CLOSED {entry['direction']} {entry['lot']} {entry['symbol']} PnL: ${profit:.2f} ({entry.get('points', 0)} points)",
                            level=level, data={"ticket": ticket, "profit": profit, "points": entry.get("points")})
        return entry

    def record_error(self, error_msg, category, context, resolution=""):
        self.error_doc.document(error_msg, category, context, resolution)
        self.activity.log("error", f"Error: {str(error_msg)[:100]}", level="error",
                         data={"category": category, "context": str(context)[:200]})

    def manage_positions(self, symbol):
        self.v7.manage_positions(symbol)

    def execute_decision(self, decision, symbol):
        success = self.v7.execute_decision(decision, symbol)
        if success:
            self.activity.log("execution", f"EXECUTED {decision.get('direction_str', '')} {symbol}",
                            data={"lot": decision.get("lot"), "confidence": decision.get("confidence")})
        else:
            self.activity.log("execution_failed", f"FAILED {decision.get('direction_str', '')} {symbol}",
                            level="warning")
        return success

    def get_dashboard_data(self):
        data = self.v7.get_dashboard_data()
        data["v8"] = {
            "journal_stats": self.journal.get_stats(),
            "open_trades": len(self.journal.get_open()),
            "activity_summary": self.activity.get_summary(),
            "decision_stats": self.audit.get_decision_stats(),
            "frequent_errors": self.error_doc.get_frequent(),
            "recent_activities": self.activity.get_recent(10),
            "recent_decisions": self.audit.get_recent(5),
        }
        return data

    def print_status(self):
        self.v7.print_status()
        v8 = self.get_dashboard_data().get("v8", {})
        stats = v8.get("journal_stats", {})
        act = v8.get("activity_summary", {})
        dec = v8.get("decision_stats", {})
        logger.info("  BRAIN V8 — RECORDING & DOCUMENTATION")
        if stats:
            logger.info("  Journal: %d trades | WR %.1f%% | PF %.2f", stats.get('total_trades', 0), stats.get('win_rate', 0), stats.get('profit_factor', 0))
            logger.info("  Total PnL: $%.2f | Avg Win: $%.2f | Avg Loss: $%.2f", stats.get('total_profit', 0), stats.get('avg_win', 0), stats.get('avg_loss', 0))
        logger.info("  Activities: %d | Decisions: %d", act.get('total', 0), dec.get('total_decisions', 0))
        freq = v8.get("frequent_errors", [])
        if freq:
            logger.info("  Frequent Errors:")
            for e in freq[:3]:
                logger.info("    [%s] %s... (%dx)", e['category'], e['message'][:50], e.get('occurrences', 1))
        recent = v8.get("recent_activities", [])[-3:]
        if recent:
            logger.info("  Recent Activity:")
            for a in recent:
                logger.info("    [%s] %s: %s", a['level'].upper(), a['category'], a['message'][:60])

    def export_data(self, filepath=None):
        return self.reporter.export_journal(filepath)
