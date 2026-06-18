"""Failover Watchdog — monitors daemon threads and restarts on failure."""
import threading
import time
import logging

logger = logging.getLogger(__name__)


class FailoverWatchdog:
    """Monitors daemon threads and restarts them if they die."""

    def __init__(self, alert_manager=None):
        self._threads = {}
        self._lock = threading.Lock()
        self._running = True
        self._alert = alert_manager
        self._thread = None

    def register(self, name, thread, restart_fn=None):
        """Register a thread for monitoring.

        Args:
            name: Human-readable name for alerts
            thread: The threading.Thread instance
            restart_fn: Callable that creates and starts a replacement thread.
                       If None, the thread is only logged as dead (no restart).
        """
        with self._lock:
            self._threads[name] = {
                "thread": thread,
                "restart_fn": restart_fn,
                "alive": True,
            }

    def start(self):
        """Start the watchdog monitoring loop in a background thread."""
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="Watchdog")
        self._thread.start()
        logger.info("Failover Watchdog started")

    def stop(self):
        self._running = False

    def _monitor_loop(self):
        while self._running:
            time.sleep(15)
            with self._lock:
                for name, info in list(self._threads.items()):
                    thread = info["thread"]
                    if not thread.is_alive():
                        if info["alive"]:
                            # Thread just died
                            logger.critical("Thread '%s' has died", name)
                            if self._alert:
                                self._alert.alert_thread_crash(name, "Thread exited unexpectedly")
                            info["alive"] = False

                            # Attempt restart
                            if info["restart_fn"]:
                                try:
                                    new_thread = info["restart_fn"]()
                                    info["thread"] = new_thread
                                    info["alive"] = True
                                    logger.info("Thread '%s' restarted successfully", name)
                                except Exception as e:
                                    logger.error("Failed to restart thread '%s': %s", name, e)
                    else:
                        info["alive"] = True
