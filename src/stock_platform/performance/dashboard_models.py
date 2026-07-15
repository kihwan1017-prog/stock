from dataclasses import dataclass
from datetime import datetime
from typing import Any

@dataclass(frozen=True, slots=True)
class StrategyPerformanceDashboardSnapshot:
    generated_at: datetime
    filters: dict[str, Any]
    summary: dict[str, Any]
    ranking: list[dict[str, Any]]
    latest_selection: dict[str, Any] | None
    leaderboard_history: list[dict[str, Any]]
    recent_runs: list[dict[str, Any]]
    walk_forward_stability: list[dict[str, Any]]
