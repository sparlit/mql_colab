import requests
import time as _time
import threading
import logging
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)

# ==========================================
# ALERTS - Telegram / Discord notifications
# ==========================================

ALERT_COOLDOWN = 60


class AlertManager:
    def __init__(self):
        self.last_alert_time = {}
        self._lock = threading.Lock()

    def _check_cooldown(self, key):
        now = _time.time()
        last = self.last_alert_time.get(key, 0)
        if now - last < ALERT_COOLDOWN:
            return False
        self.last_alert_time[key] = now
        return True

    def _send_both(self, message, key):
        self.send_telegram(message, key=f"tg_{key}")
        self.send_discord(message, key=f"dc_{key}")

    def alert_trade_open(self, symbol, direction, lot, price, confidence):
        msg = f"🟢 TRADE OPEN: {symbol} {'BUY' if direction == 1 else 'SELL'} {lot} @ {price:.5f} (conf={confidence:.2f})"
        self._send_both(msg, "trade_open")

    def alert_trade_close(self, symbol, profit, price):
        emoji = "💰" if profit >= 0 else "🔴"
        msg = f"{emoji} TRADE CLOSE: {symbol} P&L={profit:.2f} @ {price:.5f}"
        self._send_both(msg, "trade_close")

    def alert_circuit_breaker(self, reason):
        msg = f"⚠️ CIRCUIT BREAKER: {reason}"
        self._send_both(msg, "circuit_breaker")

    def alert_black_swan(self, symbol, details):
        msg = f"🚨 BLACK SWAN: {symbol} — {details}"
        self._send_both(msg, "black_swan")

    def alert_mt5_disconnect(self, details=""):
        msg = f"🔌 MT5 DISCONNECTED {details}"
        self._send_both(msg, "mt5_disconnect")

    def alert_daily_loss(self, loss_pct, equity):
        msg = f"📉 DAILY LOSS LIMIT: {loss_pct:.1f}% equity={equity:.2f}"
        self._send_both(msg, "daily_loss")

    def alert_margin_warning(self, margin_level):
        msg = f"⚠️ MARGIN WARNING: level={margin_level:.0f}%"
        self._send_both(msg, "margin_warning")

    def alert_thread_crash(self, thread_name, error):
        msg = f"💀 THREAD CRASH: {thread_name} — {error}"
        self._send_both(msg, "thread_crash")

    def alert_model_timeout(self, symbol, elapsed_ms):
        msg = f"⏱️ MODEL TIMEOUT: {symbol} {elapsed_ms:.0f}ms"
        self._send_both(msg, "model_timeout")

    def send_telegram(self, message, key="telegram"):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return False
        if not self._check_cooldown(key):
            return False
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
            resp = requests.post(url, json=payload, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.debug("Telegram send failed: %s", e)
            return False

    def send_discord(self, message, key="discord"):
        if not DISCORD_WEBHOOK_URL:
            return False
        if not self._check_cooldown(key):
            return False
        try:
            payload = {"content": message}
            resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.debug("Discord send failed: %s", e)
            return False


_alerts = None
_lock = threading.Lock()


def get_alert_manager():
    global _alerts
    if _alerts is None:
        with _lock:
            if _alerts is None:
                _alerts = AlertManager()
    return _alerts
