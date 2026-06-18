import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
from concurrent.futures import as_completed
import json
import os
import logging
import threading
from ai_client import get_ai_client
from config import DATA_DIR, get_magic_number, magic_belongs_to_brain, is_system_magic, CORRELATION_GROUPS, MIN_CONFIDENCE_TO_TRADE
from indicators import fetch_closed_rates, validate_rate_freshness, is_tradeable_now, validate_tick_freshness
from sltp_engine import get_sltp_engine
from cpu_tasks import calculate_multi_tf_signals
from parallel_executor import get_executor
from portfolio_risk import get_portfolio_manager
from risk_advanced import CorrelationStressTest, BlackSwanDetector
from gpu_engine import GPUIndicators
from portfolio_engineering import ConstrainedKelly

logger = logging.getLogger(__name__)


def _send_order_with_fallback(request):
    """Send an order trying IOC, FOK, then RETURN filling types."""
    for filling in [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]:
        req = dict(request)
        req["type_filling"] = filling
        result = mt5.order_send(req)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            return result
    return result

# ==========================================
# BRAIN CONFIGURATION
# ==========================================

# Strategy weights (higher = more influence)
STRATEGY_WEIGHTS = {
    "ma_crossover": 1.0,
    "rsi": 0.8,
    "bollinger": 0.7,
    "breakout": 0.9,
    "orderflow": 0.6,
    "momentum": 0.85,
    "support_resistance": 0.75,
    "multi_tf": 1.2,
}

# Confidence thresholds
HIGH_CONFIDENCE = 0.75
MAX_RISK_PER_TRADE = 2.0
MIN_RISK_PER_TRADE = 0.25
MAX_DRAWDOWN_KILL = 10.0
MAX_CORRELATED_POSITIONS = 2
STALE_TRADE_HOURS = 4
STALE_LOSS_MULT = 10
DRAWDOWN_CLOSE_THRESHOLD = 7.0
DAILY_LOSS_HARD_STOP = 3.0   # % of equity — halt all trading
MAX_TOTAL_RISK_PCT = 5.0     # % of equity — max open risk across all positions
SMALL_PROFIT_MULT = 5

# Signal scoring weights
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70

# Timeframes for multi-TF analysis
MULTI_TIMEFRAMES = [mt5.TIMEFRAME_M1, mt5.TIMEFRAME_M5, mt5.TIMEFRAME_M15]


