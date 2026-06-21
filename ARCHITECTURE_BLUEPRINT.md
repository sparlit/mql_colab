# AFX AUTOTRADER v2 — ARCHITECTURE BLUEPRINT
# Zero-Tolerance Full-Stack Design Document
# Generated: 2026-06-21

## 1. SYSTEM IDENTITY

**Project**: AFX AutoTrader v2 — Fully Autonomous Forex Trading System
**OS**: Windows (native), MT5 Terminal (host), Docker (deployment)
**Languages**: Python 3.11+ (core engine), Rust (performance-critical components)
**Hybrid Model**: Multithreading + Parallel Processing + Async I/O

---

## 2. FIVE-LAYER SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────┐
│  LAYER 1: DATA INGESTION                                │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │
│  │ MT5 Terminal │ │ Market Data  │ │ Alt / News   │     │
│  │ (async_mt5)  │ │ APIs         │ │ Feed         │     │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘     │
│         └────────────────┼────────────────┘             │
│                          ▼                              │
│  LAYER 2: FEATURE ENGINEERING                          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │
│  │ Indicators   │ │ Pattern Rec  │ │ ML Features  │     │
│  │ (multithread)│ │ (multithread)│ │ (multiprocess)    │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘     │
│         └────────────────┼────────────────┘             │
│                          ▼                              │
│  LAYER 3: MODEL TRAINING (parallel, per strategy)      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │
│  │ Swing Model  │ │ Day Model    │ │ Carry Model  │...  │
│  │ (ProcessPool)│ │ (ProcessPool)│ │ (ProcessPool)│     │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘     │
│         └────────────────┼────────────────┘             │
│                          ▼                              │
│  LAYER 4: DECISION ENGINE (parallel strategy eval)      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │
│  │ Risk Engine  │ │ Position     │ │ Strategy     │     │
│  │ (threaded)   │ │ Manager      │ │ Router       │     │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘     │
│         └────────────────┼────────────────┘             │
│                          ▼                              │
│  LAYER 5: TRADE EXECUTION                               │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │
│  │ Order Manager│ │ Broker API   │ │ MT5 Adapter  │     │
│  │ (async)      │ │ (async)      │ │ (async_mt5)  │     │
│  └──────────────┘ └──────────────┘ └──────────────┘     │
└─────────────────────────────────────────────────────────┘
```

---

## 3. THREADING MODEL

### Core Principle
- **ONLY** MT5 communication is async — `async_mt5.py` + `mt5_mcp.py`
- **ALL** other processing uses `ThreadPoolExecutor` (I/O-bound) or `ProcessPoolExecutor` (CPU-bound)
- No blocking calls in the async MT5 path

### Thread Pools

| Pool Name | Type | Workers | Purpose |
|-----------|------|---------|---------|
| `mt5_async_pool` | ThreadPool | 4-8 | MT5 async I/O only |
| `analysis_pool` | ThreadPool | CPU count | Feature engineering, indicator calcs |
| `model_pool` | ProcessPool | CPU count | ML model inference |
| `training_pool` | ProcessPool | CPU count | Model training (off main thread) |
| `io_pool` | ThreadPool | 8-16 | DB writes, file I/O, HTTP |
| `decision_pool` | ThreadPool | 4 | Decision evaluation per strategy |

### Concurrency Limits
- MT5 calls: max 8 concurrent (connection pool)
- Strategy evaluation: max 4 concurrent per symbol
- Order submissions: max 2 concurrent per broker account

---

## 4. STRATEGY FRAMEWORK

### Magic Numbers (Unique per Strategy)
```
SWING_TRADE    = 100001
DAY_TRADE      = 200002
CARRY_TRADE    = 300003
SCALP_TRADE    = 400004
```

### Strategy Base Interface
```python
class BaseStrategy(ABC):
    MAGIC_NUMBER: int
    strategy_name: str
    timeframe_preference: list[str]

    @abstractmethod
    def analyze(self, market_data: MarketData) → TradeSignal
    @abstractmethod
    def calculate_position_size(self, signal: TradeSignal, risk: RiskProfile) → PositionSize
    @abstractmethod
    def get_stop_loss(self, signal: TradeSignal, price: float) → float
    @abstractmethod
    def get_take_profit(self, signal: TradeSignal, price: float) → float
    @abstractmethod
    def validate_entry_conditions(self, market_data: MarketData) → bool
