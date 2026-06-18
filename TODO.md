# VERIFIABLE TODO TASK LIST
> Enforced: Zero-Tolerance Standards + OODA + Steelman Critique + Clarify/Confirm/Complete
> Created: 2026-06-18 | Total Tasks: 33 | Estimated: 10-17 days

---

## Pre-Flight Verification (MANDATORY BEFORE ANY TASK)

### Current State Audit
| Metric | Value | Verified |
|---|---|---|
| Bugs fixed this session | 68 | ✅ py_compile + pytest 81/81 |
| Files modified | 20 | ✅ All compile clean |
| Files created | 2 (watchdog.py, validation_pipeline.py) | ✅ |
| Test coverage | ~5% (81 tests, import/executor/utils only) | ✅ |
| Brain chain test coverage | 0% (7,685 lines, zero tests) | ✅ |
| MT5 thread safety | Violated in V3/V4/V2 (ThreadPool + MT5 API) | ✅ Verified |
| Orphaned modules | 23 modules never imported | ✅ Verified |
| Dead imports/constants | 45+ removed, verified clean | ✅ |

### Steelman Critique of the Plan Itself
**Strongest objection**: "33 tasks across 5 tiers is too many. You'll never finish. Prioritize ruthlessly."
**Counter**: The tasks are ordered by dependency. Tier 1 tasks (D1-D6) are prerequisites for everything else. Without tests (D6), no future changes can be verified. Without MT5 thread safety (D3), the system corrupts data. Without config validation (D1), a typo kills the account. These are not optional — they're the foundation.

**Strongest objection**: "Adding 17 orphaned modules (D10) adds 8,500 lines of untested code. You're making things worse."
**Counter**: Orphaned modules aren't "new code" — they already exist and were written for a purpose. Wiring them in means connecting existing interfaces, not writing new logic. The risk is in the integration, not the code. Tests (D6) mitigate this.

**Strongest objection**: "You're fixing 68 bugs but the architecture is still 11 layers deep. Why bother with band-aids?"
**Counter**: The 68 bug fixes are not band-aids — they're the preconditions for the architectural work. You can't restructure a building with a cracked foundation. The 11-layer collapse (D9) IS the architectural fix, but it depends on the bugs being fixed first.

---

## TIER 1: CRITICAL — Safety/Foundation (Days 1-2)

### T1.1 — MT5 Mock + Test Infrastructure
**What**: Create `tests/conftest.py` with MT5 mock fixtures. Create 7 test files with 28 tests covering brain chain.
**Why**: 7,685 lines of brain chain code have ZERO test coverage. Every future change is unverified.
**Steelman objection**: "Mocks aren't real tests — they test the mock, not the system."
**Counter**: Mocks test the LOGIC of each brain layer in isolation. Integration testing comes later. The alternative is zero tests, which is worse.

**Acceptance Criteria**:
- [ ] `tests/conftest.py` exists with `mock_mt5` fixture that provides: `copy_rates_from_pos`, `symbol_info`, `symbol_info_tick`, `account_info`, `positions_get`, `order_send`, `terminal_info`
- [ ] `tests/conftest.py` provides `synthetic_ohlcv(n)` helper generating valid OHLCV data
- [ ] `tests/conftest.py` provides `synthetic_symbol_info()` returning mock with `point`, `digits`, `trade_contract_size`, `volume_min`, `volume_max`, `volume_step`
- [ ] `tests/test_brain_v1_signals.py` — 8 tests: `_calc_indicators`, `_signal_ma`, `_signal_rsi`, `_signal_bb`, `_signal_breakout`, `_signal_momentum`, `_signal_orderflow`, `_signal_sr`
- [ ] `tests/test_brain_v1_risk.py` — 5 tests: `calculate_position_size`, `can_open_trade` (max positions, correlated, drawdown, daily loss, margin)
- [ ] `tests/test_brain_v2_regime.py` — 3 tests: `RegimeDetector.detect`, `CandlestickPatterns.detect`, `AdaptiveSLTP.calculate`
- [ ] `tests/test_brain_v3_cache.py` — 3 tests: `IndicatorCache.compute_indicators`, `CircuitBreaker`, `DataCache.get_rates`
- [ ] `tests/test_brain_v4_analysis.py` — 3 tests: `BayesianScorer`, `EntryQualityScorer.score`, `FalseBreakoutFilter.detect`
- [ ] `tests/test_brain_v6_validation.py` — 3 tests: `TradeValidator.validate_request` (valid, invalid volume, invalid SL)
- [ ] `tests/test_brain_v11_methods.py` — 3 tests: `RegimeClassifier.classify`, `MethodSelector.select`, `ParameterAdapter.adapt`
- [ ] ALL 28 tests pass with `pytest tests/ -v`
- [ ] `pytest tests/ --tb=short` shows 0 failures
- [ ] No `unittest.mock` imported in `conftest.py` — use `MagicMock` from `unittest.mock` directly in fixtures

