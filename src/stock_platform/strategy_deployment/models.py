from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class StrategyDeploymentMode(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class StrategyDeploymentStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REPLACED = "REPLACED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class StrategyDeploymentRequest:
    strategy_code: str
    strategy_performance_run_id: int
    market_code: str
    symbol: str | None
    mode: StrategyDeploymentMode
    parameter_payload: dict[str, Any]
    requested_by: str


@dataclass(frozen=True, slots=True)
class StrategyDeploymentResult:
    strategy_deployment_id: int
    strategy_code: str
    strategy_performance_run_id: int
    status: StrategyDeploymentStatus
    mode: StrategyDeploymentMode
    activated_at: datetime | None
    message: str
