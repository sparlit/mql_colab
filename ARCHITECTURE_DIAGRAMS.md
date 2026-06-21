# AFX AutoTrader v2 — Architecture Diagrams
# Mermaid-format diagrams for system visualization

## 1. Five-Layer System Architecture

```mermaid
graph TB
    subgraph L1["Layer 1: Data Ingestion"]
        MT5["MT5 Terminal<br/>(async_mt5)"]
        MARKET["Market Data APIs"]
        NEWS["News / Alt Data"]
    end

    subgraph L2["Layer 2: Feature Engineering"]
        IND["Indicators<br/>(analysis_pool)"]
        PAT["Pattern Recognition<br/>(analysis_pool)"]
        MLF["ML Features<br/>(analysis_pool)"]
    end

    subgraph L3["Layer 3: Model Training"]
        SWING_M["Swing Model<br/>(training_pool)"]
        DAY_M["Day Model<br/>(training_pool)"]
        CARRY_M["Carry Model<br/>(training_pool)"]
        SCALP_M["Scalp Model<br/>(training_pool)"]
    end

    subgraph L4["Layer 4: Decision Engine"]
        RISK["Risk Engine<br/>(decision_pool)"]
        POS["Position Manager<br/>(decision_pool)"]
        ROUTER["Strategy Router<br/>(decision_pool)"]
    end

    subgraph L5["Layer 5: Trade Execution"]
        EXEC["Trade Executor<br/>(async)"]
        BROKER["Broker API<br/>(async)"]
        MT5_ADAPTER["MT5 Adapter<br/>(async_mt5)"]
    end

    MT5 --> IND
    MT5 --> PAT
    MT5 --> MLF
    MARKET --> IND
    NEWS --> MLF

    IND --> ROUTER
    PAT --> ROUTER
    MLF --> ROUTER

    SWING_M --> ROUTER
    DAY_M --> ROUTER
    CARRY_M --> ROUTER
    SCALP_M --> ROUTER

    ROUTER --> RISK
    RISK --> POS
    POS --> EXEC

    EXEC --> BROKER
    EXEC --> MT5_ADAPTER

    style MT5 fill:#1a1a2e,color:#fff
    style MT5_ADAPTER fill:#16213e,color:#fff
    style L1 fill:#0f3460,color:#fff
    style L2 fill:#533483,color:#fff
    style L3 fill:#e94560,color:#fff
    style L4 fill:#0f3460,color:#fff
    style L5 fill:#16213e,color:#fff
```

## 2. Threading Model

```mermaid
graph LR
    subgraph Async["Async I/O (async_mt5) — ThreadPool 4-8"]
        A_MT5["MT5 Calls"]
    end

    subgraph CPU_Bound["CPU-Bound (ProcessPoolExecutor)"]
        ML_INF["ML Inference"]
        TRAINING["Model Training"]
        FEATURES["Feature Engineering"]
    end

    subgraph IO_Bound["I/O-Bound (ThreadPoolExecutor)"]
        DB["Database Writes"]
        HTTP["HTTP/API Calls"]
        FILE["File I/O"]
    end

    subgraph Decision["Decision Threads (ThreadPoolExecutor 4)"]
        STRAT["Strategy Eval"]
        RISK_EVAL["Risk Calc"]
        POS_EVAL["Position Calc"]
    end

    style Async fill:#1a1a2e,color:#fff
    style CPU_Bound fill:#e94560,color:#fff
    style IO_Bound fill:#533483,color:#fff
    style Decision fill:#0f3460,color:#fff
```

## 3. Trade Execution Flow

```mermaid
sequenceDiagram
    participant MT5 as MT5 Terminal
    participant ASYNC as async_mt5
    participant POOL as analysis_pool
    participant BRAIN as BrainEngine
    participant ROUTER as StrategyRouter
    participant RISK as RiskEngine
    participant POS as PositionManager
    participant EXEC as TradeExecutor
    participant DB as Database

    MT5->>ASYNC: Tick (async callback)
    ASYNC->>POOL: Submit to thread pool
    POOL->>BRAIN: Calculate indicators (parallel)
    BRAIN-->>ROUTER: Market analysis
    ROUTER->>RISK: Evaluate risk
    RISK-->>POS: Position size
    POS-->>EXEC: Execute order
    EXEC->>MT5: async_order_send()
    MT5-->>EXEC: Order confirmed
    EXEC->>DB: Persist position state
    EXEC-->>ROUTER: Trade result
    ROUTER-->>MT5: Update dashboard (WebSocket)
```

## 4. Strategy Inheritance

