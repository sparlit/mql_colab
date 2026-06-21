"""
Web Dashboard — AFX AutoTrader v2
Flask + Flask-SocketIO web dashboard with real-time WebSocket updates.
Displays all 4 strategy modes, P&L, positions, equity curve, and performance metrics.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from parallel_executor import get_executor

logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "afxtoken123")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ─── Global State ───────────────────────────────────────────────
_state = {
    "strategy_mode": "SWING",
    "equity": 10000.0,
    "daily_pnl": 0.0,
    "total_pnl": 0.0,
    "open_positions": [],
    "recent_signals": [],
    "equity_curve": [],
    "performance": {
        "win_rate": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
        "total_trades": 0,
    },
    "pool_status": {
        "decision": True,
        "analysis": True,
        "io": True,
        "model": True,
        "training": True,
    },
}
_state_lock = threading.RLock()

# ─── Routes ─────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html", mode=_state["strategy_mode"])

@app.route("/api/state")
def api_state():
    with _state_lock:
        return jsonify(_state)

@app.route("/api/strategy/mode", methods=["POST"])
def set_strategy_mode():
    mode = request.json.get("mode", "SWING")
    with _state_lock:
        _state["strategy_mode"] = mode
    _broadcast_state()
    return jsonify({"success": True, "mode": mode})

@app.route("/api/strategy/modes")
def list_modes():
    return jsonify([
        {"mode": "SWING", "magic": 100001, "active": _state["strategy_mode"] == "SWING"},
        {"mode": "DAY", "magic": 200002, "active": _state["strategy_mode"] == "DAY"},
        {"mode": "CARRY", "magic": 300003, "active": _state["strategy_mode"] == "CARRY"},
        {"mode": "SCALP", "magic": 400004, "active": _state["strategy_mode"] == "SCALP"},
    ])

@app.route("/api/positions")
def api_positions():
    with _state_lock:
        return jsonify(_state["open_positions"])

@app.route("/api/signals")
def api_signals():
    with _state_lock:
        signals = _state.get("recent_signals", [])
        return jsonify(signals[-50:])

@app.route("/api/equity")
def api_equity():
    with _state_lock:
        return jsonify({
            "equity": _state["equity"],
            "curve": _state.get("equity_curve", []),
            "daily_pnl": _state["daily_pnl"],
            "total_pnl": _state["total_pnl"],
        })

@app.route("/api/performance")
def api_performance():
    with _state_lock:
        return jsonify(_state["performance"])

@app.route("/api/pool_status")
def api_pool_status():
    with _state_lock:
        return jsonify(_state["pool_status"])

@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

@app.route("/metrics")
def api_metrics():
    """Prometheus metrics endpoint."""
    from metrics import metrics_text
    return metrics_text(), 200, {"Content-Type": "text/plain; charset=utf-8"}


# ─── WebSocket Events ───────────────────────────────────────────

@socketio.on("connect")
def on_connect():
    logger.info("Client connected: %s", request.sid)
    with _state_lock:
        emit("state_update", _state)


@socketio.on("disconnect")
def on_disconnect():
    logger.info("Client disconnected: %s", request.sid)


@socketio.on("strategy_change")
def on_strategy_change(data):
    mode = data.get("mode", "SWING")
    with _state_lock:
        _state["strategy_mode"] = mode
    _broadcast_state()


@socketio.on("request_state")
def on_request_state():
    with _state_lock:
        emit("state_update", _state.copy())


# ─── State Broadcasting ────────────────────────────────────────

def _broadcast_state() -> None:
    """Emit full state to all connected WebSocket clients."""
    with _state_lock:
        state_copy = json.loads(json.dumps(_state))
    socketio.emit("state_update", state_copy, broadcast=True)


def _broadcast_delta(key: str, value: Any) -> None:
    """Emit a delta update for a specific key."""
    socketio.emit("state_delta", {"key": key, "value": value}, broadcast=True)


# ─── External State Update API ──────────────────────────────────
def update_state(**kwargs) -> None:
    """Thread-safe state update from trading engine."""
    with _state_lock:
        for key, value in kwargs.items():
            _state[key] = value
    _broadcast_state()


def update_positions(positions: list) -> None:
    with _state_lock:
        _state["open_positions"] = positions
    _broadcast_delta("open_positions", positions)


def update_equity(equity: float, daily_pnl: float = 0.0, total_pnl: float = 0.0) -> None:
    with _state_lock:
        _state["equity"] = equity
        _state["daily_pnl"] = daily_pnl
        _state["total_pnl"] = total_pnl
        curve = _state.get("equity_curve", [])
        curve.append(equity)
        _state["equity_curve"] = curve[-500:]  # Keep last 500 points
    _broadcast_delta("equity", equity)
    _broadcast_delta("equity_curve", _state["equity_curve"])


def update_signal(signal: dict) -> None:
    with _state_lock:
        signals = _state.get("recent_signals", [])
        signals.append({**signal, "timestamp": datetime.now().isoformat()})
        _state["recent_signals"] = signals[-100:]
    _broadcast_delta("recent_signals", _state["recent_signals"])


def update_performance(perf: dict) -> None:
    with _state_lock:
        _state["performance"] = {**_state["performance"], **perf}
    _broadcast_delta("performance", _state["performance"])


def update_pool_status(pool_status: dict) -> None:
    with _state_lock:
        _state["pool_status"] = pool_status
    _broadcast_delta("pool_status", pool_status)


# ─── Background Update Loop ─────────────────────────────────────
_update_thread: Optional[threading.Thread] = None


def _start_background_updates(interval: float = 1.0) -> None:
    """Start background thread that periodically fetches state from engine."""

    def _update_loop():
        while True:
            try:
                # Import here to avoid circular import
                from decision_engine import get_decision_engine
                engine = get_decision_engine()
                # Update pool status
                pool_status = get_executor().get_pool_status()
                update_pool_status(pool_status)
            except Exception as e:
                logger.debug("Background update skipped: %s", e)
            time.sleep(interval)

    global _update_thread
    if _update_thread is None or not _update_thread.is_alive():
        _update_thread = threading.Thread(target=_update_loop, daemon=True)
        _update_thread.start()


# ─── Run ────────────────────────────────────────────────────────

def run_dashboard(
    host: str = "0.0.0.0",
    port: int = 5050,
    debug: bool = False,
    start_updates: bool = True,
) -> None:
    """Start the web dashboard."""
    if start_updates:
        _start_background_updates()
    logger.info("Starting web dashboard on %s:%d", host, port)
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    # Create minimal template dir for standalone testing
    import os
    os.makedirs("templates", exist_ok=True)
    os.makedirs("static", exist_ok=True)
    run_dashboard(debug=True)