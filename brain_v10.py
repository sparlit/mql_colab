import mt5_mcp as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import time as _time
from collections import deque
import threading
import logging
from ai_client import get_ai_client
from config import MAGIC_NUMBER, DATA_DIR, CORRELATION_GROUPS
from indicators import validate_rate_freshness, ema
from order_flow import OrderFlowAnalyzer
from market_intelligence import NewsCalendar, SentimentFeed
from institutional_analytics import OrderBookHeatmap, VolumeProfile
from microstructure import LatencyArbitrage, MarketImpactModel
from providers import SignalProvider

logger = logging.getLogger(__name__)

# Asset groups
FOREX_MAJORS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD"]
FOREX_CROSSES = ["EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD", "GBPAUD", "EURNZD"]
COMMODITIES = ["XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD"]
INDICES = ["US30", "US500", "NAS100", "GER40", "UK100", "JP225"]
ENERGY = ["USOIL", "UKOIL", "NATGAS"]
CRYPTO = ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"]

ALL_WATCH = FOREX_MAJORS + FOREX_CROSSES + COMMODITIES + INDICES + ENERGY + CRYPTO

# Timeframes for multi-TF analysis
TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}
MTF_WEIGHTS = {"M1": 0.05, "M5": 0.10, "M15": 0.15, "M30": 0.15, "H1": 0.25, "H4": 0.20, "D1": 0.10}

# Refresh intervals
CORRELATION_REFRESH_INTERVAL = 600


