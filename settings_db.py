"""
Settings Database Manager
Reads/writes configuration from JSON database file.
Both MQL5 EA and Python system read from the same file.
No recompilation needed - just edit the JSON file.
"""
import json
import os
import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "brain_data", "dashboard_settings.json")

# Default settings
DEFAULTS = {
    "version": "1.0",
    "last_updated": "",
    "general": {
        "refresh_ms": 1000,
        "auto_tf": True,
        "multi_chart": False,
        "max_charts": 4,
        "max_positions": 3,
        "max_daily_trades": 20
    },
    "risk": {
        "max_risk_per_trade": 1.0,
        "max_drawdown": 5.0,
        "max_spread_points": 50,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 2.5,
        "min_rr_ratio": 1.5,
        "break_even_pips": 20,
        "trail_start_pips": 30,
        "trail_step_pips": 10
    },
    "timeframes": {
        "scalping": {"primary": "M1", "confirm": "M5", "execute": "M1"},
        "day_trading": {"primary": "M5", "confirm": "M15", "execute": "M5"},
        "swing": {"primary": "H4", "confirm": "D1", "execute": "H4"},
        "position": {"primary": "D1", "confirm": "W1", "execute": "D1"},
        "technical": {"primary": "H1", "confirm": "H4", "execute": "H1"},
        "trend": {"primary": "H1", "confirm": "H4", "execute": "H1"},
        "counter_trend": {"primary": "M30", "confirm": "H1", "execute": "M30"},
        "breakout": {"primary": "H1", "confirm": "H4", "execute": "H1"},
        "momentum": {"primary": "H1", "confirm": "H4", "execute": "H1"},
        "mean_reversion": {"primary": "M30", "confirm": "H1", "execute": "M30"},
        "volatility": {"primary": "M30", "confirm": "H1", "execute": "M30"},
        "range": {"primary": "M30", "confirm": "H1", "execute": "M30"},
        "fundamental": {"primary": "D1", "confirm": "W1", "execute": "D1"},
        "sentiment": {"primary": "H4", "confirm": "D1", "execute": "H4"}
    },
    "sessions": {
        "asian": {"start": 0, "end": 7, "color": "green"},
        "london": {"start": 7, "end": 12, "color": "blue"},
        "overlap": {"start": 12, "end": 16, "color": "purple"},
        "new_york": {"start": 16, "end": 21, "color": "green"},
        "dead": {"start": 21, "end": 24, "color": "red"}
    },
    "display": {
        "show_session": True,
        "show_clock": True,
        "show_mtf_timers": True,
        "show_indicators": True,
        "show_positions": True,
        "show_strategy": True,
        "show_macro": True,
        "show_system": True,
        "font_size_header": 12,
        "font_size_regular": 9,
        "font_size_small": 8
    },
    "colors": {
        "background": "#0A0E17",
        "header": "#00B4FF",
        "green": "#00FF88",
        "red": "#FF4444",
        "yellow": "#FFBF24",
        "text": "#C8C8C8",
        "dim": "#646464",
        "bar_bg": "#1E1E28",
        "bar_fill": "#00B4FF",
        "card_bg": "#0F121C",
        "card_border": "#283C5A"
    }
}


class SettingsDB:
    """Thread-safe JSON settings database."""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self._lock = threading.Lock()
        self._cache = None
        self._load()

    def _load(self):
        """Load settings from JSON file."""
        try:
            if os.path.exists(self.db_path):
                with open(self.db_path, "r") as f:
                    self._cache = json.load(f)
                logger.info("Settings loaded from %s", self.db_path)
            else:
                self._cache = DEFAULTS.copy()
                self._save()
                logger.info("Settings created at %s", self.db_path)
        except Exception as e:
            logger.warning("Failed to load settings: %s, using defaults", e)
            self._cache = DEFAULTS.copy()

    def _save(self):
        """Save settings to JSON file."""
        try:
            self._cache["last_updated"] = datetime.now().isoformat()
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            with open(self.db_path, "w") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.error("Failed to save settings: %s", e)

    def get(self, *keys, default=None):
        """Get a nested value by keys. e.g. get('risk', 'sl_atr_mult')"""
        with self._lock:
            val = self._cache
            for key in keys:
                if isinstance(val, dict) and key in val:
                    val = val[key]
                else:
                    return default
            return val

    def set_value(self, *keys_value):
        """Set a nested value. e.g. set('risk', 'sl_atr_mult', 2.0)"""
        with self._lock:
            keys = keys_value[:-1]
            value = keys_value[-1]
            d = self._cache
            for key in keys[:-1]:
                if key not in d:
                    d[key] = {}
                d = d[key]
            d[keys[-1]] = value
            self._save()

    def get_section(self, section):
        """Get an entire section."""
        with self._lock:
            return self._cache.get(section, {}).copy()

    def reload(self):
        """Force reload from file."""
        with self._lock:
            self._load()

    def get_all(self):
        """Get all settings."""
        with self._lock:
            return self._cache.copy()


# Singleton instance
_settings = None
_settings_lock = threading.Lock()


def get_settings():
    global _settings
    if _settings is None:
        with _settings_lock:
            if _settings is None:
                _settings = SettingsDB()
    return _settings
