from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class StrategyDeploymentPipelineStatus(StrEnum):
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    DEPLOYED = "DEPLOYED"
    SWITCHED = "SWITCHED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class StrategyDeploymentPipelineResult:
    status: StrategyDeploymentPipelineStatus
    approval_run_id: int | None
    deployment_id: int | None
    switch_status: str | None
    strategy_code: str | None
    message: str
    detail: dict[str, Any]
    completed_at: datetime