class MultiTimeframeAnalyzer:
    def __init__(self):
        self.cache = {}
        self.cache_time = {}
        self._lock = threading.Lock()

    def analyze_symbol(self, symbol, timeframes=None):
        if timeframes is None:
            timeframes = list(TIMEFRAMES.keys())
        results = {}
        # Fetch M1 data for cross-timeframe alignment
        m1_rates = None
        try:
            from indicators import fetch_closed_rates, align_to_m1_grid
            m1_rates = fetch_closed_rates(symbol, mt5.TIMEFRAME_M1, 300)
        except Exception:
            pass
        for tf_name in timeframes:
            tf = TIMEFRAMES.get(tf_name)
            if tf is None:
                continue
            cache_key = f"{symbol}_{tf_name}"
            now = _time.time()
            with self._lock:
                if cache_key in self.cache and (now - self.cache_time.get(cache_key, 0)) < 30:
                    results[tf_name] = self.cache[cache_key]
                    continue
            try:
                rates = mt5.copy_rates_from_pos(symbol, tf, 0, 300)
                if rates is None or len(rates) < 50:
                    continue
                rate_check = validate_rate_freshness(rates, tf)
                if not rate_check["fresh"]:
                    continue
                # Align higher TF data to M1 grid for temporal consistency
                aligned_rates = rates
                if m1_rates is not None and tf != mt5.TIMEFRAME_M1:
                    try:
                        aligned = align_to_m1_grid(m1_rates, rates)
                        if aligned is not None and len(aligned) > 0:
                            # Use the aligned rates for analysis
                            aligned_rates = aligned
                    except Exception:
                        pass
                df = pd.DataFrame(aligned_rates)
                analysis = self._analyze_tf(df, symbol, tf_name)
                results[tf_name] = analysis
                with self._lock:
                    self.cache[cache_key] = analysis
                    self.cache_time[cache_key] = now
            except Exception as e:
                logger.debug("MTF analysis failed for %s %s: %s", symbol, tf_name, e)
        return results

    def _analyze_tf(self, df, symbol, tf_name):
        c = df['close'].values
        h = df['high'].values
        l = df['low'].values
        v = df['tick_volume'].values
        last_close = c[-1]

        ema5 = pd.Series(c).ewm(span=5).mean().values
        ema13 = pd.Series(c).ewm(span=13).mean().values
        ema21 = pd.Series(c).ewm(span=21).mean().values
        ema50 = pd.Series(c).ewm(span=50).mean().values
        ema200 = pd.Series(c).ewm(span=200).mean().values if len(c) >= 200 else None

        delta = pd.Series(c).diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss
        rsi = (100 - (100 / (1 + rs))).values

        bb_ma = pd.Series(c).rolling(20).mean().values
        bb_std = pd.Series(c).rolling(20).std().values
        bb_up = bb_ma + bb_std * 2
        bb_dn = bb_ma - bb_std * 2
        bb_width = (bb_up - bb_dn) / np.where(bb_ma == 0, 1, bb_ma) * 100

        tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
        atr = pd.Series(tr).rolling(14).mean().values
        atr_ma = pd.Series(atr).rolling(30).mean().values

        ema12 = self._ema(c, 12)
        ema26 = self._ema(c, 26)
        macd = ema12 - ema26
        macd_signal = self._ema(macd, 9)
        macd_hist = macd - macd_signal

        vol_ma = pd.Series(v).rolling(20).mean().values

        # Trend
        if ema5[-1] > ema13[-1] > ema21[-1] > ema50[-1]:
            trend = "STRONG_UP"
            trend_strength = 1.0
        elif ema5[-1] > ema13[-1] > ema21[-1]:
            trend = "UP"
            trend_strength = 0.7
        elif ema5[-1] < ema13[-1] < ema21[-1] < ema50[-1]:
            trend = "STRONG_DOWN"
            trend_strength = -1.0
        elif ema5[-1] < ema13[-1] < ema21[-1]:
            trend = "DOWN"
            trend_strength = -0.7
        else:
            trend = "RANGING"
            trend_strength = 0

        # RSI signal
        rsi_val = rsi[-1] if not np.isnan(rsi[-1]) else 50
        if rsi_val < 30:
            rsi_signal = "OVERSOLD"
        elif rsi_val > 70:
            rsi_signal = "OVERBOUGHT"
        else:
            rsi_signal = "NEUTRAL"

        # MACD signal
        if macd[-1] > macd_signal[-1] and not np.isnan(macd[-2]) and not np.isnan(macd_signal[-2]) and macd[-2] <= macd_signal[-2]:
            macd_signal_val = "BULLISH_CROSS"
        elif macd[-1] < macd_signal[-1] and not np.isnan(macd[-2]) and not np.isnan(macd_signal[-2]) and macd[-2] >= macd_signal[-2]:
            macd_signal_val = "BEARISH_CROSS"
        elif macd[-1] > macd_signal[-1]:
            macd_signal_val = "BULLISH"
        elif macd[-1] < macd_signal[-1]:
            macd_signal_val = "BEARISH"
        else:
            macd_signal_val = "NEUTRAL"

        # BB signal
        bb_pos = (last_close - bb_dn[-1]) / (bb_up[-1] - bb_dn[-1]) if (bb_up[-1] - bb_dn[-1]) > 0 else 0.5
        if bb_pos < 0.1:
            bb_signal = "OVERSOLD"
        elif bb_pos > 0.9:
            bb_signal = "OVERBOUGHT"
        elif bb_width[-1] < np.nanmedian(bb_width) * 0.7:
            bb_signal = "SQUEEZE"
        else:
            bb_signal = "NEUTRAL"

        # Volatility
        vol_ratio = atr[-1] / atr_ma[-1] if atr_ma[-1] > 0 else 1
        if vol_ratio > 1.5:
            volatility = "HIGH"
        elif vol_ratio < 0.5:
            volatility = "LOW"
        else:
            volatility = "NORMAL"

        # Volume
        vol_val = v[-1] / vol_ma[-1] if vol_ma[-1] > 0 else 1
        vol_status = "HIGH" if vol_val > 1.5 else "LOW" if vol_val < 0.5 else "NORMAL"

        # Support/Resistance
        lookback = min(50, len(df))
        recent_highs = h[-lookback:]
        recent_lows = l[-lookback:]
        resistance = np.max(recent_highs)
        support = np.min(recent_lows)
        range_pct = (resistance - support) / last_close * 100 if last_close > 0 else 0

        # Price position
        price_pos = (last_close - support) / (resistance - support) if (resistance - support) > 0 else 0.5

        # Momentum score (-1 to 1)
        momentum = 0
        if trend_strength > 0:
            momentum += 0.3
        if rsi_val < 40:
            momentum += 0.2
        elif rsi_val > 60:
            momentum -= 0.2
        if macd_hist[-1] > 0:
            momentum += 0.2
        else:
            momentum -= 0.2
        if vol_ratio > 1:
            momentum *= 1.2
        momentum = max(-1, min(1, momentum))

        return {
            "symbol": symbol,
            "timeframe": tf_name,
            "close": round(last_close, 5),
            "trend": trend,
            "trend_strength": round(trend_strength, 2),
            "rsi": round(rsi_val, 1),
            "rsi_signal": rsi_signal,
            "macd": macd_signal_val,
            "bb_signal": bb_signal,
            "bb_position": round(bb_pos, 3),
            "volatility": volatility,
            "vol_ratio": round(vol_ratio, 2),
            "volume_status": vol_status,
            "atr": round(atr[-1], 5),
            "support": round(support, 5),
            "resistance": round(resistance, 5),
            "range_pct": round(range_pct, 3),
            "price_position": round(price_pos, 3),
            "momentum": round(momentum, 3),
            "ema5": round(ema5[-1], 5),
            "ema13": round(ema13[-1], 5),
            "ema50": round(ema50[-1], 5),
        }

    @staticmethod
    def _ema(data, span):
        return ema(data, span)