**Verification**: `python -m pytest tests/ -v --tb=short` → 109+ passed, 0 failed

---

### T1.2 — Fix MT5 Thread Safety
**What**: Replace all `parallel_map_io` calls that dispatch MT5 API with sequential execution.
**Why**: MT5 Python module is documented as NOT thread-safe. Concurrent calls corrupt data.
**Steelman objection**: "Sequential calls are slower. You're trading correctness for performance."
**Counter**: MT5 calls are 5-20ms each. 6 sequential calls = ~120ms. The current parallel approach risks data corruption that could lose real money. Correctness > speed.

**Acceptance Criteria**:
- [ ] `brain_v3.py`: `DataCache.get_rates()` — replace `parallel_map_io` with `[fetch_fn(t) for t in tasks]`
- [ ] `brain_v3.py`: `DataCache.get_tick()` — replace `parallel_map_io` with sequential
- [ ] `brain_v3.py`: `DataCache.get_symbol_info()` — replace `parallel_map_io` with sequential
- [ ] `brain_v4.py`: `CorrelationMomentum.get_correlation_matrix()` — replace `parallel_map_io` with sequential
- [ ] `brain_v4.py`: `CorrelationMomentum.get_correlated_momentum()` — replace `parallel_map_io` with sequential
- [ ] `brain_v2.py`: `CrossSymbolMomentum.analyze()` — replace `ThreadPoolExecutor` with sequential
- [ ] Zero `parallel_map_io` calls remain that dispatch MT5 API functions
- [ ] All brain files compile clean (`py_compile`)
- [ ] All 109+ tests pass

**Verification**: `grep -r "parallel_map_io" brain_v*.py` → only non-MT5 uses remain (if any)

---

### T1.3 — Config Validation
**What**: Add bounds checking on all critical magic numbers in `config.py`.
**Why**: `MAX_RISK_PER_TRADE = 20` instead of `2.0` = account wipeout. No current validation.
**Steelman objection**: "Bounds checking is a band-aid. Use type-safe config."
**Counter**: Type-safe config is ideal but requires a major refactor. Bounds checking is the minimum viable safety net that can be implemented in 30 minutes.

**Acceptance Criteria**:
- [ ] `config.py` contains validation block at end of file
- [ ] All critical constants have bounds: `MAX_RISK_PER_TRADE` (0.1-10), `MIN_RISK_PER_TRADE` (0.01-5), `MAX_ORDERS_PER_SECOND` (1-100), `MAX_ORDERS_PER_MINUTE` (1-1000), `DAILY_LOSS_HARD_STOP` (0.1-20), `MAX_DRAWDOWN_KILL` (0.5-50), `MAX_SYMBOLS` (1-100), `MAX_SPREAD_POINTS` (1-1000)
- [ ] Validation raises `ValueError` with descriptive message on out-of-range
- [ ] `python -c "import config"` succeeds with valid defaults
- [ ] `python -c "import config; config.MAX_RISK_PER_TRADE=20"` raises ValueError
- [ ] All 109+ tests pass

**Verification**: Manual test with out-of-range value → ValueError

---

### T1.4 — Print Cleanup
**What**: Replace all `print()` calls in brain files with `logger.debug/info/warning`.
**Why**: Hot-path stdout floods production logs, leaks trading info, no severity routing.
**Steelman objection**: "This is cosmetic. Fix real bugs first."
**Counter**: `print()` in `brain_v2.py` fires 13 times per analysis cycle. With 30 symbols, that's 390 prints/second. This IS a performance and observability issue.

