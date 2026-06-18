import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import threading
import queue
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from brain_v1 import Brain
from brain_v2 import BrainV2
from brain_v3 import BrainV3
from brain_v4 import BrainV4
from brain_v5 import BrainV5
from brain_v6 import BrainV6
from brain_v7 import BrainV7
from brain_v8 import BrainV8
from brain_v9 import BrainV9
from brain_v10 import BrainV10
from brain_v11 import BrainV11
from mt5_exporter import MT5DataExporter
from logging_config import setup_logging
from parallel_executor import get_executor, shutdown_executor
from alerts import get_alert_manager
from metrics import get_metrics
from integration import (
    get_order_flow, get_pattern_recognition, get_ml_enhancements,
    get_market_intelligence, get_execution_optimization, get_execution_compliance,
    get_risk_advanced, get_portfolio_risk, get_data_analytics,
    get_cache_layer, get_ai_advanced, get_institutional_analytics,
    get_portfolio_engineering, get_quant_models,
)
from config import (
    MAGIC_NUMBER, SCAN_SYMBOLS, PREFERRED_SYMBOLS, MAX_SPREAD_POINTS, MAX_SYMBOLS,
    COOLDOWN_SECONDS, SCAN_INTERVAL, STATUS_INTERVAL, ANALYSIS_WORKERS, SCANNER_WORKERS,
    CORRELATION_WORKERS, POSITION_WORKERS, MONITOR_INTERVAL, DASHBOARD_PORT, EXPORT_INTERVAL,
    SCAN_INTERVAL_PARALLEL, SYSTEM_TIER, SYSTEM_CPU_NAME, SYSTEM_CPU_COUNT, SYSTEM_CPU_PHYSICAL,
    SYSTEM_CPU_FREQ, SYSTEM_CPU_ARCH, SYSTEM_CPU_USAGE,
    SYSTEM_MEMORY_GB, SYSTEM_MEMORY_AVAIL_GB, SYSTEM_MEMORY_PCT, SYSTEM_SWAP_GB,
    SYSTEM_DISK_TOTAL_GB, SYSTEM_DISK_FREE_GB, SYSTEM_DISK_PCT,
    SYSTEM_GPU_COUNT, SYSTEM_GPU_NAME, SYSTEM_GPU_VENDOR, SYSTEM_GPU_VRAM_GB,
    SYSTEM_GPU_CORES, SYSTEM_GPU_COMPUTE_CAP, SYSTEM_GPU_DRIVER,
    SYSTEM_GPU_CLOCK, SYSTEM_GPU_POWER,
    SYSTEM_GPU_TEMP, SYSTEM_GPU_UTIL, SYSTEM_GPU_CUDA, SYSTEM_GPU_OPENCL,
    SYSTEM_PLATFORM, SYSTEM_HOSTNAME, PROCESS_WORKERS, IO_WORKERS,
    GPU_ENABLED, GPU_BATCH_SIZE, BRAIN_TIMEOUT,
    MAGIC_SCALPING, MAGIC_DAY_TRADING, MAGIC_SWING, MAGIC_POSITION,
    MAGIC_TECHNICAL, MAGIC_FUNDAMENTAL, MAGIC_SENTIMENT, MAGIC_TREND,
    MAGIC_COUNTER_TREND, MAGIC_BREAKOUT, MAGIC_RANGE, MAGIC_TMC,
    MAGIC_BRAIN_V1, MAGIC_BRAIN_V2, MAGIC_BRAIN_V5, MAGIC_BRAIN_V6,
    MAX_ORDERS_PER_SECOND, MAX_ORDERS_PER_MINUTE,
    is_system_magic, get_magic_info,
)

logger = logging.getLogger(__name__)

# ==========================================
# CONFIGURATION (from config.py)
# ==========================================
TIMEFRAME = mt5.TIMEFRAME_M1
SYMBOL_GROUPS = ["forex", "metals", "crypto", "indices", "stocks"]
# ==========================================

_validation_pipeline = None


class MT5DataFetcher:
    def __init__(self):
        self.account_info = {}
        self.symbols_info = {}
        self.tradeable_symbols = []
        self._last_refresh = 0
        self._lock = threading.RLock()
        self._cache = None

    def _get_cache(self):
        if self._cache is None:
            try:
                self._cache = get_cache_layer()
            except Exception:
                pass
        return self._cache

    def refresh_all(self):
        cache = self._get_cache()
        if cache:
            # Try to load from cache first
            cached_symbols = cache.get("symbols_info")
            if cached_symbols and (time.time() - self._last_refresh) < 300:
                self.symbols_info = cached_symbols
                self.tradeable_symbols = [s for s, info in cached_symbols.items() if info.get("visible") and info.get("trade_mode") != 0]
                return
        
        with self._lock:
            self._refresh_account()
            self._refresh_symbols()
            self._last_refresh = time.time()
            
            # Cache the results
            if cache:
                try:
                    cache.set("symbols_info", self.symbols_info, ttl=300)
                except Exception:
                    pass

    def _refresh_account(self):
        acct = mt5.account_info()
        if acct:
            self.account_info = {
                "login": acct.login,
                "name": acct.name,
                "server": acct.server,
                "balance": acct.balance,
                "equity": acct.equity,
                "margin": acct.margin,
                "margin_free": acct.margin_free,
                "margin_level": acct.margin_level,
                "leverage": acct.leverage,
                "currency": acct.currency,
                "profit": acct.profit,
                "credit": acct.credit,
                "company": acct.company,
            }

    def _refresh_symbols(self):
        all_symbols = mt5.symbols_get()
        if not all_symbols:
            return
        self.symbols_info = {}
        self.tradeable_symbols = []
        safe_attrs = [
            "name", "description", "path", "point", "digits", "spread",
            "volume_min", "volume_max", "volume_step",
            "trade_tick_value", "trade_tick_size", "trade_contract_size",
            "trade_mode", "volume_real", "volume_limit",
            "margin_initial", "margin_maintenance",
            "session_open", "session_close", "session_aw",
            "trade_calc_mode", "filling_mode", "order_mode",
            "swap_long", "swap_short",
            "currency_base", "currency_profit", "currency_margin",
            "bank", "exchange",
        ]
        for sym in all_symbols:
            info = {}
            for attr in safe_attrs:
                try:
                    info[attr] = getattr(sym, attr, None)
                except (AttributeError, Exception) as e:
                    logger.debug("Attribute %s unavailable for %s: %s", attr, sym.name, e)
                    info[attr] = None
            info["visible"] = sym.visible
            self.symbols_info[sym.name] = info
            if sym.visible and sym.trade_mode != 0:
                self.tradeable_symbols.append(sym.name)

    def get_filtered_symbols(self):
        with self._lock:
            candidates = []
            for name in self.tradeable_symbols:
                info = self.symbols_info.get(name, {})
                spread = info.get("spread", 999)
                vol = info.get("volume_real", 0)
                trade_mode = info.get("trade_mode", 0)
                if trade_mode == 0:
                    continue
                if spread > MAX_SPREAD_POINTS:
                    continue
                score = 0
                if name in PREFERRED_SYMBOLS:
                    score += 100
                group = info.get("path", "").lower()
                for g in SYMBOL_GROUPS:
                    if g in group:
                        score += 10
                score += max(0, 50 - spread)
                candidates.append((name, score, spread, vol))
            candidates.sort(key=lambda x: x[1], reverse=True)
            return [c[0] for c in candidates[:MAX_SYMBOLS]]

    def get_symbol_info(self, name):
        with self._lock:
            return self.symbols_info.get(name, {})

    def get_account_info(self):
        with self._lock:
            return self.account_info.copy()

    def get_all_symbols_info(self):
        with self._lock:
            return self.symbols_info.copy()

    def print_account_summary(self):
        acct = self.get_account_info()
        logger.info("\n  ACCOUNT INFORMATION:")
        logger.info(f"    Login: {acct.get('login', '?')} | Name: {acct.get('name', '?')}")
        logger.info(f"    Server: {acct.get('server', '?')} | Company: {acct.get('company', '?')}")
        logger.info(f"    Balance: ${acct.get('balance', 0):,.2f} | Equity: ${acct.get('equity', 0):,.2f}")
        logger.info(f"    Margin: ${acct.get('margin', 0):,.2f} | Free: ${acct.get('margin_free', 0):,.2f}")
        logger.info(f"    Leverage: 1:{acct.get('leverage', '?')} | Currency: {acct.get('currency', '?')}")
        logger.info(f"    Profit: ${acct.get('profit', 0):,.2f} | Credit: ${acct.get('credit', 0):,.2f}")

    def print_symbols_summary(self):
        filtered = self.get_filtered_symbols()
        logger.info(f"\n  AVAILABLE SYMBOLS: {len(self.tradeable_symbols)} tradeable | {len(filtered)} selected")
        logger.info(f"  {'Symbol':<12} {'Spread':>8} {'Point':>10} {'Digits':>7} {'Vol Min':>8} {'Vol Max':>10} {'Swap L':>8} {'Swap S':>8}")
        logger.info(f"  {'-'*75}")
        for name in filtered[:15]:
            info = self.symbols_info.get(name, {})
            logger.info(f"  {name:<12} {info.get('spread', 0):>8} {info.get('point', 0):>10.5f} {info.get('digits', 0):>7} {info.get('volume_min', 0):>8} {info.get('volume_max', 0):>10} {info.get('swap_long', 0):>8.1f} {info.get('swap_short', 0):>8.1f}")
        if len(filtered) > 15:
            logger.info(f"  ... and {len(filtered) - 15} more")


