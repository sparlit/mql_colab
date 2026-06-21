'''Flask application configuration with SQLAlchemy support.

Provides separate settings for development and production environments.
Environment variables are loaded via python-dotenv for secret values.
'''
import os
# Export magic number constants for backward compatibility
from magic_registry import (  # noqa: F401
    MAGIC_NUMBER,
    MAGIC_SCALPING,
    MAGIC_DAY_TRADING,
    MAGIC_SWING,
    MAGIC_POSITION,
    MAGIC_TECHNICAL,
    MAGIC_FUNDAMENTAL,
    MAGIC_SENTIMENT,
    MAGIC_TREND,
    MAGIC_COUNTER_TREND,
    MAGIC_BREAKOUT,
    MAGIC_RANGE,
    MAGIC_TMC,
    MAGIC_BRAIN_V1,
    MAGIC_BRAIN_V2,
    MAGIC_BRAIN_V3,
    MAGIC_BRAIN_V4,
    MAGIC_BRAIN_V5,
    MAGIC_BRAIN_V6,
    MAGIC_BRAIN_V7,
    MAGIC_BRAIN_V8,
    MAGIC_BRAIN_V9,
)
from pathlib import Path
from dotenv import load_dotenv
# Re-export magic utilities for legacy imports
from magic_database import get_magic_number, magic_belongs_to_brain, is_system_magic  # noqa: F401

# Load .env file located in the project root (same directory as this config file)
BASE_DIR = Path(__file__).resolve().parent

# Core constants for Zero‑Tolerance compliance
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
MAX_SPREAD_POINTS = 5
MAX_SYMBOLS = 100
SCAN_SYMBOLS = []  # list of symbols to scan (populated at runtime)
# Worker pool sizes – tuned to available CPU cores
# Added missing constants for compatibility with existing modules
# MT5_TIMEFRAMES placeholder (mapping timeframe names to seconds)
MT5_TIMEFRAMES = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}
# Correlation groups placeholder – can be populated at runtime
CORRELATION_GROUPS = {}
# Minimum confidence threshold for trading decisions
MIN_CONFIDENCE_TO_TRADE = 0.5
# Notification service tokens (optional, can be None)
TELEGRAM_BOT_TOKEN = None
TELEGRAM_CHAT_ID = None
DISCORD_WEBHOOK_URL = None
# System resource descriptors
SYSTEM_TIER = os.getenv("SYSTEM_TIER", "standard")
SYSTEM_CPU_COUNT = os.cpu_count() or 1
SYSTEM_MEMORY_GB = int(os.getenv("SYSTEM_MEMORY_GB", "4"))
CPU_COUNT = os.cpu_count() or 1
ANALYSIS_WORKERS = max(1, CPU_COUNT)
SCANNER_WORKERS = max(1, CPU_COUNT // 2)
CORRELATION_WORKERS = max(1, CPU_COUNT // 2)
PROCESS_WORKERS = max(1, CPU_COUNT // 2)
IO_WORKERS = max(1, CPU_COUNT // 2)
load_dotenv(BASE_DIR / ".env")

class Config:
    """Base configuration with defaults shared across all environments."""
    # General Flask settings
    DEBUG = False
    TESTING = False
    SECRET_KEY = os.getenv("SECRET_KEY", "you-should-set-a-secret-key")

    # SQLAlchemy settings
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Default database URI – overridden in subclasses
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///" + str(BASE_DIR / "app.db"))

    # Example of other common settings
    LOG_TO_STDOUT = os.getenv("LOG_TO_STDOUT", "true").lower() in ["true", "1", "yes"]

class DevelopmentConfig(Config):
    """Configuration for local development."""
    DEBUG = True
    # Use a local SQLite database by default; can be overridden via env var
    # Prefer DATABASE_URL (e.g., Docker‑linked PostgreSQL); fall back to DEV_DATABASE_URL or local SQLite
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        os.getenv(
            "DEV_DATABASE_URL",
            "sqlite:///" + str(BASE_DIR / "dev.db")
        )
    )
    # Enable more verbose logging if desired
    LOG_LEVEL = "DEBUG"

class ProductionConfig(Config):
    """Configuration for production deployments."""
    # In production we expect DEBUG to be off (already False in base)
    # Use a robust database URL (e.g., PostgreSQL) supplied via environment variable
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql://user:password@localhost/production_db"
    )
    # Example of forcing HTTPS and secure cookies
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Helper dictionary for easy lookup, e.g., app.config.from_object(config[env])
config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
