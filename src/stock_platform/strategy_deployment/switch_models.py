from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class StrategySwitchStatus(StrEnum):
    DRY_RUN_PASSED = "DRY_RUN_PASSED"
    DRY_RUN_FAILED = "DRY_RUN_FAILED"
    SWITCHED = "SWITCHED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class StrategyStateSnapshot:
    deployment_id: int
    strategy_code: str
    state_payload: dict[str, Any]
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class StrategyDryRunResult:
    passed: bool
    strategy_code: str
    deployment_id: int
    checks: list[dict[str, Any]]
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class StrategySwitchResult:
    status: StrategySwitchStatus
    previous_deployment_id: int | None
    current_deployment_id: int | None
    strategy_code: str | None
    message: str
    completed_at: datetime