**Acceptance Criteria**:
- [ ] `grep -r "^ *print(" brain_v*.py mt5_AFxAutoTrader_v1.py` → 0 results
- [ ] All former `print()` locations use `logger.debug()` or `logger.info()` as appropriate
- [ ] Trade-related prints → `logger.info` with structured format
- [ ] Diagnostic/status prints → `logger.debug`
- [ ] Error prints → `logger.warning` or `logger.error`
- [ ] All files compile clean
- [ ] All 109+ tests pass

**Verification**: `grep -c "print(" brain_v*.py mt5_AFxAutoTrader_v1.py` → all zeros

---

### T1.5 — Dead Dependency Cleanup
**What**: Remove `plotly` from `requirements.txt`.
**Why**: Listed but never imported. ~50MB wasted download.
**Steelman objection**: "Might be needed later."
**Counter**: YAGNI. Add it back when needed. Current code has zero `import plotly`.

**Acceptance Criteria**:
- [ ] `requirements.txt` does NOT contain `plotly`
- [ ] `grep -r "import plotly" *.py` → 0 results
- [ ] All 109+ tests pass

**Verification**: `grep plotly requirements.txt` → empty

---

### T1.6 — Graceful Degradation
**What**: Add try/except wrappers at brain chain boundaries + MT5 connection check.
**Why**: MT5 disconnect or brain exception kills entire analysis cycle with no recovery.
**Steelman objection**: "Try/except hides bugs. Let them propagate."
**Counter**: In a trading system, a crash means unmanaged positions. Degradation (hold) is safer than death.

**Acceptance Criteria**:
- [ ] `BrainChain.analyze()` wrapped in try/except returning `{"action": "hold", "confidence": 0, "reason": "..."}` on failure
- [ ] `BrainChain.execute_decision()` wrapped in try/except returning False on failure
- [ ] `BrainChain.manage_positions()` wrapped in try/except logging error
- [ ] MT5 connection check at start of each `BrainV11.analyze()`: `if not mt5.terminal_info(): return hold`
- [ ] MT5 connection check at start of each `TradeExecutor.run()` iteration
- [ ] All exceptions logged with `logger.error` including traceback
- [ ] All 109+ tests pass

**Verification**: Mock `mt5.terminal_info()` to return None → system returns hold decision

---

## TIER 2: ARCHITECTURE — Core Fixes (Days 3-5)

### T2.1 — Wire Evolution Outputs
**What**: Thread `best_params` from V7 through V6→V5→V4→V3→V2→V1. V1 uses params for indicator periods.
**Why**: V7 evolution engine runs but outputs never affect trading. Decorative code.
**Steelman objection**: "Evolution might not improve trading. Wiring it adds complexity for no benefit."
**Counter**: We can't know until it's wired and measured. The wiring is minimal (add `params=None` to each `analyze()` signature). If evolution doesn't help, we can disable it later with data.

**Acceptance Criteria**:
- [ ] `brain_v7.py`: `analyze()` calls `self.v6.safe_analyze(symbol, timeframe, params=best_params)`
- [ ] `brain_v6.py`: `safe_analyze()` accepts `params=None`, forwards to `self.v5.analyze(..., params=params)`
- [ ] `brain_v5.py`: `analyze()` accepts `params=None`, forwards to `self.v4.analyze(..., params=params)`
- [ ] `brain_v4.py`: `analyze()` accepts `params=None`, forwards to `self.v3.analyze(..., params=params)`
- [ ] `brain_v3.py`: `analyze()` accepts `params=None`, forwards to `self.v2.analyze(..., params=params)`
- [ ] `brain_v2.py`: `analyze()` accepts `params=None`, forwards to `self.v1.analyze(..., params=params)`
- [ ] `brain_v1.py`: `analyze()` accepts `params=None`, passes to `calculate_all_signals(df, params=params)`
- [ ] `brain_v1.py`: `_calc_indicators(df, params=None)` uses `params.get("ema_fast", 5)` etc. for all 13 genome parameters
- [ ] `brain_v2.py`: `AdaptiveSLTP.calculate()` uses `params.get("sl_atr_mult", 1.5)` and `params.get("tp_atr_mult", 2.5)`
- [ ] ALL params have defaults — backward compatible when `params=None`
- [ ] All files compile clean
- [ ] All 109+ tests pass

