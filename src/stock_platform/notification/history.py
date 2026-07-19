"""인메모리 알림 이력 · 설정 스냅샷 (DB 테이블 없음)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.notification.events import (
    NotificationLevel,
    parse_notification_level,
)


@dataclass(frozen=True, slots=True)
class NotificationHistoryRecord:
    event_type: str
    title: str
    message: str
    channel_results: list[dict[str, Any]]
    success: bool
    created_at: datetime


class NotificationHistory:
    """최근 알림 송신 이력 (프로세스 로컬)."""

    def __init__(self, *, max_records: int = 200) -> None:
        self._records: deque[NotificationHistoryRecord] = (
            deque(maxlen=max_records)
        )

    def append(self, record: NotificationHistoryRecord) -> None:
        self._records.append(record)

    def recent(
        self,
        *,
        limit: int = 50,
    ) -> list[NotificationHistoryRecord]:
        items = list(self._records)
        if limit <= 0:
            return []
        return items[-limit:]

    def clear(self) -> None:
        self._records.clear()


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    """Telegram 알림 설정 스냅샷 (env / Settings 기반)."""

    enabled: bool
    bot_token_configured: bool
    chat_id: str
    notification_level: NotificationLevel
    ops_enabled: bool
    allowed_chat_ids: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> NotificationSettings:
        settings = get_settings()
        allowed = _parse_chat_ids(
            getattr(
                settings,
                "telegram_allowed_chat_ids",
                "",
            )
        )
        primary = settings.telegram_chat_id.strip()
        if primary and primary not in allowed:
            allowed = (primary, *allowed)
        return cls(
            enabled=settings.telegram_enabled,
            bot_token_configured=bool(
                settings.telegram_bot_token.strip()
            ),
            chat_id=primary,
            notification_level=parse_notification_level(
                getattr(
                    settings,
                    "telegram_notification_level",
                    "INFO",
                )
            ),
            ops_enabled=bool(
                getattr(
                    settings,
                    "telegram_ops_enabled",
                    False,
                )
            ),
            allowed_chat_ids=allowed,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "bot_token_configured": self.bot_token_configured,
            "chat_id": self.chat_id,
            "notification_level": self.notification_level.name,
            "ops_enabled": self.ops_enabled,
            "allowed_chat_ids": list(self.allowed_chat_ids),
        }


def _parse_chat_ids(raw: str) -> tuple[str, ...]:
    parts = [
        item.strip()
        for item in (raw or "").split(",")
        if item.strip()
    ]
    return tuple(parts)


notification_history = NotificationHistory()
