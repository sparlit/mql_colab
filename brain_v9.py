import mt5_mcp as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import json
import os
import time as _time
from collections import deque
import logging
from config import MAGIC_NUMBER, DATA_DIR, LOG_DIR

logger = logging.getLogger(__name__)

# Monitoring intervals
CPU_SAMPLE_INTERVAL = 2.0
SYSTEM_CHECK_INTERVAL = 10.0
REPORT_GENERATION_INTERVAL = 3600.0

# Alerts
CPU_ALERT_THRESHOLD = 85.0
MEMORY_ALERT_THRESHOLD = 85.0
DISK_ALERT_THRESHOLD = 90.0

# Retention
MAX_ALERT_HISTORY = 200
MAX_SYSTEM_LOG = 2000


class CPUMonitor:
    def __init__(self):
        self.usage_history = deque(maxlen=200)
        self.last_sample_time = 0
        self.last_cpu_times = None
        self._process = None
        self._try_import()

    def _try_import(self):
        try:
            import psutil
            self._psutil = psutil
        except ImportError:
            self._psutil = None

    def sample(self):
        now = _time.time()
        if now - self.last_sample_time < CPU_SAMPLE_INTERVAL:
            return self.get_current()
        self.last_sample_time = now

        if self._psutil:
            cpu = self._psutil.cpu_percent(interval=0.1)
            per_cpu = self._psutil.cpu_percent(interval=0, percpu=True)
            freq = self._psutil.cpu_freq()
            result = {
                "overall": cpu,
                "per_core": per_cpu,
                "core_count": len(per_cpu),
                "freq_current": freq.current if freq else 0,
                "freq_max": freq.max if freq else 0,
                "load_avg": self._get_load_avg(),
            }
        else:
            result = self._fallback_cpu()
        self.usage_history.append({"time": now, "data": result})
        return result

    def get_current(self):
        if self.usage_history:
            return self.usage_history[-1]["data"]
        return self.sample()

    def get_average(self, window=30):
        recent = list(self.usage_history)[-window:]
        if not recent:
            return 0
        return np.mean([d["data"]["overall"] for d in recent])

    def get_peak(self, window=60):
        recent = list(self.usage_history)[-window:]
        if not recent:
            return 0
        return max(d["data"]["overall"] for d in recent)

    def get_trend(self):
        if len(self.usage_history) < 10:
            return "stable"
        recent = [d["data"]["overall"] for d in list(self.usage_history)[-10:]]
        older = [d["data"]["overall"] for d in list(self.usage_history)[-20:-10]] if len(self.usage_history) >= 20 else recent
        diff = np.mean(recent) - np.mean(older)
        if diff > 5:
            return "rising"
        elif diff < -5:
            return "falling"
        return "stable"

    def _get_load_avg(self):
        try:
            if self._psutil:
                return list(self._psutil.getloadavg()) if hasattr(self._psutil, 'getloadavg') else [0, 0, 0]
        except (AttributeError, OSError) as e:
            logger.debug("Load average unavailable: %s", e)
        return [0, 0, 0]

    def _fallback_cpu(self):
        return {
            "overall": 0, "per_core": [], "core_count": 0,
            "freq_current": 0, "freq_max": 0, "load_avg": [0, 0, 0],
        }


