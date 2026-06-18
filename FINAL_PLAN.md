# MASTER PLAN: Scalper Pro — Complete Upgrade Roadmap
> Synthesized from graphify deep analysis + 6 blueprint reviews + 3 tear-down audits + design-level fixes
> Last updated: 2026-06-18

---

## Executive Summary

**33 active tasks** across 5 tiers. 68 bugs already fixed. 12 design-level items remaining.

### Architecture Decision
**Single-process event-driven** (Plan 4). Multi-process adds IPC overhead without speeding up MT5's blocking API. Thread pool is sufficient.

### What's Already Fixed (68 bugs)
| Category | Count | Status |
|---|---|---|
| CRITICAL bugs (brain chain) | 15 | ✅ Fixed |
| HIGH severity bugs | 5 | ✅ Fixed |
| MEDIUM severity bugs | 10 | ✅ Fixed |
| Thread safety issues | 15+ | ✅ All locked |
| Dead code removed | 45+ | ✅ All removed |
| Memory leaks fixed | 5 | ✅ All bounded |
| MT5 API fixes | 8 | ✅ Null checks, fallback filling |
| Mathematical fixes | 6 | ✅ Sharpe, RSI, confidence clamping |

---

## TIER 1: CRITICAL — Do First (Safety/Survival)

| # | Task | What | Why | Effort |
|---|---|---|---|---|
| **D1** | Config validation | Bounds checking on 50+ magic numbers at import time | `MAX_RISK_PER_TRADE = 20` instead of `2.0` = catastrophe | Low |
| **D2** | Graceful degradation | Try/except at brain chain boundaries + MT5 connection check | MT5 disconnect kills entire analysis cycle | Medium |
| **D3** | Fix MT5 thread safety | Replace `parallel_map_io` with sequential MT5 calls in V3/V4/V2 | MT5 API documented as NOT thread-safe; concurrent calls corrupt data | Low |
| **D4** | Print statement cleanup | Replace 50+ `print()` with `logger.debug/info` across V2/V3/V6/V7/V9/V11 | Hot path stdout floods, leaks info in production | Low |
| **D5** | Dead dependency cleanup | Remove unused `plotly` from requirements.txt | ~50MB wasted download | Low |
| **D6** | MT5 mock + first tests | Create `conftest.py` with MT5 mock; 28 tests covering signals, risk, validation | 7,685 lines across 11 brains have ZERO test coverage | Medium |

---

## TIER 2: HIGH — Do Next (Architecture Fixes)

| # | Task | What | Why | Effort |
|---|---|---|---|---|
| **D7** | Wire evolution outputs | Thread `best_params` through V1-V6 `analyze()` signatures; V1 uses `params.get("ema_fast", 5)` instead of hardcoded 5 | V7 evolution runs but outputs never affect trading — decorative | Medium |
| **D8** | Fix confidence cascade | Replace 14 multiplicative factors with additive scoring; each modifier gets max ±weight; single final clamp | Confidence always 0.98 — threshold check meaningless | High |
| **D9** | Collapse chain layers | Pass `df` through chain; V11 fetches once, all layers reuse; eliminate 4x redundant fetches, 3x redundant indicator calcs | 20+ MT5 calls, 12 indicator calcs per analysis | High |
| **D10** | Wire orphaned modules | 23 unused modules — wire 17 into production (portfolio_risk, risk_advanced, gpu_engine, cache_layer, etc.) | 8,500+ lines of dead code | High |
| **D11** | Wire new files | 7 created-but-unwired files (validation_pipeline, watchdog, RulesBaseline, FeatureNormalizer, EventDrivenBacktestEngine, align_to_m1_grid, _send_order_with_fallback) | New code exists but does nothing | Medium |

---

## TIER 3: MEDIUM — Do After (Data Integrity & Risk)

