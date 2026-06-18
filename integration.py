"""
Unified Integration Module
Wraps all advanced modules for use by the brain chain and orchestrator.
"""
import threading
import logging

logger = logging.getLogger(__name__)

# Lazy-loaded instances
_order_flow = None
_pattern_recognition = None
_ml_enhancements = None
_market_intelligence = None
_execution_optimization = None
_execution_compliance = None
_risk_advanced = None
_portfolio_risk = None
_gpu_engine = None
_infrastructure = None
_data_analytics = None
_providers = None
_research_dev = None
_strategies_advanced = None
_cache_layer = None
_microstructure = None
_lock = threading.Lock()


def get_order_flow():
    global _order_flow
    if _order_flow is None:
        with _lock:
            if _order_flow is None:
                try:
                    from order_flow import OrderFlowAnalyzer
                    _order_flow = OrderFlowAnalyzer()
                except Exception as e:
                    logger.debug("OrderFlow init failed: %s", e)
    return _order_flow


def get_pattern_recognition():
    global _pattern_recognition
    if _pattern_recognition is None:
        with _lock:
            if _pattern_recognition is None:
                try:
                    from pattern_recognition import CandlestickAIClassifier, SupportResistanceAI
                    _pattern_recognition = {
                        "candlestick": CandlestickAIClassifier(),
                        "support_resistance": SupportResistanceAI(),
                    }
                except Exception as e:
                    logger.debug("PatternRecognition init failed: %s", e)
    return _pattern_recognition


def get_ml_enhancements():
    global _ml_enhancements
    if _ml_enhancements is None:
        with _lock:
            if _ml_enhancements is None:
                try:
                    from ml_enhancements import FeatureStore, MLScorer, AnomalyDetector, FeatureNormalizer, EventDrivenBacktestEngine
                    normalizer = FeatureNormalizer()
                    try:
                        normalizer.load()
                    except Exception:
                        pass
                    _ml_enhancements = {
                        "features": FeatureStore(),
                        "scorer": MLScorer(),
                        "anomaly": AnomalyDetector(),
                        "normalizer": normalizer,
                        "backtest_engine": EventDrivenBacktestEngine(),
                    }
                except Exception as e:
                    logger.debug("MLEnhancements init failed: %s", e)
    return _ml_enhancements


def get_market_intelligence():
    global _market_intelligence
    if _market_intelligence is None:
        with _lock:
            if _market_intelligence is None:
                try:
                    from market_intelligence import NewsCalendar, SentimentFeed
                    _market_intelligence = {
                        "news": NewsCalendar(),
                        "sentiment": SentimentFeed(),
                    }
                except Exception as e:
                    logger.debug("MarketIntelligence init failed: %s", e)
    return _market_intelligence


def get_execution_optimization():
    global _execution_optimization
    if _execution_optimization is None:
        with _lock:
            if _execution_optimization is None:
                try:
                    from execution_optimization import TWAPExecutor, LatencyOptimizer, FillRateAnalytics
                    _execution_optimization = {
                        "twap": TWAPExecutor(),
                        "latency": LatencyOptimizer(),
                        "fill_rate": FillRateAnalytics(),
                    }
                except Exception as e:
                    logger.debug("ExecutionOptimization init failed: %s", e)
    return _execution_optimization


def get_execution_compliance():
    global _execution_compliance
    if _execution_compliance is None:
        with _lock:
            if _execution_compliance is None:
                try:
                    from execution_compliance import PositionLimitMonitor, WashTradeDetector
                    _execution_compliance = {
                        "position_limit": PositionLimitMonitor(),
                        "wash_trade": WashTradeDetector(),
                    }
                except Exception as e:
                    logger.debug("ExecutionCompliance init failed: %s", e)
    return _execution_compliance


def get_risk_advanced():
    global _risk_advanced
    if _risk_advanced is None:
        with _lock:
            if _risk_advanced is None:
                try:
                    from risk_advanced import CorrelationStressTest, RiskParity, BlackSwanDetector
                    _risk_advanced = {
                        "stress_test": CorrelationStressTest(),
                        "risk_parity": RiskParity(),
                        "black_swan": BlackSwanDetector(),
                    }
                except Exception as e:
                    logger.debug("RiskAdvanced init failed: %s", e)
    return _risk_advanced


def get_portfolio_risk():
    global _portfolio_risk
    if _portfolio_risk is None:
        with _lock:
            if _portfolio_risk is None:
                try:
                    from portfolio_risk import VaRCalculator, DrawdownCircuit, RecoveryMode
                    _portfolio_risk = {
                        "var": VaRCalculator(),
                        "drawdown": DrawdownCircuit(),
                        "recovery": RecoveryMode(),
                    }
                except Exception as e:
                    logger.debug("PortfolioRisk init failed: %s", e)
    return _portfolio_risk


def get_gpu_engine():
    global _gpu_engine
    if _gpu_engine is None:
        with _lock:
            if _gpu_engine is None:
                try:
                    from gpu_engine import get_gpu_engine as _get_gpu
                    _gpu_engine = _get_gpu()
                except Exception as e:
                    logger.debug("GPUEngine init failed: %s", e)
    return _gpu_engine


def get_infrastructure():
    global _infrastructure
    if _infrastructure is None:
        with _lock:
            if _infrastructure is None:
                try:
                    from infrastructure import KubernetesDeployer, ClickHouseWriter
                    _infrastructure = {
                        "k8s": KubernetesDeployer(),
                        "clickhouse": ClickHouseWriter(),
                    }
                except Exception as e:
                    logger.debug("Infrastructure init failed: %s", e)
    return _infrastructure