class CorrelationAnalyzer:
    def __init__(self):
        self.correlation_cache = {}
        self.cache_time = 0
        self._lock = threading.Lock()

    def calculate_correlations(self, symbols, timeframe=mt5.TIMEFRAME_H1, lookback=200):
        now = _time.time()
        with self._lock:
            if self.correlation_cache and (now - self.cache_time) < CORRELATION_REFRESH_INTERVAL:
                return self.correlation_cache

        price_data = {}
        for sym in symbols:
            try:
                rates = mt5.copy_rates_from_pos(sym, timeframe, 0, lookback)
                if rates is not None and len(rates) > 20:
                    df = pd.DataFrame(rates)
                    price_data[sym] = df['close'].pct_change().dropna().values[-lookback:]
            except Exception as e:
                logger.debug("Correlation data fetch failed for %s: %s", sym, e)

        if len(price_data) < 2:
            return {}

        min_len = min(len(v) for v in price_data.values())
        aligned = {k: v[-min_len:] for k, v in price_data.items()}
        syms = list(aligned.keys())

        matrix = {}
        for i, s1 in enumerate(syms):
            for j, s2 in enumerate(syms):
                if i < j:
                    corr = np.corrcoef(aligned[s1], aligned[s2])[0, 1]
                    matrix[f"{s1}_{s2}"] = round(corr, 3)
                    matrix[f"{s2}_{s1}"] = round(corr, 3)

        with self._lock:
            self.correlation_cache = matrix
            self.cache_time = now
        return matrix

    def get_pair_correlation(self, sym1, sym2):
        matrix = self.correlation_cache
        key = f"{sym1}_{sym2}"
        return matrix.get(key, 0)

    def get_group_correlation(self, group_name):
        group = CORRELATION_GROUPS.get(group_name)
        if not group:
            return {}
        symbols = group["symbols"]
        result = {}
        for i, s1 in enumerate(symbols):
            for j, s2 in enumerate(symbols):
                if i < j:
                    corr = self.get_pair_correlation(s1, s2)
                    result[f"{s1}_{s2}"] = corr
        return result

    def get_regime(self):
        if not self.correlation_cache:
            return "unknown"
        values = list(self.correlation_cache.values())
        avg_corr = np.mean(values) if values else 0
        if avg_corr > 0.7:
            return "risk_on"
        elif avg_corr < -0.3:
            return "divergent"
        elif avg_corr > 0.4:
            return "moderate"
        else:
            return "mixed"


class AssetScanner:
    def __init__(self):
        self.asset_data = {}
        self._lock = threading.Lock()
        self._last_scan = 0

    def scan_all(self, symbols=None):
        if symbols is None:
            symbols = ALL_WATCH
        now = _time.time()
        if now - self._last_scan < 60:
            return self.asset_data

        results = {}
        for sym in symbols:
            try:
                tick = mt5.symbol_info_tick(sym)
                info = mt5.symbol_info(sym)
                if not tick or not info:
                    continue
                results[sym] = {
                    "bid": tick.bid,
                    "ask": tick.ask,
                    "spread": info.spread,
                    "point": info.point,
                    "digits": info.digits,
                    "visible": info.visible,
                    "trade_mode": info.trade_mode,
                }
            except Exception as e:
                logger.debug("Asset scan failed for %s: %s", sym, e)

        with self._lock:
            self.asset_data = results
            self._last_scan = now
        return results

    def get_asset(self, symbol):
        return self.asset_data.get(symbol, {})

    def get_category_assets(self, category):
        mapping = {
            "forex_majors": FOREX_MAJORS,
            "forex_crosses": FOREX_CROSSES,
            "commodities": COMMODITIES,
            "indices": INDICES,
            "energy": ENERGY,
            "crypto": CRYPTO,
        }
        syms = mapping.get(category, [])
        return {s: self.asset_data.get(s, {}) for s in syms if s in self.asset_data}


