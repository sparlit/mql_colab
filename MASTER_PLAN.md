# MASTER PLAN: Scalper Pro Upgrade Roadmap
> Consolidated from graphify deep analysis + blueprint reviews
> Last updated: 2026-06-18

---

## Project Baseline
- **52 Python files** (17,795 LOC) + **10 MQL5 files** (3,632 LOC)
- **1,713 graph nodes, 3,193 edges, 111 communities**
- **God Nodes:** ScalperOrchestrator (35 edges), ThreadSafeState (32), MT5DataExporter (32), BrainV10 (31), BrainV9 (30)
- **Critical SPOF:** Single Python process hosting ALL threads, brains, trade execution, MT5 connection

---

## PLAN 1: Blueprint Analysis — Three-Tier Star Architecture

### Critical Single Point of Failure
**`ScalperOrchestrator` (`mt5_AFxAutoTrader_v1.py:999`)** — single process hosting everything. If it crashes:
- All 10+ SymbolAnalyzer threads die
- BrainChain V11→V1 stops
- PositionManager stops monitoring open positions (unmanaged risk)
- Pending trade signals lost
- Dashboard goes offline
- MT5 EA loses data feed

Graph confirms: 35 edges to 20+ communities. `integration.py` (betweenness 0.286) and main file (0.282) are top articulation points.

### What Already Exists (KEEP)
| Feature | Status |
|---|---|
| Numba JIT (`_ema_kernel`) | ✅ Exists |
| CuPy GPU indicators with auto-fallback | ✅ Exists |
| Auto hardware detection (CPU/GPU/RAM) | ✅ Exists in `config.py` |
| 4-level market state gate | ✅ Exists in `indicators.py` |
| Drawdown circuit breaker (5%) | ✅ Exists in PositionManager |
| Black swan detection (10% DD) | ✅ Exists |

### Integration Plan (P0-P6)

| Priority | Change | Impact | Effort |
|---|---|---|---|
| **P0** | Per-symbol process isolation (Tier 2) | Eliminates SPOF | High |
| **P1** | Asyncio event loop (Tier 1) | CPU savings, proper tick sub | High |
| **P2** | Dual-stream micro/macro pipeline | Redundant computation | Medium |
| **P3** | Dual-gate ML (ONNX TCN + LightGBM) | Signal quality | Medium |
| **P4** | Feature normalization (log/z-score) | ML reliability | Low |
| **P5** | Lookahead bias guard (bar-close-only) | Safety | Low |
| **P6** | 500-candle standardization | Consistency | Low |

### Files to Create/Modify
- **New:** `computation_worker.py` (Tier 2 process), `async_tier1.py`, `data_pipeline.py`, `ml_gates.py`, `safeguards.py`
- **Modify:** `mt5_AFxAutoTrader_v1.py`, `ml_enhancements.py`, `indicators.py`, `config.py`, `brain_v11.py`

### Implementation Order
1. P0 → P5 → P6 → P4 → P3 → P2 → P1

---

## PLAN 2: Architecture Critique — Robustness, Safety & Production Hardening

### Key Corrections to Plan 1
This critique **refines** Plan 1 rather than contradicting it:

| Plan 1 Proposal | Plan 2 Correction | Verdict |
|---|---|---|
| Per-symbol OS process isolation | **Consolidate to shared ProcessPoolExecutor** — per-pair process costs ~50MB each, 10 pairs = 500MB+ RAM. Batch compute is cheaper. | **ADOPT Plan 2** |
| IPC via `queue.Queue` | **Lock-free ring buffer** — prevents back-pressure blocking, overwrites oldest signals instead of dropping | **ADOPT Plan 2** |
| Lookahead bias guard (basic) | **n+1 fetch + cross-TF alignment** — fetch n+1 bars, verify last bar is closed, handle M1/H1 time misalignment | **ADOPT Plan 2** |
| Feature normalization (log returns) | **Per-timeframe StandardScaler** — M1 variance ≠ H1 variance by ~√60. Separate scalers per TF. | **ADOPT Plan 2** |
| Dual-gate ML | **Add walk-forward CV, 30-day retrain, feature leakage prevention** — compute LightGBM features on previous bar only | **ADOPT Plan 2** |

### What Already Exists (KEEP)
| Feature | Status |
|---|---|
| `queue.Queue` with maxsize + drop on full | ✅ Exists (upgrade to ring buffer) |
| `ParallelExecutor` with 5 pool types | ✅ Exists (consolidate usage) |
| `TradeJournal` persistent audit | ✅ Exists (upgrade to append-only) |
| `DecisionAuditTrail` | ✅ Exists (upgrade to persistent) |
| `PositionLimitMonitor` | ✅ Exists (wire into TradeExecutor) |
| `MetricsCollector` + Prometheus export | ✅ Exists (add structured logging) |
| `BacktestEngine` + `PaperTrader` | ✅ Exists (enhance significantly) |
| Latency measurement (time.time) | ✅ Exists (upgrade to perf_counter) |
| `ActivityLogger` | ✅ Exists (upgrade to structured JSON) |

