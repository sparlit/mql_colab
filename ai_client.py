import requests
import json
import time as _time
import threading
import logging
import os

logger = logging.getLogger(__name__)

# ==========================================
# AI CLIENT — OpenAI-Compatible Local LLM
# ==========================================
AI_BASE_URL = os.environ.get("AI_BASE_URL", "http://127.0.0.1:3001/v1")
AI_CHAT_ENDPOINT = f"{AI_BASE_URL}/chat/completions"
AI_EMBED_ENDPOINT = f"{AI_BASE_URL}/embeddings"
AI_TIMEOUT = 30
AI_MAX_RETRIES = 2
AI_CACHE_TTL = 60
# ==========================================


class AIClient:
    def __init__(self):
        self._cache = {}
        self._cache_time = {}
        self._lock = threading.Lock()
        self._available = None
        self._last_check = 0
        self._request_count = 0
        self._error_count = 0
        self._avg_latency = 0

    def is_available(self):
        now = _time.time()
        if now - self._last_check < 10:
            return self._available
        try:
            resp = requests.get(f"{AI_BASE_URL}/models", timeout=5)
            self._available = resp.status_code == 200
        except (requests.RequestException, Exception) as e:
            logger.debug("AI availability check failed: %s", e)
            self._available = False
        self._last_check = now
        return self._available

    def chat(self, messages, temperature=0.3, max_tokens=500, model=None):
        cache_key = json.dumps(messages, sort_keys=True)[:200]
        now = _time.time()
        with self._lock:
            if cache_key in self._cache and (now - self._cache_time.get(cache_key, 0)) < AI_CACHE_TTL:
                return self._cache[cache_key]

        if not self.is_available():
            return None

        payload = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if model:
            payload["model"] = model

        for attempt in range(AI_MAX_RETRIES):
            try:
                start = _time.time()
                resp = requests.post(AI_CHAT_ENDPOINT, json=payload, timeout=AI_TIMEOUT)
                latency = (_time.time() - start) * 1000
                with self._lock:
                    self._request_count += 1
                    self._avg_latency = (self._avg_latency * (self._request_count - 1) + latency) / self._request_count

                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    with self._lock:
                        self._cache[cache_key] = content
                        self._cache_time[cache_key] = _time.time()
                    return content
                else:
                    with self._lock:
                        self._error_count += 1
            except Exception as e:
                with self._lock:
                    self._error_count += 1
                if attempt < AI_MAX_RETRIES - 1:
                    _time.sleep(1)
        return None

    def chat_json(self, messages, temperature=0.2, max_tokens=800):
        result = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        if result is None:
            return None
        try:
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[1]
                if result.endswith("```"):
                    result = result[:-3]
            return json.loads(result)
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug("AI response JSON parse failed: %s", e)
            return {"raw": result}

    def analyze_signal(self, symbol, signals, regime, session, context=""):
        messages = [
            {"role": "system", "content": "You are a professional forex trading analyst. Analyze the given trading signals and provide a concise JSON response with direction, confidence, and reasoning. Always respond in valid JSON."},
            {"role": "user", "content": f"""Analyze trading signals for {symbol}:

Signals: {json.dumps(signals)}
Market Regime: {regime}
Session: {session}
Context: {context}

Respond in JSON:
{{"direction": "BUY" or "SELL" or "HOLD", "confidence": 0.0-1.0, "reasoning": "brief explanation", "risk_level": "low/medium/high"}}"""}
        ]
        return self.chat_json(messages, temperature=0.2, max_tokens=300)

    def analyze_regime(self, market_data, correlations):
        messages = [
            {"role": "system", "content": "You are a market regime analyst. Classify the current market condition. Respond in valid JSON."},
            {"role": "user", "content": f"""Analyze market regime:

Price Data: {json.dumps(market_data)[:2000]}
Correlations: {json.dumps(correlations)[:1000]}

Respond in JSON:
{{"regime": "trending/ranging/volatile/transitioning", "confidence": 0.0-1.0, "description": "brief", "bias": "bullish/bearish/neutral"}}"""}
        ]
        return self.chat_json(messages, temperature=0.3, max_tokens=300)

    def analyze_risk(self, positions, account_info, market_conditions):
        messages = [
            {"role": "system", "content": "You are a risk management expert. Assess trading risk and provide recommendations. Respond in valid JSON."},
            {"role": "user", "content": f"""Assess risk:

Open Positions: {json.dumps(positions)[:1500]}
Account: {json.dumps(account_info)[:500]}
Market: {json.dumps(market_conditions)[:1000]}

Respond in JSON:
{{"risk_score": 0.0-1.0, "max_new_trades": 0-5, "reduce_exposure": true/false, "warnings": ["list"], "recommendations": ["list"]}}"""}
        ]
        return self.chat_json(messages, temperature=0.2, max_tokens=400)

    def analyze_pattern(self, price_data, indicators):
        messages = [
            {"role": "system", "content": "You are a technical pattern recognition expert. Identify chart patterns and predict likely outcomes. Respond in valid JSON."},
            {"role": "user", "content": f"""Identify patterns:

Price: {json.dumps(price_data)[:1500]}
Indicators: {json.dumps(indicators)[:1000]}

Respond in JSON:
{{"patterns": ["list of patterns found"], "prediction": "bullish/bearish/neutral", "confidence": 0.0-1.0, "target": "price target if applicable", "invalidation": "level that invalidates"}}"""}
        ]
        return self.chat_json(messages, temperature=0.3, max_tokens=400)

    def analyze_multi_tf(self, mtf_data, symbol):
        messages = [
            {"role": "system", "content": "You are a multi-timeframe analysis expert. Synthesize signals across timeframes. Respond in valid JSON."},
            {"role": "user", "content": f"""Multi-TF analysis for {symbol}:

{json.dumps(mtf_data)[:3000]}

Respond in JSON:
{{"overall_trend": "bullish/bearish/neutral", "confidence": 0.0-1.0, "best_entry_tf": "timeframe", "confluence": "what aligns", "conflicts": "what disagrees", "recommendation": "BUY/SELL/HOLD"}}"""}
        ]
        return self.chat_json(messages, temperature=0.2, max_tokens=400)

    def generate_trade_plan(self, symbol, direction, entry, sl, tp, confidence, context):
        messages = [
            {"role": "system", "content": "You are a professional trade planner. Create a detailed trade plan. Respond in valid JSON."},
            {"role": "user", "content": f"""Create trade plan:

Symbol: {symbol} | Direction: {direction}
Entry: {entry} | SL: {sl} | TP: {tp}
Confidence: {confidence}
Context: {json.dumps(context)[:1000]}

Respond in JSON:
{{"should_trade": true/false, "adjusted_sl": "value", "adjusted_tp": "value", "lot_adjustment": "increase/same/decrease", "reasoning": "brief", "alerts": ["any concerns"]}}"""}
        ]
        return self.chat_json(messages, temperature=0.2, max_tokens=400)

    def explain_decision(self, decision, all_brain_outputs):
        messages = [
            {"role": "system", "content": "You are a trading decision explainer. Provide clear, concise explanations. Respond in valid JSON."},
            {"role": "user", "content": f"""Explain this trading decision:

Decision: {json.dumps(decision)[:1000]}
Brain Outputs: {json.dumps(all_brain_outputs)[:2000]}

Respond in JSON:
{{"summary": "1-2 sentence summary", "key_factors": ["top 3 factors"], "risk_assessment": "brief", "confidence_explanation": "why this confidence level"}}"""}
        ]
        return self.chat_json(messages, temperature=0.3, max_tokens=300)

    def get_market_sentiment(self, news_context=""):
        messages = [
            {"role": "system", "content": "You are a market sentiment analyst. Assess current sentiment. Respond in valid JSON."},
            {"role": "user", "content": f"""Assess market sentiment:

Context: {news_context[:2000]}

Respond in JSON:
{{"sentiment": "bullish/bearish/neutral", "confidence": 0.0-1.0, "key_drivers": ["list"], "risk_events": ["list"]}}"""}
        ]
        return self.chat_json(messages, temperature=0.3, max_tokens=300)

    def optimize_parameters(self, strategy_params, performance_data):
        messages = [
            {"role": "system", "content": "You are a trading parameter optimizer. Suggest parameter improvements. Respond in valid JSON."},
            {"role": "user", "content": f"""Optimize strategy parameters:

Current: {json.dumps(strategy_params)[:1000]}
Performance: {json.dumps(performance_data)[:1500]}

Respond in JSON:
{{"suggested_changes": {{"param": "new_value"}}, "reasoning": "brief", "expected_improvement": "description"}}"""}
        ]
        return self.chat_json(messages, temperature=0.4, max_tokens=400)

    def get_stats(self):
        return {
            "available": self._available,
            "requests": self._request_count,
            "errors": self._error_count,
            "avg_latency_ms": round(self._avg_latency, 1),
            "cache_size": len(self._cache),
        }


_ai_client = None
_ai_lock = threading.Lock()


def get_ai_client():
    global _ai_client
    if _ai_client is None:
        with _ai_lock:
            if _ai_client is None:
                _ai_client = AIClient()
    return _ai_client
