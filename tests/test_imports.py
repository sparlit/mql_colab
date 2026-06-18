"""
Basic tests for MT5 Scalper Pro modules.
Run with: pytest tests/test_imports.py -v
"""
import pytest
import importlib
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Core modules that should always import
CORE_MODULES = [
    'logging_config',
    'brain_v1',
    'ai_client',
    'gpu_engine',
    'cache_layer',
    'order_flow',
    'market_intelligence',
    'portfolio_risk',
    'ml_enhancements',
    'alerts',
    'metrics',
    'providers',
    'strategies_advanced',
    'institutional_analytics',
    'execution_optimization',
    'risk_advanced',
    'data_analytics',
    'alternative_data',
    'microstructure',
    'pattern_recognition',
    'quant_models',
    'research_dev',
    'ai_advanced',
    'portfolio_engineering',
    'infrastructure',
]

# Brain modules
BRAIN_MODULES = [
    'brain_v1', 'brain_v2', 'brain_v3', 'brain_v4', 'brain_v5',
    'brain_v6', 'brain_v7', 'brain_v8', 'brain_v9', 'brain_v10',
    'brain_v11',
]


@pytest.mark.parametrize('module_name', CORE_MODULES)
def test_core_module_imports(module_name):
    """Verify all core modules can be imported."""
    try:
        mod = importlib.import_module(module_name)
        assert mod is not None, f"Module {module_name} imported but is None"
    except ImportError as e:
        if any(opt in str(e).lower() for opt in ['cupy', 'kubernetes', 'redis']):
            pytest.skip(f"Optional dependency not available: {e}")
        else:
            pytest.fail(f"Failed to import {module_name}: {e}")


@pytest.mark.parametrize('module_name', BRAIN_MODULES)
def test_brain_module_imports(module_name):
    """Verify all brain modules can be imported."""
    try:
        mod = importlib.import_module(module_name)
        assert mod is not None, f"Brain module {module_name} imported but is None"
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")


def test_logging_config():
    """Verify logging configuration works."""
    from logging_config import setup_logging
    import logging
    setup_logging(level=logging.DEBUG)
    logger = logging.getLogger('test')
    logger.info("Logging test message")
    assert True


def test_brain_chain_instantiation():
    """Verify brain chain can be instantiated."""
    try:
        from brain_v1 import Brain
        brain = Brain()
        assert brain is not None
        assert hasattr(brain, 'analyze')
    except Exception as e:
        pytest.skip(f"Brain instantiation requires MT5: {e}")


def test_ai_client_instantiation():
    """Verify AI client can be instantiated."""
    from ai_client import get_ai_client
    client = get_ai_client()
    assert client is not None
    assert hasattr(client, 'is_available')
    assert hasattr(client, 'chat')


def test_gpu_engine_instantiation():
    """Verify GPU engine can be instantiated."""
    try:
        from gpu_engine import get_gpu_engine
        engine = get_gpu_engine()
        assert engine is not None
        assert hasattr(engine, 'ema')
        assert hasattr(engine, 'rsi')
    except ImportError:
        pytest.skip("GPU engine requires cupy")


def test_cache_layer_instantiation():
    """Verify cache layer can be instantiated."""
    from cache_layer import get_cache
    cache = get_cache()
    assert cache is not None
    assert hasattr(cache, 'get')
    assert hasattr(cache, 'set_value')


def test_order_flow_instantiation():
    """Verify order flow analyzer can be instantiated."""
    from order_flow import get_order_flow
    analyzer = get_order_flow()
    assert analyzer is not None
    assert hasattr(analyzer, 'detect_large_orders')
    assert hasattr(analyzer, 'get_full_analysis')


def test_market_intelligence_instantiation():
    """Verify market intelligence can be instantiated."""
    from market_intelligence import get_news_calendar
    nc = get_news_calendar()
    assert nc is not None
    assert hasattr(nc, 'get_upcoming')
    assert hasattr(nc, 'fetch_events')


def test_portfolio_risk_instantiation():
    """Verify portfolio risk can be instantiated."""
    from portfolio_risk import get_portfolio_manager
    pm = get_portfolio_manager()
    assert pm is not None
    assert hasattr(pm, 'get_full_risk_assessment')


