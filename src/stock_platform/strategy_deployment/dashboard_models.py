from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class StrategyOperationsDashboardSnapshot:
    generated_at: datetime
    market_code: str
    symbol: str | None
    active_deployment: dict[str, Any] | None
    runtime: dict[str, Any]
    latest_approval: dict[str, Any] | None
    latest_pipeline: dict[str, Any] | None
    latest_performance: dict[str, Any] | None
    recent_deployments: list[dict[str, Any]]
    recent_approvals: list[dict[str, Any]]
    recent_switches: list[dict[str, Any]]
    recent_pipeline_runs: list[dict[str, Any]]
    recent_performance_checks: list[dict[str, Any]]
