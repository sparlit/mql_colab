# MODULE-PURPOSE MATRIX — AFX AutoTrader v2
# Maps every .py file to responsibility, public API, magic numbers
# Updated: 2026-06-21

---

## STRATEGY MAGIC NUMBERS

| Strategy | Magic Number | File | Version |
|----------|-------------|------|---------|
| SWING | 100001 | `strategy_swing.py` | v1 |
| DAY | 200002 | `strategy_day.py` | v1 |
| CARRY | 300003 | `strategy_carry.py` | v1 |
| SCALP | 400004 | `strategy_scalp.py` | v1 |
| BASE | 0 | `strategy_base.py` | N/A |

---

## EXISTING MODULES (to be consolidated/refactored)

### Core Engine (HIGH PRIORITY — consolidate into new architecture)

| File | Purpose | Public API | Current Status | Consolidation Target |
|------|---------|------------|----------------|---------------------|
| `brain_v1.py` | Main brain, analyzes market, generates signals | `Brain.analyze()`, `Brain.record_trade_result()`, `BrainStats` | EXISTING | → `brain_engine.py` |
| `brain_v2.py` | Pattern-based brain variant | `BrainV2.analyze()` | EXISTING (duplicate) | → `brain_engine.py` |
| `brain_v3.py` | ML-enhanced brain variant | `BrainV3.analyze()` | EXISTING (duplicate) | → `brain_engine.py` |
| `brain_v4.py` | Scalping brain variant | `BrainV4.analyze()` | EXISTING (duplicate) | → `brain_engine.py` |
| `brain_v5.py` | Parameter optimizer brain | `BrainV5.analyze()` | EXISTING (duplicate) | → `brain_engine.py` |
| `brain_v6.py` | Validation brain | `BrainV6.analyze()` | EXISTING (duplicate) | → `brain_engine.py` |
| `brain_v7.py` | Carry-aware brain | `BrainV7.analyze()` | EXISTING (duplicate) | → `brain_engine.py` |
| `brain_v8.py` | Institutional brain | `BrainV8.analyze()` | EXISTING (duplicate) | → `brain_engine.py` |
| `brain_v9.py` | Day trading brain | `BrainV9.analyze()` | EXISTING (duplicate) | → `brain_engine.py` |
| `brain_v10.py` | Advanced ML brain | `BrainV10.analyze()` | EXISTING (duplicate) | → `brain_engine.py` |
| `brain_v11.py` | Full feature brain | `BrainV11.analyze()` | EXISTING (duplicate) | → `brain_engine.py` |
| `trading_engine.py` | Trade orchestration | `TradingEngine.analyze()`, `TradingEngine.submit_order()` | EXISTING | → `trade_executor.py` |
| `parallel_executor.py` | Task execution engine | `ParallelExecutor.submit()`, `ParallelExecutor.map()` | EXISTING | → (keep, upgrade) |
| `magic_registry.py` | Magic number registry | `register_magic()`, `get_magic()` | EXISTING | → (keep, expand) |

### Risk & Portfolio

| File | Purpose | Public API | Consolidation Target |
|------|---------|------------|---------------------|
| `portfolio_risk.py` | Portfolio-level risk management | `PortfolioManager`, `VaRCalculator`, `DrawdownCircuit` | → `risk_engine.py` |
| `risk_advanced.py` | Advanced risk (correlation, tail hedge) | `AdvancedRiskManager`, `BlackSwanDetector` | → `risk_engine.py` |
| `sltp_engine.py` | Stop-loss / take-profit calculation | `SLTPEngine.calculate_sl()`, `SLTPEngine.calculate_tp()` | → `risk_engine.py` |

### Data & Features

| File | Purpose | Public API | Consolidation Target |
|------|---------|------------|---------------------|
| `indicators.py` | Technical indicator calculations | `calculate_rsi()`, `calculate_ema()`, `calculate_bollinger()` | → (keep, thread-safe) |
| `ml_features.py` | ML feature engineering | `FeatureEngine.extract()`, `FeatureEngine.transform()` | → (keep, parallel) |
| `backtest_data.py` | Historical data management | `BacktestData.load()`, `BacktestData.get_rates()` | → (keep) |
| `magic_database.py` | Magic-based trade database | `MagicDatabase.query()`, `MagicDatabase.insert()` | → (keep) |