class BrainStats:
    def __init__(self):
        self.trades = []
        self.equity_curve = []
        self.peak_equity = 0
        self.current_drawdown = 0
        self.daily_stats = {}
        self._lock = threading.Lock()
        self._load_history()

    def _load_history(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "trade_history.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
                self.trades = data.get("trades", [])
                self.equity_curve = data.get("equity_curve", [])

    def _save_history(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "trade_history.json")
        tmp = path + ".tmp"
        with self._lock:
            with open(tmp, "w") as f:
                json.dump({"trades": self.trades[-500:], "equity_curve": self.equity_curve[-2000:]}, f)
        if os.path.exists(path):
            os.replace(tmp, path)
        else:
            os.rename(tmp, path)

    def record_trade(self, trade_info):
        with self._lock:
            self.trades.append(trade_info)
            acct = mt5.account_info()
            if acct:
                self.equity_curve.append({"time": datetime.now().isoformat(), "equity": acct.equity})
                if acct.equity > self.peak_equity:
                    self.peak_equity = acct.equity
                dd = (self.peak_equity - acct.equity) / self.peak_equity * 100 if self.peak_equity > 0 else 0
                self.current_drawdown = dd
        self._save_history()

    def get_win_rate(self, lookback=50):
        recent = self.trades[-lookback:] if len(self.trades) >= lookback else self.trades
        if not recent:
            return 50.0
        wins = sum(1 for t in recent if t.get("profit", 0) > 0)
        return wins / len(recent) * 100

    def get_profit_factor(self, lookback=50):
        recent = self.trades[-lookback:] if len(self.trades) >= lookback else self.trades
        gross_profit = sum(t.get("profit", 0) for t in recent if t.get("profit", 0) > 0)
        gross_loss = abs(sum(t.get("profit", 0) for t in recent if t.get("profit", 0) < 0))
        if gross_loss == 0:
            return 999.0
        return gross_profit / gross_loss

    def get_expectancy(self, lookback=50):
        recent = self.trades[-lookback:] if len(self.trades) >= lookback else self.trades
        if not recent:
            return 0
        return np.mean([t.get("profit", 0) for t in recent])

    def get_sharpe_ratio(self, lookback=100):
        recent = self.trades[-lookback:] if len(self.trades) >= lookback else self.trades
        if len(recent) < 10:
            return 0
        returns = [t.get("profit", 0) for t in recent]
        mean_r = np.mean(returns)
        std_r = np.std(returns)
        if std_r == 0:
            return 0
        return mean_r / std_r

    def get_avg_win_loss(self, lookback=50):
        recent = self.trades[-lookback:] if len(self.trades) >= lookback else self.trades
        wins = [t.get("profit", 0) for t in recent if t.get("profit", 0) > 0]
        losses = [t.get("profit", 0) for t in recent if t.get("profit", 0) < 0]
        avg_win = np.mean(wins) if wins else 0
        avg_loss = abs(np.mean(losses)) if losses else 0
        return avg_win, avg_loss

    def get_win_streak(self):
        streak = 0
        for t in reversed(self.trades):
            if t.get("profit", 0) >= 0:
                streak += 1
            else:
                break
        return streak

    def get_loss_streak(self):
        streak = 0
        for t in reversed(self.trades):
            if t.get("profit", 0) < 0:
                streak += 1
            else:
                break
        return streak

    def get_daily_pnl(self):
        today = datetime.now().date()
        day_trades = [t for t in self.trades if t.get("time", "")[:10] == str(today)]
        return sum(t.get("profit", 0) for t in day_trades)

    def get_trade_count_today(self):
        today = datetime.now().date()
        return len([t for t in self.trades if t.get("time", "")[:10] == str(today)])

    def get_strategy_stats(self):
        strat_stats = {}
        for t in self.trades:
            strat = t.get("strategy", "unknown")
            if strat not in strat_stats:
                strat_stats[strat] = {"wins": 0, "losses": 0, "total_pnl": 0}
            if t.get("profit", 0) >= 0:
                strat_stats[strat]["wins"] += 1
            else:
                strat_stats[strat]["losses"] += 1
            strat_stats[strat]["total_pnl"] += t.get("profit", 0)
        for s in strat_stats:
            total = strat_stats[s]["wins"] + strat_stats[s]["losses"]
            strat_stats[s]["win_rate"] = strat_stats[s]["wins"] / total * 100 if total > 0 else 0
        return strat_stats

    def get_kelly_fraction(self, lookback=100):
        recent = self.trades[-lookback:] if len(self.trades) >= lookback else self.trades
        if len(recent) < 20:
            return 0.02
        wins = [t.get("profit", 0) for t in recent if t.get("profit", 0) > 0]
        losses = [abs(t.get("profit", 0)) for t in recent if t.get("profit", 0) < 0]
        if not wins or not losses:
            return 0.02
        win_rate = len(wins) / len(recent)
        avg_win = np.mean(wins)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 0.02
        win_loss_ratio = avg_win / avg_loss
        kelly = win_rate - ((1 - win_rate) / win_loss_ratio)
        return max(0.01, min(kelly * 0.5, 0.05))

    def get_full_report(self):
        return {
            "win_rate": self.get_win_rate(),
            "profit_factor": self.get_profit_factor(),
            "expectancy": self.get_expectancy(),
            "sharpe": self.get_sharpe_ratio(),
            "avg_win": self.get_avg_win_loss()[0],
            "avg_loss": self.get_avg_win_loss()[1],
            "win_streak": self.get_win_streak(),
            "loss_streak": self.get_loss_streak(),
            "daily_pnl": self.get_daily_pnl(),
            "daily_trades": self.get_trade_count_today(),
            "drawdown": self.current_drawdown,
            "kelly": self.get_kelly_fraction(),
            "total_trades": len(self.trades),
            "strategy_stats": self.get_strategy_stats(),
        }


def _signal_multi_tf_cpu_standalone(symbol):
    """Standalone CPU-optimized multi-TF signal calculation (picklable for process pool)."""
    import MetaTrader5 as mt5

    tf_map = {
        mt5.TIMEFRAME_M1: "M1",
        mt5.TIMEFRAME_M5: "M5",
        mt5.TIMEFRAME_M15: "M15",
    }
    timeframes = list(tf_map.keys())

    tf_signals = calculate_multi_tf_signals((symbol, timeframes))

    if not tf_signals:
        return {"direction": 0, "confidence": 0, "name": "multi_tf"}

    values = list(tf_signals.values())
    buy_count = sum(1 for v in values if v == 1)
    sell_count = sum(1 for v in values if v == -1)
    total = len(values)

    if buy_count == total:
        return {"direction": 1, "confidence": 0.9, "name": "multi_tf"}
    if sell_count == total:
        return {"direction": -1, "confidence": 0.9, "name": "multi_tf"}
    if buy_count > sell_count:
        return {"direction": 1, "confidence": buy_count / total * 0.7, "name": "multi_tf"}
    if sell_count > buy_count:
        return {"direction": -1, "confidence": sell_count / total * 0.7, "name": "multi_tf"}
    return {"direction": 0, "confidence": 0, "name": "multi_tf"}


class SignalAnalyzer:
    def __init__(self):
        self.strategy_performance = {}
        self._executor = None
        self._gpu = None
    
    def _get_executor(self):
        if self._executor is None:
            self._executor = get_executor()
        return self._executor

    def _get_gpu(self):
        if self._gpu is None:
            try:
                self._gpu = GPUIndicators()
            except Exception:
                pass
        return self._gpu

    def calculate_all_signals(self, symbol, timeframe, params=None, df=None):
        if df is None:
            rates = fetch_closed_rates(symbol, timeframe, 300)
            if rates is None:
                return {"signals": {}, "df": None}

            # Validate rate freshness — reject stale data
            rate_check = validate_rate_freshness(rates, timeframe)
            if not rate_check["fresh"]:
                logger.debug("calculate_all_signals: stale data for %s — %s", symbol, rate_check["reason"])
                return {"signals": {}, "df": None}

            df = pd.DataFrame(rates)
        self._calc_indicators(df, params=params)
        
        executor = self._get_executor()
        
        signal_funcs = [
            ("ma_crossover", self._signal_ma, (df,)),
            ("rsi", self._signal_rsi, (df,)),
            ("bollinger", self._signal_bb, (df,)),
            ("breakout", self._signal_breakout, (df,)),
            ("orderflow", self._signal_orderflow, (df,)),
            ("momentum", self._signal_momentum, (df,)),
            ("support_resistance", self._signal_sr, (df, symbol)),
        ]
        
        signal_results = {}
        for name, func, args in signal_funcs:
            try:
                signal_results[name] = executor.submit_analysis_task(func, *args)
            except Exception as e:
                logger.warning("Signal %s failed: %s", name, e)
                signal_results[name] = {"direction": 0, "confidence": 0, "name": name}
        
        try:
            signal_results["multi_tf"] = executor.submit_cpu_task(
                _signal_multi_tf_cpu_standalone, symbol
            )
        except Exception as e:
            logger.warning("Multi-TF signal failed: %s", e)
            signal_results["multi_tf"] = {"direction": 0, "confidence": 0, "name": "multi_tf"}
        
        return {"signals": signal_results, "df": df}

    def _calc_indicators(self, df, params=None):
        gpu = self._get_gpu()
        if gpu and gpu.gpu_available:
            try:
                c = df['close'].values.astype(np.float64)
                h = df['high'].values.astype(np.float64)
                l = df['low'].values.astype(np.float64)
                v = df['tick_volume'].values.astype(np.float64)
                p = params or {}
                df['EMA5'] = gpu.ema(c, p.get('ema_fast', 5))
                df['EMA8'] = gpu.ema(c, 8)
                df['EMA13'] = gpu.ema(c, 13)
                df['EMA21'] = gpu.ema(c, p.get('ema_slow', 21))
                df['EMA50'] = gpu.ema(c, 50)
                df['EMA200'] = gpu.ema(c, 200)
                df['RSI'] = gpu.rsi(c, p.get('rsi_period', 14))
                df['RSI_FAST'] = gpu.rsi(c, 7)
                bb_upper, bb_mid, bb_lower, bb_width = gpu.bollinger_bands(c)
                df['BB_MA'] = bb_mid
                df['BB_UP'] = bb_upper
                df['BB_DN'] = bb_lower
                df['BB_WIDTH'] = bb_width
                tr_arr = gpu.atr(h, l, c, 14)
                df['TR'] = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
                df['ATR'] = pd.Series(tr_arr).rolling(window=14).mean().values if len(tr_arr) < len(df) else tr_arr
                df['ATR_MA'] = pd.Series(df['ATR']).rolling(window=30).mean().values
                df['HIGH_N'] = pd.Series(h).rolling(window=20).max().values
                df['LOW_N'] = pd.Series(l).rolling(window=20).min().values
                df['VOL_MA'] = pd.Series(v).rolling(window=20).mean().values
                macd_line, macd_signal, macd_hist = gpu.macd(c)
                df['MACD'] = macd_line
                df['MACD_SIGNAL'] = macd_signal
                df['MACD_HIST'] = macd_hist
                stoch_k, stoch_d = gpu.stochastic(h, l, c)
                df['STOCH_K'] = stoch_k
                df['STOCH_D'] = stoch_d
                df['MOM'] = c - np.roll(c, 10)
                df.loc[df.index[:10], 'MOM'] = 0
                df['ROC'] = pd.Series(c).pct_change(periods=10).values * 100
                df['VWAP'] = gpu.vwap(c, v)
                df['OBV'] = gpu.obv(c, v)
                return
            except Exception as e:
                logger.debug("GPU indicators failed, falling back to CPU: %s", e)
        p = params or {}
        df['EMA5'] = df['close'].ewm(span=p.get('ema_fast', 5), adjust=False).mean()
        df['EMA8'] = df['close'].ewm(span=8, adjust=False).mean()
        df['EMA13'] = df['close'].ewm(span=13, adjust=False).mean()
        df['EMA21'] = df['close'].ewm(span=p.get('ema_slow', 21), adjust=False).mean()
        df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['EMA200'] = df['close'].ewm(span=200, adjust=False).mean()
        rsi_period = p.get('rsi_period', 14)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
        loss = loss.replace(0, 1e-10)
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        fast_gain = delta.where(delta > 0, 0).rolling(7).mean()
        fast_loss = (-delta.where(delta < 0, 0)).rolling(7).mean()
        fast_loss = fast_loss.replace(0, 1e-10)
        df['RSI_FAST'] = 100 - (100 / (1 + (fast_gain / fast_loss)))
        df['BB_MA'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['BB_UP'] = df['BB_MA'] + (bb_std * 2.0)
        df['BB_DN'] = df['BB_MA'] - (bb_std * 2.0)
        df['BB_WIDTH'] = (df['BB_UP'] - df['BB_DN']) / df['BB_MA'] * 100
        df['TR'] = np.maximum(df['high'] - df['low'],
                              np.maximum(abs(df['high'] - df['close'].shift(1)),
                                         abs(df['low'] - df['close'].shift(1))))
        df['ATR'] = df['TR'].rolling(window=14).mean()
        df['ATR_MA'] = df['ATR'].rolling(window=30).mean()
        df['HIGH_N'] = df['high'].rolling(window=20).max()
        df['LOW_N'] = df['low'].rolling(window=20).min()
        df['VOL_MA'] = df['tick_volume'].rolling(window=20).mean()
        df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
        df['MACD_SIGNAL'] = df['MACD'].ewm(span=9).mean()
        df['MACD_HIST'] = df['MACD'] - df['MACD_SIGNAL']
        df['STOCH_K'] = ((df['close'] - df['low'].rolling(14).min()) /
                         (df['high'].rolling(14).max() - df['low'].rolling(14).min())) * 100
        df['STOCH_D'] = df['STOCH_K'].rolling(3).mean()
        df['MOM'] = df['close'] - df['close'].shift(10)
        df['ROC'] = df['close'].pct_change(periods=10) * 100
        df['VWAP'] = (df['close'] * df['tick_volume']).rolling(20).sum() / df['tick_volume'].rolling(20).sum()
        df['OBV'] = (np.sign(df['close'].diff()) * df['tick_volume']).fillna(0).cumsum()

    def _signal_ma(self, df):
        last = df.iloc[-1]
        prev = df.iloc[-2]
        vol_ok = last['ATR'] > last['ATR_MA']
        buy_score = 0
        sell_score = 0
        if prev['EMA5'] <= prev['EMA13'] and last['EMA5'] > last['EMA13']:
            buy_score += 0.4
        if prev['EMA8'] <= prev['EMA21'] and last['EMA8'] > last['EMA21']:
            buy_score += 0.3
        if last['close'] > last['EMA50']:
            buy_score += 0.15
        if last['close'] > last['EMA200']:
            buy_score += 0.15
        if prev['EMA5'] >= prev['EMA13'] and last['EMA5'] < last['EMA13']:
            sell_score += 0.4
        if prev['EMA8'] >= prev['EMA21'] and last['EMA8'] < last['EMA21']:
            sell_score += 0.3
        if last['close'] < last['EMA50']:
            sell_score += 0.15
        if last['close'] < last['EMA200']:
            sell_score += 0.15
        if vol_ok:
            buy_score *= 1.2
            sell_score *= 1.2
        buy_score = min(buy_score, 1.0)
        sell_score = min(sell_score, 1.0)
        if buy_score > sell_score and buy_score > 0.3:
            return {"direction": 1, "confidence": buy_score, "name": "ma_crossover"}
        if sell_score > buy_score and sell_score > 0.3:
            return {"direction": -1, "confidence": sell_score, "name": "ma_crossover"}
        return {"direction": 0, "confidence": 0, "name": "ma_crossover"}

    def _signal_rsi(self, df):
        last = df.iloc[-1]
        prev = df.iloc[-2]
        vol_ok = last['ATR'] > last['ATR_MA']
        buy_conf = 0
        sell_conf = 0
        if last['RSI'] < 30:
            buy_conf = 0.5 + (30 - last['RSI']) / 30 * 0.5
        elif last['RSI'] < 40:
            buy_conf = (40 - last['RSI']) / 40 * 0.3
        elif last['RSI'] > 70:
            sell_conf = 0.5 + (last['RSI'] - 70) / 30 * 0.5
        elif last['RSI'] > 60:
            sell_conf = (last['RSI'] - 60) / 40 * 0.3
        if prev['RSI'] < 30 and last['RSI'] >= 30:
            buy_conf = max(buy_conf, 0.7)
        if prev['RSI'] > 70 and last['RSI'] <= 70:
            sell_conf = max(sell_conf, 0.7)
        if last['RSI'] < 50 and last['MACD'] > last['MACD_SIGNAL']:
            buy_conf += 0.1
        if last['RSI'] > 50 and last['MACD'] < last['MACD_SIGNAL']:
            sell_conf += 0.1
        if vol_ok:
            buy_conf *= 1.15
            sell_conf *= 1.15
        buy_conf = min(buy_conf, 1.0)
        sell_conf = min(sell_conf, 1.0)
        if buy_conf > sell_conf and buy_conf > 0.2:
            return {"direction": 1, "confidence": buy_conf, "name": "rsi"}
        if sell_conf > buy_conf and sell_conf > 0.2:
            return {"direction": -1, "confidence": sell_conf, "name": "rsi"}
        return {"direction": 0, "confidence": 0, "name": "rsi"}

    def _signal_bb(self, df):
        last = df.iloc[-1]
        prev = df.iloc[-2]
        vol_ok = last['ATR'] > last['ATR_MA']
        buy_conf = 0
        sell_conf = 0
        bb_pos = (last['close'] - last['BB_DN']) / (last['BB_UP'] - last['BB_DN']) if (last['BB_UP'] - last['BB_DN']) > 0 else 0.5
        if last['close'] <= last['BB_DN']:
            buy_conf = 0.6 + (1 - bb_pos) * 0.4
        elif bb_pos < 0.2:
            buy_conf = 0.3
        elif last['close'] >= last['BB_UP']:
            sell_conf = 0.6 + bb_pos * 0.4
        elif bb_pos > 0.8:
            sell_conf = 0.3
        if prev['close'] <= prev['BB_DN'] and last['close'] > last['BB_DN']:
            buy_conf = max(buy_conf, 0.75)
        if prev['close'] >= prev['BB_UP'] and last['close'] < last['BB_UP']:
            sell_conf = max(sell_conf, 0.75)
        bb_width_avg = df['BB_WIDTH'].rolling(50).mean().iloc[-1] if 'BB_WIDTH' in df.columns else last['BB_WIDTH']
        if last['BB_WIDTH'] < bb_width_avg * 0.7:
            buy_conf *= 0.7
            sell_conf *= 0.7
        if vol_ok:
            buy_conf *= 1.1
            sell_conf *= 1.1
        buy_conf = min(buy_conf, 1.0)
        sell_conf = min(sell_conf, 1.0)
        if buy_conf > sell_conf and buy_conf > 0.2:
            return {"direction": 1, "confidence": buy_conf, "name": "bollinger"}
        if sell_conf > buy_conf and sell_conf > 0.2:
            return {"direction": -1, "confidence": sell_conf, "name": "bollinger"}
        return {"direction": 0, "confidence": 0, "name": "bollinger"}

    def _signal_breakout(self, df):
        last = df.iloc[-1]
        prev = df.iloc[-2]
        vol_ok = last['ATR'] > last['ATR_MA']
        vol_confirm = last['tick_volume'] > last['VOL_MA'] * 1.3
        buy_conf = 0
        sell_conf = 0
        if prev['close'] <= prev['HIGH_N'] and last['close'] > last['HIGH_N']:
            if vol_ok and vol_confirm:
                buy_conf = 0.8
            else:
                buy_conf = 0.4
        if prev['close'] >= prev['LOW_N'] and last['close'] < last['LOW_N']:
            if vol_ok and vol_confirm:
                sell_conf = 0.8
            else:
                sell_conf = 0.4
        if last['MACD_HIST'] > 0 and last['MACD_HIST'] > prev['MACD_HIST']:
            buy_conf += 0.1
        if last['MACD_HIST'] < 0 and last['MACD_HIST'] < prev['MACD_HIST']:
            sell_conf += 0.1
        buy_conf = min(buy_conf, 1.0)
        sell_conf = min(sell_conf, 1.0)
        if buy_conf > sell_conf and buy_conf > 0.2:
            return {"direction": 1, "confidence": buy_conf, "name": "breakout"}
        if sell_conf > buy_conf and sell_conf > 0.2:
            return {"direction": -1, "confidence": sell_conf, "name": "breakout"}
        return {"direction": 0, "confidence": 0, "name": "breakout"}

    def _signal_orderflow(self, df):
        last = df.iloc[-1]
        prev = df.iloc[-2]
        buy_conf = 0
        sell_conf = 0
        obv_slope = (last['OBV'] - df['OBV'].iloc[-5]) / 5
        obv_ma = df['OBV'].rolling(20).mean().iloc[-1]
        if obv_slope > 0 and last['OBV'] > obv_ma:
            buy_conf = 0.5 + min(abs(obv_slope) / (abs(obv_ma) + 1) * 10, 0.5)
        elif obv_slope < 0 and last['OBV'] < obv_ma:
            sell_conf = 0.5 + min(abs(obv_slope) / (abs(obv_ma) + 1) * 10, 0.5)
        vwap_diff = (last['close'] - last['VWAP']) / last['VWAP'] * 100 if last['VWAP'] > 0 else 0
        if vwap_diff > 0.05:
            buy_conf += 0.2
        elif vwap_diff < -0.05:
            sell_conf += 0.2
        buy_conf = min(buy_conf, 1.0)
        sell_conf = min(sell_conf, 1.0)
        if buy_conf > sell_conf and buy_conf > 0.2:
            return {"direction": 1, "confidence": buy_conf, "name": "orderflow"}
        if sell_conf > buy_conf and sell_conf > 0.2:
            return {"direction": -1, "confidence": sell_conf, "name": "orderflow"}
        return {"direction": 0, "confidence": 0, "name": "orderflow"}

    def _signal_momentum(self, df):
        last = df.iloc[-1]
        prev = df.iloc[-2]
        buy_conf = 0
        sell_conf = 0
        if last['MACD'] > last['MACD_SIGNAL'] and prev['MACD'] <= prev['MACD_SIGNAL']:
            buy_conf += 0.4
        elif last['MACD'] > last['MACD_SIGNAL']:
            buy_conf += 0.2
        if last['MACD'] < last['MACD_SIGNAL'] and prev['MACD'] >= prev['MACD_SIGNAL']:
            sell_conf += 0.4
        elif last['MACD'] < last['MACD_SIGNAL']:
            sell_conf += 0.2
        if last['STOCH_K'] < 20 and last['STOCH_K'] > last['STOCH_D']:
            buy_conf += 0.3
        elif last['STOCH_K'] > 80 and last['STOCH_K'] < last['STOCH_D']:
            sell_conf += 0.3
        if last['MOM'] > 0 and last['ROC'] > 0:
            buy_conf += 0.2
        elif last['MOM'] < 0 and last['ROC'] < 0:
            sell_conf += 0.2
        if last['MACD_HIST'] > 0 and last['MACD_HIST'] > prev['MACD_HIST']:
            buy_conf += 0.1
        if last['MACD_HIST'] < 0 and last['MACD_HIST'] < prev['MACD_HIST']:
            sell_conf += 0.1
        buy_conf = min(buy_conf, 1.0)
        sell_conf = min(sell_conf, 1.0)
        if buy_conf > sell_conf and buy_conf > 0.3:
            return {"direction": 1, "confidence": buy_conf, "name": "momentum"}
        if sell_conf > buy_conf and sell_conf > 0.3:
            return {"direction": -1, "confidence": sell_conf, "name": "momentum"}
        return {"direction": 0, "confidence": 0, "name": "momentum"}

    def _signal_sr(self, df, symbol=None):
        last = df.iloc[-1]
        buy_conf = 0
        sell_conf = 0
        lookback = 50
        highs = df['high'].iloc[-lookback:].values
        lows = df['low'].iloc[-lookback:].values
        current_price = last['close']
        resistance_levels = []
        support_levels = []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                resistance_levels.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                support_levels.append(lows[i])
        sym_info = mt5.symbol_info(symbol) if symbol else None
        point = sym_info.point if sym_info else 0.0001
        nearest_support = max([s for s in support_levels if s < current_price], default=0)
        nearest_resistance = min([r for r in resistance_levels if r > current_price], default=float('inf'))
        if nearest_support > 0:
            dist_support = (current_price - nearest_support) / current_price * 100
            if dist_support < 0.1:
                buy_conf = 0.7
            elif dist_support < 0.2:
                buy_conf = 0.4
        if nearest_resistance < float('inf'):
            dist_resistance = (nearest_resistance - current_price) / current_price * 100
            if dist_resistance < 0.1:
                sell_conf = 0.7
            elif dist_resistance < 0.2:
                sell_conf = 0.4
        if last['ATR'] > last['ATR_MA']:
            buy_conf *= 1.1
            sell_conf *= 1.1
        buy_conf = min(buy_conf, 1.0)
        sell_conf = min(sell_conf, 1.0)
        if buy_conf > sell_conf and buy_conf > 0.2:
            return {"direction": 1, "confidence": buy_conf, "name": "support_resistance"}
        if sell_conf > buy_conf and sell_conf > 0.2:
            return {"direction": -1, "confidence": sell_conf, "name": "support_resistance"}
        return {"direction": 0, "confidence": 0, "name": "support_resistance"}


class RiskManager:
    def __init__(self, stats):
        self.stats = stats
        self._portfolio_risk = None
        self._black_swan = BlackSwanDetector()
        self._constrained_kelly = ConstrainedKelly()

    def _get_portfolio_risk(self):
        if self._portfolio_risk is None:
            try:
                self._portfolio_risk = get_portfolio_manager()
            except Exception:
                pass
        return self._portfolio_risk

    def calculate_position_size(self, symbol, sl_points, confidence):
        info = mt5.symbol_info(symbol)
        if info is None:
            return 0.01
        account = mt5.account_info()
        kelly = self._constrained_kelly.calculate(
            self.stats.get_win_rate() / 100,
            self.stats.get_avg_win_loss()[0],
            self.stats.get_avg_win_loss()[1],
            self.stats.current_drawdown / 100,
        )
        base_risk = account.balance * kelly
        if confidence >= HIGH_CONFIDENCE:
            risk_mult = 1.3
        elif confidence >= MIN_CONFIDENCE_TO_TRADE:
            risk_mult = 1.0
        else:
            risk_mult = 0.5
        dd = self.stats.current_drawdown
        if dd > 5:
            dd_mult = max(0.3, 1 - (dd - 5) / 10)
        else:
            dd_mult = 1.0
        pm = self._get_portfolio_risk()
        pm_mult = 1.0
        if pm:
            try:
                assessment = pm.get_full_risk_assessment()
                pm_mult = assessment.get("size_multiplier", 1.0)
            except Exception:
                pass
        risk_amount = base_risk * risk_mult * dd_mult * pm_mult
        risk_pct = (risk_amount / account.balance) * 100
        risk_pct = max(MIN_RISK_PER_TRADE, min(risk_pct, MAX_RISK_PER_TRADE))
        risk_amount = account.balance * (risk_pct / 100)
        tick_value = info.trade_tick_value
        tick_size = info.trade_tick_size
        if tick_value == 0 or tick_size == 0:
            return 0.01
        sl_distance = sl_points * info.point
        lot = risk_amount / (sl_distance / tick_size * tick_value)
        lot = max(info.volume_min, min(lot, info.volume_max))
        lot = round(lot / info.volume_step) * info.volume_step
        return round(lot, 2)

    def calculate_dynamic_sl_tp(self, symbol, direction, df):
        """Calculate SL/TP using advanced engine that defeats SL hunters."""
        engine = get_sltp_engine()
        result = engine.calculate_sl_tp(symbol, direction, df)
        return result["sl"], result["tp"], result["sl_points"], result["tp_points"]

    def can_open_trade(self, symbol, direction):
        open_positions = mt5.positions_get()
        my_positions = [p for p in (open_positions or []) if is_system_magic(p.magic)]
        if len(my_positions) >= 5:
            return False, "Max positions reached"
        correlated_count = 0
        symbol_group = None
        for group, group_data in CORRELATION_GROUPS.items():
            if symbol in group_data["symbols"]:
                symbol_group = group_data["symbols"]
                break
        if symbol_group:
            for p in my_positions:
                if p.symbol in symbol_group:
                    correlated_count += 1
        if correlated_count >= MAX_CORRELATED_POSITIONS:
            return False, "Too many correlated positions"
        same_direction = sum(1 for p in my_positions if p.symbol == symbol and
                            (p.type == mt5.ORDER_TYPE_BUY and direction == 1 or
                             p.type == mt5.ORDER_TYPE_SELL and direction == -1))
        if same_direction >= 2:
            return False, "Max same-direction trades on symbol"
        if self.stats.current_drawdown > MAX_DRAWDOWN_KILL:
            return False, f"Drawdown kill switch ({self.stats.current_drawdown:.1f}%)"
        # Daily loss circuit breaker
        account = mt5.account_info()
        if account:
            daily_pnl = self.stats.get_daily_pnl()
            daily_loss_pct = abs(daily_pnl) / account.equity * 100 if daily_pnl < 0 else 0
            if daily_loss_pct >= DAILY_LOSS_HARD_STOP:
                return False, f"Daily loss hard stop ({daily_loss_pct:.1f}% >= {DAILY_LOSS_HARD_STOP}%)"
        # Margin safety
        if account:
            margin_level = (account.equity / account.margin * 100) if account.margin > 0 else 9999
            if margin_level < 150:
                return False, f"Emergency: margin level {margin_level:.0f}% < 150%"
            if margin_level < 300:
                return False, f"Margin level {margin_level:.0f}% < 300% — orders blocked"
            # Portfolio risk cap: total open risk vs equity
            total_risk = sum(abs(p.volume * p.price * 0.01) for p in my_positions)
            total_risk_pct = total_risk / account.equity * 100 if account.equity > 0 else 0
            if total_risk_pct >= MAX_TOTAL_RISK_PCT:
                return False, f"Total portfolio risk {total_risk_pct:.1f}% >= {MAX_TOTAL_RISK_PCT}%"
            if account.margin_free < account.balance * 0.2:
                return False, "Low free margin"
        daily_trades = self.stats.get_trade_count_today()
        if daily_trades >= 20:
            return False, "Max daily trades reached"
        try:
            swan = self._black_swan.detect()
            if swan and swan.get("detected") and swan.get("severity", 0) > 0.5:
                return False, f"Black swan detected: {swan.get('type', '')} (z={swan.get('z_score', 0)})"
        except Exception:
            pass
        pm = self._get_portfolio_risk()
        if pm:
            try:
                assessment = pm.get_full_risk_assessment()
                if assessment.get("drawdown_status") == "halted":
                    return False, "Portfolio drawdown halt"
                if assessment.get("hedge_needed"):
                    logger.debug("Portfolio hedge recommended: %s", assessment.get("hedge_info"))
            except Exception:
                pass
        return True, "OK"

    def should_close_early(self, position):
        if position.profit < 0:
            open_time = datetime.fromtimestamp(position.time)
            hours_open = (datetime.now() - open_time).total_seconds() / 3600
            if hours_open > STALE_TRADE_HOURS and position.profit < -position.volume * STALE_LOSS_MULT:
                return True, "Stale losing trade"
        if self.stats.current_drawdown > DRAWDOWN_CLOSE_THRESHOLD:
            if position.profit > 0 and position.profit < position.volume * SMALL_PROFIT_MULT:
                return True, "Drawdown protection - bank small profits"
        return False, ""


class Brain:
    def __init__(self):
        self.stats = BrainStats()
        self.analyzer = SignalAnalyzer()
        self.risk = RiskManager(self.stats)
        self.last_signals = {}
        self.ai = get_ai_client()
        self._executor = None
    
    def _get_executor(self):
        if self._executor is None:
            self._executor = get_executor()
        return self._executor

    def _ai_enhance(self, symbol, signals, direction, confidence):
        try:
            if not self.ai.is_available():
                return direction, confidence
            sig_summary = {}
            for name, sig in signals.items():
                sig_summary[name] = {"dir": sig.get("direction", 0), "conf": round(sig.get("confidence", 0), 3)}
            result = self.ai.analyze_signal(symbol, sig_summary, "unknown", "unknown")
            if result and isinstance(result, dict):
                ai_dir = result.get("direction", "HOLD")
                ai_conf = result.get("confidence", 0.5)
                if ai_dir == "BUY" and direction >= 0:
                    direction = 1
                    confidence = min(confidence * 1.1, 0.95)
                elif ai_dir == "SELL" and direction <= 0:
                    direction = -1
                    confidence = min(confidence * 1.1, 0.95)
                elif ai_dir == "HOLD":
                    confidence *= 0.8
        except Exception as e:
            logger.debug("AI enhance skipped for %s: %s", symbol, e)
        return direction, confidence

    def analyze(self, symbol, timeframe=mt5.TIMEFRAME_M1, params=None, df=None):
        # === MARKET STATE GATE ===
        # Validate market is open and data is fresh before computing signals.
        # This is the innermost guard — prevents hallucinated signals from stale data.
        tradeable = is_tradeable_now(symbol, timeframe)
        if not tradeable["can_trade"]:
            return {
                "action": "hold",
                "direction": 0,
                "confidence": 0,
                "reason": f"market_closed: {tradeable['reason']}",
                "signals": {},
                "active": [],
            }

        signals_result = self.analyzer.calculate_all_signals(symbol, timeframe, params=params, df=df)
        signals = signals_result["signals"]
        df = signals_result["df"]
        self.last_signals = signals
        weighted_buy = 0
        weighted_sell = 0
        total_weight = 0
        active_signals = []
        for name, sig in signals.items():
            weight = STRATEGY_WEIGHTS.get(name, 1.0)
            if sig["direction"] == 1:
                weighted_buy += sig["confidence"] * weight
                active_signals.append(f"+{name}({sig['confidence']:.2f})")
            elif sig["direction"] == -1:
                weighted_sell += sig["confidence"] * weight
                active_signals.append(f"-{name}({sig['confidence']:.2f})")
            total_weight += weight
        buy_score = weighted_buy / total_weight
        sell_score = weighted_sell / total_weight
        net_score = buy_score - sell_score
        confidence = abs(net_score)
        if net_score > 0:
            direction = 1
        elif net_score < 0:
            direction = -1
        else:
            direction = 0
        direction, confidence = self._ai_enhance(symbol, signals, direction, confidence)
        if confidence < MIN_CONFIDENCE_TO_TRADE:
            return {
                "action": "hold",
                "direction": direction,
                "confidence": confidence,
                "buy_score": buy_score,
                "sell_score": sell_score,
                "signals": signals,
                "active": active_signals,
            }
        can_trade, reason = self.risk.can_open_trade(symbol, direction)
        if not can_trade:
            return {
                "action": "blocked",
                "direction": direction,
                "confidence": confidence,
                "reason": reason,
                "signals": signals,
                "active": active_signals,
            }
        if df is None:
            rates = fetch_closed_rates(symbol, timeframe, 200)
            if rates is not None and len(rates) >= 50:
                import pandas as pd
                df = pd.DataFrame(rates)
        sl, tp, atr_sl, atr_tp = self.risk.calculate_dynamic_sl_tp(symbol, direction, df) if df is not None else (0, 0, 100, 200)
        # Safety net: if SLTP engine returned 0, compute simple ATR-based fallback
        if sl == 0 or tp == 0:
            info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            if info and tick:
                point = info.point
                price = tick.ask if direction == 1 else tick.bid
                sl = round(price - 100 * point, info.digits) if direction == 1 else round(price + 100 * point, info.digits)
                tp = round(price + 200 * point, info.digits) if direction == 1 else round(price - 200 * point, info.digits)
                atr_sl, atr_tp = 100, 200
        lot = self.risk.calculate_position_size(symbol, atr_sl, confidence)
        return {
            "action": "trade",
            "direction": direction,
            "direction_str": "BUY" if direction == 1 else "SELL",
            "confidence": confidence,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "lot": lot,
            "sl_points": atr_sl,
            "tp_points": atr_tp,
            "sl": sl,
            "tp": tp,
            "signals": signals,
            "active": active_signals,
            "stats": self.stats.get_full_report(),
        }

    def record_trade_result(self, ticket, symbol, direction, lot, price, sl, tp, profit, strategy="combined"):
        trade_info = {
            "ticket": ticket,
            "symbol": symbol,
            "direction": direction,
            "lot": lot,
            "price": price,
            "sl": sl,
            "tp": tp,
            "profit": profit,
            "strategy": strategy,
            "time": datetime.now().isoformat(),
            "confidence": self.last_signals.get("_last_confidence", 0),
        }
        self.stats.record_trade(trade_info)

    def manage_positions(self, symbol):
        open_positions = mt5.positions_get()
        my_positions = [p for p in (open_positions or []) if is_system_magic(p.magic) and p.symbol == symbol]
        info = mt5.symbol_info(symbol)
        if info is None:
            return
        point = info.point
        for pos in my_positions:
            close, reason = self.risk.should_close_early(pos)
            if close:
                logger.info("Closing %s: %s", pos.ticket, reason)
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    continue
                # Validate tick freshness before close
                tick_check = validate_tick_freshness(tick, symbol)
                if not tick_check["fresh"]:
                    continue
                close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": pos.volume,
                    "type": close_type,
                    "position": pos.ticket,
                    "price": close_price,
                     "magic": pos.magic,
                    "comment": "BrainClose",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = _send_order_with_fallback(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.record_trade_result(pos.ticket, symbol, pos.type, pos.volume, close_price, pos.sl, pos.tp, pos.profit)
            new_sl = 0
            try:
                sltp = get_sltp_engine()
                # Calculate profit in pips
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    current_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
                    profit_pips = (current_price - pos.price_open) / point if pos.type == mt5.ORDER_TYPE_BUY else (pos.price_open - current_price) / point
                else:
                    current_price = pos.price_current
                    profit_pips = (current_price - pos.price_open) / point if pos.type == mt5.ORDER_TYPE_BUY else (pos.price_open - current_price) / point
                # Get ATR for the symbol
                atr = 0
                try:
                    rates = fetch_closed_rates(symbol, mt5.TIMEFRAME_M15, 14)
                    if rates is not None and len(rates) >= 14:
                        high = rates['high']
                        low = rates['low']
                        close = rates['close']
                        tr = np.maximum(high[1:] - low[1:], np.maximum(abs(high[1:] - close[:-1]), abs(low[1:] - close[:-1])))
                        atr = float(np.mean(tr[-14:]))
                except Exception:
                    atr = point * 50  # Fallback
                direction = 1 if pos.type == mt5.ORDER_TYPE_BUY else -1
                trail_result = sltp.manage_trailing_stop(
                    ticket=pos.ticket, symbol=symbol, direction=direction,
                    entry_price=pos.price_open, current_sl=pos.sl, current_tp=pos.tp,
                    atr=atr, profit_pips=profit_pips,
                    trail_start_pips=30, trail_step_pips=10,
                    break_even_pips=20, break_even_offset_pips=5
                )
                if trail_result and trail_result.get("action") == "modify":
                    new_sl = trail_result["new_sl"]
            except Exception:
                # Fallback to simple trailing stop
                if pos.type == mt5.ORDER_TYPE_BUY:
                    trail_sl = pos.price_current - (50 * point)
                    if trail_sl > pos.sl + (10 * point):
                        new_sl = round(trail_sl, info.digits)
                elif pos.type == mt5.ORDER_TYPE_SELL:
                    trail_sl = pos.price_current + (50 * point)
                    if trail_sl < pos.sl - (10 * point) or pos.sl == 0:
                        new_sl = round(trail_sl, info.digits)
            if new_sl > 0:
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": symbol,
                    "sl": new_sl,
                    "tp": pos.tp,
                }
                mod_result = mt5.order_send(request)
                if mod_result is None or mod_result.retcode != mt5.TRADE_RETCODE_DONE:
                    logger.warning("SL/TP modification failed for %s: %s", symbol, mod_result.comment if mod_result else "None")


    def execute_decision(self, decision, symbol):
        if decision["action"] != "trade":
            return False
        # Full market state check
        tradeable = is_tradeable_now(symbol)
        if not tradeable["can_trade"]:
            return False
        direction = decision["direction"]
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return False
        # Validate tick freshness
        tick_check = validate_tick_freshness(tick, symbol)
        if not tick_check["fresh"]:
            return False
        info = mt5.symbol_info(symbol)
        if direction == 1:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        # Ensure magic number is set in decision
        decision["magic"] = decision.get("magic", get_magic_number("v1", "technical", symbol))
        
        # Ensure SL/TP are valid (not zero) — use SLTP engine for optimal placement
        info = mt5.symbol_info(symbol)
        if info:
            point = info.point
            digits = info.digits
            if decision["sl"] == 0 or decision["tp"] == 0:
                rates = fetch_closed_rates(symbol, mt5.TIMEFRAME_M1, 200)
                df = pd.DataFrame(rates) if rates is not None and len(rates) >= 50 else None
                if df is not None:
                    sl_result = self.risk.calculate_dynamic_sl_tp(symbol, direction, df)
                    if decision["sl"] == 0:
                        decision["sl"] = sl_result[0]
                    if decision["tp"] == 0:
                        decision["tp"] = sl_result[1]
            # Final fallback: hardcoded ATR-based if engine still returned 0
            if decision["sl"] == 0:
                decision["sl"] = round(price - 100 * point, digits) if direction == 1 else round(price + 100 * point, digits)
            if decision["tp"] == 0:
                decision["tp"] = round(price + 200 * point, digits) if direction == 1 else round(price - 200 * point, digits)
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": decision["lot"],
            "type": order_type,
            "price": price,
            "sl": decision["sl"],
            "tp": decision["tp"],
             "magic": decision["magic"],
            "comment": f"Brain:{decision['confidence']:.2f}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = _send_order_with_fallback(request)
        if result is None:
            logger.warning("Trade Error: order_send returned None (connection lost?)")
            return False
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.warning("Trade Error: %s", result.comment)
            return False
        fill_price = result.price if hasattr(result, 'price') else price
        logger.info("%s @ %s | Lot: %s | Conf: %.2f", decision['direction_str'], fill_price, decision['lot'], decision['confidence'])
        self.record_trade_result(result.order, symbol, direction, decision["lot"], fill_price, decision["sl"], decision["tp"], 0)
        self.last_signals["_last_confidence"] = decision["confidence"]
        return {"order": result.order, "price": fill_price, "volume": decision["lot"]}

    def get_dashboard_data(self):
        report = self.stats.get_full_report()
        report["last_signals"] = {k: v for k, v in self.last_signals.items() if k != "_last_confidence"}
        return report

    def print_status(self):
        report = self.stats.get_full_report()
        logger.info("BRAIN STATUS")
        logger.info("  Win Rate: %.1f%%  |  Profit Factor: %.2f", report['win_rate'], report['profit_factor'])
        logger.info("  Expectancy: $%.2f  |  Sharpe: %.2f", report['expectancy'], report['sharpe'])
        logger.info("  Drawdown: %.1f%%  |  Kelly: %.2f%%", report['drawdown'], report['kelly'] * 100)
        logger.info("  Streak: W%d / L%d", report['win_streak'], report['loss_streak'])
        logger.info("  Daily P&L: $%.2f  |  Trades Today: %d", report['daily_pnl'], report['daily_trades'])
        logger.info("  Total Trades: %d", report['total_trades'])
        if report['strategy_stats']:
            logger.info("  Strategy Performance:")
            for strat, stats in report['strategy_stats'].items():
                logger.info("    %s: WR %.0f%% | PnL $%.2f", strat, stats['win_rate'], stats['total_pnl'])

# Alias for consistency with other brain modules
BrainV1 = Brain

# Validate brain config constants
def _validate_brain_config():
    errors = []
    def check(name, value, lo, hi):
        if not isinstance(value, (int, float)):
            errors.append(f"{name}={value!r} is not numeric")
        elif value < lo or value > hi:
            errors.append(f"{name}={value} out of range [{lo}, {hi}]")
    check("MAX_RISK_PER_TRADE", MAX_RISK_PER_TRADE, 0.1, 10.0)
    check("MIN_RISK_PER_TRADE", MIN_RISK_PER_TRADE, 0.01, 5.0)
    check("MAX_DRAWDOWN_KILL", MAX_DRAWDOWN_KILL, 0.5, 50.0)
    check("MAX_CORRELATED_POSITIONS", MAX_CORRELATED_POSITIONS, 1, 10)
    check("DAILY_LOSS_HARD_STOP", DAILY_LOSS_HARD_STOP, 0.1, 20.0)
    check("MAX_TOTAL_RISK_PCT", MAX_TOTAL_RISK_PCT, 0.5, 20.0)
    if errors:
        raise ValueError("Brain config validation failed:\n  " + "\n  ".join(errors))
_validate_brain_config()