```

### Strategy Mode Selection
- Global env var `ACTIVE_STRATEGY_MODE=SWING|DAY|CARRY|SCALP`
- `StrategyRouter` delegates to the active strategy
- All strategies can run in parallel for comparison mode

---

## 5. TRADING MODES

### 5.1 SWING TRADING (Default Start)
- **Magic**: 100001
- **Holding Period**: 1-7 days
- **Timeframe**: H4, D1
- **Risk Per Trade**: 1-2%
- **Max Open Trades**: 5
- **Indicators**: EMA 50/200, RSI, MACD, Bollinger Bands
- **MM Features**: Swing detection, trend continuation, reversal patterns

### 5.2 DAY TRADING
- **Magic**: 200002
- **Holding Period**: intraday (0-24h)
- **Timeframe**: M5, M15, H1
- **Risk Per Trade**: 0.5-1%
- **Max Open Trades**: 10
- **Indicators**: VWAP, EMA 9/21, RSI, Volume Profile
- **MM Features**: Intraday volatility filtering, news event avoidance

### 5.3 CARRY TRADING
- **Magic**: 300003
- **Holding Period**: 1-4 weeks
- **Timeframe**: D1, W1
- **Risk Per Trade**: 2-3%
- **Max Open Trades**: 3
- **Indicators**: Interest rate differential, roll analysis, EM sovereign spreads
- **MM Features**: Central bank policy tracking, roll yield optimization

### 5.4 SCALPING
- **Magic**: 400004
- **Holding Period**: seconds to minutes
- **Timeframe**: M1, M5
- **Risk Per Trade**: 0.1-0.25%
- **Max Open Trades**: 20
- **Indicators**: Level 2 orderbook, tick chart, EMA 5/15, Stochastic
- **MM Features**: Latency optimization, spread monitoring, tick-by-tick execution

---

## 6. MODULE MAP

| Module | Purpose | Public API | Magic |
|--------|---------|------------|-------|
| `mt5_mcp.py` | Sync shim for MT5 async calls | `mt5.initialize()`, `mt5.copyrates()`, `mt5.order_send()` | N/A |
| `async_mt5.py` | Async MT5 API wrappers | `async_initialize()`, `async_copyrates()`, `async_order_send()` | N/A |
| `strategy_base.py` | Base class for all strategies | `BaseStrategy`, `TradeSignal`, `PositionSize` | 0 |
| `strategy_swing.py` | Swing trading logic | `SwingStrategy(Magic=100001)` | 100001 |
| `strategy_day.py` | Day trading logic | `DayStrategy(Magic=200002)` | 200002 |
| `strategy_carry.py` | Carry trading logic | `CarryStrategy(Magic=300003)` | 300003 |
| `strategy_scalp.py` | Scalping logic | `ScalpStrategy(Magic=400004)` | 400004 |
| `strategy_router.py` | Routes to active strategy | `StrategyRouter.set_mode()`, `StrategyRouter.analyze()` | N/A |
| `brain_engine.py` | Unified brain (from v1-v11) | `BrainEngine.analyze()`, `BrainEngine.train()` | N/A |
| `risk_engine.py` | Unified risk management | `RiskEngine.calculate_position()`, `RiskEngine.validate_trade()` | N/A |
| `position_manager.py` | Position sizing & tracking | `PositionManager.open()`, `PositionManager.close()`, `PositionManager.get_暴露()` | N/A |
| `decision_engine.py` | Orchestrates all engines | `DecisionEngine.evaluate()`, `DecisionEngine.execute()` | N/A |
| `trade_executor.py` | Order execution with CB | `TradeExecutor.submit()`, `TradeExecutor.cancel()` | N/A |
| `backtest_engine.py` | Multi-strategy backtesting | `BacktestEngine.run()` | N/A |
| `ml_training_pipeline.py` | Multi-strategy ML training | `MLTrainingPipeline.train()`, `MLTrainingPipeline.optimize()` | N/A |
| `parallel_executor.py` | Unified task executor | `ParallelExecutor.submit()`, `ParallelExecutor.map()` | N/A |
| `native_proDashboard.py` | Native desktop dashboard | `ProDashboard.run()` | N/A |
| `web_dashboard.py` | Web dashboard (Flask) | `WebDashboard.run()` | N/A |
| `mt5_dashboard.py` | MT5 terminal dashboard | `MT5Dashboard.run()` | N/A |

---

## 7. DATA FLOW (Per Trade Cycle)

```
T+0ms   → MT5 tick arrives via async callback
T+5ms   → Tick queued to analysis_pool (ThreadPoolExecutor)
T+10ms  → Indicator calculation (multithreaded, 4 threads)
T+30ms  → Strategy.analyze() called (active strategy mode)
T+50ms  → RiskEngine.calculate_position() (threaded)
T+60ms  → DecisionEngine.evaluate() — final signal
T+65ms  → TradeExecutor.submit() → async_mt5 → MT5 broker
T+70ms  → Order confirmed → PositionManager updated
T+75ms  → All dashboards updated (WebSocket push)
T+100ms → Cycle complete, await next tick
```

---

## 8. DEPENDENCY GRAPH

```
mt5_mcp.py
  └─ async_mt5.py
       └─ MetaTrader5 Python SDK (external)
  └─ No other internal deps

