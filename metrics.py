import time as _time
import threading
import logging

logger = logging.getLogger(__name__)

# ==========================================
# PROMETHEUS METRICS — Export for Grafana
# ==========================================


class MetricsCollector:
    def __init__(self):
        self.counters = {}
        self.gauges = {}
        self.histograms = {}
        self._lock = threading.Lock()

    def inc(self, name, value=1, labels=None):
        with self._lock:
            key = self._make_key(name, labels)
            self.counters[key] = self.counters.get(key, 0) + value

    def set_value(self, name, value, labels=None):
        with self._lock:
            key = self._make_key(name, labels)
            self.gauges[key] = value

    def observe(self, name, value, labels=None):
        with self._lock:
            key = self._make_key(name, labels)
            if key not in self.histograms:
                self.histograms[key] = []
            self.histograms[key].append(value)
            if len(self.histograms[key]) > 1000:
                self.histograms[key] = self.histograms[key][-500:]

    def _make_key(self, name, labels):
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
            return f'{name}{{{label_str}}}'
        return name

    def get_prometheus_format(self):
        lines = []
        with self._lock:
            for key, val in self.counters.items():
                lines.append(f"# TYPE {key.split('{')[0]} counter")
                lines.append(f"{key} {val}")
            for key, val in self.gauges.items():
                lines.append(f"# TYPE {key.split('{')[0]} gauge")
                lines.append(f"{key} {val}")
            for key, vals in self.histograms.items():
                name = key.split('{')[0]
                lines.append(f"# TYPE {name} histogram")
                lines.append(f'{key}_count {len(vals)}')
                lines.append(f'{key}_sum {sum(vals):.4f}')
                lines.append(f'{key}_avg {sum(vals)/max(len(vals),1):.4f}')
        return "\n".join(lines)

    def get_json(self):
        with self._lock:
            return {
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
                "histograms": {k: {"count": len(v), "sum": sum(v), "avg": sum(v)/max(len(v),1)} for k, v in self.histograms.items()},
            }


class PerformanceProfiler:
    """Performance profiler for tracking timing metrics."""
    def __init__(self):
        self.timings = {}
        self.call_counts = {}
        self.total_time = 0
        self._lock = threading.Lock()

    def start(self, label):
        self.timings[label] = _time.time()

    def end(self, label):
        if label in self.timings:
            elapsed = (_time.time() - self.timings.pop(label)) * 1000
            with self._lock:
                if label not in self.call_counts:
                    self.call_counts[label] = {"total_ms": 0, "count": 0, "max_ms": 0}
                self.call_counts[label]["total_ms"] += elapsed
                self.call_counts[label]["count"] += 1
                self.call_counts[label]["max_ms"] = max(self.call_counts[label]["max_ms"], elapsed)
                self.total_time += elapsed
            return elapsed
        return 0

    def record(self, label, ms):
        _metrics.observe("duration_ms", ms, {"component": label})

    def get_report(self):
        with self._lock:
            report = {}
            for label, data in self.call_counts.items():
                avg = data["total_ms"] / data["count"] if data["count"] > 0 else 0
                report[label] = {
                    "avg_ms": round(avg, 2),
                    "max_ms": round(data["max_ms"], 2),
                    "calls": data["count"],
                    "total_ms": round(data["total_ms"], 2),
                }
            return report


_metrics = MetricsCollector()
_profiler = PerformanceProfiler()


def get_metrics():
    return _metrics