**Verification**: Unit test that V1 with custom params produces different indicator values than default params

---

### T2.2 — Fix Confidence Cascade
**What**: Replace 14 multiplicative factors with additive adjustments. Each modifier gets max ±weight. Single final clamp.
**Why**: Current system: 14 multipliers → confidence always 0.98 → threshold check meaningless.
**Steelman objection**: "Multiplicative captures interaction effects. Additive underfits."
**Counter**: The current system doesn't capture interactions — it collapses to 0.98. At least additive gives meaningful separation between signals. We can add interactions later if needed.

**Acceptance Criteria**:
- [ ] `brain_v2.py`: V2 modifiers stored as `decision["confidence_adjustments"] = {"regime": delta, "session": delta, ...}` instead of `decision["confidence"] *= mod`
- [ ] `brain_v3.py`: V3 modifiers stored as additive deltas
- [ ] `brain_v4.py`: V4 modifiers stored as additive deltas
- [ ] `brain_v5.py`: V5 modifiers stored as additive deltas
- [ ] `brain_v7.py`: V7 modifiers stored as additive deltas
- [ ] `brain_v10.py`: V10 AI/trend modifiers stored as additive deltas
- [ ] `brain_v11.py`: Final combination: `final = max(0.1, min(base + sum(adjustments), 0.98))`
- [ ] Each modifier has a documented max weight (e.g., regime ±0.15, session ±0.10)
- [ ] No `*=` on `decision["confidence"]` remains in V2/V3/V4/V5/V7/V10
- [ ] All files compile clean
- [ ] All 109+ tests pass
- [ ] Test: synthetic signal with favorable modifiers produces confidence in [0.6, 0.95] range (not 0.98)

**Verification**: Unit test with known base=0.5 and known adjustments → final in expected range

---

### T2.3 — Collapse Chain Layers
**What**: V11 fetches df once, passes through all layers. Each layer accepts `df=None` and skips re-fetch if provided.
**Why**: 20+ MT5 calls, 12 indicator calcs per analysis. Should be ~8 calls, ~4 calcs.
**Steelman objection**: "Touching every brain layer's analyze() signature is high risk."
**Counter**: Adding `df=None` default is backward compatible. No existing call site changes. Only new callers (V11) pass the df.

**Acceptance Criteria**:
- [ ] `brain_v11.py`: `analyze()` fetches df once via `fetch_closed_rates()`, passes to `self.v10.analyze(symbol, timeframe, df=df)`
- [ ] `brain_v10.py`: `analyze(symbol, timeframe, df=None)` — if df provided, skip M1 rate fetch
- [ ] `brain_v9.py`: `analyze(symbol, timeframe, df=None)` — pass through
- [ ] `brain_v8.py`: `analyze(symbol, timeframe, df=None)` — pass through
- [ ] `brain_v7.py`: `analyze(symbol, timeframe, df=None)` — pass through
- [ ] `brain_v6.py`: `safe_analyze(symbol, timeframe, df=None)` — pass through
- [ ] `brain_v5.py`: `analyze(symbol, timeframe, df=None)` — pass through
- [ ] `brain_v4.py`: `analyze(symbol, timeframe, df=None)` — pass through, skip CorrelationMomentum fetch if df available
- [ ] `brain_v3.py`: `analyze(symbol, timeframe, df=None)` — pass through, skip cache fetch if df provided
- [ ] `brain_v2.py`: `analyze(symbol, timeframe, df=None)` — pass through, reuse V1's indicators
- [ ] `brain_v1.py`: `analyze(symbol, timeframe, df=None)` — skip re-fetch if df provided
- [ ] All `copy_rates_from_pos` calls in brain chain reduced from 20+ to ~8
- [ ] All indicator calculations reduced from 12 to ~4
- [ ] All files compile clean
- [ ] All 109+ tests pass

**Verification**: Count MT5 API calls before/after with mock counter

