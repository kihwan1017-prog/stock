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
    """STEP 8-5-18 — UBA/Paper 단위 Daily Loss 결과."""

    user_broker_account_id: int | None
    paper_account_id: int | None
    broker_code: str
    # 마스킹 표시용 — 내부 식별자로 사용 금지
    masked_account_ref: str
    trading_date: str
    currency: str
    realized_profit_loss: Decimal
    unrealized_profit_loss: Decimal
    combined_profit_loss: Decimal
    current_loss_amount: Decimal
    loss_limit_amount: Decimal
    status: DailyLossMonitorStatus
    kill_switch_activated: bool
    checked_at: datetime
