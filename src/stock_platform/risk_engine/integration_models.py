from __future__ import annotations

from dataclasses import dataclass

from stock_platform.risk_engine.models import (
    RiskEvaluationResult,
)


@dataclass(frozen=True, slots=True)
class RiskCheckedOrderResult:
    allowed: bool
    blocked_reason: str | None
    evaluation: RiskEvaluationResult