class MemoryMonitor:
    def __init__(self):
        self.usage_history = deque(maxlen=200)
        self._psutil = None
        self._try_import()

    def _try_import(self):
        try:
            import psutil
            self._psutil = psutil
        except ImportError:
            self._psutil = None

    def sample(self):
        if self._psutil:
            mem = self._psutil.virtual_memory()
            swap = self._psutil.swap_memory()
            result = {
                "total_gb": round(mem.total / (1024**3), 2),
                "used_gb": round(mem.used / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
                "percent": mem.percent,
                "swap_total_gb": round(swap.total / (1024**3), 2),
                "swap_used_gb": round(swap.used / (1024**3), 2),
                "swap_percent": swap.percent,
            }
        else:
            result = {"total_gb": 0, "used_gb": 0, "available_gb": 0, "percent": 0, "swap_total_gb": 0, "swap_used_gb": 0, "swap_percent": 0}
        self.usage_history.append({"time": _time.time(), "data": result})
        return result

    def get_current(self):
        if self.usage_history:
            return self.usage_history[-1]["data"]
        return self.sample()

    def get_average(self, window=30):
        recent = list(self.usage_history)[-window:]
        if not recent:
            return 0
        return np.mean([d["data"]["percent"] for d in recent])

    def get_trend(self):
        if len(self.usage_history) < 10:
            return "stable"
        recent = [d["data"]["percent"] for d in list(self.usage_history)[-10:]]
        older = [d["data"]["percent"] for d in list(self.usage_history)[-20:-10]] if len(self.usage_history) >= 20 else recent
        diff = np.mean(recent) - np.mean(older)
        if diff > 3:
            return "rising"
        elif diff < -3:
            return "falling"
        return "stable"


class ProcessMonitor:
    def __init__(self):
        self.process_info = {}
        self._psutil = None
        self._try_import()

    def _try_import(self):
        try:
            import psutil
            self._psutil = psutil
        except ImportError:
            self._psutil = None

    def get_process_info(self, process_name=None):
        if not self._psutil:
            return {"processes": [], "mt5_running": False, "python_running": False}
        mt5_running = False
        python_running = False
        mt5_cpu = 0
        mt5_mem = 0
        python_cpu = 0
        python_mem = 0
        processes = []
        for proc in self._psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
            try:
                info = proc.info
                name = info.get('name', '').lower()
                cpu = info.get('cpu_percent', 0) or 0
                mem = info.get('memory_percent', 0) or 0
                if 'terminal64' in name or 'metatrader' in name:
                    mt5_running = True
                    mt5_cpu += cpu
                    mt5_mem += mem
                if 'python' in name:
                    python_running = True
                    python_cpu += cpu
                    python_mem += mem
                if cpu > 1.0 or mem > 1.0:
                    processes.append({"name": info.get('name', '?'), "pid": info.get('pid', 0), "cpu": round(cpu, 1), "mem": round(mem, 1)})
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
                logger.debug("Process info error: %s", e)
            except Exception as e:
                logger.debug("Unexpected process error: %s", e)
        processes.sort(key=lambda x: x['cpu'], reverse=True)
        return {
            "mt5_running": mt5_running,
            "mt5_cpu": round(mt5_cpu, 1),
            "mt5_mem": round(mt5_mem, 1),
            "python_running": python_running,
            "python_cpu": round(python_cpu, 1),
            "python_mem": round(python_mem, 1),
            "top_processes": processes[:10],
        }


class SystemMonitor:
    def __init__(self):
        self.cpu = CPUMonitor()
        self.memory = MemoryMonitor()
        self.process = ProcessMonitor()
        self.disk_usage = {}
        self.system_info = {}
        self.alerts = deque(maxlen=MAX_ALERT_HISTORY)
        self.system_log = deque(maxlen=MAX_SYSTEM_LOG)
        self._psutil = None
        self._try_import()

    def _try_import(self):
        try:
            import psutil
            self._psutil = psutil
            self.system_info = {
                "cpu_count": psutil.cpu_count(),
                "cpu_count_physical": psutil.cpu_count(logical=False),
                "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
            }
        except (ImportError, Exception) as e:
            logger.debug("System info initialization failed: %s", e)

    def full_check(self):
        cpu_data = self.cpu.sample()
        mem_data = self.memory.sample()
        proc_data = self.process.get_process_info()
        disk_data = self._get_disk_usage()
        self._check_alerts(cpu_data, mem_data, disk_data)
        return {
            "cpu": cpu_data,
            "memory": mem_data,
            "processes": proc_data,
            "disk": disk_data,
            "system_info": self.system_info,
            "timestamp": datetime.now().isoformat(),
        }

    def _get_disk_usage(self):
        if not self._psutil:
            return {}
        disks = {}
        for part in self._psutil.disk_partitions():
            try:
                usage = self._psutil.disk_usage(part.mountpoint)
                disks[part.mountpoint] = {
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "percent": usage.percent,
                }
            except (OSError, PermissionError) as e:
                logger.debug("Disk usage error for %s: %s", part.mountpoint, e)
        self.disk_usage = disks
        return disks

    def _check_alerts(self, cpu_data, mem_data, disk_data):
        now = datetime.now().isoformat()
        if cpu_data["overall"] > CPU_ALERT_THRESHOLD:
            self.alerts.append({"time": now, "type": "cpu_high", "value": cpu_data["overall"], "threshold": CPU_ALERT_THRESHOLD})
        if mem_data["percent"] > MEMORY_ALERT_THRESHOLD:
            self.alerts.append({"time": now, "type": "memory_high", "value": mem_data["percent"], "threshold": MEMORY_ALERT_THRESHOLD})
        for mount, disk in disk_data.items():
            if disk["percent"] > DISK_ALERT_THRESHOLD:
                self.alerts.append({"time": now, "type": "disk_high", "mount": mount, "value": disk["percent"], "threshold": DISK_ALERT_THRESHOLD})

    def log_system(self, category, message, level="info"):
        entry = {"time": datetime.now().isoformat(), "category": category, "message": message, "level": level}
        self.system_log.append(entry)
        return entry

    def get_alerts(self, n=10):
        return list(self.alerts)[-n:]

    def get_health_score(self):
        cpu = self.cpu.get_average()
        mem = self.memory.get_average()
        score = 100
        if cpu > 80:
            score -= (cpu - 80) * 2
        if mem > 80:
            score -= (mem - 80) * 2
        if self.disk_usage:
            for d in self.disk_usage.values():
                if d["percent"] > 85:
                    score -= (d["percent"] - 85) * 3
        return max(0, min(100, score))


class TradingProgressTracker:
    def __init__(self):
        self.session_start = datetime.now()
        self.session_trades = 0
        self.session_wins = 0
        self.session_losses = 0
        self.session_pnl = 0.0
        self.session_peak_equity = 0
        self.session_max_drawdown = 0
        self.daily_targets = {"trades": 20, "profit": 100, "max_loss": -50}
        self.hourly_pnl = deque(maxlen=24)
        self.trade_rate_history = deque(maxlen=60)
        self._last_trade_count = 0
        self._last_rate_check = _time.time()

    def record_trade(self, profit):
        self.session_trades += 1
        self.session_pnl += profit
        if profit >= 0:
            self.session_wins += 1
        else:
            self.session_losses += 1

    def update_equity(self, equity):
        if equity > self.session_peak_equity:
            self.session_peak_equity = equity
        dd = (self.session_peak_equity - equity) / self.session_peak_equity * 100 if self.session_peak_equity > 0 else 0
        if dd > self.session_max_drawdown:
            self.session_max_drawdown = dd

    def get_trade_rate(self):
        now = _time.time()
        elapsed = now - self._last_rate_check
        if elapsed >= 60:
            rate = (self.session_trades - self._last_trade_count) / (elapsed / 60)
            self.trade_rate_history.append({"time": now, "rate": rate})
            self._last_trade_count = self.session_trades
            self._last_rate_check = now
        if self.trade_rate_history:
            return self.trade_rate_history[-1]["rate"]
        return 0

    def get_progress(self):
        elapsed = (datetime.now() - self.session_start).total_seconds() / 3600
        return {
            "session_duration_hours": round(elapsed, 2),
            "session_trades": self.session_trades,
            "session_wins": self.session_wins,
            "session_losses": self.session_losses,
            "session_win_rate": round(self.session_wins / max(self.session_trades, 1) * 100, 1),
            "session_pnl": round(self.session_pnl, 2),
            "session_max_drawdown": round(self.session_max_drawdown, 2),
            "trades_per_hour": round(self.session_trades / max(elapsed, 0.01), 1),
            "target_progress": {
                "trades": f"{self.session_trades}/{self.daily_targets['trades']}",
                "profit": f"${self.session_pnl:.2f}/${self.daily_targets['profit']}",
                "trades_pct": min(100, round(self.session_trades / self.daily_targets['trades'] * 100)),
                "profit_pct": min(100, round(self.session_pnl / max(self.daily_targets['profit'], 1) * 100)),
            },
        }


class ReportEngine:
    def __init__(self, system_monitor, progress_tracker):
        self.sys = system_monitor
        self.progress = progress_tracker
        self.reports = deque(maxlen=20)
        self._last_report_time = 0

    def generate_system_report(self):
        sys_data = self.sys.full_check()
        progress = self.progress.get_progress()
        alerts = self.sys.get_alerts(5)
        report = {
            "type": "system",
            "time": datetime.now().isoformat(),
            "system": {
                "health_score": self.sys.get_health_score(),
                "cpu_avg": self.sys.cpu.get_average(),
                "cpu_peak": self.sys.cpu.get_peak(),
                "cpu_trend": self.sys.cpu.get_trend(),
                "memory_percent": sys_data["memory"]["percent"],
                "memory_used_gb": sys_data["memory"]["used_gb"],
                "memory_trend": self.sys.memory.get_trend(),
            },
            "trading": progress,
            "alerts": alerts,
            "processes": sys_data["processes"],
        }
        self.reports.append(report)
        self._save_report(report)
        return report

    def generate_trading_report(self, journal_stats=None):
        progress = self.progress.get_progress()
        report = {
            "type": "trading",
            "time": datetime.now().isoformat(),
            "session": progress,
            "journal": journal_stats or {},
            "performance": {
                "health_score": self.sys.get_health_score(),
                "cpu_avg": self.sys.cpu.get_average(),
                "memory_percent": self.sys.memory.get_current()["percent"],
            },
        }
        self.reports.append(report)
        return report

    def generate_alert_report(self):
        alerts = self.sys.get_alerts(20)
        return {
            "type": "alerts",
            "time": datetime.now().isoformat(),
            "total_alerts": len(alerts),
            "alerts": alerts,
            "health_score": self.sys.get_health_score(),
        }

    def _save_report(self, report):
        os.makedirs(LOG_DIR, exist_ok=True)
        filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path = os.path.join(LOG_DIR, filename)
        with open(path, "w") as f:
            json.dump(report, f, indent=2, default=str)

    def get_recent_reports(self, n=5):
        return list(self.reports)[-n:]


class DashboardDataProvider:
    def __init__(self, system_monitor, progress_tracker, report_engine):
        self.sys = system_monitor
        self.progress = progress_tracker
        self.reports = report_engine
        self._cache = {}
        self._cache_time = 0
        self._cache_ttl = 2.0

    def get_full_dashboard_data(self, brain_chain=None):
        now = _time.time()
        if self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        sys_data = self.sys.full_check()
        progress = self.progress.get_progress()
        alerts = self.sys.get_alerts(10)
        health = self.sys.get_health_score()

        data = {
            "system": {
                "health_score": round(health, 1),
                "cpu": {
                    "overall": round(sys_data["cpu"]["overall"], 1),
                    "average": round(self.sys.cpu.get_average(), 1),
                    "peak": round(self.sys.cpu.get_peak(), 1),
                    "trend": self.sys.cpu.get_trend(),
                    "core_count": sys_data["cpu"]["core_count"],
                    "per_core": sys_data["cpu"]["per_core"],
                    "freq_current": sys_data["cpu"]["freq_current"],
                },
                "memory": {
                    "percent": round(sys_data["memory"]["percent"], 1),
                    "used_gb": sys_data["memory"]["used_gb"],
                    "total_gb": sys_data["memory"]["total_gb"],
                    "available_gb": sys_data["memory"]["available_gb"],
                    "trend": self.sys.memory.get_trend(),
                    "swap_percent": sys_data["memory"]["swap_percent"],
                },
                "disk": sys_data["disk"],
                "processes": {
                    "mt5_running": sys_data["processes"]["mt5_running"],
                    "mt5_cpu": sys_data["processes"]["mt5_cpu"],
                    "mt5_mem": sys_data["processes"]["mt5_mem"],
                    "python_running": sys_data["processes"]["python_running"],
                    "python_cpu": sys_data["processes"]["python_cpu"],
                    "python_mem": sys_data["processes"]["python_mem"],
                    "top": sys_data["processes"]["top_processes"][:5],
                },
                "info": sys_data["system_info"],
            },
            "progress": progress,
            "alerts": alerts,
            "alert_count": len(alerts),
            "reports": {
                "recent": self.reports.get_recent_reports(3),
                "total": len(self.reports.reports),
            },
        }

        if brain_chain:
            try:
                brain_data = brain_chain.get_dashboard_data()
                data["brains"] = brain_data
            except Exception as e:
                logger.debug("Brain chain dashboard data failed: %s", e)
                data["brains"] = {}

        self._cache = data
        self._cache_time = now
        return data


class BrainV9:
    def __init__(self, brain_v8):
        self.v8 = brain_v8
        self.sys_monitor = SystemMonitor()
        self.progress = TradingProgressTracker()
        self.report_engine = ReportEngine(self.sys_monitor, self.progress)
        self.dashboard = DashboardDataProvider(self.sys_monitor, self.progress, self.report_engine)
        self._last_system_check = 0
        self._last_report_gen = 0
        self._monitoring_active = True

    def analyze(self, symbol, timeframe=mt5.TIMEFRAME_M1, df=None):
        self._system_check()
        decision = self.v8.analyze(symbol, timeframe, df=df)
        self._track_progress(decision)
        return decision

    def _system_check(self):
        now = _time.time()
        if now - self._last_system_check < SYSTEM_CHECK_INTERVAL:
            return
        self._last_system_check = now
        sys_data = self.sys_monitor.full_check()
        health = self.sys_monitor.get_health_score()
        alerts = self.sys_monitor.get_alerts(3)
        if alerts:
            for a in alerts[-2:]:
                self.sys_monitor.log_system("alert", f"{a['type']}: {a.get('value', '?')}", level="warning")
        if health < 50:
            self.sys_monitor.log_system("critical", f"System health critical: {health:.0f}", level="critical")
        if now - self._last_report_gen > REPORT_GENERATION_INTERVAL:
            self.report_engine.generate_system_report()
            self._last_report_gen = now

    def _track_progress(self, decision):
        try:
            acct = mt5.account_info()
            if acct:
                self.progress.update_equity(acct.equity)
        except Exception as e:
            logger.debug("Equity update failed: %s", e)

    def record_trade(self, profit):
        self.progress.record_trade(profit)
        self.v8.activity.log("trade_recorded", f"PnL: ${profit:.2f}", data={"session_pnl": self.progress.session_pnl})

    def manage_positions(self, symbol):
        self.v8.manage_positions(symbol)

    def execute_decision(self, decision, symbol):
        success = self.v8.execute_decision(decision, symbol)
        if success:
            self.sys_monitor.log_system("execution", f"Trade executed: {decision.get('direction_str', '')} {symbol}")
        return success

    def record_trade_open(self, *args, **kwargs):
        return self.v8.record_trade_open(*args, **kwargs)

    def record_trade_close(self, *args, **kwargs):
        return self.v8.record_trade_close(*args, **kwargs)

    def get_dashboard_data(self):
        return self.dashboard.get_full_dashboard_data(self.v8)

    def get_system_report(self):
        return self.report_engine.generate_system_report()

    def get_trading_report(self):
        return self.report_engine.generate_trading_report(self.v8.journal.get_stats())

    def get_alert_report(self):
        return self.report_engine.generate_alert_report()

    def print_status(self):
        self.v8.print_status()
        health = self.sys_monitor.get_health_score()
        cpu = self.sys_monitor.cpu.get_current()
        mem = self.sys_monitor.memory.get_current()
        progress = self.progress.get_progress()
        alerts = self.sys_monitor.get_alerts(5)
        logger.info("  BRAIN V9 — REPORTING & SYSTEM MONITORING")
        logger.info("  System Health: %.0f/100", health)
        logger.info("  CPU: %.1f%% (avg: %.1f%%, peak: %.1f%%, trend: %s)", cpu.get('overall', 0), self.sys_monitor.cpu.get_average(), self.sys_monitor.cpu.get_peak(), self.sys_monitor.cpu.get_trend())
        logger.info("  Cores: %s | Freq: %.0fMHz", cpu.get('core_count', '?'), cpu.get('freq_current', 0))
        logger.info("  Memory: %.1f%% (%.1f/%.1fGB, trend: %s)", mem.get('percent', 0), mem.get('used_gb', 0), mem.get('total_gb', 0), self.sys_monitor.memory.get_trend())
        logger.info("  Swap: %.1f%%", mem.get('swap_percent', 0))
        proc = self.sys_monitor.process.get_process_info()
        logger.info("  MT5: %s (CPU: %.1f%%, Mem: %.1f%%)", 'Running' if proc.get('mt5_running') else 'STOPPED', proc.get('mt5_cpu', 0), proc.get('mt5_mem', 0))
        logger.info("  Python: %s (CPU: %.1f%%, Mem: %.1f%%)", 'Running' if proc.get('python_running') else 'STOPPED', proc.get('python_cpu', 0), proc.get('python_mem', 0))
        logger.info("")
        logger.info("  Session Progress:")
        logger.info("    Duration: %.1fh | Trades: %d | WR: %.0f%%", progress['session_duration_hours'], progress['session_trades'], progress['session_win_rate'])
        logger.info("    PnL: $%.2f | Max DD: %.1f%%", progress['session_pnl'], progress['session_max_drawdown'])
        logger.info("    Rate: %.1f trades/hour", progress['trades_per_hour'])
        tp = progress.get("target_progress", {})
        logger.info("    Targets: Trades %s (%d%%) | Profit %s (%d%%)", tp.get('trades', '?'), tp.get('trades_pct', 0), tp.get('profit', '?'), tp.get('profit_pct', 0))
        if alerts:
            logger.info("")
            logger.info("  Recent Alerts:")
            for a in alerts[-3:]:
                logger.info("    [%s] %s (threshold: %s)", a['type'], a.get('value', '?'), a.get('threshold', '?'))
        disk = self.sys_monitor.disk_usage
        if disk:
            logger.info("")
            logger.info("  Disk:")
            for mount, d in list(disk.items())[:3]:
                logger.info("    %s: %.0f%% (%.1fGB free)", mount, d['percent'], d['free_gb'])
