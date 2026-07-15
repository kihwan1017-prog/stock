from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class LiveTransitionCheckCode(StrEnum):
    MOCK_MODE_DISABLED = "MOCK_MODE_DISABLED"
    LIVE_ORDER_ENABLED = "LIVE_ORDER_ENABLED"
    ACCOUNT_NUMBER_PRESENT = "ACCOUNT_NUMBER_PRESENT"
    APP_CREDENTIALS_PRESENT = "APP_CREDENTIALS_PRESENT"
    WEBSOCKET_CONFIGURED = "WEBSOCKET_CONFIGURED"
    RECOVERY_TRADING_DISABLED = "RECOVERY_TRADING_DISABLED"
    PAPER_VALIDATION_APPROVED = "PAPER_VALIDATION_APPROVED"
    MAX_ORDER_LIMIT_VALID = "MAX_ORDER_LIMIT_VALID"
    DAILY_LOSS_LIMIT_VALID = "DAILY_LOSS_LIMIT_VALID"
    MANUAL_APPROVAL_REQUIRED = "MANUAL_APPROVAL_REQUIRED"


class LiveTransitionCheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"


@dataclass(frozen=True, slots=True)
class LiveTransitionCheckResult:
    code: LiveTransitionCheckCode
    status: LiveTransitionCheckStatus
    message: str
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LiveTransitionPlan:
    ready: bool
    generated_at: datetime
    max_order_amount: Decimal
    max_daily_loss: Decimal
    checks: list[LiveTransitionCheckResult]
