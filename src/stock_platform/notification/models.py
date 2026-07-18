from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class NotificationChannel(StrEnum):
    LOG = "LOG"
    TELEGRAM = "TELEGRAM"
    SLACK = "SLACK"
    DISCORD = "DISCORD"


class NotificationSendStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    title: str
    message: str
    detail: dict[str, Any]


@dataclass(frozen=True, slots=True)
class NotificationChannelResult:
    channel: NotificationChannel
    status: NotificationSendStatus
    message: str
    sent_at: datetime


@dataclass(frozen=True, slots=True)
class NotificationSendResult:
    success: bool
    results: list[NotificationChannelResult]
    sent_at: datetime