---

### T2.4 — Wire Orphaned Modules
**What**: Connect 17 orphaned modules into the brain chain via `integration.py`.
**Why**: 8,500+ lines of existing code doing nothing.
**Steelman objection**: "Wiring untested code is dangerous."
**Counter**: The modules already have public interfaces (tested by `test_imports.py`). Wiring means calling existing methods, not writing new logic.

**Acceptance Criteria**:
- [ ] `integration.py`: `get_risk_advanced()` returns working `AdvancedRiskManager` instance
- [ ] `integration.py`: `get_portfolio_risk()` returns working `PortfolioManager` instance
- [ ] `integration.py`: `get_gpu_engine()` returns working `GPUIndicators` instance
- [ ] `integration.py`: `get_cache_layer()` returns working cache instance
- [ ] `integration.py`: `get_order_flow()` returns working order flow instance
- [ ] `integration.py`: `get_pattern_recognition()` returns working pattern instance
- [ ] `integration.py`: `get_market_intelligence()` returns working intelligence instance
- [ ] `integration.py`: `get_institutional_analytics()` returns working analytics instance
- [ ] `integration.py`: `get_portfolio_engineering()` returns working engineering instance
- [ ] `integration.py`: `get_execution_optimization()` returns working optimizer instance
- [ ] `integration.py`: `get_data_analytics()` returns working analytics instance
- [ ] `integration.py`: `get_alternative_data()` returns working data instance
- [ ] `integration.py`: `get_microstructure()` returns working microstructure instance
- [ ] `integration.py`: `get_quant_models()` returns working models instance
- [ ] `integration.py`: `get_providers()` returns working provider instance
- [ ] `integration.py`: `get_strategies_advanced()` returns working strategies instance
- [ ] `brain_v1.py`: Uses `risk_advanced.AdvancedRiskManager` for enhanced risk checks
- [ ] `brain_v10.py`: Uses `order_flow`, `microstructure`, `institutional_analytics` for intelligence
- [ ] `brain_v11.py`: Uses `strategies_advanced` for MarketMaker/ArbitrageEngine methods
- [ ] `infrastructure.py` — DEFERRED (not needed until production scaling)
- [ ] All files compile clean
- [ ] All 109+ tests pass

**Verification**: `python -c "from integration import *; print('All imports OK')"`

---

### T2.5 — Wire New Files
**What**: Connect 7 created-but-unwired files into the system.
**Why**: New code exists but does nothing.

**Acceptance Criteria**:
- [ ] `watchdog.py`: `FailoverWatchdog` registered in `ScalperOrchestrator.run()` with restart functions for SymbolAnalyzer, PositionManager, TradeExecutor
- [ ] `validation_pipeline.py`: `ValidationPipeline.can_trade()` called in `TradeExecutor.run()` before order execution
- [ ] `ml_enhancements.py`: `RulesBaseline.evaluate()` used as fallback when `MLScorer.predict()` returns 0.5 (untrained)
- [ ] `ml_enhancements.py`: `FeatureNormalizer` initialized and used in `FeatureStore.get_feature_vector()` when scaler is fitted
- [ ] `ml_enhancements.py`: `EventDrivenBacktestEngine` available for validation pipeline backtest phase
- [ ] `indicators.py`: `align_to_m1_grid()` called in `brain_v10.py` `MultiTimeframeAnalyzer._analyze_tf()` for higher TF alignment
- [ ] `brain_v1.py`: `_send_order_with_fallback()` used in V2 and V6 execution paths (not just V1)
- [ ] All files compile clean
- [ ] All 109+ tests pass

**Verification**: Each wired file is called at least once in the production code path

---

## TIER 3: DATA/RISK — Safety Net (Days 6-8)

### T3.1 — Open Candle Masking
**What**: `rates = fetch_closed_rates(symbol, timeframe, count)` drops incomplete bar.
**Acceptance Criteria**:
- [ ] `indicators.py`: `fetch_closed_rates()` returns `rates[:-1]` (already implemented)
- [ ] All `mt5.copy_rates_from_pos()` calls in brain chain use `fetch_closed_rates()` instead
- [ ] `grep -r "copy_rates_from_pos" brain_v*.py` → only in `fetch_closed_rates` definition
- [ ] All 109+ tests pass