class MarketRegimeDetector:
    def __init__(self):
        self.regime_history = deque(maxlen=50)
        self.current_regime = "unknown"
        self.regime_confidence = 0

    def detect(self, mtf_results, correlations):
        signals = {"trend_count": 0, "range_count": 0, "vol_high": 0, "vol_low": 0}
        total = 0
        for sym, tfs in mtf_results.items():
            for tf_name, data in tfs.items():
                total += 1
                if "UP" in data.get("trend", "") or "DOWN" in data.get("trend", ""):
                    signals["trend_count"] += 1
                else:
                    signals["range_count"] += 1
                if data.get("volatility") == "HIGH":
                    signals["vol_high"] += 1
                elif data.get("volatility") == "LOW":
                    signals["vol_low"] += 1

        if total == 0:
            return "unknown", 0

        trend_pct = signals["trend_count"] / total
        range_pct = signals["range_count"] / total
        vol_high_pct = signals["vol_high"] / total
        avg_corr = 0
        if correlations:
            vals = [v for v in correlations.values() if isinstance(v, (int, float))]
            avg_corr = np.mean(vals) if vals else 0

        if trend_pct > 0.6 and avg_corr > 0.5:
            regime = "trending_correlated"
            conf = trend_pct * avg_corr
        elif trend_pct > 0.6:
            regime = "trending_divergent"
            conf = trend_pct * 0.7
        elif range_pct > 0.6:
            regime = "ranging"
            conf = range_pct * 0.8
        elif vol_high_pct > 0.5:
            regime = "volatile"
            conf = vol_high_pct * 0.9
        else:
            regime = "mixed"
            conf = 0.5

        self.current_regime = regime
        self.regime_confidence = round(conf, 3)
        self.regime_history.append({"regime": regime, "conf": conf, "time": _time.time()})
        return regime, conf