### Integration Plan (Q0-Q8)

| Priority | Change | Impact | Effort |
|---|---|---|---|
| **Q0** | Shared ProcessPoolExecutor for Tier 2 (batch per-pair) | SPOF mitigation, memory efficient | High |
| **Q1** | Lock-free ring buffer for signals | Prevents IPC deadlock, priority signals survive | Medium |
| **Q2** | Lookahead guard: n+1 fetch + cross-TF alignment | Data integrity | Low |
| **Q3** | Per-timeframe StandardScaler normalization | ML reliability | Medium |
| **Q4** | Dual-gate with walk-forward CV + 30-day retrain + feature leakage fix | ML robustness | High |
| **Q5** | Shared ONNX model batch inference (10 pairs → 1 forward pass) | 70% memory/CPU savings | Medium |
| **Q6** | Structured JSON logging + health-check endpoint | Observability | Medium |
| **Q7** | Credential encryption (OS keyring / Fernet) | Security | Low |
| **Q8** | Position sizing hard caps + max daily loss + audit trail append-only | Compliance | Medium |

### Files to Create/Modify
- **New:** `ring_buffer.py`, `health_check.py`, `credential_store.py`, `structured_logging.py`
- **Modify:** `parallel_executor.py` (consolidate pools), `mt5_AFxAutoTrader_v1.py` (ring buffer, health endpoint), `indicators.py` (n+1 guard), `ml_enhancements.py` (per-TF scaler, walk-forward), `execution_compliance.py` (wire PositionLimitMonitor), `brain_v8.py` (append-only audit), `logging_config.py` (JSON format), `config.py` (hard caps)

### Implementation Order
1. Q2 (lookahead guard — quick safety win)
2. Q1 (ring buffer — IPC reliability)
3. Q8 (hard caps + audit — compliance)
4. Q3 (normalization — prerequisite for Q4)
5. Q5 (shared ONNX batch — memory savings)
6. Q4 (dual-gate robustness — requires Q3)
7. Q6 (structured logging — observability)
8. Q7 (credential encryption — security)
9. Q0 (shared ProcessPool — architectural consolidation)

---

## PLAN 3: Updated Blueprint — Shared Memory, CPU Pinning, Retraining, IPC Tests

### Redundancy Check
This blueprint is ~80% consolidated from Plans 1+2. Only 4 genuinely new items:

| Item | Already Covered? | New Value |
|---|---|---|
| Shared memory pool | ❌ Plan 2 Q0 only uses ProcessPoolExecutor | Zero-copy data between tiers |
| CPU core pinning | ❌ Not mentioned anywhere | Eliminates context-switch jitter |
| Automated 30-day retrain | ⚠️ Plan 2 Q4 mentions it but no pipeline | Operational automation |
| IPC unit tests | ❌ Not in any plan | Race condition prevention |

### What Already Exists (KEEP)
| Feature | Status |
|---|---|
| `DashboardMMapWriter` (mmap binary dashboard) | ✅ Exists — file-backed, not shared-memory |
| `ParallelExecutor` (5 pool types) | ✅ Exists — add shared memory + pinning |
| `config.py` CPU detection (physical/logical cores) | ✅ Exists — use for pinning |
| `BacktestEngine` + `PaperTrader` | ✅ Exists — enhance for walk-forward |
| `test_parallel_executor.py` (14 tests) | ✅ Exists — add IPC tests |

### Integration Plan (R0-R3)

| Priority | Change | Impact | Effort |
|---|---|---|---|
| **R0** | Shared memory pool for Tier 1↔2 data (zero-copy candle matrices) | Eliminates IPC serialization overhead | Medium |
| **R1** | CPU core pinning for Tier 2 computation process | Eliminates context-switch jitter, predictable latency | Low |
| **R2** | Automated 30-day retraining pipeline (scheduled + triggered) | Prevents model drift, maintains signal quality | High |
| **R3** | IPC unit tests (ring buffer, shared memory, signal flow) | Catches race conditions before production | Medium |

### Implementation Details

**R0 — Shared Memory Pool:**
```python
from multiprocessing.shared_memory import SharedMemory
import numpy as np

# Tier 1 writes candle matrix to shared memory
shm = SharedMemory(name="candle_matrix_eurusd", create=True, size=500*8*6)  # 500 candles x 6 fields x float64
shared_array = np.ndarray((500, 6), dtype=np.float64, buffer=shm.buf)
shared_array[:] = candle_matrix  # zero-copy write

# Tier 2 reads directly — no serialization, no IPC queue
```