class ThreadSafeState:
    def __init__(self):
        self._lock = threading.RLock()
        self._data = {}
        self._last_trade_time = {}
        self._last_status = {}
        self._last_confidence = {}
        self._last_regime = {}
        self._last_session = {}
        self._running = True

    def is_running(self):
        with self._lock:
            return self._running

    def stop(self):
        with self._lock:
            self._running = False

    def get_last_trade_time(self, symbol):
        with self._lock:
            return self._last_trade_time.get(symbol, datetime(2000, 1, 1))

    def set_last_trade_time(self, symbol, t):
        with self._lock:
            self._last_trade_time[symbol] = t

    def get_last_confidence(self, symbol):
        with self._lock:
            return self._last_confidence.get(symbol, 0)

    def set_last_confidence(self, symbol, c):
        with self._lock:
            self._last_confidence[symbol] = c

    def get_last_regime(self, symbol):
        with self._lock:
            return self._last_regime.get(symbol, "unknown")

    def set_last_regime(self, symbol, r):
        with self._lock:
            self._last_regime[symbol] = r

    def get_last_session(self, symbol):
        with self._lock:
            return self._last_session.get(symbol, "unknown")

    def set_last_session(self, symbol, s):
        with self._lock:
            self._last_session[symbol] = s

    def can_trade(self, symbol):
        with self._lock:
            # Check cooldown
            last = self._last_trade_time.get(symbol, datetime(2000, 1, 1))
            if (datetime.now() - last).total_seconds() < COOLDOWN_SECONDS:
                return False
            
            # Check MT5 terminal allows trading
            terminal = mt5.terminal_info()
            if terminal is None or not terminal.trade_allowed:
                return False

            # Check if symbol is tradeable
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                return False
            if symbol_info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
                return False
            
            # Check if tick data is available and fresh
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return False
            tick_age = (datetime.now() - datetime.fromtimestamp(tick.time)).total_seconds()
            # Handle broker time sync: negative age = broker ahead, treat as fresh
            if tick_age < 0:
                tick_age = 0
            if tick_age > 10:
                return False
            
            return True

    def set_data(self, key, value):
        with self._lock:
            self._data[key] = value

    def get_data(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)


