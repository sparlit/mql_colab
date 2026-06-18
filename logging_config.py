"""
Centralized logging configuration for MT5 Scalper Pro.
Import and call setup_logging() at application start.
"""
import logging
import logging.handlers
import json
import sys
import os
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production observability."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_data"):
            log_entry["extra"] = record.extra_data
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(level=logging.INFO, log_file='scalper.log', max_bytes=10*1024*1024, backup_count=5,
                  json_format=False):
    """Configure structured logging for the entire application.

    Args:
        level: Logging level
        log_file: Log filename
        max_bytes: Max size per log file before rotation
        backup_count: Number of backup files to keep
        json_format: If True, use JSON format for file logs
    """
    log_dir = os.path.join(os.path.dirname(__file__), 'brain_data', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_file)

    logging.root.handlers.clear()

    # Console handler — always human-readable
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    # File handler — JSON or plain text
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, mode='a', maxBytes=max_bytes,
        backupCount=backup_count, encoding='utf-8'
    )
    if json_format:
        file_handler.setFormatter(JSONFormatter())
    else:
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))

    logging.basicConfig(
        level=level,
        handlers=[console_handler, file_handler]
    )

    # Error handler — separate file for errors and above
    error_path = os.path.join(log_dir, 'errors.log')
    error_handler = logging.handlers.RotatingFileHandler(
        error_path, mode='a', maxBytes=max_bytes,
        backupCount=backup_count, encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    if json_format:
        error_handler.setFormatter(JSONFormatter())
    else:
        error_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
    logging.root.addHandler(error_handler)

    # Suppress noisy third-party loggers
    for name in ['urllib3', 'requests', 'werkzeug']:
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.info("Logging initialized - level=%s, file=%s, json=%s", level, log_path, json_format)