**R1 — CPU Core Pinning:**
```python
import os
import psutil

def pin_to_core(core_id):
    p = psutil.Process(os.getpid())
    p.cpu_affinity([core_id])

# Pin Tier 2 to last available core
pin_to_core(psutil.cpu_count(logical=False) - 1)
```

**R2 — Retraining Pipeline:**
```python
# New file: retrain_pipeline.py
class RetrainPipeline:
    def __init__(self, retrain_interval_days=30):
        self.interval = timedelta(days=retrain_interval_days)
        self.last_retrain = None
    
    def should_retrain(self):
        return self.last_retrain is None or \
               datetime.now() - self.last_retrain > self.interval
    
    def run_walk_forward(self, symbol, lookback_days=365, step_days=30):
        # Walk-forward: train on [0, T], test on [T, T+step], slide forward
        # Returns: per-step accuracy, feature importance drift
        pass
    
    def retrain_tcn(self, training_data):
        # Train PyTorch TCN → export to ONNX
        pass
    
    def retrain_lightgbm(self, training_data):
        # Train LightGBM with leak-free features (previous bar only)
        pass
    
    def validate_and_deploy(self, new_model, benchmark_model):
        # Only deploy if new model outperforms on walk-forward metrics
        pass
```

**R3 — IPC Unit Tests:**
```python
# New file: tests/test_ipc.py
def test_ring_buffer_push_pop():
    buf = SignalRingBuffer(size=10)
    buf.push({"signal": "buy", "confidence": 0.8})
    assert buf.pop()["confidence"] == 0.8

def test_ring_buffer_overwrite_oldest():
    buf = SignalRingBuffer(size=3)
    for i in range(5):
        buf.push({"id": i})
    assert buf.pop()["id"] == 2  # oldest overwritten

def test_shared_memory_write_read():
    # Tier 1 writes, Tier 2 reads — same process for test
    pass

def test_concurrent_push_pop():
    # Multi-threaded push/pop correctness
    pass
```

### Files to Create/Modify
- **New:** `retrain_pipeline.py`, `tests/test_ipc.py`, `tests/test_retrain.py`
- **Modify:** `parallel_executor.py` (add shared memory, CPU pinning), `mt5_AFxAutoTrader_v1.py` (integrate retrain pipeline, shared memory writes), `ml_enhancements.py` (walk-forward CV), `config.py` (retrain interval config)

---

## PLAN 4: Revised Blueprint — Risk-First, Single-Process, Phased Validation

### Paradigm Shift (Overrides Plans 1-3)
This blueprint **fundamentally challenges** the multi-process architecture:

| Plan 1-3 Assumption | Plan 4 Reality | Verdict |
|---|---|---|
| Multi-process bypasses GIL for speed | **MT5 API is synchronous/blocking** — data retrieval takes 100-500ms regardless. Multi-process adds IPC overhead without speeding up the bottleneck. | **ADOPT Plan 4** |
| <5ms end-to-end latency | **200-500ms is realistic** — MT5 `copy_rates` is blocking, broker execution adds 10-20ms | **ADOPT Plan 4** |
| 8-branch TCN + LightGBM ensemble | **Phased evolution**: rules → LightGBM → optional TCN. Prove simpler models fail first. | **ADOPT Plan 4** |
| Jump to live trading | **Mandatory 3-phase validation**: backtest (4wk) → paper (8wk) → live micro-lot (12wk) | **ADOPT Plan 4** |
| Risk management as enhancement | **Risk management as foundation** — most critical addition | **ADOPT Plan 4** |

### What Already Exists vs What's Missing

| Risk Item | Status | Location |
|---|---|---|
| Max 2% risk per trade | ✅ EXISTS | `brain_v1.py:627` — Kelly-based, capped at 2% |
| Kelly calculation | ✅ EXISTS | `brain_v1.py:194` — 0.5 Kelly scaling |
| Max 5% total account risk | ❌ MISSING | — |
| Price tolerance (10 pips) | ❌ MISSING | — |
| Spread rejection (>3x avg) | ⚠️ PARTIAL | `brain_v6.py:222` — hardcoded 50pts, not dynamic |
| Correlation blocking | ✅ EXISTS | `brain_v1.py:651` — max 2 correlated |
| Daily loss circuit breaker (-3%) | ❌ MISSING | Only 5% halt exists |
| Soft warning (-1.5%) | ❌ MISSING | — |
| Margin safety (300%/150%) | ❌ MISSING | Only 20% free margin check |
| Consecutive loss halting | ✅ EXISTS | `brain_v3.py:197` — 4-5 loss threshold |
| Rolling win rate | ✅ EXISTS | `brain_v1.py:111` — 50-trade lookback |
| Sharpe ratio monitoring | ✅ EXISTS | `brain_v1.py:132` — 100-trade lookback |
| Slippage monitoring | ✅ EXISTS | `brain_v2.py:379` — per-trade tracking |
| Order rejection rate | ❌ MISSING | Only error counting |

