from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class LiveTransitionCheckCode(StrEnum):
    GLOBAL_LIVE_ORDER_ENABLED = "GLOBAL_LIVE_ORDER_ENABLED"
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
    # Broker-aware / UPBIT ACCOUNT
    SCOPE_ACCOUNT_REQUIRED = "SCOPE_ACCOUNT_REQUIRED"
    UBA_EXISTS = "UBA_EXISTS"
    UBA_BROKER_MATCH = "UBA_BROKER_MATCH"
    UBA_ACTIVE = "UBA_ACTIVE"
    CONNECTION_CONNECTED = "CONNECTION_CONNECTED"
    CREDENTIAL_PRESENT = "CREDENTIAL_PRESENT"
    CREDENTIAL_VERIFIED = "CREDENTIAL_VERIFIED"
    RECOVERY_STATUS_OK = "RECOVERY_STATUS_OK"
    TRADING_NOT_PAUSED = "TRADING_NOT_PAUSED"
    NO_ACTIVE_CONFLICTS = "NO_ACTIVE_CONFLICTS"
    KILL_SWITCH_OFF = "KILL_SWITCH_OFF"
    ACCOUNT_NOT_PAUSED = "ACCOUNT_NOT_PAUSED"
    NO_DB_OPEN_ORDERS = "NO_DB_OPEN_ORDERS"
    ACTIVATION_LIFECYCLE_NOTE = "ACTIVATION_LIFECYCLE_NOTE"
    UNSUPPORTED_BROKER = "UNSUPPORTED_BROKER"


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
    broker_code: str = "KIWOOM"
    scope: str = "BROKER"
    user_broker_account_id: int | None = None