| # | Task | What | Why | Effort |
|---|---|---|---|---|
| **F7** | Open candle masking | `rates = mt5.copy_rates_from_pos(...)[0:-1]` — drop incomplete bar | Every indicator includes forming bar = lookahead bias | Low |
| **F5** | Dynamic spread rejection | Reject if spread > 3× rolling average (replace hardcoded 50pts) | Hardcoded threshold doesn't adapt | Low |
| **F6** | Price tolerance check | Reject if entry > 10 pips from last tick | No price staleness check on execution | Low |
| **F10** | Market Session Filter | `is_valid_session()` gate: configurable hours, weekend filter | `get_current_session()` exists but is tagging only | Low |
| **F12** | Wire alerts to crash events | Add alerts for: thread crash, circuit breaker, black swan, MT5 disconnect, daily loss | Operator has zero visibility into failures | Low |
| **F3** | Daily loss circuit breaker | -3% hard stop, -1.5% soft warning, reset at 00:00 broker time | No daily loss limit exists | Low |
| **F4** | Margin safety gates | Block at <300%, emergency close at <150% | Only 20% free margin check exists | Low |
| **F13** | Max 5% portfolio risk | Block if total open risk > 5% of equity | No portfolio-level exposure cap | Medium |
| **F8** | Failover Watchdog | Monitor daemon threads, restart on death, alert operator | Silent thread death = silent failure | Medium |
| **F9** | Event-driven bar close | Cache last-seen bar timestamp, emit BarCloseEvent on new bar | Currently polls 10ms, processes every tick — wasteful | Medium |
| **F11** | Forward-fill alignment | Align all higher TFs onto M1 timestamp grid | No cross-TF alignment — misaligned signals | Medium |
| **F19** | Order rate limiter | Max 5/sec, 30/min global cap | Only per-symbol 10s cooldown exists | Low |
| **F20** | Centralized lookbacks | Micro=100, Medium=150, Macro=50 bars | Lookbacks ad-hoc per module (50-200 range) | Low |

---

## TIER 4: MEDIUM — ML & Validation

| # | Task | What | Why | Effort |
|---|---|---|---|---|
| **F14** | Phase 1 model | Rules + EMA/RSI/ATR baseline | MLScorer is dead code; need working baseline | Medium |
| **F15** | Feature normalization | Per-timeframe StandardScaler + log-returns | Raw features break across regimes | Medium |
| **F16** | Event-driven backtester | Bid/ask ticks, spread, slippage, partial fills, costs | Current backtester uses single price — results meaningless | High |
| **F17** | 3-phase validation | Backtest (4wk) → Paper (8wk) → Live micro-lot (12wk) | No validation path — jumping to live = gambling | High |

---

## TIER 5: LOW — Polish

| # | Task | What | Why | Effort |
|---|---|---|---|---|
| **F18** | Structured JSON logging | Wire JSON formatter, replace all prints | Plain text logging, no structured fields | Medium |
| **D12** | Missing original items | Credential encryption, health endpoint, 500-candle standard | Items from original master plan never implemented | Medium |
| **F21** | Phase 3 TCN | M1/M5/M15 parallel 1D-CNN (only if Phase 2 succeeds) | Future model evolution | High |

---

## Dependency Graph

```
D1 (Config validation) ─────────────────────────────────────┐
D2 (Graceful degradation) ──────────────────────────────────┤
D3 (MT5 thread safety) ─────────────────────────────────────┤
D4 (Print cleanup) ─────────────────────────────────────────┤
D5 (Dead deps) ─────────────────────────────────────────────┤
D6 (Tests + MT5 mock) ──► D7, D8, D9 (verify fixes) ───────┤
                                                            │
D7 (Wire evolution) ────────────────────────────────────────┤
D8 (Fix confidence) ────────────────────────────────────────┤
D9 (Collapse layers) ──► depends on D7, D8 ─────────────────┤
D10 (Wire orphans) ──► depends on D9 ───────────────────────┤
D11 (Wire new files) ──► depends on D9 ─────────────────────┤
                                                            │
F7 (Candle mask) ──► F11 (Forward-fill) ────────────────────┤
F5 (Spread) ────────────────────────────────────────────────┤
F6 (Price tolerance) ───────────────────────────────────────┤
F10 (Session filter) ───────────────────────────────────────┤
F12 (Alert wiring) ──► depends on F3, F8 ───────────────────┤
F3 (Daily loss) ──► F8 (Watchdog) ──► F12 ──────────────────┤
F4 (Margin safety) ─────────────────────────────────────────┤
F13 (Portfolio risk) ───────────────────────────────────────┤
F9 (Bar close) ──► F10 ─────────────────────────────────────┤
                                                            │
F14 (Phase 1 model) ──► F15 ──► F16 ──► F17 ───────────────┤
F18 (Structured logging) ───────────────────────────────────┤
F19 (Rate limiter) ─────────────────────────────────────────┤
F20 (Lookbacks) ────────────────────────────────────────────┤
F21 (Phase 3 TCN) ── only if F17 passes ────────────────────┘
```

---

## Implementation Order (13 Steps)