**Score: 7/14 fully exist, 1 partial, 6 missing**

### Integration Plan (S0-S8)

| Priority | Change | Impact | Effort |
|---|---|---|---|
| **S0** | Daily loss circuit breaker (-3% hard, -1.5% soft) + margin safety (300%/150%) | Critical risk gap | Low |
| **S1** | Price tolerance (10 pips) + dynamic spread rejection (3x avg) | Prevent toxic fills | Low |
| **S2** | Max 5% total account risk + order rejection rate tracking | Portfolio-level safety | Medium |
| **S3** | Event-driven bar close detection (replace schedule polling) | Eliminate temporal misalignment | Medium |
| **S4** | Event-driven backtester (replace vectorized BacktestEngine) | Realistic validation | High |
| **S5** | Phased model: Phase 1 = rules + 2-3 indicators, Phase 2 = LightGBM | Pragmatic ML | Medium |
| **S6** | 3-phase validation pipeline (backtest → paper → live) | Non-negotiable safety path | High |
| **S7** | Single-process event loop (override multi-process from Plans 1-3) | Simplicity, determinism | High |
| **S8** | Emergency protocols (black swan >5 ATR, spread >10x, disconnect >30s) | Survival | Medium |

### Architecture Override

**Plans 1-3 proposed:** Multi-process Tier 1/Tier 2/Tier 3 with IPC queues.
**Plan 4 proposes:** Single-process event-driven with thread pool.

```
┌─────────────────────────────────────────────────────────────┐
│                    SINGLE PYTHON PROCESS                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  MT5 I/O    │  │  Event      │  │  Thread Pool      │  │
│  │  Adapter    │◄─┤  Loop       │◄─┤  (CPU-Bound Work) │  │
│  │  (Blocking) │  │  (Asyncio)  │  │  (Model Inference)│  │
│  └──────┬──────┘  └──────┬──────┘  └─────────────────────┘  │
│         │                │                                     │
│         ▼                ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │           STATE MACHINE (Single Source of Truth)        │   │
│  │  Portfolio State | Risk Limits | Signal Queue           │   │
│  │  Order History | Drawdown Tracker | Position Sizing     │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Model Phased Evolution

| Phase | Duration | Model | Goal |
|---|---|---|---|
| Phase 1 (Wks 1-4) | Rules + EMA/RSI/ATR | Prove infrastructure works | Sharpe > 0.5 |
| Phase 2 (Wks 5-12) | LightGBM (20-50 features) | ML edge validation | Walk-forward Sharpe > 0.8 |
| Phase 3 (Mo 4-6+) | Single-branch 1D-CNN/TCN (ONNX) | Only if Phase 2 saturates | Must outperform Phase 2 |

### Validation Pipeline (Non-Negotiable)

| Phase | Duration | Requirements |
|---|---|---|
| **A: Backtest** | Min 4 weeks | Walk-forward, 12mo+ OOS, spread+slippage, Monte Carlo (1000 runs), Sharpe > 0.8, Max DD < 15% |
| **B: Paper** | Min 8 weeks | Same code as backtest, real ticks, simulated execution, P&L divergence < 10% |
| **C: Live Micro** | Min 12 weeks | 0.01 lots, daily review, Sharpe > 0.3, Max DD < 5% |

### Emergency Protocols

| Trigger | Action |
|---|---|
| Price moves >5 ATR in <5 min | Close ALL positions, halt 1 hour |
| Spread widens >10x normal | Close ALL positions, halt 1 hour |
| Broker disconnect >30s | Close ALL positions, halt 1 hour |
| MT5 terminal crash | Halt trading, graceful shutdown, manual intervention |
| Model inference timeout >5s | Halt trading, fallback to rules-only |
| Daily equity loss >3% | Hard stop, no new trades until 00:00 broker time |
| Daily equity loss >1.5% | Soft warning, reduce position size 50% |
| Margin level <300% | Block new orders |
| Margin level <150% | Emergency close all |

### Files to Create/Modify
- **New:** `risk_engine.py` (comprehensive pre-trade/post-trade checks), `event_bus.py` (bar close event stream), `backtest_engine_v2.py` (event-driven), `validation_pipeline.py` (backtest→paper→live), `emergency_protocol.py`
- **Modify:** `mt5_AFxAutoTrader_v1.py` (single-process event loop), `indicators.py` (bar close detection), `execution_compliance.py` (wire PositionLimitMonitor, add price tolerance), `brain_v1.py` (portfolio risk cap), `brain_v6.py` (dynamic spread rejection), `config.py` (risk thresholds)

---

## PLAN 5: Quantum Architecture — Watchdog, Session Filter, Temporal Alignment, Alert Wiring

### Redundancy Check
This blueprint is ~70% covered by Plans 1-4. Genuinely new items:

| New Item | In Plans 1-4? | Value |
|---|---|---|
| Failover Watchdog (heartbeat + auto-restart) | ❌ Not anywhere | **CRITICAL** — threads die silently, nothing restarts them |
| Market Session Filter (trading hours mask) | ⚠️ Session detection exists but NOT used as a gate | **HIGH** — prevents trading in dead zones |
| Open candle masking | ⚠️ Flagged in master plan but NOT implemented | **HIGH** — eliminates lookahead bias |
| Forward-fill temporal alignment | ⚠️ Flagged but NOT implemented | **HIGH** — cross-TF causality |
| Wire alerts to crash/error events | ❌ Alerts only fire on trade open/close | **HIGH** — operator visibility |

### What Already Exists (KEEP)
| Feature | Status |
|---|---|
| `AlertManager` with Telegram/Discord | ✅ Exists — only wired to trade open/close |
| `is_tradeable_now()` 4-level gate | ✅ Exists — terminal, symbol, tick freshness, rate freshness |
| `get_current_session()` (asian/london/overlap/ny/dead) | ✅ Exists — used for tagging, NOT gating |
| `SystemMonitor` health checks | ✅ Exists — internal only, no external alerts |
| `MLScorer` conditional gate | ✅ Already runs only when brain says "trade" |

### Integration Plan (W0-W4)

| Priority | Change | Impact | Effort |
|---|---|---|---|
| **W0** | Failover Watchdog — heartbeat monitor + auto-restart + crash alert | **Survival** — prevents silent death | Medium |
| **W1** | Wire alerts to ALL error/crash events (not just trade open/close) | **Visibility** — operator knows immediately | Low |
| **W2** | Market Session Filter — configurable trading hours mask + weekend filter | **Safety** — no trading in dead zones | Low |
| **W3** | Open candle masking — exclude current incomplete bar from all calculations | **Data integrity** — eliminates lookahead | Low |
| **W4** | Forward-fill temporal alignment — align all TFs to M1 timestamp grid | **Causality** — cross-TF consistency | Medium |

### Implementation Details

**W0 — Failover Watchdog:**
```python
class FailoverWatchdog:
    def __init__(self, tier2_process, heartbeat_timeout=60):
        self.tier2 = tier2_process
        self.timeout = heartbeat_timeout
        self.last_heartbeat = time.time()
    
    def record_heartbeat(self):
        self.last_heartbeat = time.time()
    
    def monitor(self):
        while True:
            if time.time() - self.last_heartbeat > self.timeout:
                logger.critical("Tier 2 heartbeat timeout — restarting")
                self.tier2.terminate()
                self.tier2.start()
                self.alert_manager.send_telegram("watchdog", "Tier 2 restarted after crash")
                self.last_heartbeat = time.time()
            time.sleep(10)