```mermaid
classDiagram
    class BaseStrategy {
        <<abstract>>
        +MAGIC_NUMBER: int
        +strategy_name: str
        +timeframe_preference: list
        +analyze(MarketData) TradeSignal
        +calculate_position_size(TradeSignal, RiskProfile) PositionSize
        +get_stop_loss(TradeSignal, float) float
        +get_take_profit(TradeSignal, float) float
        +validate_entry_conditions(MarketData) bool
    }

    class SwingStrategy {
        +MAGIC_NUMBER = 100001
        +strategy_name = "SWING"
        +timeframe_preference = ["H4", "D1"]
        +analyze(MarketData) TradeSignal
    }

    class DayStrategy {
        +MAGIC_NUMBER = 200002
        +strategy_name = "DAY"
        +timeframe_preference = ["M5", "M15", "H1"]
        +analyze(MarketData) TradeSignal
    }

    class CarryStrategy {
        +MAGIC_NUMBER = 300003
        +strategy_name = "CARRY"
        +timeframe_preference = ["D1", "W1"]
        +analyze(MarketData) TradeSignal
    }

    class ScalpStrategy {
        +MAGIC_NUMBER = 400004
        +strategy_name = "SCALP"
        +timeframe_preference = ["M1", "M5"]
        +analyze(MarketData) TradeSignal
    }

    class StrategyRouter {
        +active_strategy: BaseStrategy
        +set_mode(mode: str)
        +analyze(MarketData) TradeSignal
    }

    BaseStrategy <|-- SwingStrategy
    BaseStrategy <|-- DayStrategy
    BaseStrategy <|-- CarryStrategy
    BaseStrategy <|-- ScalpStrategy
    StrategyRouter --> BaseStrategy
```

## 5. Parallel Executor Architecture

```mermaid
graph TB
    subgraph TaskQueue["Task Queue (PriorityQueue)"]
        T1["Task 1 (priority=1)"]
        T2["Task 2 (priority=2)"]
        T3["Task 3 (priority=3)"]
    end

    subgraph ThreadPools["Thread Pools"]
        A_POOL["analysis_pool<br/>(CPU_count threads)"]
        D_POOL["decision_pool<br/>(4 threads)"]
        IO_POOL["io_pool<br/>(8-16 threads)"]
    end

    subgraph ProcessPools["Process Pools"]
        M_POOL["model_pool<br/>(CPU_count processes)"]
        TRAIN_POOL["training_pool<br/>(CPU_count processes)"]
    end

    T1 --> A_POOL
    T2 --> D_POOL
    T3 --> IO_POOL

    A_POOL --> M_POOL
    D_POOL --> M_POOL
    IO_POOL --> TRAIN_POOL
```

## 6. Dashboard Architecture

```mermaid
graph TB
    subgraph DataSource["Data Source"]
        CORE["Core Engine<br/>(parallel_executor)"]
    end

    subgraph Native["Native Dashboard"]
        NATIVE["native_proDashboard.py<br/>PyQt6/tkinter"]
        NATIVE_DB[(Shared Memory)]
    end

    subgraph Web["Web Dashboard"]
        WEB["web_dashboard.py<br/>Flask + SocketIO"]
        WS["WebSocket<br/>(every tick)"]
    end

    subgraph MT5["MT5 Terminal"]
        MT5_UI["MT5 UI<br/>MQL5 Dashboard"]
        MT5_BRIDGE["DLL Bridge"]
    end

    CORE --> NATIVE_DB
    CORE --> WS
    WS --> WEB
    CORE --> MT5_BRIDGE
    MT5_BRIDGE --> MT5_UI

    style NATIVE fill:#1a1a2e,color:#fff
    style WEB fill:#533483,color:#fff
    style MT5_UI fill:#0f3460,color:#fff
    style CORE fill:#e94560,color:#fff
```

## 7. Graceful Shutdown

```mermaid
stateDiagram-v2
    [*] --> Running
    Running --> ShuttingDown: SIGTERM/SIGINT
    ShuttingDown --> NoNewTrades: Set shutdown flag
    NoNewTrades --> CancelPending: Cancel async MT5 orders
    CancelPending --> WaitInflight: Wait in-flight decisions (max 30s)
    WaitInflight --> ClosePools: Shutdown ThreadPoolExecutors
    ClosePools --> FlushDB: Persist position state
    FlushDB --> ExportMeta: Write metadata.yaml
    ExportMeta --> [*]: Exit 0
```

## 8. Circuit Breaker Pattern

```mermaid
stateDiagram-v2
    [*] --> Closed
    Closed --> Open: Error threshold exceeded
    Open --> HalfOpen: Timeout elapsed (30s)
    HalfOpen --> Closed: Success
    HalfOpen --> Open: Failure

    note right of Closed: Normal operation<br/>MT5 calls allowed
    note right of Open: Circuit open<br/>All MT5 calls blocked<br/>Exponential backoff
    note right of HalfOpen: Testing circuit<br/>1 probe call allowed
```