| Step | Items | Effort | Risk | What |
|------|-------|--------|------|------|
| 1 | D6 | Medium | None | MT5 mock + 28 tests (safety net) |
| 2 | D3 | Low | Low | Fix MT5 thread safety (sequential calls) |
| 3 | D1 | Low | None | Config validation (bounds checking) |
| 4 | D4, D5 | Low | None | Print cleanup + dead deps |
| 5 | D2 | Medium | Low | Graceful degradation (try/except + MT5 check) |
| 6 | D7 | Medium | Low | Wire evolution params through chain |
| 7 | D11 | Medium | Medium | Wire new files (validation, watchdog, RulesBaseline, etc.) |
| 8 | D10 | High | Medium | Wire orphaned modules (17 modules) |
| 9 | D8 | High | Medium | Fix confidence cascade (additive scoring) |
| 10 | D9 | High | High | Collapse chain layers (shared df) |
| 11 | F7,F5,F6,F10,F12,F3,F4,F13,F8,F9,F11,F19,F20 | Medium | Low | Risk + data integrity items (batch) |
| 12 | D12, F18 | Medium | Low | Missing original items + structured logging |
| 13 | F14,F15,F16,F17,F21 | High | Medium | ML + validation pipeline |

---

## Files to Modify (Cumulative)

| File | Items | Key Changes |
|------|-------|-------------|
| `brain_v1.py` | D7, D9, F7 | Accept `params` dict for indicators, accept `df` param, open candle masking |
| `brain_v2.py` | D7, D9, D10, F7 | Accept params/df, wire CandlestickAIClassifier, adaptive SLTP from params |
| `brain_v3.py` | D3, D7, D9 | Sequential MT5 calls, accept params/df, share indicator cache |
| `brain_v4.py` | D7, D8, D9, D10 | Accept params/df, additive scoring, wire CorrelationMomentum properly |
| `brain_v5.py` | D7, D8 | Accept params, additive scoring |
| `brain_v6.py` | D2, D8, D10 | Graceful degradation wrapper, additive scoring, wire AdvancedRiskManager |
| `brain_v7.py` | D7, D8 | Thread best_params to V6, additive scoring |
| `brain_v8.py` | D4 | Replace prints with logger |
| `brain_v9.py` | D4, D10 | Replace prints with logger, wire SystemMonitor properly |
| `brain_v10.py` | D8, D9, D10 | Additive scoring, accept df, wire order_flow/microstructure/institutional |
| `brain_v11.py` | D7, D8, D9, D10 | Thread params, additive scoring, accept df, wire strategies_advanced |
| `mt5_AFxAutoTrader_v1.py` | D2, D4, D11, F8, F12 | Graceful degradation, print cleanup, wire watchdog/validation, alert wiring |
| `indicators.py` | F7, F10, F11 | Open candle masking, session filter, forward-fill |
| `config.py` | D1, F19, F20 | Bounds validation, rate limiter, lookback constants |
| `ml_enhancements.py` | F14, F15, F16, D11 | Phase 1 model, normalization, backtest, wire RulesBaseline/FeatureNormalizer |
| `alerts.py` | F12 | Wire to crash/error events |
| `logging_config.py` | F18 | JSON format, severity routing |
| `execution_compliance.py` | F6 | Price tolerance check |
| `requirements.txt` | D5 | Remove plotly |
| `tests/conftest.py` | D6 | NEW — MT5 mock fixtures |
| `tests/test_brain_v1_signals.py` | D6 | NEW — 8 signal tests |
| `tests/test_brain_v1_risk.py` | D6 | NEW — 5 risk tests |
| `tests/test_brain_v2_regime.py` | D6 | NEW — 3 regime tests |
| `tests/test_brain_v3_cache.py` | D6 | NEW — 3 cache tests |
| `tests/test_brain_v4_analysis.py` | D6 | NEW — 3 analysis tests |
| `tests/test_brain_v6_validation.py` | D6 | NEW — 3 validation tests |
| `tests/test_brain_v11_methods.py` | D6 | NEW — 3 method tests |

---

## Success Criteria

| Metric | Current | Target |
|---|---|---|
| Test coverage (brain chain) | 0% | 50%+ |
| MT5 thread safety | Violated in V3/V4/V2 | Sequential access only |
| Confidence range | Always 0.98 | Meaningful [0.3-0.98] |
| MT5 API calls per analysis | 20+ | ~8 |
| Indicator calculations per analysis | 12 | ~4 |
| Evolution outputs applied | Never | Wired to V1-V6 indicators |
| Orphaned modules | 23 dead | 17 wired in, 1 deferred |
| Print statements in hot paths | 50+ | 0 (all logger) |
| Config validation | None | All magic numbers bounded |
| Graceful degradation | None | try/except + MT5 check |
| Alert coverage | 4 call sites | 20+ call sites |

---

## Total Estimated Effort

| Tier | Items | Days |
|------|-------|------|
| Tier 1 (Critical) | D1-D6 | 1-2 |
| Tier 2 (Architecture) | D7-D11 | 3-5 |
| Tier 3 (Data/Risk) | F3-F13, F19, F20 | 2-3 |
| Tier 4 (ML/Validation) | F14-F17 | 3-5 |
| Tier 5 (Polish) | D12, F18, F21 | 1-2 |
| **Total** | **33 items** | **10-17 days** |