```

**W1 — Alert Wiring (currently 4 lines, needs ~20 more):**
```python
# Wire to these events:
# - Thread crash/unhandled exception → alerts.send_telegram("crash", ...)
# - Drawdown circuit breaker trip → alerts.send_telegram("circuit_breaker", ...)
# - Black swan detection → alerts.send_telegram("black_swan", ...)
# - MT5 disconnect → alerts.send_telegram("mt5_disconnect", ...)
# - Model inference timeout → alerts.send_telegram("model_timeout", ...)
# - Daily loss limit hit → alerts.send_telegram("daily_loss", ...)
```

**W2 — Market Session Filter:**
```python
# config.py additions:
TRADING_HOURS_ENABLED = True
TRADING_SESSIONS = {
    "london": {"start": 7, "end": 16},   # UTC
    "new_york": {"start": 12, "end": 21},
}
WEEKEND_TRADING = False
HOLIDAY_CALENDAR = []  # List of dates to skip

# indicators.py addition:
def is_valid_session():
    now = datetime.utcnow()
    if not WEEKEND_TRADING and now.weekday() >= 5:
        return False
    if now.date() in HOLIDAY_CALENDAR:
        return False
    hour = now.hour
    return any(s["start"] <= hour < s["end"] for s in TRADING_SESSIONS.values())
```

**W3 — Open Candle Masking:**
```python
# In every mt5.copy_rates_from_pos() call:
rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 501)
rates = rates[:-1]  # Drop the last (incomplete) candle
# Exception: M1 current bar is ALLOWED for tick freshness check only
```

**W4 — Forward-Fill Temporal Alignment:**
```python
# New utility: align_to_m1_grid()
def align_to_m1_grid(m1_rates, higher_tf_rates, higher_tf):
    """
    Forward-fill higher TF data onto M1 timestamp grid.
    Each M1 bar gets the LAST CLOSED higher-TF bar's values.
    """
    m1_times = pd.Series(m1_rates['time'])
    ht_df = pd.DataFrame(higher_tf_rates)
    ht_df = ht_df.set_index('time')
    # Reindex to M1 times, forward-fill
    aligned = ht_df.reindex(m1_times, method='ffill')
    return aligned