class BrainChain:
    def __init__(self):
        self.v1 = Brain()
        self.v2 = BrainV2(self.v1)
        self.v3 = BrainV3(self.v2)
        self.v4 = BrainV4(self.v3)
        self.v5 = BrainV5(self.v4)
        self.v6 = BrainV6(self.v5)
        self.v7 = BrainV7(self.v6)
        self.v8 = BrainV8(self.v7)
        self.v9 = BrainV9(self.v8)
        self.v10 = BrainV10(self.v9)
        self.v11 = BrainV11(self.v10)  # Meta-brain orchestrator
        # Per-operation locks for better concurrency
        # NOTE: _analyze_lock intentionally REMOVED — allows all 12 SymbolAnalyzer
        # threads to run brain analysis in parallel (one chain per symbol).
        # V11 protects its own shared state (current_method, current_config) internally.
        self._execute_lock = threading.Lock()
        self._position_lock = threading.Lock()
        self._record_lock = threading.Lock()
        self._executor = get_executor()

    def analyze(self, symbol, timeframe):
        try:
            return self.v11.analyze(symbol, timeframe)
        except Exception as e:
            logger.error("Brain chain analysis failed for %s: %s", symbol, e, exc_info=True)
            return {"action": "hold", "confidence": 0, "direction": 0,
                    "direction_str": "NEUTRAL", "reason": f"Analysis error: {e}",
                    "lot": 0, "sl": 0, "tp": 0, "sl_points": 0, "tp_points": 0,
                    "signals": {}, "active": []}

    def execute_decision(self, decision, symbol):
        try:
            with self._execute_lock:
                return self.v11.execute_decision(decision, symbol)
        except Exception as e:
            logger.error("Trade execution failed for %s: %s", symbol, e, exc_info=True)
            return False

    def manage_positions(self, symbol):
        try:
            with self._position_lock:
                return self.v10.manage_positions(symbol)
        except Exception as e:
            logger.error("Position management failed for %s: %s", symbol, e, exc_info=True)
            return False

    def record_trade_close(self, ticket, price, profit, reason):
        with self._record_lock:
            self.v10.record_trade_close(ticket, price, profit, reason)

    def record_trade(self, profit):
        with self._record_lock:
            self.v10.record_trade(profit)

    def record_trade_open(self, *args, **kwargs):
        with self._record_lock:
            return self.v10.record_trade_open(*args, **kwargs)

    def record_v7_outcome(self, confidence, won, profit, regime, session, strategy):
        with self._record_lock:
            self.v7.record_trade_outcome(confidence, won, profit, regime, session, strategy)

    def record_v4_outcome(self, strategy, confidence, won, hour):
        with self._record_lock:
            self.v4.record_trade_outcome(strategy, confidence, won, hour)

    def record_v5_data(self, strategy, confidence, won, profit, session):
        with self._record_lock:
            self.v5.auto_weighter.record(strategy, won, profit)
            self.v5.edge_decay.record(confidence, won)
            self.v5.session_memory.record(session, won, profit)

    def save_v7_pattern(self, symbol, timeframe, profit, confidence):
        with self._record_lock:
            self.v7.save_pattern(symbol, timeframe, profit, confidence)

    def record_v11_outcome(self, method, won, pnl):
        with self._record_lock:
            self.v11.record_trade_outcome(method, won, pnl)

    def print_status(self):
        self.v10.print_status()
        v11_status = self.v11.get_status()
        logger.info(f"\n{'='*60}")
        logger.info(f"  BRAIN V11 — AUTONOMOUS META-BRAIN")
        logger.info(f"{'='*60}")
        logger.info(f"  Current Method: {v11_status['current_method']}")
        logger.info(f"  Config: SL={v11_status['config'].get('sl_atr_mult', '?')}x | TP={v11_status['config'].get('tp_atr_mult', '?')}x | Risk={v11_status['config'].get('risk_per_trade', '?')}%")
        logger.info(f"  Recent Methods: {', '.join(v11_status['recent_methods'])}")
        if v11_status['method_performance']:
            logger.info(f"  Method Performance:")
            for m, perf in v11_status['method_performance'].items():
                wr = perf.get('wins', 0) / max(perf.get('wins', 0) + perf.get('losses', 0), 1) * 100
                logger.info(f"    {m}: {wr:.0f}% WR ({perf['wins']}W/{perf['losses']}L) PnL=${perf['pnl']:.2f}")

    def get_dashboard_data(self):
        data = self.v10.get_dashboard_data()
        data['v11'] = self.v11.get_status()
        return data

    def full_scan(self):
        return self.v10.full_scan()


class SymbolAnalyzer(threading.Thread):
    """Tick-driven symbol analyzer.

    Instead of sleeping for a fixed interval, this thread polls MT5 for
    new ticks and runs the brain chain analysis on EVERY tick change.
    This ensures the system reacts to price movements instantly.
    """

    # Minimum time between analyses for the same symbol (seconds)
    # Prevents overwhelming the brain chain on extremely fast ticks
    MIN_ANALYSIS_INTERVAL = 0.2

    def __init__(self, symbol, brain_chain, state, result_queue):
        super().__init__(daemon=True)
        self.symbol = symbol
        self.brain = brain_chain
        self.state = state
        self.result_queue = result_queue
        self.name = f"Analyzer-{symbol}"
        self._last_tick_time = 0
        self._last_tick_vol = 0
        self._last_analysis_time = 0
        self._last_bar_time = 0  # Track bar close events

    def _has_new_tick(self):
        """Check if a new tick has arrived since last check."""
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return False, None
        # Detect new tick by time change OR volume change
        if tick.time != self._last_tick_time or tick.volume != self._last_tick_vol:
            self._last_tick_time = tick.time
            self._last_tick_vol = tick.volume
            return True, tick
        return False, tick

    def _has_new_bar(self):
        """Check if a new M1 bar has closed since last check.

        Returns True only when the current bar's open time differs from
        the last seen bar time — meaning the previous bar has closed.
        """
        try:
            rates = mt5.copy_rates_from_pos(self.symbol, TIMEFRAME, 0, 2)
            if rates is not None and len(rates) >= 2:
                current_bar_time = rates[-1]['time']
                if current_bar_time != self._last_bar_time:
                    self._last_bar_time = current_bar_time
                    return True
        except Exception:
            pass
        return False

    def run(self):
        while self.state.is_running():
            try:
                # === MT5 CONNECTION CHECK ===
                terminal = mt5.terminal_info()
                if terminal is None or not terminal.trade_allowed:
                    logger.warning("MT5 disconnected or trading disabled — waiting")
                    time.sleep(2)
                    continue

                # === BAR CLOSE EVENT LOOP ===
                # Only analyze when a new M1 bar closes — not on every tick
                if not self._has_new_bar():
                    time.sleep(0.5)  # Check for new bar every 500ms
                    continue

                # Rate-limit: don't analyze more than once per MIN_ANALYSIS_INTERVAL
                now = time.time()
                if (now - self._last_analysis_time) < self.MIN_ANALYSIS_INTERVAL:
                    continue
                self._last_analysis_time = now

                # Fetch current tick for dashboard state
                tick = mt5.symbol_info_tick(self.symbol)
                if tick is None:
                    time.sleep(0.5)
                    continue

                # === MARKET STATE GATE ===
                from indicators import is_tradeable_now
                tradeable = is_tradeable_now(self.symbol, TIMEFRAME)
                if not tradeable["can_trade"]:
                    # Store closed state for dashboard
                    import shared_state
                    shared_state.set_analysis(self.symbol, {
                        "symbol": self.symbol,
                        "tick_time": "--:--:--",
                        "tick_age_ms": 0,
                        "bid": 0, "ask": 0, "spread": 0,
                        "action": "hold",
                        "direction": "NEUTRAL",
                        "confidence": 0,
                        "method": "N/A",
                        "regime": "unknown",
                        "session": "unknown",
                        "analysis_ms": 0,
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "tick_count": 0,
                        "market_closed": True,
                        "close_reason": tradeable.get("reason", ""),
                    })
                    time.sleep(1)
                    continue

                # Check cooldown
                if not self.state.can_trade(self.symbol):
                    time.sleep(1)
                    continue

                # === RUN BRAIN CHAIN ON NEW TICK ===
                analysis_start = time.time()
                decision = self.brain.analyze(self.symbol, TIMEFRAME)
                analysis_ms = (time.time() - analysis_start) * 1000
                
                # Enhance decision with ML scoring
                try:
                    ml = get_ml_enhancements()
                    if ml and decision.get("action") == "trade":
                        features = ml.get("features")
                        scorer = ml.get("scorer")
                        if features and scorer:
                            feature_vector = features.get_feature_vector({
                                "confidence": decision.get("confidence", 0),
                                "direction": decision.get("direction", 0),
                                "regime": decision.get("v2_analysis", {}).get("regime", "unknown"),
                                "session": decision.get("v2_analysis", {}).get("session", "unknown"),
                            })
                            try:
                                normalizer = ml.get("normalizer")
                                if normalizer:
                                    feature_vector = normalizer.transform(TIMEFRAME, feature_vector)
                            except Exception:
                                pass
                            ml_score = scorer.predict(feature_vector)
                            if ml_score is not None and ml_score != 0.5:
                                decision["confidence"] = decision.get("confidence", 0) * 0.7 + ml_score * 0.3
                                decision["ml_enhanced"] = True
                            else:
                                try:
                                    from ml_enhancements import RulesBaseline
                                    baseline = RulesBaseline()
                                    rates = mt5.copy_rates_from_pos(self.symbol, TIMEFRAME, 0, 200)
                                    if rates is not None and len(rates) >= 50:
                                        import pandas as pd
                                        df_baseline = pd.DataFrame(rates)
                                        baseline_result = baseline.evaluate(df_baseline)
                                        baseline_conf = baseline_result.get("confidence", 0)
                                        baseline_action = baseline_result.get("action", "hold")
                                        if baseline_action != "hold" and baseline_conf > 0.3:
                                            decision["confidence"] = decision.get("confidence", 0) * 0.8 + baseline_conf * 0.2
                                            decision["baseline_enhanced"] = True
                                except Exception:
                                    pass
                except Exception as e:
                    logger.debug("ML enhancement failed: %s", e)

                # Store analysis state for dashboard
                import shared_state
                sym_info = mt5.symbol_info(self.symbol)
                spread = round((tick.ask - tick.bid) / sym_info.point) if sym_info else 0
                shared_state.set_analysis(self.symbol, {
                    "symbol": self.symbol,
                    "tick_time": datetime.fromtimestamp(tick.time).strftime("%H:%M:%S"),
                    "tick_age_ms": int((time.time() - tick.time) * 1000) if tick.time > 0 else 0,
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "spread": spread,
                    "action": decision.get("action", "hold"),
                    "direction": decision.get("direction_str", "NEUTRAL"),
                    "confidence": decision.get("confidence", 0),
                    "method": decision.get("v11", {}).get("method", "N/A") if decision.get("v11") else "N/A",
                    "regime": decision.get("v2_analysis", {}).get("regime", "unknown") if decision.get("v2_analysis") else "unknown",
                    "session": decision.get("v2_analysis", {}).get("session", "unknown") if decision.get("v2_analysis") else "unknown",
                    "analysis_ms": round(analysis_ms, 1),
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "tick_count": self._last_tick_vol,
                    "market_closed": False,
                })
                
                # Attach tick data to decision for execution
                decision["tick_time"] = tick.time
                decision["tick_bid"] = tick.bid
                decision["tick_ask"] = tick.ask

                self.result_queue.put({
                    "type": "decision",
                    "symbol": self.symbol,
                    "decision": decision,
                    "time": datetime.now(),
                })
            except Exception as e:
                self.result_queue.put({
                    "type": "error",
                    "symbol": self.symbol,
                    "error": str(e),
                    "time": datetime.now(),
                })
                time.sleep(1)