def get_data_analytics():
    global _data_analytics
    if _data_analytics is None:
        with _lock:
            if _data_analytics is None:
                try:
                    from data_analytics import TickDatabase, RealTimePnL, PerformanceAttribution
                    _data_analytics = {
                        "tick_db": TickDatabase(),
                        "pnl": RealTimePnL(),
                        "attribution": PerformanceAttribution(),
                    }
                except Exception as e:
                    logger.debug("DataAnalytics init failed: %s", e)
    return _data_analytics


def get_providers():
    global _providers
    if _providers is None:
        with _lock:
            if _providers is None:
                try:
                    from providers import SignalProvider, PortfolioMultiSymbol
                    _providers = {
                        "signal": SignalProvider(),
                        "portfolio": PortfolioMultiSymbol(),
                    }
                except Exception as e:
                    logger.debug("Providers init failed: %s", e)
    return _providers


def get_research_dev():
    global _research_dev
    if _research_dev is None:
        with _lock:
            if _research_dev is None:
                try:
                    from research_dev import AlphaDecayAnalyzer, CrossValidationFramework, WalkForwardOptimizer
                    _research_dev = {
                        "alpha_decay": AlphaDecayAnalyzer(),
                        "cross_validation": CrossValidationFramework(),
                        "walk_forward": WalkForwardOptimizer(),
                    }
                except Exception as e:
                    logger.debug("ResearchDev init failed: %s", e)
    return _research_dev


def get_strategies_advanced():
    global _strategies_advanced
    if _strategies_advanced is None:
        with _lock:
            if _strategies_advanced is None:
                try:
                    from strategies_advanced import MarketMaker, ArbitrageEngine
                    _strategies_advanced = {
                        "market_maker": MarketMaker(),
                        "arbitrage": ArbitrageEngine(),
                    }
                except Exception as e:
                    logger.debug("StrategiesAdvanced init failed: %s", e)
    return _strategies_advanced


def get_cache_layer():
    global _cache_layer
    if _cache_layer is None:
        with _lock:
            if _cache_layer is None:
                try:
                    from cache_layer import get_cache
                    _cache_layer = get_cache()
                except Exception as e:
                    logger.debug("CacheLayer init failed: %s", e)
    return _cache_layer


def get_microstructure():
    global _microstructure
    if _microstructure is None:
        with _lock:
            if _microstructure is None:
                try:
                    from microstructure import MarketImpactModel, QueuePositionEstimator, AdverseSelectionDetector
                    _microstructure = {
                        "impact": MarketImpactModel(),
                        "queue": QueuePositionEstimator(),
                        "adverse_selection": AdverseSelectionDetector(),
                    }
                except Exception as e:
                    logger.debug("Microstructure init failed: %s", e)
    return _microstructure


_ai_advanced = None
_institutional_analytics = None
_portfolio_engineering = None
_quant_models = None


def get_ai_advanced():
    global _ai_advanced
    if _ai_advanced is None:
        with _lock:
            if _ai_advanced is None:
                try:
                    from ai_advanced import MomentumPredictor, GPTCommentary, MultiAgentRL
                    _ai_advanced = {
                        "predictor": MomentumPredictor(),
                        "commentary": GPTCommentary(),
                        "rl_agent": MultiAgentRL(),
                    }
                except Exception as e:
                    logger.debug("AIAdvanced init failed: %s", e)
    return _ai_advanced


def get_institutional_analytics():
    global _institutional_analytics
    if _institutional_analytics is None:
        with _lock:
            if _institutional_analytics is None:
                try:
                    from institutional_analytics import OrderBookHeatmap, VolumeProfile, SmartMoneyIndex, COTReport
                    _institutional_analytics = {
                        "order_book": OrderBookHeatmap(),
                        "volume_profile": VolumeProfile(),
                        "smart_money": SmartMoneyIndex(),
                        "cot_report": COTReport(),
                    }
                except Exception as e:
                    logger.debug("InstitutionalAnalytics init failed: %s", e)
    return _institutional_analytics


def get_portfolio_engineering():
    global _portfolio_engineering
    if _portfolio_engineering is None:
        with _lock:
            if _portfolio_engineering is None:
                try:
                    from portfolio_engineering import HierarchicalRiskParity, BlackLitterman, ConstrainedKelly
                    _portfolio_engineering = {
                        "hrp": HierarchicalRiskParity(),
                        "black_litterman": BlackLitterman(),
                        "kelly": ConstrainedKelly(),
                    }
                except Exception as e:
                    logger.debug("PortfolioEngineering init failed: %s", e)
    return _portfolio_engineering


def get_quant_models():
    global _quant_models
    if _quant_models is None:
        with _lock:
            if _quant_models is None:
                try:
                    from quant_models import MonteCarloSimulator, GARCHModel, KalmanFilter, HiddenMarkovModel
                    _quant_models = {
                        "monte_carlo": MonteCarloSimulator(),
                        "garch": GARCHModel(),
                        "kalman": KalmanFilter(),
                        "hmm": HiddenMarkovModel(),
                    }
                except Exception as e:
                    logger.debug("QuantModels init failed: %s", e)
    return _quant_models


_settings_db = None


def get_settings_db():
    global _settings_db
    if _settings_db is None:
        with _lock:
            if _settings_db is None:
                try:
                    from settings_db import SettingsDB
                    _settings_db = SettingsDB()
                except Exception as e:
                    logger.debug("SettingsDB init failed: %s", e)
    return _settings_db