```

### Files to Create/Modify
- **New:** `watchdog.py` (FailoverWatchdog class)
- **Modify:** `mt5_AFxAutoTrader_v1.py` (integrate watchdog, wire alerts to crash events), `indicators.py` (add `is_valid_session()`, open candle masking), `config.py` (trading hours mask, holiday calendar), `alerts.py` (add error/crash alert methods), `brain_v1.py` (open candle masking in rate fetches)

### Paradigm Shift (Overrides Plans 1-3)
This blueprint **fundamentally challenges** the multi-process architecture:

| Plan 1-3 Assumption | Plan 4 Reality | Verdict |
|---|---|---|
| Multi-process bypasses GIL for speed | **MT5 API is synchronous/blocking** — data retrieval takes 100-500ms regardless. Multi-process adds IPC overhead without speeding up the bottleneck. | **ADOPT Plan 4** |
| <5ms end-to-end latency | **200-500ms is realistic** — MT5 `copy_rates` is blocking, broker execution adds 10-20ms | **ADOPT Plan 4** |
| 8-branch TCN + LightGBM ensemble | **Phased evolution**: rules → LightGBM → optional TCN. Prove simpler models fail first. | **ADOPT Plan 4** |
| Jump to live trading | **Mandatory 3-phase validation**: backtest (4wk) → paper (8wk) → live micro-lot (12wk) | **ADOPT Plan 4** |
| Risk management as enhancement | **Risk management as foundation** — most critical addition | **ADOPT Plan 4** |

### What Already Exists vs What's Missing

| Risk Item | Status | Location |
|---|---|---|
| Max 2% risk per trade | ✅ EXISTS | `brain_v1.py:627` — Kelly-based, capped at 2% |
| Kelly calculation | ✅ EXISTS | `brain_v1.py:194` — 0.5 Kelly scaling |
| Max 5% total account risk | ❌ MISSING | — |
| Price tolerance (10 pips) | ❌ MISSING | — |
| Spread rejection (>3x avg) | ⚠️ PARTIAL | `brain_v6.py:222` — hardcoded 50pts, not dynamic |
| Correlation blocking | ✅ EXISTS | `brain_v1.py:651` — max 2 correlated |
| Daily loss circuit breaker (-3%) | ❌ MISSING | Only 5% halt exists |
| Soft warning (-1.5%) | ❌ MISSING | — |
| Margin safety (300%/150%) | ❌ MISSING | Only 20% free margin check |
| Consecutive loss halting | ✅ EXISTS | `brain_v3.py:197` — 4-5 loss threshold |
| Rolling win rate | ✅ EXISTS | `brain_v1.py:111` — 50-trade lookback |
| Sharpe ratio monitoring | ✅ EXISTS | `brain_v1.py:132` — 100-trade lookback |
| Slippage monitoring | ✅ EXISTS | `brain_v2.py:379` — per-trade tracking |
| Order rejection rate | ❌ MISSING | Only error counting |

**Score: 7/14 fully exist, 1 partial, 6 missing**

### Integration Plan (S0-S8)

| Priority | Change | Impact | Effort |
|---|---|---|---|
| **S0** | Daily loss circuit breaker (-3% hard, -1.5% soft) + margin safety (300%/150%) | Critical risk gap | Low |
| **S1** | Price tolerance (10 pips) + dynamic spread rejection (3x avg) | Prevent toxic fills | Low |
| **S2** | Max 5% total account risk + order rejection rate tracking | Portfolio-level safety | Medium |
| **S3** | Event-driven bar close detection (replace schedule polling) | Eliminate temporal misalignment | Medium |
| **S4** | Event-driven backtester (replace vectorized BacktestEngine) | Realistic validation | High |
| **S5** | Phased model: Phase 1 = rules + 2-3 indicators, Phase 2 = LightGBM | Pragmatic ML | Medium |
| **S6** | 3-phase validation pipeline (backtest → paper → live) | Non-negotiable safety path | High |
| **S7** | Single-process event loop (override multi-process from Plans 1-3) | Simplicity, determinism | High |
| **S8** | Emergency protocols (black swan >5 ATR, spread >10x, disconnect >30s) | Survival | Medium |

### Architecture Override

**Plans 1-3 proposed:** Multi-process Tier 1/Tier 2/Tier 3 with IPC queues.
**Plan 4 proposes:** Single-process event-driven with thread pool.

```
┌─────────────────────────────────────────────────────────────┐
│                    SINGLE PYTHON PROCESS                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  MT5 I/O    │  │  Event      │  │  Thread Pool      │  │
│  │  Adapter    │◄─┤  Loop       │◄─┤  (CPU-Bound Work) │  │
│  │  (Blocking) │  │  (Asyncio)  │  │  (Model Inference)│  │
│  └──────┬──────┘  └──────┬──────┘  └─────────────────────┘  │
│         │                │                                     │
│         ▼                ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │           STATE MACHINE (Single Source of Truth)        │   │
│  │  Portfolio State | Risk Limits | Signal Queue           │   │
│  │  Order History | Drawdown Tracker | Position Sizing     │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Why single-process wins:**
- MT5 API is single-threaded; multiple processes compete for the same terminal lock
- Eliminates IPC serialization overhead, queue backpressure, debugging complexity
- GIL is released during numpy/ONNX operations — thread pool is sufficient
- Centralized state machine enables deterministic replay for debugging

