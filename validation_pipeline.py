"""3-Phase Validation Pipeline: Backtest → Paper → Live.

Non-negotiable gate criteria at each phase. No skipping.
"""
import json
import os
import logging
from datetime import datetime
from config import DATA_DIR

logger = logging.getLogger(__name__)

# Phase gate criteria
PHASE_CRITERIA = {
    "backtest": {
        "min_sharpe": 0.8,
        "max_drawdown_pct": 15.0,
        "min_profit_factor": 1.3,
        "min_win_rate": 35.0,
        "max_win_rate": 65.0,  # Outside this = overfitting
        "min_recovery_factor": 2.0,
        "min_trades": 100,
        "min_duration_weeks": 4,
    },
    "paper": {
        "max_pnl_divergence_pct": 10.0,  # Paper vs backtest P&L divergence
        "min_duration_weeks": 8,
        "min_trades": 20,
        "max_drawdown_pct": 10.0,
    },
    "live": {
        "min_sharpe": 0.3,
        "max_drawdown_pct": 5.0,
        "min_duration_weeks": 12,
        "min_trades": 30,
        "max_daily_loss_pct": 3.0,
    },
}


class ValidationPipeline:
    """Manages the 3-phase validation lifecycle."""

    def __init__(self):
        self.state = {
            "current_phase": "backtest",  # backtest | paper | live | halted
            "backtest": {"passed": False, "results": None, "date": None},
            "paper": {"passed": False, "results": None, "date": None},
            "live": {"passed": False, "results": None, "date": None},
            "halt_reason": None,
        }
        self._load_state()

    def _load_state(self):
        path = os.path.join(DATA_DIR, "validation_state.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    self.state = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

    def _save_state(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "validation_state.json")
        with open(path, "w") as f:
            json.dump(self.state, f, indent=2, default=str)

    def evaluate_backtest(self, results):
        """Evaluate backtest results against gate criteria.

        Args:
            results: dict from EventDrivenBacktestEngine.run()

        Returns:
            dict with 'passed' (bool), 'criteria_met' (dict), 'failures' (list)
        """
        criteria = PHASE_CRITERIA["backtest"]
        failures = []
        met = {}

        checks = {
            "sharpe": ("sharpe_ratio", "min_sharpe", lambda v, t: v >= t),
            "drawdown": ("max_drawdown", "max_drawdown_pct", lambda v, t: v <= t),
            "profit_factor": ("profit_factor", "min_profit_factor", lambda v, t: v >= t),
            "win_rate_low": ("win_rate", "min_win_rate", lambda v, t: v >= t),
            "win_rate_high": ("win_rate", "max_win_rate", lambda v, t: v <= t),
            "trades": ("total_trades", "min_trades", lambda v, t: v >= t),
        }

        for name, (result_key, criteria_key, check) in checks.items():
            value = results.get(result_key, 0)
            threshold = criteria[criteria_key]
            passed = check(value, threshold)
            met[name] = {"value": value, "threshold": threshold, "passed": passed}
            if not passed:
                failures.append(f"{name}: {value} vs {threshold}")

        all_passed = len(failures) == 0
        self.state["backtest"] = {
            "passed": all_passed,
            "results": results,
            "date": datetime.now().isoformat(),
            "criteria_met": met,
        }
        if all_passed:
            self.state["current_phase"] = "paper"
        self._save_state()

        return {
            "passed": all_passed,
            "criteria_met": met,
            "failures": failures,
            "next_phase": "paper" if all_passed else None,
        }

    def evaluate_paper(self, results, backtest_results):
        """Evaluate paper trading results.

        Args:
            results: dict from paper trading session
            backtest_results: dict from original backtest (for divergence check)

        Returns:
            dict with 'passed', 'criteria_met', 'failures'
        """
        criteria = PHASE_CRITERIA["paper"]
        failures = []
        met = {}

        # Check P&L divergence
        if backtest_results:
            bt_return = backtest_results.get("total_return", 0)
            paper_return = results.get("total_return", 0)
            divergence = abs(bt_return - paper_return)
            met["pnl_divergence"] = {
                "value": divergence,
                "threshold": criteria["max_pnl_divergence_pct"],
                "passed": divergence <= criteria["max_pnl_divergence_pct"],
            }
            if divergence > criteria["max_pnl_divergence_pct"]:
                failures.append(f"P&L divergence: {divergence:.1f}% > {criteria['max_pnl_divergence_pct']}%")

        # Check drawdown
        dd = results.get("max_drawdown", 0)
        met["drawdown"] = {
            "value": dd,
            "threshold": criteria["max_drawdown_pct"],
            "passed": dd <= criteria["max_drawdown_pct"],
        }
        if dd > criteria["max_drawdown_pct"]:
            failures.append(f"Drawdown: {dd:.1f}% > {criteria['max_drawdown_pct']}%")

        all_passed = len(failures) == 0
        self.state["paper"] = {
            "passed": all_passed,
            "results": results,
            "date": datetime.now().isoformat(),
            "criteria_met": met,
        }
        if all_passed:
            self.state["current_phase"] = "live"
        self._save_state()

        return {
            "passed": all_passed,
            "criteria_met": met,
            "failures": failures,
            "next_phase": "live" if all_passed else None,
        }

    def evaluate_live(self, results):
        """Evaluate live micro-lot trading results.

        Args:
            results: dict from live trading period

        Returns:
            dict with 'passed', 'criteria_met', 'failures'
        """
        criteria = PHASE_CRITERIA["live"]
        failures = []
        met = {}

        checks = {
            "sharpe": ("sharpe_ratio", "min_sharpe", lambda v, t: v >= t),
            "drawdown": ("max_drawdown", "max_drawdown_pct", lambda v, t: v <= t),
            "trades": ("total_trades", "min_trades", lambda v, t: v >= t),
        }

        for name, (result_key, criteria_key, check) in checks.items():
            value = results.get(result_key, 0)
            threshold = criteria[criteria_key]
            passed = check(value, threshold)
            met[name] = {"value": value, "threshold": threshold, "passed": passed}
            if not passed:
                failures.append(f"{name}: {value} vs {threshold}")

        all_passed = len(failures) == 0
        self.state["live"] = {
            "passed": all_passed,
            "results": results,
            "date": datetime.now().isoformat(),
            "criteria_met": met,
        }
        if all_passed:
            self.state["current_phase"] = "production"
        self._save_state()

        return {
            "passed": all_passed,
            "criteria_met": met,
            "failures": failures,
            "next_phase": "production" if all_passed else None,
        }

    def can_trade(self):
        """Check if the system is allowed to trade live.

        Returns:
            bool: True only if current_phase is 'live' or 'production'
        """
        return self.state["current_phase"] in ("live", "production")

    def get_status(self):
        """Get current pipeline status."""
        return {
            "phase": self.state["current_phase"],
            "backtest_passed": self.state["backtest"]["passed"],
            "paper_passed": self.state["paper"]["passed"],
            "live_passed": self.state["live"]["passed"],
            "halt_reason": self.state.get("halt_reason"),
        }

    def halt(self, reason):
        """Halt all trading."""
        self.state["current_phase"] = "halted"
        self.state["halt_reason"] = reason
        self._save_state()
        logger.critical("Validation pipeline HALTED: %s", reason)
