from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class StrategyApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    FORCED = "FORCED"


class StrategyApprovalStatus(StrEnum):
    PENDING = "PENDING"
    EVALUATED = "EVALUATED"
    DEPLOYED = "DEPLOYED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class StrategyApprovalPolicy:
    minimum_score: Decimal = Decimal("0.60")
    minimum_sharpe_ratio: Decimal = Decimal("0.80")
    maximum_drawdown_rate: Decimal = Decimal("0.20")
    minimum_win_rate: Decimal = Decimal("0.45")
    minimum_trade_count: int = 20
    minimum_confidence_score: Decimal = Decimal("0.60")
    require_walk_forward: bool = True
    require_positive_return: bool = True
    require_kill_switch_inactive: bool = True
    require_runtime_healthy: bool = True


@dataclass(frozen=True, slots=True)
class StrategyApprovalCheck:
    check_code: str
    passed: bool
    message: str
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StrategyApprovalEvaluation:
    decision: StrategyApprovalDecision
    checks: list[StrategyApprovalCheck]
    evaluated_at: datetime
    reason: str