### Model Phased Evolution

| Phase | Duration | Model | Goal |
|---|---|---|---|
| Phase 1 (Wks 1-4) | Rules + EMA/RSI/ATR | Prove infrastructure works | Sharpe > 0.5 |
| Phase 2 (Wks 5-12) | LightGBM (20-50 features) | ML edge validation | Walk-forward Sharpe > 0.8 |
| Phase 3 (Mo 4-6+) | Single-branch 1D-CNN/TCN (ONNX) | Only if Phase 2 saturates | Must outperform Phase 2 |

### Validation Pipeline (Non-Negotiable)

| Phase | Duration | Requirements |
|---|---|---|
| **A: Backtest** | Min 4 weeks | Walk-forward, 12mo+ OOS, spread+slippage, Monte Carlo (1000 runs), Sharpe > 0.8, Max DD < 15% |
| **B: Paper** | Min 8 weeks | Same code as backtest, real ticks, simulated execution, P&L divergence < 10% |
| **C: Live Micro** | Min 12 weeks | 0.01 lots, daily review, Sharpe > 0.3, Max DD < 5% |

### Emergency Protocols

| Trigger | Action |
|---|---|
| Price moves >5 ATR in <5 min | Close ALL positions, halt 1 hour |
| Spread widens >10x normal | Close ALL positions, halt 1 hour |
| Broker disconnect >30s | Close ALL positions, halt 1 hour |
| MT5 terminal crash | Halt trading, graceful shutdown, manual intervention |
| Model inference timeout >5s | Halt trading, fallback to rules-only |
| Daily equity loss >3% | Hard stop, no new trades until 00:00 broker time |
| Daily equity loss >1.5% | Soft warning, reduce position size 50% |
| Margin level <300% | Block new orders |
| Margin level <150% | Emergency close all |

### Files to Create/Modify
- **New:** `risk_engine.py` (comprehensive pre-trade/post-trade checks), `event_bus.py` (bar close event stream), `backtest_engine_v2.py` (event-driven), `validation_pipeline.py` (backtest→paper→live), `emergency_protocol.py`
- **Modify:** `mt5_AFxAutoTrader_v1.py` (single-process event loop), `indicators.py` (bar close detection), `execution_compliance.py` (wire PositionLimitMonitor, add price tolerance), `brain_v1.py` (portfolio risk cap), `brain_v6.py` (dynamic spread rejection), `config.py` (risk thresholds)

---

## Cross-Plan Dependencies

| Plan | Depends On | Blocks |
|---|---|---|
| Plan 1 P0 (Per-symbol process) | — | **OVERRIDDEN by Plan 4 S7** (single-process) |
| Plan 1 P1 (Asyncio) | — | **REFINED by Plan 4 S7** (asyncio within single process) |
| Plan 2 Q0 (Shared ProcessPool) | — | **OVERRIDDEN by Plan 4 S7** |
| Plan 2 Q1 (Ring buffer) | — | **SUPERSEDED by Plan 4 S3** (event-driven bar close) |
| Plan 2 Q3 (Per-TF normalization) | — | Still valid, feeds into Plan 4 S5 |
| Plan 4 S0 (Daily loss + margin) | — | Foundation for all risk |
| Plan 4 S1 (Price tolerance + spread) | — | Foundation for execution |
| Plan 4 S3 (Event-driven bar close) | — | Replaces schedule polling, feeds S4/S5 |
| Plan 4 S4 (Event-driven backtester) | Plan 4 S3 | Prerequisite for S6 validation |
| Plan 4 S5 (Phased model) | — | Phase 1 = rules, Phase 2 = LightGBM |
| Plan 4 S6 (3-phase validation) | Plan 4 S4 | Non-negotiable path to live |
| Plan 4 S7 (Single-process event loop) | — | **Overrides Plans 1-3 multi-process** |
| Plan 4 S8 (Emergency protocols) | Plan 4 S0 | Survival layer |
| Plan 5 W0 (Failover Watchdog) | — | **CRITICAL** — threads die silently |
| Plan 5 W1 (Alert wiring to crashes) | — | Operator visibility |
| Plan 5 W2 (Market Session Filter) | — | Low-liquidity prevention |
| Plan 5 W3 (Open candle masking) | — | Lookahead elimination |
| Plan 5 W4 (Forward-fill alignment) | — | Cross-TF causality |

