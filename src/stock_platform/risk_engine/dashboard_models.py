from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class RiskDashboardPositionSummary:
    cash_balance: Decimal
    invested_amount: Decimal
    total_asset_value: Decimal
    investment_ratio: Decimal
    open_position_count: int


@dataclass(frozen=True, slots=True)
class RiskDashboardSnapshot:
    generated_at: datetime
    account_number: str
    kill_switch: dict[str, Any]
    daily_loss: dict[str, Any]
    broker: dict[str, Any]
    notification: dict[str, Any]
    risk_engine: dict[str, Any]
    execution: dict[str, Any]
    position: RiskDashboardPositionSummary | None
    recent_events: list[dict[str, Any]]