class PositionManager(threading.Thread):
    """Tick-driven position manager.

    Monitors open positions on every tick for each symbol.
    Checks trailing stops, take profits, and risk limits in real-time.
    """

    def __init__(self, brain_chain, state, symbols):
        super().__init__(daemon=True)
        self.brain = brain_chain
        self.state = state
        self.symbols = symbols
        self.name = "PositionManager"
        self._last_tick_times = {s: 0 for s in symbols}

    def run(self):
        while self.state.is_running():
            try:
                # Check each symbol for new ticks — manage positions on tick change
                for symbol in self.symbols:
                    tick = mt5.symbol_info_tick(symbol)
                    if tick is None:
                        continue
                    # Only manage if tick changed
                    if tick.time == self._last_tick_times.get(symbol):
                        continue
                    self._last_tick_times[symbol] = tick.time

                    self.brain.manage_positions(symbol)
                
                # Portfolio risk checks (less frequent — every 5s)
                try:
                    portfolio_risk = get_portfolio_risk()
                    if portfolio_risk:
                        drawdown = portfolio_risk.get("drawdown")
                        if drawdown:
                            acct = mt5.account_info()
                            if acct:
                                equity = acct.equity
                                peak = max(self.state.get_data("peak_equity", 0), equity)
                                self.state.set_data("peak_equity", peak)
                                current_dd = (peak - equity) / peak * 100 if peak > 0 else 0
                                if current_dd > 5.0:
                                    logger.warning("Drawdown circuit breaker: %.2f%% (threshold: 5%%)", current_dd)
                                    self.state.set_data("drawdown_circuit_breaker", "OPEN")
                                else:
                                    self.state.set_data("drawdown_circuit_breaker", "CLOSED")
                except Exception as e:
                    logger.debug("Portfolio risk check failed: %s", e)
                
                # Black swan detection (less frequent)
                try:
                    risk_adv = get_risk_advanced()
                    if risk_adv:
                        black_swan = risk_adv.get("black_swan")
                        if black_swan:
                            acct = mt5.account_info()
                            if acct:
                                equity = acct.equity
                                peak = self.state.get_data("peak_equity", 0)
                                if peak > 0:
                                    dd_pct = (peak - equity) / peak * 100
                                    if dd_pct > 10.0:
                                        logger.warning("BLACK SWAN DETECTED: Drawdown %.2f%% exceeds 10%% threshold", dd_pct)
                                        self.state.set_data("black_swan_detected", True)
                                        self.state.set_data("trading_halted", True)
                except Exception as e:
                    logger.debug("Advanced risk check failed: %s", e)
                
                # Small sleep to avoid 100% CPU when no ticks flowing
                time.sleep(0.05)
            except Exception as e:
                self.state.set_data("last_position_error", str(e))
                time.sleep(1)


class TradeChecker(threading.Thread):
    def __init__(self, brain_chain, state, symbols):
        super().__init__(daemon=True)
        self.brain = brain_chain
        self.state = state
        self.symbols = symbols
        self.name = "TradeChecker"
        self._last_check = {}
        self._processed_tickets = set()
        self._max_processed = 10000

    def run(self):
        while self.state.is_running():
            try:
                now = datetime.now()
                start = now - timedelta(seconds=STATUS_INTERVAL + 10)
                deals = mt5.history_deals_get(start, now, group="*")
                for symbol in self.symbols:
                    last = self._last_check.get(symbol, datetime.min)
                    if (now - last).total_seconds() < 15:
                        continue
                    self._last_check[symbol] = now

                    if not deals:
                        continue
                    for deal in deals:
                        if deal.ticket in self._processed_tickets:
                            continue
                        if is_system_magic(deal.magic) and deal.entry == mt5.DEAL_ENTRY_OUT:
                            self._processed_tickets.add(deal.ticket)
                            # Prune if too large
                            if len(self._processed_tickets) > self._max_processed:
                                self._processed_tickets = set(list(self._processed_tickets)[-5000:])
                            self.brain.record_trade_close(deal.ticket, deal.price, deal.profit, "mt5_close")
                            self.brain.record_trade(deal.profit)
                            conf = self.state.get_last_confidence(deal.symbol)
                            regime = self.state.get_last_regime(deal.symbol)
                            session = self.state.get_last_session(deal.symbol)
                            self.brain.record_v7_outcome(conf, deal.profit >= 0, deal.profit, regime, session, "combined")
                            self.brain.record_v4_outcome("combined", conf, deal.profit >= 0, now.hour)
                            self.brain.record_v5_data("combined", conf, deal.profit >= 0, deal.profit, session)
                            self.brain.save_v7_pattern(deal.symbol, TIMEFRAME, deal.profit, conf)
                            self.brain.record_v11_outcome("combined", deal.profit >= 0, deal.profit)
                            # Send trade close alert
                            try:
                                alerts = get_alert_manager()
                                alerts.alert_trade_close(deal.symbol, deal.profit, deal.price)
                            except Exception as e:
                                logger.debug("Trade close alert failed: %s", e)
                            # Record metrics
                            try:
                                metrics = get_metrics()
                                metrics.inc("trades_closed_total", labels={"symbol": deal.symbol, "result": "win" if deal.profit >= 0 else "loss"})
                                metrics.observe("trade_profit", deal.profit)
                            except Exception as e:
                                logger.debug("Metrics recording failed: %s", e)
                time.sleep(10)
            except Exception as e:
                self.state.set_data("last_checker_error", str(e))
                time.sleep(10)