---

### T3.2 — Dynamic Spread Rejection
**What**: Reject if spread > 3× rolling 1-hour average.
**Acceptance Criteria**:
- [ ] `brain_v6.py`: `TradeValidator` tracks rolling spread history
- [ ] Spread rejection uses `avg_spread * 3.0` instead of hardcoded 50pts
- [ ] `brain_v2.py`: `ExecutionMonitor.is_spread_too_high()` uses dynamic threshold
- [ ] All 109+ tests pass

---

### T3.3 — Price Tolerance Check
**What**: Reject if entry > 10 pips from last tick.
**Acceptance Criteria**:
- [ ] `brain_v6.py`: `TradeValidator.validate_request()` checks `abs(entry_price - tick_price) > 10 * point`
- [ ] All 109+ tests pass

---

### T3.4 — Market Session Filter
**What**: `is_valid_session()` gate in `is_tradeable_now()`.
**Acceptance Criteria**:
- [ ] `indicators.py`: `is_valid_session()` checks configurable hours, weekend, holiday
- [ ] `indicators.py`: `is_tradeable_now()` calls `is_valid_session()` as first gate
- [ ] `config.py`: `TRADING_SESSIONS_ENABLED`, `TRADING_HOURS`, `WEEKEND_TRADING` defined
- [ ] All 109+ tests pass

---

### T3.5 — Alert Wiring
**What**: Wire alerts to crash/error events (thread crash, circuit breaker, black swan, MT5 disconnect, daily loss).
**Acceptance Criteria**:
- [ ] `alerts.py`: `alert_circuit_breaker()`, `alert_black_swan()`, `alert_mt5_disconnect()`, `alert_daily_loss()`, `alert_thread_crash()`, `alert_model_timeout()` all exist
- [ ] `brain_v3.py`: Circuit breaker trip calls `alert_circuit_breaker()`
- [ ] `brain_v1.py`: Black swan detection calls `alert_black_swan()`
- [ ] `mt5_AFxAutoTrader_v1.py`: MT5 disconnect calls `alert_mt5_disconnect()`
- [ ] `mt5_AFxAutoTrader_v1.py`: Daily loss limit calls `alert_daily_loss()`
- [ ] `watchdog.py`: Thread death calls `alert_thread_crash()`
- [ ] All 109+ tests pass

---

### T3.6 — Daily Loss Circuit Breaker
**What**: -3% hard stop, -1.5% soft warning, reset at 00:00.
**Acceptance Criteria**:
- [ ] `brain_v1.py`: `can_open_trade()` checks daily P&L against `DAILY_LOSS_HARD_STOP` (3.0%)
- [ ] `brain_v1.py`: `can_open_trade()` reduces size 50% when daily loss > `DAILY_LOSS_SOFT_WARN` (1.5%)
- [ ] Daily loss resets at midnight broker time
- [ ] All 109+ tests pass

---

### T3.7 — Margin Safety Gates
**What**: Block at <300%, emergency close at <150%.
**Acceptance Criteria**:
- [ ] `brain_v1.py`: `can_open_trade()` checks `margin_level = equity / margin * 100`
- [ ] Block new orders if margin_level < 300%
- [ ] Emergency close all if margin_level < 150%
- [ ] All 109+ tests pass

---

### T3.8 — Max 5% Portfolio Risk
**What**: Block if total open risk > 5% of equity.
**Acceptance Criteria**:
- [ ] `brain_v1.py`: `can_open_trade()` sums `abs(volume * price * 0.01)` across all positions
- [ ] Block if total_risk / equity > 5%
- [ ] All 109+ tests pass

---

### T3.9 — Failover Watchdog
**What**: Monitor daemon threads, restart on death, alert operator.
**Acceptance Criteria**:
- [ ] `watchdog.py`: `FailoverWatchdog` has `register(name, thread, restart_fn)`, `start()`, `stop()`
- [ ] `mt5_AFxAutoTrader_v1.py`: All daemon threads registered with restart functions
- [ ] Watchdog thread runs every 15s, checks `thread.is_alive()`
- [ ] On death: log + alert + call restart_fn
- [ ] All 109+ tests pass

