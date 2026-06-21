"""
Run Tracker — AFX AutoTrader v2
Generates metadata.yaml per run for full reproducibility.
Captures: random seeds, data hashes, model versions, git commit, performance metrics.
"""

from __future__ import annotations

import hashlib
import os
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class RunMetadata:
    """Metadata for a single run."""
    run_id: str
    timestamp_utc: str
    strategy_mode: str
    random_seed: int
    data_hash: str
    model_version: str
    python_version: str
    git_commit: str
    git_branch: str
    mt5_build: str
    platform: str
    performance_metrics: Dict[str, float] = field(default_factory=dict)
    hyperparameters: Dict[str, Any] = field(default_factory=dict)
    feature_importance: Dict[str, float] = field(default_factory=dict)
    notes: str = ""


class RunTracker:
    """
    Tracks run metadata for reproducibility.

    Usage:
        tracker = RunTracker()
        tracker.start_run(strategy_mode="SWING", random_seed=42)
        tracker.record_performance(sharpe_ratio=1.45, max_drawdown=0.12, win_rate=0.63)
        tracker.save_metadata()
    """

    def __init__(self, metadata_dir: str = "brain_data"):
        self._metadata_dir = metadata_dir
        self._run: Optional[RunMetadata] = None
        self._hash_alg = hashlib.sha256

    def start_run(
        self,
        strategy_mode: str = "SWING",
        random_seed: Optional[int] = None,
        model_version: str = "v2.2.0",
    ) -> RunMetadata:
        """Start a new run and capture initial metadata."""
        seed = random_seed if random_seed is not None else random.randint(0, 99999)
        random.seed(seed)

        git_info = self._get_git_info()

        self._run = RunMetadata(
            run_id=str(uuid.uuid4()),
            timestamp_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            strategy_mode=strategy_mode,
            random_seed=seed,
            data_hash="",
            model_version=model_version,
            python_version=self._get_python_version(),
            git_commit=git_info["commit"],
            git_branch=git_info["branch"],
            mt5_build=str(self._get_mt5_build()),
            platform="windows" if os.name == "nt" else "linux",
        )

        return self._run

    def update_data_hash(self, data_path: str) -> None:
        """Compute hash of training data."""
        if self._run is None:
            raise RuntimeError("start_run() must be called first")
        h = self._hash_alg()
        try:
            with open(data_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            self._run.data_hash = h.hexdigest()[:16]
        except Exception:
            self._run.data_hash = "unavailable"

    def record_performance(
        self,
        sharpe_ratio: float = 0.0,
        max_drawdown: float = 0.0,
        win_rate: float = 0.0,
        total_trades: int = 0,
        profit_factor: float = 0.0,
        **kwargs: float,
    ) -> None:
        """Record performance metrics for the run."""
        if self._run is None:
            return
        self._run.performance_metrics = {
            "sharpe_ratio": round(sharpe_ratio, 4),
            "max_drawdown": round(max_drawdown, 4),
            "win_rate": round(win_rate, 4),
            "total_trades": total_trades,
            "profit_factor": round(profit_factor, 4),
            **kwargs,
        }

    def record_hyperparameters(self, **params: Any) -> None:
        """Record hyperparameters used in this run."""
        if self._run is None:
            return
        self._run.hyperparameters = {k: v for k, v in params.items() if v is not None}

    def record_feature_importance(self, importance: Dict[str, float]) -> None:
        """Record feature importance from model."""
        if self._run is None:
            return
        self._run.feature_importance = {k: round(v, 4) for k, v in importance.items()}

    def save_metadata(self, filename: Optional[str] = None) -> str:
        """Save metadata.yaml to disk. Returns the path."""
        if self._run is None:
            raise RuntimeError("start_run() must be called first")

        os.makedirs(self._metadata_dir, exist_ok=True)
        path = os.path.join(
            self._metadata_dir,
            filename or f"metadata_{self._run.run_id[:8]}.yaml",
        )

        with open(path, "w") as f:
            yaml.dump(asdict(self._run), f, default_flow_style=False, sort_keys=False)

        return path

    def get_current_run(self) -> Optional[RunMetadata]:
        return self._run

    def _get_git_info(self) -> Dict[str, str]:
        info = {"commit": "unknown", "branch": "unknown"}
        try:
            import subprocess
            commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            info = {"commit": commit, "branch": branch}
        except Exception:
            pass
        return info

    def _get_python_version(self) -> str:
        import sys
        return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    def _get_mt5_build(self) -> int:
        try:
            from mt5_mcp import terminal_info
            ti = terminal_info()
            if ti:
                return getattr(ti, "build", 0)
        except Exception:
            pass
        return 0


# ─── Singleton ─────────────────────────────────────────────────
_tracker: Optional[RunTracker] = None


def get_run_tracker() -> RunTracker:
    global _tracker
    if _tracker is None:
        _tracker = RunTracker()
    return _tracker