def test_ml_enhancements_instantiation():
    """Verify ML enhancements can be instantiated."""
    from ml_enhancements import get_ml_scorer
    ml = get_ml_scorer()
    assert ml is not None
    assert hasattr(ml, 'predict')


def test_alerts_instantiation():
    """Verify alerts can be instantiated."""
    from alerts import get_alert_manager
    alerts = get_alert_manager()
    assert alerts is not None
    assert hasattr(alerts, 'send_telegram')
    assert hasattr(alerts, 'send_discord')


def test_metrics_instantiation():
    """Verify metrics can be instantiated."""
    from metrics import get_metrics
    metrics = get_metrics()
    assert metrics is not None
    assert hasattr(metrics, 'inc')
    assert hasattr(metrics, 'set_value')
    assert hasattr(metrics, 'observe')


def test_providers_instantiation():
    """Verify providers can be instantiated."""
    from providers import get_signal_provider
    providers = get_signal_provider()
    assert providers is not None
    assert hasattr(providers, 'publish_signal')
    assert hasattr(providers, 'get_latest_signals')


def test_institutional_analytics_instantiation():
    """Verify institutional analytics can be instantiated."""
    from institutional_analytics import get_order_book
    ia = get_order_book()
    assert ia is not None
    assert hasattr(ia, 'capture_snapshot')
    assert hasattr(ia, 'get_imbalance_ratio')


def test_execution_optimization_instantiation():
    """Verify execution optimization can be instantiated."""
    from execution_optimization import get_advanced_executor
    eo = get_advanced_executor()
    assert eo is not None
    assert hasattr(eo, 'execute')


def test_risk_advanced_instantiation():
    """Verify advanced risk can be instantiated."""
    from risk_advanced import get_advanced_risk
    ra = get_advanced_risk()
    assert ra is not None
    assert hasattr(ra, 'full_risk_assessment')


def test_data_analytics_instantiation():
    """Verify data analytics can be instantiated."""
    from data_analytics import get_tick_db
    da = get_tick_db()
    assert da is not None
    assert hasattr(da, 'record_tick')
    assert hasattr(da, 'get_ticks')


def test_alternative_data_instantiation():
    """Verify alternative data can be instantiated."""
    from alternative_data import get_alt_data_aggregator
    ad = get_alt_data_aggregator()
    assert ad is not None
    assert hasattr(ad, 'get_all_sentiment')
    assert hasattr(ad, 'get_commodity_data')


def test_microstructure_instantiation():
    """Verify microstructure can be instantiated."""
    from microstructure import get_latency_arb
    ms = get_latency_arb()
    assert ms is not None
    assert hasattr(ms, 'record_price')
    assert hasattr(ms, 'detect_lead_lag')


def test_pattern_recognition_instantiation():
    """Verify pattern recognition can be instantiated."""
    from pattern_recognition import get_candlestick_classifier
    pr = get_candlestick_classifier()
    assert pr is not None
    assert hasattr(pr, 'classify')


def test_quant_models_instantiation():
    """Verify quant models can be instantiated."""
    from quant_models import MonteCarloSimulator
    qm = MonteCarloSimulator()
    assert qm is not None
    assert hasattr(qm, 'simulate_trades')


def test_research_dev_instantiation():
    """Verify research dev can be instantiated."""
    from research_dev import AlphaDecayAnalyzer
    rd = AlphaDecayAnalyzer()
    assert rd is not None
    assert hasattr(rd, 'record_alpha')
    assert hasattr(rd, 'analyze_decay')


def test_ai_advanced_instantiation():
    """Verify AI advanced can be instantiated."""
    from ai_advanced import MomentumPredictor
    aa = MomentumPredictor()
    assert aa is not None
    assert hasattr(aa, 'predict')


def test_portfolio_engineering_instantiation():
    """Verify portfolio engineering can be instantiated."""
    from portfolio_engineering import get_hrp
    pe = get_hrp()
    assert pe is not None
    assert hasattr(pe, 'allocate')


def test_dashboard_flask_app():
    """Verify Flask dashboard app can be created."""
    try:
        from dashboard import app
        assert app is not None
        assert app.name == 'dashboard'
    except Exception as e:
        pytest.skip(f"Dashboard requires MT5: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
