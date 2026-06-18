import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from json_compat import dumps as json_dumps, loads as json_loads, dump as json_dump, load as json_load
import os
import time
import threading
import logging
from datetime import datetime, timedelta, timezone
from config import (
    MAGIC_NUMBER, SCAN_SYMBOLS,
    is_system_magic,
)

logger = logging.getLogger(__name__)

# ==========================================
# MT5 DASHBOARD DATA EXPORTER
# Feeds real-time data to MQL5 EA dashboard
# ==========================================
EXPORT_DIR = os.path.join(os.path.dirname(__file__), "brain_data")
REFRESH_INTERVAL = 1.0
# ==========================================


class MT5DataExporter:
    def __init__(self):
        self.export_dir = EXPORT_DIR
        self._lock = threading.Lock()
        self._running = True
        self._last_scan_time = time.time()
        self._last_analysis_time = time.time()
        os.makedirs(self.export_dir, exist_ok=True)

        # Memory-mapped binary writer (fastest)
        self._mmap_writer = None
        try:
            from dashboard_optimizer import DashboardMMapWriter
            mmap_path = os.path.join(self.export_dir, "dashboard.bin")
            self._mmap_writer = DashboardMMapWriter(mmap_path)
            logger.info("Dashboard binary writer initialized: %s", mmap_path)
        except Exception as e:
            logger.debug("MMap writer init failed: %s", e)
        os.makedirs(os.path.join(self.export_dir, "logs"), exist_ok=True)

        # Detect all MT5 write paths
        self._mt5_common_dir = None
        self._mt5_local_dir = None
        try:
            info = mt5.terminal_info()
            if info:
                # Common folder (FILE_COMMON)
                self._mt5_common_dir = os.path.join(info.commondata_path, "brain_data")
                os.makedirs(self._mt5_common_dir, exist_ok=True)
                os.makedirs(os.path.join(self._mt5_common_dir, "logs"), exist_ok=True)

                # Local terminal folder (no FILE_COMMON)
                self._mt5_local_dir = os.path.join(info.data_path, "MQL5", "Files", "brain_data")
                os.makedirs(self._mt5_local_dir, exist_ok=True)
                os.makedirs(os.path.join(self._mt5_local_dir, "logs"), exist_ok=True)

                logger.info("MT5 Export paths: common=%s local=%s", self._mt5_common_dir, self._mt5_local_dir)
        except Exception as e:
            logger.debug("MT5 path detection failed: %s", e)

    def export_all(self):
        try:
            self._export_brain_data()
            with self._lock:
                self._export_positions()
                self._export_symbols()
                self._export_account()
                self._export_history()
        except Exception as e:
            print(f"[Exporter] Error: {e}")

    def _export_brain_data(self):
        """Export brain status data for MT5 EA dashboard."""
        try:
            brain_path = os.path.join(self.export_dir, "brain_status.json")
            if os.path.exists(brain_path):
                with open(brain_path, "r") as f:
                    data = json_load(f)
                self._save_json("mt5_dashboard.json", data)
        except Exception as e:
            logger.debug("Brain data export failed: %s", e)

    def _export_positions(self):
        open_pos = mt5.positions_get()
        my_pos = [p for p in (open_pos or []) if is_system_magic(p.magic)]
        positions = []
        for p in my_pos:
            dur = (datetime.now() - datetime.fromtimestamp(p.time)).total_seconds()
            hours = int(dur // 3600)
            mins = int((dur % 3600) // 60)
            info = mt5.symbol_info(p.symbol)
            point = info.point if info else 0.0001
            if p.type == 0:
                pips = (p.price_current - p.price_open) / point
            else:
                pips = (p.price_open - p.price_current) / point
            positions.append({
                "ticket": p.ticket,
                "symbol": p.symbol,
                "type": p.type,
                "volume": p.volume,
                "price_open": p.price_open,
                "price_current": p.price_current,
                "sl": p.sl,
                "tp": p.tp,
                "profit": round(p.profit, 2),
                "pips": round(pips, 1),
                "duration": f"{hours}h {mins}m" if hours > 0 else f"{mins}m",
            })
        self._save_json("mt5_positions.json", {"positions": positions, "count": len(positions)})

    def _export_symbols(self):
        symbols = []
        # Timeframes for MTF analysis
        timeframes = {
            "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1,
        }
        for sym_name in SCAN_SYMBOLS:
            tick = mt5.symbol_info_tick(sym_name)
            info = mt5.symbol_info(sym_name)
            if not tick or not info:
                continue

            # MTF trend analysis
            mtf_trends = {}
            for tf_name, tf_const in timeframes.items():
                rates = mt5.copy_rates_from_pos(sym_name, tf_const, 0, 50)
                trend = "NEUTRAL"
                strength = 0
                ema_short = 0
                ema_long = 0
                if rates is not None and len(rates) > 20:
                    df = pd.DataFrame(rates)
                    df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()
                    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean() if len(df) > 50 else df['EMA20']
                    ema_short = float(df['EMA20'].iloc[-1])
                    ema_long = float(df['EMA50'].iloc[-1])
                    close_val = float(df['close'].iloc[-1])
                    if close_val > ema_short > ema_long:
                        trend = "BUY"
                        strength = min(100, int((close_val - ema_long) / ema_long * 10000))
                    elif close_val < ema_short < ema_long:
                        trend = "SELL"
                        strength = min(100, int((ema_long - close_val) / ema_long * 10000))
                    else:
                        trend = "NEUTRAL"
                        strength = 0
                mtf_trends[tf_name] = {"trend": trend, "strength": strength, "ema_short": round(ema_short, 5), "ema_long": round(ema_long, 5)}

            # M1 specific data
            rates_m1 = mt5.copy_rates_from_pos(sym_name, mt5.TIMEFRAME_M1, 0, 50)
            atr = 0
            high_vol = False
            trend_m1 = "NEUTRAL"
            if rates_m1 is not None and len(rates_m1) > 14:
                df = pd.DataFrame(rates_m1)
                df['TR'] = np.maximum(df['high'] - df['low'],
                                      np.maximum(abs(df['high'] - df['close'].shift(1)),
                                                 abs(df['low'] - df['close'].shift(1))))
                df['ATR'] = df['TR'].rolling(14).mean()
                df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()
                atr_val = df['ATR'].iloc[-1]
                if not np.isnan(atr_val):
                    atr = float(atr_val)
                atr_ma = df['ATR'].rolling(30).median().iloc[-1]
                if not np.isnan(atr_ma) and atr_ma > 0:
                    high_vol = atr > atr_ma
                close_val = float(df['close'].iloc[-1])
                ema20_val = float(df['EMA20'].iloc[-1])
                if close_val > ema20_val:
                    trend_m1 = "BUY"
                elif close_val < ema20_val:
                    trend_m1 = "SELL"

            # Compute overall MTF consensus
            buy_count = sum(1 for v in mtf_trends.values() if v["trend"] == "BUY")
            sell_count = sum(1 for v in mtf_trends.values() if v["trend"] == "SELL")
            total_tf = len(mtf_trends)
            if buy_count > sell_count and buy_count >= total_tf * 0.5:
                consensus = "BUY"
            elif sell_count > buy_count and sell_count >= total_tf * 0.5:
                consensus = "SELL"
            else:
                consensus = "NEUTRAL"

            symbols.append({
                "name": sym_name,
                "bid": tick.bid,
                "ask": tick.ask,
                "spread": info.spread,
                "point": info.point,
                "digits": info.digits,
                "atr": round(atr, 5),
                "trend": trend_m1,
                "high_vol": high_vol,
                "volume_min": info.volume_min,
                "volume_max": info.volume_max,
                "swap_long": info.swap_long,
                "swap_short": info.swap_short,
                "mtf": mtf_trends,
                "mtf_consensus": consensus,
                "mtf_buy_count": buy_count,
                "mtf_sell_count": sell_count,
            })
        self._save_json("mt5_symbols.json", {"symbols": symbols, "count": len(symbols)})

    def _export_account(self):
        acct = mt5.account_info()
        if not acct:
            return
        data = {
            "login": acct.login,
            "name": acct.name,
            "server": acct.server,
            "company": acct.company,
            "balance": acct.balance,
            "equity": acct.equity,
            "margin": acct.margin,
            "margin_free": acct.margin_free,
            "margin_level": acct.margin_level,
            "leverage": acct.leverage,
            "currency": acct.currency,
            "profit": acct.profit,
            "credit": acct.credit,
            "timestamp": datetime.now().isoformat(),
        }
        self._save_json("mt5_account.json", data)

    def _export_history(self):
        now = datetime.now()
        start = now - timedelta(days=30)
        deals = mt5.history_deals_get(start, now, group="*")
        history = []
        for d in (deals or []):
            if is_system_magic(d.magic) and d.entry == mt5.DEAL_ENTRY_OUT:
                history.append({
                    "ticket": d.ticket,
                    "time": datetime.fromtimestamp(d.time).strftime("%m-%d %H:%M"),
                    "symbol": d.symbol,
                    "type": d.type,
                    "volume": d.volume,
                    "price": d.price,
                    "profit": round(d.profit, 2),
                    "comment": d.comment,
                })
        self._save_json("mt5_history.json", {"history": history[-50:], "count": len(history)})

    def write_brain_status(self, regime, session, consensus, confidence, circuit_breaker,
                           health_score, cpu, memory, errors, avg_spread, analyses, skips, last_dir):
        data = {
            "regime": regime,
            "session": session,
            "consensus": consensus,
            "confidence": confidence,
            "circuit_breaker": circuit_breaker,
            "health_score": health_score,
            "cpu": cpu,
            "memory": memory,
            "errors": errors,
            "avg_spread": avg_spread,
            "analyses": analyses,
            "skips": skips,
            "last_direction": last_dir,
            "timestamp": datetime.now().isoformat(),
        }
        self._save_json("brain_status.json", data)

    def _calc_sharpe(self, trades):
        if len(trades) < 10:
            return 0
        returns = [t.get("profit", 0) for t in trades]
        mean_r = np.mean(returns)
        std_r = np.std(returns)
        if std_r == 0:
            return 0
        return round(mean_r / std_r * np.sqrt(252), 2)

    def _calc_kelly(self, trades):
        if len(trades) < 20:
            return 0.02
        wins = [t.get("profit", 0) for t in trades if t.get("profit", 0) > 0]
        losses = [abs(t.get("profit", 0)) for t in trades if t.get("profit", 0) < 0]
        if not wins or not losses:
            return 0.02
        win_rate = len(wins) / len(trades)
        avg_win = np.mean(wins)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 0.02
        wl_ratio = avg_win / avg_loss
        kelly = win_rate - ((1 - win_rate) / wl_ratio)
        return max(0.01, min(kelly * 0.5, 0.05))

    def _save_json(self, filename, data):
        filepath = os.path.join(self.export_dir, filename)
        tmp = filepath + ".tmp"
        with open(tmp, "w") as f:
            json_dump(data, f, default=str)
        if os.path.exists(filepath):
            os.replace(tmp, filepath)
        else:
            os.rename(tmp, filepath)

        # Also write to MT5 common data folder (for EA dashboard)
        if self._mt5_common_dir:
            try:
                mt5_path = os.path.join(self._mt5_common_dir, filename)
                mt5_tmp = mt5_path + ".tmp"
                with open(mt5_tmp, "w") as f:
                    json_dump(data, f, default=str)
                os.replace(mt5_tmp, mt5_path)
            except Exception as e:
                logger.debug("MT5 common write failed for %s: %s", filename, e)

        # Also write to MT5 local Files folder (fallback)
        if self._mt5_local_dir:
            try:
                local_path = os.path.join(self._mt5_local_dir, filename)
                local_tmp = local_path + ".tmp"
                with open(local_tmp, "w") as f:
                    json_dump(data, f, default=str)
                os.replace(local_tmp, local_path)
            except Exception as e:
                logger.debug("MT5 local write failed for %s: %s", filename, e)

        # Write binary format for fast EA reads
        if filename == "mt5_dashboard.json" and self._mmap_writer:
            try:
                self._mmap_writer.write(data)
                # Also write binary to MT5 folders
                if self._mt5_common_dir:
                    import shutil
                    shutil.copy2(os.path.join(self.export_dir, "dashboard.bin"),
                                os.path.join(self._mt5_common_dir, "dashboard.bin"))
                if self._mt5_local_dir:
                    import shutil
                    shutil.copy2(os.path.join(self.export_dir, "dashboard.bin"),
                                os.path.join(self._mt5_local_dir, "dashboard.bin"))
            except Exception as e:
                logger.debug("Binary write failed: %s", e)

    def _load_json(self, filename):
        filepath = os.path.join(self.export_dir, filename)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r") as f:
                return json_load(f)
        except (ValueError, OSError) as e:
            logger.debug("JSON load failed for %s: %s", filepath, e)
            return None

    def run_continuous(self):
        print(f"[MT5 Exporter] Started. Exporting to: {self.export_dir}")
        print(f"[MT5 Exporter] Refresh: {REFRESH_INTERVAL}s | Symbols: {len(SCAN_SYMBOLS)}")
        try:
            while self._running:
                self.export_all()
                time.sleep(REFRESH_INTERVAL)
        except KeyboardInterrupt:
            print("\n[MT5 Exporter] Stopped.")
            self._running = False


def run_exporter():
    if not mt5.initialize():
        print("MT5 Init Failed. Ensure MT5 is open and logged in.")
        return
    exporter = MT5DataExporter()
    exporter.run_continuous()
    mt5.shutdown()


if __name__ == "__main__":
    run_exporter()