### Execution

| File | Purpose | Public API | Consolidation Target |
|------|---------|------------|---------------------|
| `execution_compliance.py` | Smart order routing, dark pool | `SmartOrderRouter`, `DarkPoolDetector`, `PFOFAnalyzer` | → `trade_executor.py` |
| `execution_optimization.py` | TWAP, iceberg, latency optimization | `TWAPExecutor`, `IcebergDetector`, `AdvancedExecutor` | → `trade_executor.py` |
| `order_flow.py` | Order flow analysis | `OrderFlowAnalyzer`, `LiquidityMap` | → (keep, parallel) |

### Dashboards

| File | Purpose | Public API | Consolidation Target |
|------|---------|------------|---------------------|
| `dashboard.py` | Main dashboard | `Dashboard.run()`, `Dashboard.update()` | → split into 3 below |
| `native_proDashboard.py` | NEW: Native desktop dashboard | `ProDashboard.run()` | → NEW (T111) |
| `web_dashboard.py` | NEW: Web dashboard | `WebDashboard.run()` | → NEW (T112) |
| `mt5_dashboard.py` | NEW: MT5 terminal dashboard | `MT5Dashboard.run()` | → NEW (T113) |

### MT5 Integration

| File | Purpose | Public API | Consolidation Target |
|------|---------|------------|---------------------|
| `mt5_mcp.py` | Sync shim for async MT5 | `mt5.initialize()`, `mt5.order_send()`, `mt5.positions_get()` | → (keep, verify) |
| `async_mt5.py` | Async MT5 wrappers | `async_initialize()`, `async_order_send()` | → (keep, audit) |
| `mt5_exporter.py` | MT5 data exporter | `MT5DataExporter.export()` | → (keep) |
| `mt5_AFxAutoTrader_v1.py` | Main MT5 EA | `OnTimer()`, `OnTick()` | → (keep, refactor) |

### Analytics

| File | Purpose | Public API | Consolidation Target |
|------|---------|------------|---------------------|
| `data_analytics.py` | Real-time P&L, trade replay | `TickDatabase`, `RealTimePnL`, `TradeReplay` | → (keep, expand) |
| `institutional_analytics.py` | Order book, volume profile | `VolumeProfile`, `DeltaDivergence`, `FootprintChart` | → (keep) |
| `pattern_recognition.py` | Chart pattern recognition | `PatternRecognizer.identify()` | → (keep, parallel) |
| `quant_models.py` | Quantitative models | `QuantModels.calculate()` | → (keep) |
| `microstructure.py` | Market microstructure | `Microstructure.analyze()` | → (keep) |
| `market_intelligence.py` | Market intelligence | `MarketIntel.analyze()` | → (keep) |

### Training

| File | Purpose | Public API | Consolidation Target |
|------|---------|------------|---------------------|
| `batch_train.py` | Batch ML training | `BatchTrainer.train()` | → `ml_training_pipeline.py` |
| `train_ml.py` | ML model training | `MLTrainer.train()` | → `ml_training_pipeline.py` |
| `ml_model.py` | ML model inference | `MLModel.predict()` | → (keep, ProcessPool) |
| `ml_enhancements.py` | ML enhancements | `MLEnhancements.enhance()` | → (keep) |

### Configuration & Utilities

| File | Purpose | Public API | Notes |
|------|---------|------------|-------|
| `config.py` | Configuration management | `Config.load()`, `Config.get()` | Keep |
| `cache_layer.py` | Caching layer | `CacheLayer.get()`, `CacheLayer.set()` | Keep |
| `infrastructure.py` | Infrastructure utilities | `setup_logging()`, `setup_metrics()` | Keep |
| `providers.py` | Data providers | `Provider.fetch()` | Keep |
| `alerts.py` | Alert system | `AlertManager.send()` | Keep |
| `validation_pipeline.py` | Data validation | `Validator.validate()` | Keep |
| `walk_forward.py` | Walk-forward analysis | `WalkForward.run()` | Keep |

