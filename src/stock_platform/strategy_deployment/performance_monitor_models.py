from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class DeploymentPerformanceStatus(StrEnum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    STOP_REQUIRED = "STOP_REQUIRED"
    STOPPED = "STOPPED"
    NOT_ENOUGH_DATA = "NOT_ENOUGH_DATA"


@dataclass(frozen=True, slots=True)
class DeploymentPerformancePolicy:
    minimum_trade_count: int = 5
    minimum_total_return_rate: Decimal = Decimal("-0.03")
    maximum_drawdown_rate: Decimal = Decimal("0.10")
    minimum_win_rate: Decimal = Decimal("0.30")
    minimum_profit_factor: Decimal = Decimal("0.80")
    maximum_consecutive_losses: int = 5
    auto_stop_enabled: bool = False


@dataclass(frozen=True, slots=True)
class DeploymentPerformanceSnapshot:
    deployment_id: int
    strategy_code: str
    total_trade_count: int
    total_return_rate: Decimal
    maximum_drawdown_rate: Decimal
    win_rate: Decimal
    profit_factor: Decimal | None
    consecutive_losses: int
    status: DeploymentPerformanceStatus
    checks: list[dict[str, Any]]
    checked_at: datetime
