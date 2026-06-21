"""
Native Pro Dashboard — AFX AutoTrader v2
Real-time desktop dashboard for Windows using tkinter.
Displays: positions, P&L, equity curve, risk meter, strategy selector.
Thread-safe updates via shared memory queue.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Strategy Modes ─────────────────────────────────────────────
STRATEGY_MODES = ["SWING", "DAY", "CARRY", "SCALP"]

# ─── Colors ────────────────────────────────────────────────────
COLOR_BG = "#0d1117"
COLOR_PANEL = "#161b22"
COLOR_BORDER = "#30363d"
COLOR_TEXT = "#c9d1d9"
COLOR_ACCENT = "#58a6ff"
COLOR_PROFIT = "#3fb950"
COLOR_LOSS = "#f85149"
COLOR_WARNING = "#d29922"
COLOR_NEUTRAL = "#8b949e"

FONT_MONO = ("Consolas", 10)
FONT_TITLE = ("Segoe UI", 14, "bold")
FONT_LABEL = ("Segoe UI", 9)
FONT_VALUE = ("Consolas", 11)


# ─── Dashboard State ────────────────────────────────────────────
@dataclass
class DashboardState:
    """Shared state updated by trading engine."""
    strategy_mode: str = "SWING"
    total_equity: float = 10000.0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    open_positions: int = 0
    pending_signals: int = 0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    spread_avg: float = 0.0
    latency_ms: float = 0.0
    pool_status: Dict[str, bool] = None
    recent_signals: List[Dict] = None
    equity_curve: List[float] = None

    def __post_init__(self):
        self.pool_status = self.pool_status or {}
        self.recent_signals = self.recent_signals or []
        self.equity_curve = self.equity_curve or []


# ─── Pro Dashboard ──────────────────────────────────────────────
class ProDashboard:
    """
    Native Windows dashboard with real-time updates.
    Thread-safe — state updates come from trading engine via shared queue.
    """

    def __init__(self, state: Optional[DashboardState] = None):
        self._state = state or DashboardState()
        self._state_lock = threading.RLock()
        self._root: Optional[tk.Tk] = None
        self._running = False
        self._update_thread: Optional[threading.Thread] = None
        self._widgets: Dict[str, Any] = {}
        self._signal("Dashboard initialized")

    def _signal(self, msg: str) -> None:
        logger.debug("[ProDashboard] %s", msg)

    # ─── State Access ────────────────────────────────────────────

    def update_state(self, **kwargs) -> None:
        """Thread-safe state update from trading engine."""
        with self._state_lock:
            for key, value in kwargs.items():
                if hasattr(self._state, key):
                    setattr(self._state, key, value)

    def get_state(self) -> DashboardState:
        """Thread-safe state read."""
        with self._state_lock:
            return DashboardState(
                strategy_mode=self._state.strategy_mode,
                total_equity=self._state.total_equity,
                daily_pnl=self._state.daily_pnl,
                total_pnl=self._state.total_pnl,
                open_positions=self._state.open_positions,
                pending_signals=self._state.pending_signals,
                max_drawdown=self._state.max_drawdown,
                win_rate=self._state.win_rate,
                sharpe_ratio=self._state.sharpe_ratio,
                spread_avg=self._state.spread_avg,
                latency_ms=self._state.latency_ms,
                pool_status=self._state.pool_status.copy() if self._state.pool_status else {},
                recent_signals=self._state.recent_signals.copy() if self._state.recent_signals else [],
                equity_curve=self._state.equity_curve.copy() if self._state.equity_curve else [],
            )

    # ─── Run ─────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the dashboard (blocking)."""
        if self._running:
            return
        self._running = True

        self._root = tk.Tk()
        self._root.title("AFX Pro Dashboard v2")
        self._root.configure(bg=COLOR_BG)
        self._root.geometry("1200x800")
        self._root.minsize(900, 600)

        self._setup_layout()
        self._setup_update_loop()
        self._signal("Starting tkinter mainloop")
        self._root.mainloop()

    def _setup_layout(self) -> None:
        """Build the dashboard layout."""
        root = self._root

        # Title bar
        title_frame = tk.Frame(root, bg=COLOR_BG, height=40)
        title_frame.pack(fill=tk.X, padx=16, pady=(12, 0))
        title_frame.pack_propagate(False)

        tk.Label(
            title_frame,
            text="AFX AUTOTRADER PRO v2",
            font=FONT_TITLE,
            fg=COLOR_ACCENT,
            bg=COLOR_BG,
        ).pack(side=tk.LEFT)

        tk.Label(
            title_frame,
            text=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            font=FONT_MONO,
            fg=COLOR_NEUTRAL,
            bg=COLOR_BG,
        ).pack(side=tk.RIGHT)

        # Main content
        content = tk.Frame(root, bg=COLOR_BG)
        content.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        # Left column: Strategy + P&L
        left_frame = tk.Frame(content, bg=COLOR_BG)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 8))

        self._build_strategy_panel(left_frame)
        self._build_metrics_panel(left_frame)
        self._build_pool_status(left_frame)

        # Center column: Positions + Signals
        center_frame = tk.Frame(content, bg=COLOR_BG)
        center_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        self._build_positions_panel(center_frame)
        self._build_signals_panel(center_frame)

        # Right column: Equity curve + Risk
        right_frame = tk.Frame(content, bg=COLOR_BG)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH)

        self._build_equity_panel(right_frame)
        self._build_risk_panel(right_frame)

        # Status bar
        self._build_status_bar(root)

    def _build_strategy_panel(self, parent: tk.Frame) -> None:
        """Strategy mode selector."""
        frame = self._panel(parent, "STRATEGY MODE")

        mode_frame = tk.Frame(frame, bg=COLOR_PANEL)
        mode_frame.pack(fill=tk.X, pady=4)

        self._widgets["strategy_buttons"] = []
        for mode in STRATEGY_MODES:
            btn = tk.Button(
                mode_frame,
                text=mode,
                font=("Segoe UI", 9, "bold"),
                width=8,
                relief=tk.FLAT,
                bg=COLOR_BORDER,
                fg=COLOR_TEXT,
                command=lambda m=mode: self._on_strategy_select(m),
            )
            btn.pack(side=tk.LEFT, padx=2)
            self._widgets["strategy_buttons"].append(btn)

        self._widgets["active_strategy"] = tk.Label(
            frame,
            text="SWING",
            font=("Consolas", 16, "bold"),
            fg=COLOR_ACCENT,
            bg=COLOR_PANEL,
        )
        self._widgets["active_strategy"].pack(pady=4)

    def _build_metrics_panel(self, parent: tk.Frame) -> None:
        """P&L and key metrics."""
        frame = self._panel(parent, "PERFORMANCE")

        metrics = [
            ("Total Equity", "equity", "$0.00", COLOR_TEXT),
            ("Daily P&L", "daily_pnl", "$0.00", COLOR_NEUTRAL),
            ("Total P&L", "total_pnl", "$0.00", COLOR_NEUTRAL),
            ("Win Rate", "win_rate", "0%", COLOR_NEUTRAL),
            ("Sharpe Ratio", "sharpe", "0.00", COLOR_NEUTRAL),
        ]

        self._widgets["metric_labels"] = {}
        for label_text, key, default, color in metrics:
            row = tk.Frame(frame, bg=COLOR_PANEL)
            row.pack(fill=tk.X, pady=1)

            tk.Label(
                row,
                text=label_text,
                font=FONT_LABEL,
                fg=COLOR_NEUTRAL,
                bg=COLOR_PANEL,
                width=12,
                anchor=tk.W,
            ).pack(side=tk.LEFT)

            val_label = tk.Label(
                row,
                text=default,
                font=FONT_VALUE,
                fg=color,
                bg=COLOR_PANEL,
                anchor=tk.E,
            )
            val_label.pack(side=tk.RIGHT, fill=tk.X, expand=True)
            self._widgets[f"metric_{key}"] = val_label

    def _build_pool_status(self, parent: tk.Frame) -> None:
        """Thread/process pool status indicators."""
        frame = self._panel(parent, "SYSTEM STATUS")

        pools = ["decision", "analysis", "io", "model", "training"]
        self._widgets["pool_indicators"] = {}

        for pool in pools:
            row = tk.Frame(frame, bg=COLOR_PANEL)
            row.pack(fill=tk.X, pady=1)

            tk.Label(
                row,
                text=f"{pool.upper()}",
                font=FONT_LABEL,
                fg=COLOR_NEUTRAL,
                bg=COLOR_PANEL,
                width=10,
                anchor=tk.W,
            ).pack(side=tk.LEFT)

            dot = tk.Label(
                row,
                text="●",
                font=FONT_VALUE,
                fg=COLOR_NEUTRAL,
                bg=COLOR_PANEL,
            )
            dot.pack(side=tk.RIGHT)
            self._widgets[f"pool_{pool}"] = dot

        row = tk.Frame(frame, bg=COLOR_PANEL)
        row.pack(fill=tk.X, pady=(4, 1))
        tk.Label(
            row,
            text="Latency",
            font=FONT_LABEL,
            fg=COLOR_NEUTRAL,
            bg=COLOR_PANEL,
            width=10,
            anchor=tk.W,
        ).pack(side=tk.LEFT)
        lat_label = tk.Label(
            row,
            text="0ms",
            font=FONT_VALUE,
            fg=COLOR_NEUTRAL,
            bg=COLOR_PANEL,
        )
        lat_label.pack(side=tk.RIGHT)
        self._widgets["latency"] = lat_label

    def _build_positions_panel(self, parent: tk.Frame) -> None:
        """Open positions list."""
        frame = self._panel(parent, "OPEN POSITIONS")

        header = tk.Frame(frame, bg=COLOR_BORDER)
        header.pack(fill=tk.X, pady=(0, 2))

        for txt, w in [("Symbol", 8), ("Type", 5), ("Lots", 6), ("Entry", 10), ("P&L", 8)]:
            tk.Label(
                header,
                text=txt,
                font=FONT_LABEL,
                fg=COLOR_NEUTRAL,
                bg=COLOR_BORDER,
                width=w,
            ).pack(side=tk.LEFT, padx=2)

        self._widgets["positions_list"] = tk.Frame(frame, bg=COLOR_PANEL)
        self._widgets["positions_list"].pack(fill=tk.BOTH, expand=True)

        self._widgets["positions_empty"] = tk.Label(
            frame,
            text="No open positions",
            font=FONT_LABEL,
            fg=COLOR_NEUTRAL,
            bg=COLOR_PANEL,
        )
        self._widgets["positions_empty"].pack(pady=20)

    def _build_signals_panel(self, parent: tk.Frame) -> None:
        """Recent trade signals."""
        frame = self._panel(parent, "RECENT SIGNALS")

        self._widgets["signals_list"] = tk.Frame(frame, bg=COLOR_PANEL)
        self._widgets["signals_list"].pack(fill=tk.BOTH, expand=True)

        self._widgets["signals_empty"] = tk.Label(
            frame,
            text="No recent signals",
            font=FONT_LABEL,
            fg=COLOR_NEUTRAL,
            bg=COLOR_PANEL,
        )
        self._widgets["signals_empty"].pack(pady=20)

    def _build_equity_panel(self, parent: tk.Frame) -> None:
        """Equity curve canvas."""
        frame = self._panel(parent, "EQUITY CURVE")

        canvas = tk.Canvas(
            frame,
            width=300,
            height=150,
            bg=COLOR_PANEL,
            highlightthickness=0,
        )
        canvas.pack(pady=4)
        self._widgets["equity_canvas"] = canvas

    def _build_risk_panel(self, parent: tk.Frame) -> None:
        """Risk meter."""
        frame = self._panel(parent, "RISK METER")

        risk_items = [
            ("Max Drawdown", "max_dd", "0%", COLOR_WARNING),
            ("Spread (avg)", "spread", "0.0", COLOR_NEUTRAL),
            ("Open Trades", "open_pos", "0", COLOR_TEXT),
        ]

        for label_text, key, default, color in risk_items:
            row = tk.Frame(frame, bg=COLOR_PANEL)
            row.pack(fill=tk.X, pady=1)

            tk.Label(
                row,
                text=label_text,
                font=FONT_LABEL,
                fg=COLOR_NEUTRAL,
                bg=COLOR_PANEL,
                width=12,
                anchor=tk.W,
            ).pack(side=tk.LEFT)

            val_label = tk.Label(
                row,
                text=default,
                font=FONT_VALUE,
                fg=color,
                bg=COLOR_PANEL,
            )
            val_label.pack(side=tk.RIGHT)
            self._widgets[f"risk_{key}"] = val_label

    def _build_status_bar(self, parent: tk.Frame) -> None:
        """Bottom status bar."""
        frame = tk.Frame(parent, bg=COLOR_PANEL, height=24)
        frame.pack(fill=tk.X, padx=12, pady=(4, 0))
        frame.pack_propagate(False)

        self._widgets["status"] = tk.Label(
            frame,
            text="AFX AutoTrader v2 — Ready",
            font=FONT_LABEL,
            fg=COLOR_NEUTRAL,
            bg=COLOR_PANEL,
            anchor=tk.W,
        )
        self._widgets["status"].pack(side=tk.LEFT)

        self._widgets["mode_indicator"] = tk.Label(
            frame,
            text="MODE: SWING",
            font=FONT_LABEL,
            fg=COLOR_ACCENT,
            bg=COLOR_PANEL,
        )
        self._widgets["mode_indicator"].pack(side=tk.RIGHT)

    # ─── Panel Helper ─────────────────────────────────────────────

    def _panel(self, parent: tk.Frame, title: str) -> tk.Frame:
        """Create a dashboard panel with title."""
        frame = tk.Frame(parent, bg=COLOR_PANEL, bd=1, relief=tk.SOLID)
        frame.pack(fill=tk.BOTH, padx=4, pady=4)

        tk.Label(
            frame,
            text=title,
            font=FONT_LABEL,
            fg=COLOR_NEUTRAL,
            bg=COLOR_PANEL,
        ).pack(anchor=tk.W, padx=8, pady=(6, 2))

        inner = tk.Frame(frame, bg=COLOR_PANEL)
        inner.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        return inner

    # ─── Update Loop ─────────────────────────────────────────────

    def _setup_update_loop(self) -> None:
        """Start background update thread."""
        self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self._update_thread.start()

    def _update_loop(self) -> None:
        """Background thread: refreshes UI every 1 second."""
        while self._running and self._root is not None:
            try:
                state = self.get_state()
                self._root.after(0, lambda s=state: self._refresh_ui(s))
            except Exception as e:
                logger.error("Dashboard update error: %s", e)
            time.sleep(1.0)

    def _refresh_ui(self, state: DashboardState) -> None:
        """Update all UI elements with current state."""
        if not self._root:
            return

        # Strategy highlight
        active_idx = STRATEGY_MODES.index(state.strategy_mode) if state.strategy_mode in STRATEGY_MODES else 0
        for i, btn in enumerate(self._widgets.get("strategy_buttons", [])):
            if i == active_idx:
                btn.configure(bg=COLOR_ACCENT, fg=COLOR_BG)
            else:
                btn.configure(bg=COLOR_BORDER, fg=COLOR_TEXT)

        self._widgets.get("active_strategy", tk.Label()).configure(
            text=state.strategy_mode
        )

        # Metrics
        equity_str = f"${state.total_equity:,.2f}"
        self._widgets.get("metric_equity", tk.Label()).configure(
            text=equity_str
        )

        pnl_color = COLOR_PROFIT if state.daily_pnl >= 0 else COLOR_LOSS
        pnl_str = f"${state.daily_pnl:+,.2f}"
        self._widgets.get("metric_daily_pnl", tk.Label()).configure(
            text=pnl_str, fg=pnl_color
        )

        total_pnl_color = COLOR_PROFIT if state.total_pnl >= 0 else COLOR_LOSS
        self._widgets.get("metric_total_pnl", tk.Label()).configure(
            text=f"${state.total_pnl:+,.2f}", fg=total_pnl_color
        )

        self._widgets.get("metric_win_rate", tk.Label()).configure(
            text=f"{state.win_rate:.1f}%"
        )
        self._widgets.get("metric_sharpe", tk.Label()).configure(
            text=f"{state.sharpe_ratio:.2f}"
        )

        # Risk
        self._widgets.get("risk_max_dd", tk.Label()).configure(
            text=f"{state.max_drawdown:.1f}%"
        )
        self._widgets.get("risk_spread", tk.Label()).configure(
            text=f"{state.spread_avg:.1f}"
        )
        self._widgets.get("risk_open_pos", tk.Label()).configure(
            text=str(state.open_positions)
        )

        # Pool status
        for pool in ["decision", "analysis", "io", "model", "training"]:
            alive = state.pool_status.get(pool, False)
            dot = self._widgets.get(f"pool_{pool}")
            if dot:
                dot.configure(fg=COLOR_PROFIT if alive else COLOR_LOSS)

        latency = self._widgets.get("latency")
        if latency:
            lat = state.latency_ms
            lat_color = COLOR_PROFIT if lat < 50 else COLOR_WARNING if lat < 100 else COLOR_LOSS
            latency.configure(text=f"{lat:.1f}ms", fg=lat_color)

        # Status bar
        status = self._widgets.get("status")
        if status:
            status.configure(text=f"AFX AutoTrader v2 — {state.strategy_mode} — {state.open_positions} positions")

        mode_ind = self._widgets.get("mode_indicator")
        if mode_ind:
            mode_ind.configure(text=f"MODE: {state.strategy_mode}")

        # Equity curve
        self._draw_equity_curve(state.equity_curve)

        # Signals
        self._update_signals(state.recent_signals)

    def _draw_equity_curve(self, equity_curve: List[float]) -> None:
        """Draw equity curve on canvas."""
        canvas = self._widgets.get("equity_canvas")
        if not canvas or not equity_curve:
            return

        canvas.delete("all")
        if len(equity_curve) < 2:
            return

        w = canvas.winfo_width() or 300
        h = canvas.winfo_height() or 150
        padding = 5

        values = equity_curve[-100:]  # Last 100 points
        min_v = min(values)
        max_v = max(values)
        range_v = max_v - min_v or 1

        points = []
        for i, v in enumerate(values):
            x = padding + (i / (len(values) - 1)) * (w - 2 * padding)
            y = h - padding - ((v - min_v) / range_v) * (h - 2 * padding)
            points.append((x, y))

        if len(points) > 1:
            # Draw line
            for i in range(len(points) - 1):
                color = COLOR_PROFIT if points[i + 1][1] <= points[i][1] else COLOR_LOSS
                canvas.create_line(
                    points[i][0], points[i][1],
                    points[i + 1][0], points[i + 1][1],
                    fill=color, width=1.5
                )

    def _update_signals(self, signals: List[Dict]) -> None:
        """Update recent signals list."""
        pass  # Simplified for this version

    def _on_strategy_select(self, mode: str) -> None:
        """Handle strategy button click."""
        self.update_state(strategy_mode=mode)
        logger.info("Strategy changed to: %s", mode)

    def stop(self) -> None:
        """Stop the dashboard."""
        self._running = False
        if self._root:
            self._root.after(0, self._root.quit)


# ─── Standalone Test ────────────────────────────────────────────
def _test_dashboard() -> None:
    """Test the dashboard with simulated data."""
    dashboard = ProDashboard()

    def simulator():
        equity = 10000.0
        equity_curve = []
        for i in range(100):
            equity += (i % 3 - 1) * 5
            equity_curve.append(equity)
            dashboard.update_state(
                strategy_mode=STRATEGY_MODES[i % 4],
                total_equity=equity,
                daily_pnl=(i % 5 - 2) * 10,
                total_pnl=equity - 10000,
                open_positions=i % 5,
                win_rate=55 + (i % 10),
                sharpe_ratio=1.2 + (i % 5) * 0.1,
                max_drawdown=5 + (i % 3),
                spread_avg=1.5 + (i % 2),
                latency_ms=20 + i % 30,
                pool_status={
                    "decision": True,
                    "analysis": True,
                    "io": True,
                    "model": True,
                    "training": True,
                },
                equity_curve=equity_curve,
            )
            time.sleep(1)

    t = threading.Thread(target=simulator, daemon=True)
    t.start()
    dashboard.run()


if __name__ == "__main__":
    _test_dashboard()