---

### T3.10 — Event-Driven Bar Close
**What**: Detect M1 bar close via timestamp comparison, not tick polling.
**Acceptance Criteria**:
- [ ] `mt5_AFxAutoTrader_v1.py`: `SymbolAnalyzer._has_new_bar()` compares `rates[0].time` with cached timestamp
- [ ] Analysis triggers on bar close, not every tick
- [ ] All 109+ tests pass

---

### T3.11 — Forward-Fill Alignment
**What**: Align higher TFs to M1 timestamp grid.
**Acceptance Criteria**:
- [ ] `indicators.py`: `align_to_m1_grid(m1_rates, higher_tf_rates)` implemented
- [ ] `brain_v10.py`: Uses `align_to_m1_grid()` in MTF analysis
- [ ] All 109+ tests pass

---

### T3.12 — Order Rate Limiter
**What**: Max 5/sec, 30/min global cap.
**Acceptance Criteria**:
- [ ] `config.py`: `MAX_ORDERS_PER_SECOND = 5`, `MAX_ORDERS_PER_MINUTE = 30`
- [ ] `mt5_AFxAutoTrader_v1.py`: `TradeExecutor` enforces rate limits
- [ ] All 109+ tests pass

---

### T3.13 — Centralized Lookbacks
**What**: Micro=100, Medium=150, Macro=50.
**Acceptance Criteria**:
- [ ] `config.py`: `LOOKBACK_MICRO = 100`, `LOOKBACK_MEDIUM = 150`, `LOOKBACK_MACRO = 50`
- [ ] Brain files reference config constants instead of hardcoded values
- [ ] All 109+ tests pass

---

## TIER 4: ML/VALIDATION (Days 9-12)

### T4.1 — Phase 1 Rules Model
**What**: RulesBaseline as fallback when MLScorer untrained.
**Acceptance Criteria**:
- [ ] `ml_enhancements.py`: `RulesBaseline.evaluate(df)` returns `{"action": "buy/sell/hold", "confidence": 0-1, "reasons": [...]}`
- [ ] Used when `MLScorer.predict()` returns 0.5 (untrained default)
- [ ] All 109+ tests pass

---

### T4.2 — Feature Normalization
**What**: Per-timeframe StandardScaler.
**Acceptance Criteria**:
- [ ] `ml_enhancements.py`: `FeatureNormalizer.fit(tf, data)`, `transform(tf, vector)`, `save()`, `load()`
- [ ] Integrated into `FeatureStore.get_feature_vector()`
- [ ] All 109+ tests pass

---

### T4.3 — Event-Driven Backtester
**What**: Replace naive backtester with spread/slippage/cost modeling.
**Acceptance Criteria**:
- [ ] `ml_enhancements.py`: `EventDrivenBacktestEngine.run(signals, bars, ...)` returns metrics dict
- [ ] Models spread, slippage, commission, partial fills
- [ ] Returns: final_balance, total_return, win_rate, max_drawdown, profit_factor, sharpe_ratio
- [ ] All 109+ tests pass

---

### T4.4 — 3-Phase Validation Pipeline
**What**: Backtest → Paper → Live gate.
**Acceptance Criteria**:
- [ ] `validation_pipeline.py`: `evaluate_backtest(results)` checks Sharpe>0.8, DD<15%, PF>1.3
- [ ] `validation_pipeline.py`: `evaluate_paper(results, bt_results)` checks P&L divergence<10%
- [ ] `validation_pipeline.py`: `evaluate_live(results)` checks Sharpe>0.3, DD<5%
- [ ] `validation_pipeline.py`: `can_trade()` returns True only if phase is "live" or "production"
- [ ] State persisted to `brain_data/validation_state.json`
- [ ] All 109+ tests pass

---

## TIER 5: POLISH (Days 13-14)

### T5.1 — Structured JSON Logging
**What**: Wire JSON formatter, replace remaining prints.
**Acceptance Criteria**:
- [ ] `logging_config.py`: `JSONFormatter` available, `setup_logging(json_format=True)` works
- [ ] Error log file at `brain_data/logs/errors.log`
- [ ] All remaining `print()` in non-brain files converted to logger
- [ ] All 109+ tests pass