class SystemMonitor(threading.Thread):
    def __init__(self, brain_chain, state):
        super().__init__(daemon=True)
        self.brain = brain_chain
        self.state = state
        self.name = "SystemMonitor"

    def run(self):
        while self.state.is_running():
            try:
                self.brain.v9._system_check()
                self.state.set_data("health_score", self.brain.v9.sys_monitor.get_health_score())
                self.state.set_data("cpu", self.brain.v9.sys_monitor.cpu.get_current())
                self.state.set_data("memory", self.brain.v9.sys_monitor.memory.get_current())
                time.sleep(MONITOR_INTERVAL)
            except Exception as e:
                self.state.set_data("monitor_error", str(e))
                time.sleep(10)


class StatusPrinter(threading.Thread):
    def __init__(self, brain_chain, state):
        super().__init__(daemon=True)
        self.brain = brain_chain
        self.state = state
        self.name = "StatusPrinter"

    def run(self):
        last_print = datetime.now()
        while self.state.is_running():
            try:
                now = datetime.now()
                if (now - last_print).total_seconds() >= STATUS_INTERVAL:
                    self.brain.print_status()
                    last_print = now
                time.sleep(5)
            except Exception as e:
                logger.warning("Status print error: %s", e)
                time.sleep(10)


class TradeExecutor(threading.Thread):
    def __init__(self, brain_chain, state, trade_queue):
        super().__init__(daemon=True)
        self.brain = brain_chain
        self.state = state
        self.trade_queue = trade_queue
        self.name = "TradeExecutor"
        self._order_times = []

    def run(self):
        while self.state.is_running():
            try:
                item = self.trade_queue.get(timeout=2)
                if item is None:
                    continue
                symbol = item["symbol"]
                decision = item["decision"]

                # === MARKET STATE GATE ===
                # Final validation before execution: reject if market closed or data stale
                # Also checks symbol-specific market closed cooldown
                if self.state.get_data("trading_halted"):
                    logger.warning("TradeExecutor: trading halted (black swan detected)")
                    continue
                from indicators import is_tradeable_now
                tradeable = is_tradeable_now(symbol)
                if not tradeable["can_trade"]:
                    logger.warning("TradeExecutor: rejecting %s — %s", symbol, tradeable["reason"])
                    continue

                if not self.state.can_trade(symbol):
                    continue

                # Check execution compliance before trading
                try:
                    compliance = get_execution_compliance()
                    if compliance:
                        position_limit = compliance.get("position_limit")
                        if position_limit:
                            limits = position_limit.check_limits(symbol)
                            if not limits["positions_ok"]:
                                logger.warning("Position limit reached for %s: %d/%d",
                                    symbol, limits["current_positions"], limits["limits"]["max_positions"])
                                continue
                        wash_trade = compliance.get("wash_trade")
                        if wash_trade:
                            # Check for wash trades (opposite trades at similar prices)
                            open_positions = mt5.positions_get()
                            for pos in (open_positions or []):
                                if pos.symbol == symbol and pos.type != (0 if decision.get("direction") == 1 else 1):
                                    tick = mt5.symbol_info_tick(symbol)
                                    sym_info = mt5.symbol_info(symbol)
                                    if tick and sym_info and abs(pos.price_open - (tick.ask if decision.get("direction") == 1 else tick.bid)) < 5 * sym_info.point:
                                        logger.warning("Wash trade detected for %s", symbol)
                                        continue
                except Exception as e:
                    logger.debug("Compliance check failed: %s", e)

                # Validation pipeline gate
                try:
                    if _validation_pipeline is not None and not _validation_pipeline.can_trade():
                        logger.debug("TradeExecutor: blocked by validation pipeline (phase=%s)",
                            _validation_pipeline.get_status()["phase"])
                        continue
                except Exception:
                    pass

                # Global order rate limiter
                now = time.time()
                recent_orders = [t for t in getattr(self, '_order_times', []) if now - t < 60]
                self._order_times = recent_orders
                if len(recent_orders) >= MAX_ORDERS_PER_MINUTE:
                    logger.warning("Order rate limit reached: %d orders in last 60s", len(recent_orders))
                    continue
                if recent_orders and now - recent_orders[-1] < 1.0 / MAX_ORDERS_PER_SECOND:
                    time.sleep(1.0 / MAX_ORDERS_PER_SECOND - (now - recent_orders[-1]))

                exec_start = time.time()
                result = self.brain.execute_decision(decision, symbol)
                exec_latency_ms = (time.time() - exec_start) * 1000
                if result:
                    self._order_times.append(time.time())
                    self.state.set_last_trade_time(symbol, datetime.now())
                    self.state.set_last_confidence(symbol, decision.get("confidence", 0))
                    v2_info = decision.get("v2_analysis", {})
                    self.state.set_last_regime(symbol, v2_info.get("regime", "unknown"))
                    self.state.set_last_session(symbol, v2_info.get("session", "unknown"))

                    tick = mt5.symbol_info_tick(symbol)
                    price = result.get("price", tick.ask if decision.get("direction") == 1 else tick.bid) if isinstance(result, dict) else (tick.ask if decision.get("direction") == 1 else tick.bid if tick else 0)
                    ticket = result.get('order', 0) if isinstance(result, dict) else 0
                    self.brain.record_trade_open(
                        ticket, symbol, decision.get("direction"), decision.get("lot", 0),
                        price, decision.get("sl", 0), decision.get("tp", 0),
                        decision.get("confidence", 0), decision.get("active", []),
                        self.state.get_last_regime(symbol), self.state.get_last_session(symbol)
                    )
                    self.state.set_data(f"last_trade_{symbol}", {
                        "time": datetime.now().isoformat(),
                        "direction": decision.get("direction_str"),
                        "confidence": decision.get("confidence"),
                        "lot": decision.get("lot"),
                    })
                    # Record execution metrics
                    try:
                        eo = get_execution_optimization()
                        if eo:
                            fill_rate = eo.get("fill_rate")
                            if fill_rate:
                                # Record fill rate with actual latency
                                fill_rate.record_fill({
                                    "symbol": symbol,
                                    "direction": decision.get("direction_str"),
                                    "expected_price": price,
                                    "actual_price": price,
                                    "volume": decision.get("lot", 0),
                                    "latency_ms": round(exec_latency_ms, 1),
                                    "time": datetime.now().isoformat(),
                                })
                    except Exception as e:
                        logger.debug("Execution optimization failed: %s", e)
                    # Record metrics
                    try:
                        metrics = get_metrics()
                        metrics.inc("trades_opened_total", labels={"symbol": symbol, "direction": decision.get("direction_str")})
                        metrics.observe("trade_confidence", decision.get("confidence", 0))
                    except Exception as e:
                        logger.debug("Metrics recording failed: %s", e)
                    # Send trade alert
                    try:
                        alerts = get_alert_manager()
                        alerts.alert_trade_open(symbol, decision.get("direction", 0),
                            decision.get("lot", 0), price, decision.get("confidence", 0))
                    except Exception as e:
                        logger.debug("Trade alert failed: %s", e)
            except queue.Empty:
                continue
            except Exception as e:
                self.state.set_data("executor_error", str(e))
                time.sleep(2)


