from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class RealtimeExecutionMode(StrEnum):
    PAPER = "PAPER"
    LIVE = "LIVE"
    MOCK = "MOCK"


@dataclass(frozen=True, slots=True)
class RealtimeExecutionConfig:
    # account_id는 설정/호출부에서 명시 주입 (기본값 1 금지)
    mode: RealtimeExecutionMode = RealtimeExecutionMode.PAPER
    account_id: int = 0
    order_amount: Decimal = Decimal("100000")
    auto_fill: bool = True
    allow_buy: bool = True
    allow_sell: bool = True
    # STEP8-2 — ResolvedRiskPolicy 해석용 (Paper는 user_id만)
    user_id: int | None = None
    user_broker_account_id: int | None = None

    def __post_init__(self) -> None:
        if self.account_id <= 0:
            raise ValueError(
                "RealtimeExecutionConfig.account_id must be > 0 "
                "(set REALTIME_PAPER_ACCOUNT_ID)"
            )


@dataclass(frozen=True, slots=True)
class RealtimeExecutionResult:
    exchange_code: str
    symbol: str
    signal_action: str
    execution_mode: str
    order_id: int | None
    trade_id: int | None
    order_status: str
    quantity: Decimal
    order_price: Decimal
    reason_code: str
    executed_at: datetime
