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
    # § STEP12-19 — "READY_TO_START"는 STEP31-1 PaperStrategyDeploymentService
    # 의 ACTIVE(실제 활성/실행 중)와 완전히 다른 의미다: Runtime을 실제로
    # 시작하지 않고 "START 직전까지 구성이 확정됨"만 나타낸다. 기존 ACTIVE
    # 의 의미를 절대 재사용/변경하지 않기 위해 별도 값으로 추가한다.
    READY_TO_START = "READY_TO_START"
    # § STEP12-20 — "READY_TO_OPERATE"는 같은 Deployment 행이 Operation
    # Readiness Certification까지 통과했음을 나타낸다(여전히 Runtime 미실행
    # — READY_TO_START과 마찬가지로 ACTIVE와 구분된다). STEP13의 실제 START
    # 승인 전 마지막 상태다.
    READY_TO_OPERATE = "READY_TO_OPERATE"


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
