from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class DailyLossMonitorStatus(StrEnum):
    SAFE = "SAFE"
    LIMIT_REACHED = "LIMIT_REACHED"
    KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"


@dataclass(frozen=True, slots=True)
class DailyLossSnapshot:
    broker_code: str
    account_number: str
    realized_profit_loss: Decimal
    unrealized_profit_loss: Decimal
    combined_profit_loss: Decimal
    current_loss_amount: Decimal
    loss_limit_amount: Decimal
    status: DailyLossMonitorStatus
    kill_switch_activated: bool
    checked_at: datetime