class ParallelScanner(threading.Thread):
    def __init__(self, brain_chain, state, symbols):
        super().__init__(daemon=True)
        self.brain = brain_chain
        self.state = state
        self.symbols = symbols
        self.name = "ParallelScanner"
        self._last_full_scan = 0
        self._executor = get_executor()

    def _scan_symbol_mtf(self, symbol):
        try:
            return symbol, self.brain.v10.get_symbol_mtf(symbol)
        except Exception as e:
            logger.debug("MTF scan failed for %s: %s", symbol, e)
            return symbol, {}

    def _scan_asset(self, symbol):
        try:
            return symbol, self.brain.v10.get_asset_price(symbol)
        except Exception as e:
            logger.debug("Asset scan failed for %s: %s", symbol, e)
            return symbol, {}

    def run(self):
        while self.state.is_running():
            try:
                now = time.time()
                if now - self._last_full_scan < SCAN_INTERVAL_PARALLEL:
                    time.sleep(5)
                    continue
                self._last_full_scan = now

                # Submit all MTF scan tasks asynchronously
                mtf_futures = {}
                mtf_symbols = self.symbols[:15]
                for sym in mtf_symbols:
                    try:
                        future = self._executor.submit(self._scan_symbol_mtf, sym)
                        mtf_futures[sym] = future
                    except Exception as e:
                        logger.debug("MTF scan submit failed for %s: %s", sym, e)

                # Collect MTF results
                mtf_results = {}
                for sym, future in mtf_futures.items():
                    try:
                        result = future.result(timeout=30)
                        if result[1]:
                            mtf_results[result[0]] = result[1]
                    except Exception as e:
                        logger.debug("MTF scan failed for %s: %s", sym, e)

                # Submit all asset scan tasks asynchronously
                asset_futures = {}
                for sym in self.symbols:
                    try:
                        future = self._executor.submit(self._scan_asset, sym)
                        asset_futures[sym] = future
                    except Exception as e:
                        logger.debug("Asset scan submit failed for %s: %s", sym, e)

                # Collect asset results
                asset_results = {}
                for sym, future in asset_futures.items():
                    try:
                        result = future.result(timeout=30)
                        if result[1]:
                            asset_results[result[0]] = result[1]
                    except Exception as e:
                        logger.debug("Asset scan failed for %s: %s", sym, e)

                # Parallel correlation calculation
                corr_future = self._executor.submit(self.brain.v10.correlation.calculate_correlations, self.symbols[:20])
                try:
                    correlations = corr_future.result(timeout=30)
                except Exception as e:
                    logger.warning("Correlation calculation failed: %s", e)
                    correlations = {}

                # Update regime
                try:
                    regime, conf = self.brain.v10.regime_detector.detect(mtf_results, correlations)
                    self.state.set_data("market_regime", regime)
                    self.state.set_data("regime_confidence", conf)
                except Exception as e:
                    logger.debug("Regime detection failed: %s", e)

                # Collect order flow data for active symbols
                try:
                    order_flow = get_order_flow()
                    if order_flow:
                        for sym in self.symbols[:5]:
                            order_flow.on_tick(sym)
                except Exception as e:
                    logger.debug("Order flow collection failed: %s", e)

                # Collect pattern recognition data
                try:
                    patterns = get_pattern_recognition()
                    if patterns:
                        for sym in self.symbols[:5]:
                            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 100)
                            if rates is not None and len(rates) > 10:
                                import pandas as pd
                                df = pd.DataFrame(rates)
                                candlestick = patterns.get("candlestick")
                                if candlestick:
                                    candle_patterns = candlestick.classify(df)
                                    self.state.set_data(f"patterns_{sym}", candle_patterns)
                except Exception as e:
                    logger.debug("Pattern recognition failed: %s", e)

                # Collect market intelligence
                try:
                    intelligence = get_market_intelligence()
                    if intelligence:
                        news = intelligence.get("news")
                        if news:
                            events = news.get_upcoming_events()
                            self.state.set_data("upcoming_events", events)
                except Exception as e:
                    logger.debug("Market intelligence failed: %s", e)

                self.state.set_data("mtf_results", mtf_results)
                self.state.set_data("asset_prices", asset_results)
                self.state.set_data("correlations", correlations)
                self.state.set_data("last_scan_time", datetime.now().isoformat())

            except Exception as e:
                self.state.set_data("scanner_error", str(e))
                time.sleep(10)

    def shutdown(self):
        # Executor is managed centrally, don't shutdown here
        pass