---

## Master Priority Queue (updated as plans arrive)

| # | Task | Plan | Priority | Status |
|---|---|---|---|---|
| 1 | Daily loss circuit breaker (-3%/-1.5%) + margin safety | Plan 4 S0 | CRITICAL | Pending |
| 2 | Price tolerance (10 pips) + dynamic spread rejection (3x avg) | Plan 4 S1 | CRITICAL | Pending |
| 3 | Emergency protocols (black swan, disconnect, timeout) | Plan 4 S8 | CRITICAL | Pending |
| 4 | Max 5% total account risk + order rejection tracking | Plan 4 S2 | HIGH | Pending |
| 5 | Event-driven bar close detection | Plan 4 S3 | HIGH | Pending |
| 6 | Single-process event loop (override multi-process) | Plan 4 S7 | HIGH | Pending |
| 7 | Event-driven backtester (replace vectorized) | Plan 4 S4 | HIGH | Pending |
| 8 | Phased model: Phase 1 = rules + indicators | Plan 4 S5 | HIGH | Pending |
| 9 | 3-phase validation pipeline (backtest→paper→live) | Plan 4 S6 | HIGH | Pending |
| 10 | Feature normalization (per-TF StandardScaler) | Plan 2 Q3 | HIGH | Pending |
| 11 | 500-candle standardization | Plan 1 P6 | HIGH | Pending |
| 12 | Structured JSON logging + health endpoint | Plan 2 Q6 | MEDIUM | Pending |
| 13 | Credential encryption | Plan 2 Q7 | MEDIUM | Pending |
| 14 | Failover Watchdog (heartbeat + auto-restart) | Plan 5 W0 | CRITICAL | Pending |
| 15 | Wire alerts to crash/error events | Plan 5 W1 | HIGH | Pending |
| 16 | Market Session Filter (trading hours mask) | Plan 5 W2 | HIGH | Pending |
| 17 | Open candle masking (exclude incomplete bar) | Plan 5 W3 | HIGH | Pending |
| 18 | Forward-fill temporal alignment (all TFs → M1 grid) | Plan 5 W4 | HIGH | Pending |
| 19 | ~~Per-symbol process isolation~~ | ~~Plan 1 P0~~ | ~~CRITICAL~~ | **OVERRIDDEN by Plan 4 S7** |
| 20 | ~~Shared ProcessPoolExecutor~~ | ~~Plan 2 Q0~~ | ~~HIGH~~ | **OVERRIDDEN by Plan 4 S7** |
| 21 | ~~Lock-free ring buffer~~ | ~~Plan 2 Q1~~ | ~~CRITICAL~~ | **SUPERSEDED by Plan 4 S3** |
| 22 | ~~Shared memory pool~~ | ~~Plan 3 R0~~ | ~~HIGH~~ | **OVERRIDDEN by Plan 4 S7** |
| 23 | ~~CPU core pinning~~ | ~~Plan 3 R1~~ | ~~HIGH~~ | **OVERRIDDEN by Plan 4 S7** |

---

## Files Modified (cumulative across all plans)

| File | Plans |
|---|---|
| `mt5_AFxAutoTrader_v1.py` | Plan 1, Plan 2, **Plan 4** |
| `config.py` | Plan 1, Plan 2, **Plan 4** |
| `indicators.py` | Plan 1, Plan 2, **Plan 4** |
| `ml_enhancements.py` | Plan 1, Plan 2, **Plan 4** |
| `brain_v11.py` | Plan 1 |
| `brain_v8.py` | Plan 2 |
| `brain_v1.py` | **Plan 4** (portfolio risk cap) |
| `brain_v6.py` | **Plan 4** (dynamic spread rejection) |
| `parallel_executor.py` | Plan 2 |
| `execution_compliance.py` | Plan 2, **Plan 4** |
| `logging_config.py` | Plan 2 |
| **New** `risk_engine.py` | **Plan 4** |
| **New** `event_bus.py` | **Plan 4** |
| **New** `backtest_engine_v2.py` | **Plan 4** |
| **New** `validation_pipeline.py` | **Plan 4** |
| **New** `emergency_protocol.py` | **Plan 4** |
| **New** `ring_buffer.py` | Plan 2 |
| **New** `health_check.py` | Plan 2 |
| **New** `credential_store.py` | Plan 2 |
| **New** `structured_logging.py` | Plan 2 |
| **New** `retrain_pipeline.py` | Plan 3 |
| **New** `tests/test_ipc.py` | Plan 3 |
| **New** `tests/test_retrain.py` | Plan 3 |
| **New** `watchdog.py` | **Plan 5** |
| **Modify** `alerts.py` | **Plan 5** (wire to crash/error events) |