class BrainV10:
    def __init__(self, brain_v9):
        self.v9 = brain_v9
        self.mtf = MultiTimeframeAnalyzer()
        self.correlation = CorrelationAnalyzer()
        self.scanner = AssetScanner()
        self.regime_detector = MarketRegimeDetector()
        self.last_analysis = {}
        self._analysis_lock = threading.Lock()
        self.ai = get_ai_client()
        self._order_flow = None
        self._news = None
        self._sentiment = None
        self._order_book = None
        self._volume_profile = None
        self._latency_arb = None
        self._impact_model = None
        self._signal_provider = None
        try:
            self._order_flow = OrderFlowAnalyzer()
            self._news = NewsCalendar()
            self._sentiment = SentimentFeed()
            self._order_book = OrderBookHeatmap()
            self._volume_profile = VolumeProfile()
            self._latency_arb = LatencyArbitrage()
            self._impact_model = MarketImpactModel()
            self._signal_provider = SignalProvider()
        except Exception:
            pass

    def analyze(self, symbol, timeframe=mt5.TIMEFRAME_M1, df=None):
        decision = self.v9.analyze(symbol, timeframe, df=df)

        # If upstream already blocked due to market state, propagate immediately
        if decision.get("action") == "hold" and "market_closed" in decision.get("reason", ""):
            return decision

        mtf_data = self.mtf.analyze_symbol(symbol)
        with self._analysis_lock:
            self.last_analysis = {
                "symbol": symbol,
                "mtf": mtf_data,
                "time": datetime.now().isoformat(),
            }
        if mtf_data:
            weighted_momentum = 0
            total_weight = 0
            for tf_name, data in mtf_data.items():
                weight = MTF_WEIGHTS.get(tf_name, 0.1)
                weighted_momentum += data.get("momentum", 0) * weight
                total_weight += weight
            if total_weight > 0:
                avg_momentum = weighted_momentum / total_weight
            else:
                avg_momentum = 0
            decision["v10_mtf_momentum"] = round(avg_momentum, 3)

            # AI multi-TF synthesis (additive adjustments)
            try:
                if self.ai.is_available() and decision.get("action") == "trade":
                    ai_result = self.ai.analyze_multi_tf(mtf_data, symbol)
                    if ai_result and isinstance(ai_result, dict):
                        ai_rec = ai_result.get("recommendation", "HOLD")
                        ai_conf = ai_result.get("confidence", 0.5)
                        adjs = decision.get('confidence_adjustments', {})
                        if ai_rec == "BUY" and decision.get("direction") == 1:
                            adjs['v10_ai_boost'] = 0.15
                        elif ai_rec == "SELL" and decision.get("direction") == -1:
                            adjs['v10_ai_boost'] = 0.15
                        elif ai_rec == "HOLD":
                            adjs['v10_ai_boost'] = -0.10
                        else:
                            adjs['v10_ai_boost'] = 0.0
                        decision['confidence_adjustments'] = adjs
                        decision["v10_ai_synthesis"] = ai_result
            except Exception as e:
                logger.debug("V10 AI synthesis failed: %s", e)
            decision["v10_mtf_trend"] = mtf_data.get("H1", {}).get("trend", "unknown")
            if decision.get("action") == "trade":
                direction = decision.get("direction", 0)
                h1_trend = mtf_data.get("H1", {}).get("trend_strength", 0)
                adjs = decision.get('confidence_adjustments', {})
                # H1 trend alignment (additive adjustments, max ±10%)
                if direction == 1 and h1_trend < -0.3:
                    adjs['v10_h1_trend'] = -0.40
                elif direction == -1 and h1_trend > 0.3:
                    adjs['v10_h1_trend'] = -0.40
                elif direction == 1 and h1_trend > 0.5:
                    adjs['v10_h1_trend'] = 0.10
                elif direction == -1 and h1_trend < -0.5:
                    adjs['v10_h1_trend'] = 0.10
                else:
                    adjs['v10_h1_trend'] = 0.0
                decision['confidence_adjustments'] = adjs
                base = decision.get("confidence", 0)
                total_adj = sum(adjs.values())
                decision["confidence"] = max(0.1, min(base + total_adj, 0.98))

        # Order flow analysis
        if self._order_flow and decision.get("action") == "trade":
            try:
                self._order_flow.on_tick(symbol)
                of_signal = self._order_flow.get_imbalance(symbol)
                if of_signal and of_signal.get("imbalance", 0) != 0:
                    of_dir = 1 if of_signal["imbalance"] > 0 else -1
                    if of_dir == decision.get("direction"):
                        adjs = decision.get('confidence_adjustments', {})
                        adjs['v10_order_flow'] = 0.05
                        decision['confidence_adjustments'] = adjs
                        decision["confidence"] = max(0.1, min(decision["confidence"] + 0.05, 0.98))
            except Exception:
                pass

        # News calendar impact
        if self._news and decision.get("action") == "trade":
            try:
                impact_mod, impact_reason = self._news.get_impact_modifier()
                if impact_mod < 1.0:
                    adjs = decision.get('confidence_adjustments', {})
                    adjs['v10_news'] = (impact_mod - 1.0) * 0.15
                    decision['confidence_adjustments'] = adjs
                    decision["confidence"] = max(0.1, min(decision["confidence"] + adjs['v10_news'], 0.98))
            except Exception:
                pass

        # Order book analytics
        if self._order_book and decision.get("action") == "trade":
            try:
                self._order_book.capture_snapshot(symbol)
                imbalance = self._order_book.get_imbalance_ratio()
                if imbalance > 1.2 and decision.get("direction") == 1:
                    adjs = decision.get('confidence_adjustments', {})
                    adjs['v10_order_book'] = 0.05
                    decision['confidence_adjustments'] = adjs
                    decision["confidence"] = max(0.1, min(decision["confidence"] + 0.05, 0.98))
                elif imbalance < 0.8 and decision.get("direction") == -1:
                    adjs = decision.get('confidence_adjustments', {})
                    adjs['v10_order_book'] = 0.05
                    decision['confidence_adjustments'] = adjs
                    decision["confidence"] = max(0.1, min(decision["confidence"] + 0.05, 0.98))
            except Exception:
                pass

        # Microstructure analysis
        if self._impact_model and decision.get("action") == "trade":
            try:
                info = mt5.symbol_info(symbol)
                if info:
                    vol = decision.get("lot", 0.01) * info.trade_tick_value * 1000
                    adv = info.volume_real if hasattr(info, 'volume_real') else 100000
                    sigma = decision.get("v10_mtf_momentum", 0.01)
                    impact = self._impact_model.estimate_impact(vol, adv, max(abs(sigma), 0.001))
                    if impact and impact.get("total_bps", 0) > 5:
                        adjs = decision.get('confidence_adjustments', {})
                        adjs['v10_microstructure'] = -0.05
                        decision['confidence_adjustments'] = adjs
                        decision["confidence"] = max(0.1, min(decision["confidence"] - 0.05, 0.98))
            except Exception:
                pass

        # Signal provider publish
        if self._signal_provider and decision.get("action") == "trade":
            try:
                self._signal_provider.publish_signal(
                    symbol=symbol,
                    direction=decision.get("direction", 0),
                    price=decision.get("sl", 0),
                    sl=decision.get("sl", 0),
                    tp=decision.get("tp", 0),
                    lot=decision.get("lot", 0.01),
                    confidence=decision.get("confidence", 0),
                    strategy="v10_intelligence",
                )
            except Exception:
                pass

        return decision

    def full_scan(self):
        self.scanner.scan_all()
        all_syms = list(self.scanner.asset_data.keys())[:30]
        mtf_results = {}
        for sym in all_syms[:15]:
            mtf_results[sym] = self.mtf.analyze_symbol(sym, ["M15", "H1", "H4", "D1"])
        correlations = self.correlation.calculate_correlations(all_syms)
        regime, regime_conf = self.regime_detector.detect(mtf_results, correlations)
        return {
            "symbols_scanned": len(all_syms),
            "mtf_results": mtf_results,
            "correlations": correlations,
            "regime": regime,
            "regime_confidence": regime_conf,
            "groups": {name: self.correlation.get_group_correlation(name) for name in CORRELATION_GROUPS},
        }

    def get_symbol_mtf(self, symbol):
        return self.mtf.analyze_symbol(symbol)

    def get_correlation(self, sym1, sym2):
        return self.correlation.get_pair_correlation(sym1, sym2)

    def get_market_regime(self):
        return self.regime_detector.current_regime, self.regime_detector.regime_confidence

    def get_asset_price(self, symbol):
        return self.scanner.get_asset(symbol)

    def get_category(self, category):
        return self.scanner.get_category_assets(category)

    def manage_positions(self, symbol):
        self.v9.manage_positions(symbol)

    def execute_decision(self, decision, symbol):
        return self.v9.execute_decision(decision, symbol)

    def record_trade(self, *args, **kwargs):
        self.v9.record_trade(*args, **kwargs)

    def record_trade_close(self, *args, **kwargs):
        self.v9.record_trade_close(*args, **kwargs)

    def record_trade_open(self, *args, **kwargs):
        return self.v9.record_trade_open(*args, **kwargs)

    def print_status(self):
        self.v9.print_status()
        regime, conf = self.get_market_regime()
        scan = self.last_analysis
        logger.info("  BRAIN V10 — MULTI-TIMEFRAME & CORRELATION")
        logger.info("  Market Regime: %s (confidence: %.2f)", regime, conf)
        if scan.get("mtf"):
            sym = scan.get("symbol", "?")
            logger.info("")
            logger.info("  MTF Analysis: %s", sym)
            for tf, data in scan["mtf"].items():
                logger.info("    %4s: %-14s RSI:%5.1f MACD:%-16s Mom:%+.3f ATR:%s", tf, data['trend'], data['rsi'], data['macd'], data['momentum'], data['volatility'])

    def get_dashboard_data(self):
        data = self.v9.get_dashboard_data()
        regime, conf = self.get_market_regime()
        data["v10"] = {
            "regime": regime,
            "regime_confidence": conf,
            "last_symbol": self.last_analysis.get("symbol", ""),
            "mtf_momentum": self.last_analysis.get("mtf", {}).get("H1", {}).get("momentum", 0),
            "mtf_trend": self.last_analysis.get("mtf", {}).get("H1", {}).get("trend", "unknown"),
        }
        return data