---

## NEW MODULES TO CREATE

| File | Purpose | Public API | Task |
|------|---------|------------|------|
| `strategy_base.py` | Abstract base for all strategies | `BaseStrategy`, `TradeSignal`, `PositionSize` | T37 |
| `strategy_swing.py` | Swing trading strategy | `SwingStrategy(MAGIC=100001)` | T38 |
| `strategy_day.py` | Day trading strategy | `DayStrategy(MAGIC=200002)` | T39 |
| `strategy_carry.py` | Carry trading strategy | `CarryStrategy(MAGIC=300003)` | T40 |
| `strategy_scalp.py` | Scalping strategy | `ScalpStrategy(MAGIC=400004)` | T41 |
| `strategy_router.py` | Routes to active strategy | `StrategyRouter.set_mode()`, `analyze()` | T42 |
| `brain_engine.py` | Unified brain (consolidated v1-v11) | `BrainEngine.analyze()`, `BrainEngine.train()` | T49 |
| `risk_engine.py` | Unified risk management | `RiskEngine.calculate_position()`, `validate_trade()` | T50 |
| `position_manager.py` | Position sizing & tracking | `PositionManager.open()`, `close()`, `get_exposure()` | T51 |
| `decision_engine.py` | Decision orchestration | `DecisionEngine.evaluate()`, `execute()` | T52 |
| `trade_executor.py` | Order execution with circuit breaker | `TradeExecutor.submit()`, `cancel()` | T53 |
| `backtest_engine.py` | Multi-strategy backtesting | `BacktestEngine.run()` | T54 |
| `ml_training_pipeline.py` | Multi-strategy ML training | `MLTrainingPipeline.train()`, `optimize()` | T55 |

---

## DEPRECATION PLAN

The following files will be deprecated and removed after consolidation:

| File | Deprecate After | Reason |
|------|----------------|--------|
| `brain_v2.py` | T49 complete | Duplicate of brain_v1 |
| `brain_v3.py` | T49 complete | Duplicate of brain_v1 |
| `brain_v4.py` | T49 complete | Duplicate of brain_v1 |
| `brain_v5.py` | T49 complete | Duplicate of brain_v1 |
| `brain_v6.py` | T49 complete | Duplicate of brain_v1 |
| `brain_v7.py` | T49 complete | Duplicate of brain_v1 |
| `brain_v8.py` | T49 complete | Duplicate of brain_v1 |
| `brain_v9.py` | T49 complete | Duplicate of brain_v1 |
| `brain_v10.py` | T49 complete | Duplicate of brain_v1 |
| `brain_v11.py` | T49 complete | Duplicate of brain_v1 |
| `sltp_engine.py` | T50 complete | Merged into risk_engine.py |
| `risk_advanced.py` | T50 complete | Merged into risk_engine.py |
| `dashboard.py` | T44/T45/T46 complete | Split into 3 specialized dashboards |

---

## MAGIC NUMBER REGISTRY

```python
MAGIC_REGISTRY = {
    # Strategy magics (unique, 6 digits starting 1xx xxx)
    100001: "SWING_TRADE_V1",
    200002: "DAY_TRADE_V1",
    300003: "CARRY_TRADE_V1",
    400004: "SCALP_TRADE_V1",

    # Internal magics (5 digits starting 5xxxx)
    50001: "PORTFOLIO_MANAGER",
    50002: "RISK_ENGINE",
    50003: "POSITION_MANAGER",
    50004: "DECISION_ENGINE",
    50005: "TRADE_EXECUTOR",
    50006: "BRAIN_ENGINE",
    50007: "BACKTEST_ENGINE",
    50008: "ML_PIPELINE",

    # Dashboard magics (5 digits starting 9xxxx)
    90001: "NATIVE_DASHBOARD",
    90002: "WEB_DASHBOARD",
    90003: "MT5_DASHBOARD",
}
```

---

*This matrix is the ground truth for module ownership. Update this document when adding/removing modules.*