strategy_router.py
  ├─ strategy_base.py
  ├─ strategy_swing.py
  ├─ strategy_day.py
  ├─ strategy_carry.py
  └─ strategy_scalp.py

decision_engine.py
  ├─ strategy_router.py
  ├─ risk_engine.py
  ├─ position_manager.py
  └─ trade_executor.py

parallel_executor.py
  ├─ strategy_router.py
  ├─ brain_engine.py
  ├─ ml_features.py
  └─ indicators.py

brain_engine.py (consolidated from v1-v11)
  ├─ indicators.py
  ├─ ml_features.py
  └─ pattern_recognition.py
```

---

## 9. DASHBOARD ARCHITECTURE

### 9.1 Native Pro Dashboard
- **Framework**: Custom tkinter/PyQt6 on Windows
- **Features**: Real-time P&L, open positions, strategy mode selector, risk meter, equity curve
- **Update**: Every 1 second via shared memory

### 9.2 Web Dashboard
- **Framework**: Flask + Flask-SocketIO
- **Features**: Full tradingview-style charts, all strategies, trade history, performance metrics
- **Update**: WebSocket push every tick

### 9.3 MT5 Terminal Dashboard
- **Integration**: MQL5 DLL callbacks
- **Features**: Native MT5 UI elements, indicator panels, expert advisory panel
- **Update**: Real-time via MT5 DLL bridge

---

## 10. GRACEFUL SHUTDOWN SEQUENCE

```
SIGTERM/SIGINT received
  → Set shutdown flag (atomic)
  → Stop accepting new trades
  → Cancel all pending async MT5 orders (with timeout)
  → Wait for in-flight decisions to complete (max 30s)
  → Close all ThreadPoolExecutors (wait for tasks)
  → Flush all position state to database
  → Export metadata.yaml for this run
  → Exit 0
```

---

## 11. FAILURE HANDLING

| Failure Point | Strategy |
|--------------|----------|
| MT5 disconnected | Retry with exponential backoff (1s, 2s, 4s, 8s, max 60s) |
| Order rejected | Circuit breaker opens, pause submissions for 30s |
| Brain returns invalid signal | Log error, skip trade, alert dashboard |
| Risk limit exceeded | Hard stop — no new positions, alert all dashboards |
| Database write fails | Queue to memory, retry with exponential backoff |
| Training process crashes | Restart with checkpoint resume |

---

## 12. REPRODUCIBILITY METADATA.YAML

```yaml
run_id: "uuid-v4"
timestamp_utc: "2026-06-21T00:00:00Z"
strategy_mode: "SWING"  # or DAY, CARRY, SCALP
random_seed: 42
data_hash: "sha256-of-training-data"
model_version: "v2.1.0"
python_version: "3.11"
mt5_build: 12345
git_commit: "abc123def"
performance_metrics:
  sharpe_ratio: 1.45
  max_drawdown: 0.12
  win_rate: 0.63
```

---

## 13. PERFORMANCE REQUIREMENTS

| Metric | Target |
|--------|--------|
| Tick-to-decision latency | <50ms (p99) |
| Tick-to-execution latency | <100ms (p99) |
| MT5 reconnection time | <5s |
| Dashboard update latency | <1s |
| Memory usage (idle) | <500MB |
| CPU usage (swing mode, idle) | <5% |
| Max concurrent MT5 connections | 8 |
| Strategy evaluation throughput | 1000/sec |

---

## 14. SECURITY REQUIREMENTS

- All MT5 API keys stored in environment variables (no hardcoding)
- Database credentials via DATABASE_URL env var only
- No secrets in logs (structured logging with secret redaction)
- Input validation on all user-provided parameters
- Rate limiting on all HTTP endpoints
- SQL injection prevention via parameterized queries

---

## 15. DEPLOYMENT TARGETS

| Environment | Configuration |
|-------------|---------------|
| Windows Dev | Local MT5 terminal, SQLite, debug logging |
| Windows Prod | Local MT5, PostgreSQL, strict logging |
| Docker Dev | MT5 in separate container, docker-compose |
| Docker Prod | MT5 in separate container, PostgreSQL, health checks |

---

*This document is the ground truth for the AFX AutoTrader v2 architecture.*
*All implementation must follow this blueprint exactly.*
*Any deviation requires documented design decision in ARCHITECTURE_DECISIONS.md.*