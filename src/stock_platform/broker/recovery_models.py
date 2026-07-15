from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class RecoveryComponent(StrEnum):
    KIWOOM_ACCOUNT = "KIWOOM_ACCOUNT"
    KIWOOM_PENDING_ORDERS = "KIWOOM_PENDING_ORDERS"
    KIWOOM_ORDER_WEBSOCKET = "KIWOOM_ORDER_WEBSOCKET"
    REALTIME_STRATEGY = "REALTIME_STRATEGY"
    REALTIME_EXECUTION = "REALTIME_EXECUTION"
    REALTIME_SCHEDULER = "REALTIME_SCHEDULER"


class RecoveryStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class RecoveryStepResult:
    component: RecoveryComponent
    status: RecoveryStatus
    message: str
    started_at: datetime
    finished_at: datetime
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RecoveryRunResult:
    started_at: datetime
    finished_at: datetime
    success: bool
    steps: list[RecoveryStepResult]
