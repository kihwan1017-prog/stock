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
    TOSS = "TOSS"  # sender 미구현 — formatter/template만 준비


class NotificationSendStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    title: str
    message: str
    detail: dict[str, Any]
    # 한글 템플릿 렌더 결과 (없으면 title/message 사용)
    rendered_title: str | None = None
    rendered_body: str | None = None
    # 채널 본문에 raw JSON 첨부 여부 (기본 False — 사용자 가독성)
    include_raw_json: bool = False
    original_payload: dict[str, Any] | None = None
    template_id: int | None = None
    template_version: int | None = None
    locale: str = "ko-KR"
    missing_variables: tuple[str, ...] = ()
    category: str | None = None
    severity: str | None = None


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