---

### T5.2 — Missing Original Items
**What**: Credential encryption, health endpoint, 500-candle standard.
**Acceptance Criteria**:
- [ ] `credential_store.py`: `encrypt_password()`, `decrypt_password()` using Fernet
- [ ] `dashboard.py`: `/health` endpoint returns `{"status": "ok", "phase": "...", "uptime": ...}`
- [ ] `config.py`: `LOOKBACK_CANDLES = 500` defined
- [ ] All 109+ tests pass

---

### T5.3 — Phase 3 TCN (Conditional)
**What**: Multi-branch 1D-CNN only if Phase 2 (LightGBM) shows edge.
**Acceptance Criteria**:
- [ ] Deferred until T4.3 backtester shows LightGBM has Sharpe > 0.8
- [ ] If implemented: M1/M5/M15 parallel branches, ONNX export, <100ms inference
- [ ] All 109+ tests pass

---

## Verification Checklist (Run After EVERY Task)

```bash
# 1. All files compile
python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['brain_v1.py','brain_v2.py','brain_v3.py','brain_v4.py','brain_v5.py','brain_v6.py','brain_v7.py','brain_v8.py','brain_v9.py','brain_v10.py','brain_v11.py','mt5_AFxAutoTrader_v1.py','indicators.py','ml_enhancements.py','config.py','alerts.py','logging_config.py','watchdog.py','validation_pipeline.py','cpu_tasks.py']]"

# 2. All tests pass
python -m pytest tests/ -v --tb=short

# 3. No print() in brain files
grep -c "print(" brain_v*.py mt5_AFxAutoTrader_v1.py

# 4. No parallel_map_io for MT5
grep -r "parallel_map_io" brain_v*.py | grep -v "def parallel_map_io"

# 5. No hardcoded MT5 filling type without fallback
grep -r "ORDER_FILLING_IOC" brain_v*.py | grep -v "fallback"

# 6. No dead imports
grep -r "^from.*import.*UNUSED" brain_v*.py  # (manual check)

# 7. No unbounded collections
grep -r "= set()" brain_v*.py | grep -v "maxlen"  # (manual check)
```

---

## Steelman Critique of the Entire Plan

**Objection 1**: "33 tasks is too many. You'll lose focus."
**Counter**: Tasks are grouped into 5 tiers with clear dependencies. Tier 1 (6 tasks) takes 1-2 days and creates the safety net. Each subsequent tier builds on the previous. No task is optional.

**Objection 2**: "You're fixing the brain chain but not the dashboard, exporters, or infrastructure."
**Counter**: The brain chain is the core. Dashboard/exporters are read-only consumers. Fixing the brain chain fixes the data they consume. Infrastructure (Kafka, Redis) is deferred until production scaling is needed.

**Objection 3**: "No integration tests. Unit tests with mocks aren't enough."
**Counter**: True. This plan creates the mock infrastructure (T1.1) and unit tests. Integration tests (running against actual MT5 terminal) are a separate effort that requires a live MT5 environment. The mocks verify logic; integration tests verify behavior.

**Objection 4**: "The confidence cascade fix (T2.2) changes trading behavior. How do you know it's better?"
**Counter**: We don't. That's why T4.3 (backtester) exists. Run the backtester before and after the confidence change. If Sharpe improves, keep it. If not, revert.

**Objection 5**: "You're wiring 17 orphaned modules (T2.4) without testing them."
**Counter**: `test_imports.py` already verifies each module can be imported and has the expected interface. Wiring means calling existing tested interfaces. The risk is in the integration, which is covered by T1.1's brain chain tests.

---

## Commit Strategy

After each tier completes:
```
git commit -m "tier-1: MT5 mock, thread safety, config validation, print cleanup, graceful degradation"
git commit -m "tier-2: evolution wiring, confidence fix, chain collapse, orphan wiring"
git commit -m "tier-3: risk gates, session filter, alerts, watchdog, bar close"
git commit -m "tier-4: rules model, normalization, backtester, validation pipeline"
git commit -m "tier-5: structured logging, credential encryption, health endpoint"
```
