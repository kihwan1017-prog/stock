from __future__ import annotations

from typing import Protocol

from stock_platform.notification.events import (
    NotificationEventType,
)
from stock_platform.notification.publisher import (
    notification_publisher,
)


class RiskAlertNotifier(Protocol):
    async def send(
        self,
        *,
        title: str,
        message: str,
        detail: dict,
    ) -> None:
        ...


class CompositeRiskAlertNotifier:
    """리스크 알림은 Publisher만 사용한다 (TelegramSender 직접 호출 금지)."""

    async def send(
        self,
        *,
        title: str,
        message: str,
        detail: dict,
    ) -> None:
        event_type = str(
            detail.get("event_type")
            or NotificationEventType.KILL_SWITCH
        )
        await notification_publisher.publish_async(
            event_type=event_type,
            title=title,
            message=message,
            detail=detail,
        )


class LoggingRiskAlertNotifier(
    CompositeRiskAlertNotifier
):
    """
    하위 호환용 이름.

    STEP54: Publisher → NotificationService → TelegramSender.
    """
