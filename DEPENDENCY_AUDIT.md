# Dependency Audit — AFX AutoTrader v2
# Document all external imports with version pins and justification
# Updated: 2026-06-21

---

## Core Dependencies (Required)

| Package | Version Pin | Justification | Security |
|---------|-------------|---------------|----------|
| `MetaTrader5` | `>=5.0.45` | Official MT5 Python SDK. Required for broker connectivity. Pinned to avoid breaking API changes from minor versions. | Review: Verify SDK source (official MetaQuotes) |
| `pandas` | `>=2.0.0` | DataFrame operations for indicators, feature engineering, backtest data. Pinned for consistent column API across versions. | PyPI, widely used, stable |
| `numpy` | `>=1.24.0` | Array operations for all numerical computation. Required by pandas, numba. Pinned for SIMD compatibility. | PyPI, stable |
| `flask` | `>=3.0.0` | Web dashboard (web_dashboard.py). Flask-SocketIO for WebSocket. Pinned to 3.x for async support. | PyPI, widely used, stable |
| `flask-sqlalchemy` | `>=3.0.0` | ORM for database operations. Required for settings_db.py and magic_database.py. | PyPI, stable |
| `Flask-Migrate` | `>=4.0.0` | Database migrations. Only used during Docker startup (entrypoint.sh). | PyPI, stable |
| `requests` | `>=2.31.0` | HTTP client for market data APIs, alternative data. Pinned for security (2.31.0 fixed CVE-2023-32681). | PyPI, security-critical |
| `psutil` | `>=5.9.0` | System resource monitoring (CPU, memory). Used in infrastructure.py for resource tracking. | PyPI, stable |
| `psycopg2-binary` | `>=2.9.0` | PostgreSQL adapter. Binary wheel for easier installation. Used via DATABASE_URL env var. | PyPI, stable |

## ML Dependencies

| Package | Version Pin | Justification | Security |
|---------|-------------|---------------|----------|
| `lightgbm` | `>=4.0.0` | Gradient boosting for ML training pipeline (ml_training_pipeline.py). Falls back to sklearn if unavailable. | PyPI, widely used |
| `scipy` | `>=1.11.0` | Optional — used in quant_models.py and gpu_engine.py for advanced math. Only installed if explicitly uncommented. | PyPI, stable |

## Performance Dependencies

| Package | Version Pin | Justification | Security |
|---------|-------------|---------------|----------|
| `orjson` | `>=3.9.0` | 5-10x faster JSON serialization than stdlib. Used in logging_config.py for structured JSON output. | PyPI, stable |
| `numba` | `>=0.59.0` | JIT compilation for hot loops (indicators, pattern recognition). Falls back to pandas/numpy if unavailable. | PyPI, stable |

## Optional Dependencies (Not Installed by Default)

| Package | Version Pin | Justification | Status |
|---------|-------------|---------------|--------|
| `redis` | `>=5.0.0` | L3 cache (cache_layer.py) and cluster manager (infrastructure.py). Commented out — not installed by default. | PyPI |
| `kafka-python` | `>=2.0.0` | Kafka producer for infrastructure.py. Commented out — not installed by default. | PyPI, unmaintained (prefer confluent-kafka-python) |
| `cupy-cuda12x` | `>=12.0.0` | GPU acceleration for gpu_engine.py. Requires NVIDIA CUDA. Commented out — only for GPU build. | PyPI |

---

## Internal Imports (No Version Pins Needed)

These are local modules — no external version pins required:

```
strategy_base.py       → strategy framework (local)
strategy_swing.py      → strategy implementation (local)
strategy_day.py       → strategy implementation (local)
strategy_carry.py      → strategy implementation (local)
strategy_scalp.py      → strategy implementation (local)
strategy_router.py     → strategy routing (local)
parallel_executor.py   → thread/process pool management (local)
brain_engine.py        → unified brain (local)
risk_engine.py         → risk management (local)
position_manager.py    → position tracking (local)
decision_engine.py     → decision orchestration (local)
trade_executor.py      → order execution (local)
backtest_engine.py     → backtesting (local)
ml_training_pipeline.py → ML training (local)
mt5_mcp.py             → MT5 sync shim (local)
async_mt5.py            → MT5 async wrappers (local)
indicators.py          → technical indicators (local)
pattern_recognition.py → pattern recognition (local)
ml_features.py         → feature engineering (local)
```

---

## Security Notes

1. **MetaTrader5 SDK** — Source is official MetaQuotes. Verify package integrity on PyPI.
2. **psycopg2-binary** — Binary wheel. For production, prefer psycopg2 (compiled) for performance.
3. **requests** — Always pin to latest security release. Current pin (>=2.31.0) addresses known CVEs.
4. **Flask** — Ensure debug=False in production (web_dashboard.py should set debug=False).
5. **No secrets in requirements.txt** — All credentials via environment variables (DATABASE_URL, etc.).

---

## Known Vulnerabilities (Checked)

| Package | Last Audited | Notes |
|---------|-------------|-------|
| requests | 2026-06-21 | Pin >=2.31.0 resolves CVE-2023-32681 |
| flask | 2026-06-21 | 3.x series is current. debug mode only in dev. |
| pandas | 2026-06-21 | Stable, widely used |
| numpy | 2026-06-21 | Stable, widely used |
| MetaTrader5 | 2026-06-21 | Official SDK, local network only |
| lightgbm | 2026-06-21 | Widely used in production ML |
| orjson | 2026-06-21 | Rust-based, memory-safe |
| numba | 2026-06-21 | LLVM-based, memory-safe |

---

*Update this document when adding or removing dependencies.*