class ScalperOrchestrator:
    def __init__(self):
        self.brain = BrainChain()
        self.state = ThreadSafeState()
        self.data_fetcher = MT5DataFetcher()
        self.exporter = MT5DataExporter()
        self.trade_queue = queue.Queue(maxsize=100)
        self.result_queue = queue.Queue(maxsize=200)
        self.threads = []
        self.active_symbols = []
        self._running = True

    def _process_decisions(self):
        while self._running:
            try:
                item = self.result_queue.get(timeout=2)
                if item is None:
                    continue
                if item["type"] == "decision":
                    decision = item["decision"]
                    symbol = item["symbol"]
                    action = decision.get("action", "hold")
                    if action == "trade":
                        # Validation pipeline gate
                        if not self.validation.can_trade():
                            logger.debug("Trade blocked by validation pipeline (phase=%s)", self.validation.get_status()["phase"])
                            continue
                        try:
                            self.trade_queue.put_nowait({"symbol": symbol, "decision": decision})
                        except queue.Full:
                            logger.warning("Trade queue full — dropping signal for %s (conf=%.2f)", symbol, decision.get("confidence", 0))
                elif item["type"] == "error":
                    self.state.set_data(f"error_{item['symbol']}", item["error"])
            except queue.Empty:
                continue
            except Exception as e:
                logger.warning("Decision processing error: %s", e)
                time.sleep(1)

    def _exporter_loop(self):
        while self._running:
            try:
                self.exporter.export_all()
                # Feed brain status to exporter
                v9 = self.brain.v9
                v8 = v9.v8
                health = v9.sys_monitor.get_health_score()
                cpu = v9.sys_monitor.cpu.get_current().get("overall", 0)
                mem = v9.sys_monitor.memory.get_current().get("percent", 0)
                errors = len(v8.error_doc.errors) if hasattr(v8, 'error_doc') else 0
                regime, _ = self.brain.v10.get_market_regime()
                self.exporter.write_brain_status(
                    regime=regime,
                    session=self.state.get_data("last_session") or "unknown",
                    consensus=self.state.get_data("consensus") or "NEUTRAL",
                    confidence=self.state.get_data("confidence") or 0,
                    circuit_breaker="OPEN" if v9.v6.circuit_breaker.is_open() else "CLOSED",
                    health_score=health, cpu=cpu, memory=mem, errors=errors,
                    avg_spread=0, analyses=0, skips=0,
                    last_dir=self.state.get_data("last_direction") or ""
                )
                # Record data analytics
                try:
                    analytics = get_data_analytics()
                    if analytics:
                        pnl = analytics.get("pnl")
                        if pnl:
                            # Record equity curve
                            acct = mt5.account_info()
                            if acct:
                                pnl.record_equity({
                                    "time": datetime.now().isoformat(),
                                    "equity": acct.equity,
                                    "balance": acct.balance,
                                    "margin": acct.margin,
                                    "profit": acct.profit,
                                })
                except Exception as e:
                    logger.debug("Data analytics failed: %s", e)
                time.sleep(EXPORT_INTERVAL)
            except Exception as e:
                time.sleep(2)

    def run(self):
        if not mt5.initialize():
            logger.error("MT5 Init Failed. Ensure MT5 is open and logged in.")
            return

        # Pull all data from MT5
        logger.info("\n  Connecting to MT5...")
        self.data_fetcher.refresh_all()
        self.active_symbols = self.data_fetcher.get_filtered_symbols()
        
        if not self.active_symbols:
            logger.error("  No tradeable symbols found. Check MT5 connection.")
            mt5.shutdown()
            return

        # Register symbols and state with shared_state for dashboard access
        import shared_state
        shared_state.set_symbols(self.active_symbols)
        shared_state.set_engine_state(self.state)
        shared_state.set_brain_chain(self.brain)

        account = self.data_fetcher.get_account_info()
        self._print_banner(account)
        self.brain.v8.activity.log("startup", f"Parallel scalper started. Symbols: {self.active_symbols}, Balance: {account.get('balance', 0)}")

        # Start web dashboard
        self._start_dashboard()

        # Start MT5 EA data exporter
        exp_thread = threading.Thread(target=self._exporter_loop, daemon=True, name="MT5Exporter")
        exp_thread.start()
        self.threads.append(exp_thread)
        logger.info(f"  MT5 EA Exporter: Running (feeds ScalperPro_Dashboard.mq5)")

        # Start analyzer threads (one per symbol)
        for symbol in self.active_symbols:
            t = SymbolAnalyzer(symbol, self.brain, self.state, self.result_queue)
            t.start()
            self.threads.append(t)

        # Start position manager
        pm = PositionManager(self.brain, self.state, self.active_symbols)
        pm.start()
        self.threads.append(pm)

        # Start trade checker
        tc = TradeChecker(self.brain, self.state, self.active_symbols)
        tc.start()
        self.threads.append(tc)

        # Start system monitor
        sm = SystemMonitor(self.brain, self.state)
        sm.start()
        self.threads.append(sm)

        # Start status printer
        sp = StatusPrinter(self.brain, self.state)
        sp.start()
        self.threads.append(sp)

        # Start trade executor
        te = TradeExecutor(self.brain, self.state, self.trade_queue)
        te.start()
        self.threads.append(te)

        # Initialize validation pipeline (before threads that reference it)
        from validation_pipeline import ValidationPipeline
        self.validation = ValidationPipeline()
        global _validation_pipeline
        _validation_pipeline = self.validation
        vp_status = self.validation.get_status()
        if not self.validation.can_trade():
            logger.warning("Validation pipeline: phase=%s — live trading DISABLED until backtest+paper pass", vp_status["phase"])

        # Start decision processor
        dp_thread = threading.Thread(target=self._process_decisions, daemon=True, name="DecisionProcessor")
        dp_thread.start()
        self.threads.append(dp_thread)

        # Start parallel scanner (V10)
        scanner = ParallelScanner(self.brain, self.state, self.active_symbols)
        scanner.start()
        self.threads.append(scanner)

        # Start failover watchdog with restart functions
        from watchdog import FailoverWatchdog
        watchdog = FailoverWatchdog(alert_manager=get_alert_manager())

        for t in self.threads:
            if hasattr(t, 'name'):
                restart_fn = None
                if t.name.startswith("Analyzer-"):
                    sym = t.symbol
                    def _make_analyzer_restart(symbol):
                        def _restart():
                            new_t = SymbolAnalyzer(symbol, self.brain, self.state, self.result_queue)
                            new_t.start()
                            return new_t
                        return _restart
                    restart_fn = _make_analyzer_restart(sym)
                elif t.name == "PositionManager":
                    def _restart_pm():
                        pm = PositionManager(self.brain, self.state, self.active_symbols)
                        pm.start()
                        return pm
                    restart_fn = _restart_pm
                elif t.name == "TradeExecutor":
                    def _restart_te():
                        te = TradeExecutor(self.brain, self.state, self.trade_queue)
                        te.start()
                        return te
                    restart_fn = _restart_te
                watchdog.register(t.name, t, restart_fn=restart_fn)
        watchdog.start()

        total_threads = len(self.threads)
        total_workers = ANALYSIS_WORKERS + SCANNER_WORKERS + CORRELATION_WORKERS
        logger.info("  Active Threads: %d + %d pool workers", total_threads, total_workers)
        logger.info("  Active Symbols: %s", ', '.join(self.active_symbols))
        logger.info("  Parallel Pool: %d analysis | %d scanner | %d correlation", ANALYSIS_WORKERS, SCANNER_WORKERS, CORRELATION_WORKERS)
        logger.info("  Dedicated: PositionManager | TradeChecker | Executor | Monitor | Printer | Exporter | Scanner")
        logger.info("  Dashboards: http://localhost:%d (web) + MT5 Terminal Panel (EA)", DASHBOARD_PORT)
        logger.info("  Data Export: brain_data/ (JSON files for MT5 EA)")
        logger.info("  Press Ctrl+C to stop.")

        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self._running = False
            self.state.stop()
            time.sleep(2)
            self.brain.v8.activity.log("shutdown", "Parallel scalper stopped by user")
            logger.info("Stopped.")
        finally:
            shutdown_executor(wait=False)
            mt5.shutdown()

    def _start_dashboard(self):
        try:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(__file__))
            from dashboard import app
            def run_flask():
                app.run(host='127.0.0.1', port=DASHBOARD_PORT, debug=False, use_reloader=False)
            flask_thread = threading.Thread(target=run_flask, daemon=True, name="Dashboard")
            flask_thread.start()
            self.threads.append(flask_thread)
        except Exception as e:
            logger.warning("Dashboard start failed: %s", e)

    def _print_banner(self, account):
        self.data_fetcher.print_account_summary()
        self.data_fetcher.print_symbols_summary()
        n_symbols = len(self.active_symbols)
        total_threads = 10 + n_symbols + 1
        total_workers = PROCESS_WORKERS + ANALYSIS_WORKERS + SCANNER_WORKERS + CORRELATION_WORKERS + IO_WORKERS
        total_tasks = total_threads + total_workers
        logger.info("AUTONOMOUS FOREX AUTOTRADER — FULLY INTEGRATED MULTI-BRAIN ENGINE")
        logger.info("")
        logger.info("SYSTEM AUTO-DETECTION [%s TIER]:", SYSTEM_TIER)
        logger.info("  CPU: %s", SYSTEM_CPU_NAME)
        logger.info("  Cores: %d physical / %d logical | %d MHz (%s)", SYSTEM_CPU_PHYSICAL, SYSTEM_CPU_COUNT, SYSTEM_CPU_FREQ, SYSTEM_CPU_ARCH)
        logger.info("  RAM: %sGB total | %sGB available | %s%% used | Swap: %sGB", SYSTEM_MEMORY_GB, SYSTEM_MEMORY_AVAIL_GB, SYSTEM_MEMORY_PCT, SYSTEM_SWAP_GB)
        if SYSTEM_GPU_COUNT > 0:
            logger.info("  GPU: %s (%s)", SYSTEM_GPU_NAME, SYSTEM_GPU_VENDOR)
            logger.info("  GPU VRAM: %sGB | Cores: %d | Clock: %d MHz | Power: %dW", SYSTEM_GPU_VRAM_GB, SYSTEM_GPU_CORES, SYSTEM_GPU_CLOCK, SYSTEM_GPU_POWER)
            logger.info("  GPU Driver: %s | Compute: %s | Temp: %sC | Util: %s%%", SYSTEM_GPU_DRIVER, SYSTEM_GPU_COMPUTE_CAP, SYSTEM_GPU_TEMP, SYSTEM_GPU_UTIL)
            logger.info("  GPU Accel: %s | Batch: %d", 'ENABLED (CuPy)' if GPU_ENABLED else 'DISABLED (insufficient VRAM)', GPU_BATCH_SIZE)
        else:
            logger.info("  GPU: Not detected | Using CPU-only acceleration")
        logger.info("  Disk: %sGB total | %sGB free | Platform: %s | Host: %s", SYSTEM_DISK_TOTAL_GB, SYSTEM_DISK_FREE_GB, SYSTEM_PLATFORM, SYSTEM_HOSTNAME)
        logger.info("  Auto-tuned Workers:")
        logger.info("    ProcessPool: %d | I/O: %d | Analysis: %d", PROCESS_WORKERS, IO_WORKERS, ANALYSIS_WORKERS)
        logger.info("    Scanner: %d | Correlation: %d | Position: %d", SCANNER_WORKERS, CORRELATION_WORKERS, POSITION_WORKERS)
        logger.info("  Settings:")
        logger.info("    Max Symbols: %d | Brain Timeout: %ds | Scan Interval: %ds", MAX_SYMBOLS, BRAIN_TIMEOUT, SCAN_INTERVAL_PARALLEL)
        logger.info("")
        logger.info("BRAIN PIPELINE (10 brains — ALL PARALLEL):")
        logger.info("  ThreadPool: 10 brain workers running simultaneously")
        logger.info("  V1: 8 strategies | Kelly | Dynamic SL/TP | Drawdown protection")
        logger.info("  V2: Regime | Sessions | Candles | Fractals | Z-Score | Cross-symbol")
        logger.info("  V3: Cache | Circuit breaker | Adaptive polling | Micro-price | Profiler")
        logger.info("  V4: Bayesian | Divergence | False breakout | Entry quality | Correlation")
        logger.info("  V5: Auto-weighting | Edge decay | Parameter optimization | Session memory")
        logger.info("  V6: Error detection | Auto-recovery | Trade validation | Health monitoring")
        logger.info("  V7: Evolution engine | Pattern memory | Performance adaptation | Continuous improvement")
        logger.info("  V8: Trade journal | Activity logger | Decision audit | Report generation")
        logger.info("  V9: CPU monitor | Memory monitor | Process monitor | Progress tracker | Alerts")
        logger.info("  V10: Multi-timeframe | Correlation | Asset scanner | Market regime | Cross-asset analysis")
        logger.info("  Merge: Weighted consensus + confidence voting across all 10 brains")
        logger.info("")
        logger.info("DUAL DASHBOARD SYSTEM:")
        logger.info("  Web: http://localhost:%d (Flask, auto-refresh)", DASHBOARD_PORT)
        logger.info("  MT5: ScalperPro_Dashboard.mq5 (real-time terminal panel)")
        logger.info("  Data: brain_data/*.json (JSON bridge, 1s refresh)")
        logger.info("")
        logger.info("PARALLEL ARCHITECTURE:")
        logger.info("  ThreadPoolExecutor Pools:")
        logger.info("    Brain Pool:    10 workers (all brains parallel)")
        logger.info("    Analysis Pool: %d workers (symbol brain pipeline)", ANALYSIS_WORKERS)
        logger.info("    Scanner Pool:  %d workers (V10 MTF + asset scan)", SCANNER_WORKERS)
        logger.info("    Corr Pool:     %d workers (cross-symbol correlation)", CORRELATION_WORKERS)
        logger.info("  ProcessPoolExecutor:")
        logger.info("    CPU Pool:      %d workers (CPU-bound tasks)", PROCESS_WORKERS)
        logger.info("    I/O Pool:      %d workers (I/O-bound tasks)", IO_WORKERS)
        logger.info("  Dedicated Threads:")
        logger.info("    Symbol Analyzers: %d (1 per active symbol)", n_symbols)
        logger.info("    Position Manager | Trade Checker | Trade Executor")
        logger.info("    System Monitor | Status Printer | MT5 Exporter")
        logger.info("    Decision Processor | Parallel Scanner | Web Dashboard")
        logger.info("  Total: %d threads + %d pool workers = %d concurrent tasks", total_threads, total_workers, total_tasks)


if __name__ == "__main__":
    setup_logging()
    orchestrator = ScalperOrchestrator()
    orchestrator.run()
