"""알림 이벤트 Publisher — 채널 전송은 NotificationService에 위임.

구조: Publisher → NotificationService → TelegramSender(복합 채널)
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

from stock_platform.notification.events import (
    NotificationEventType,
)

if TYPE_CHECKING:
    from stock_platform.notification.service import (
        NotificationService,
    )


logger = structlog.get_logger(__name__)

# STEP53 호환 별칭
ExitNotificationEventType = NotificationEventType

TELEGRAM_READY_EXIT_EVENTS = frozenset(
    {
        NotificationEventType.STOP_LOSS,
        NotificationEventType.TAKE_PROFIT,
        NotificationEventType.TRAILING_STOP,
        NotificationEventType.RELATIVE_LOSS,
        NotificationEventType.KILL_SWITCH,
        NotificationEventType.DAILY_LOSS,
    }
)


@dataclass(frozen=True, slots=True)
class PublishedNotification:
    event_type: str
    title: str
    message: str
    detail: dict[str, Any]
    published_at: datetime


class NotificationPublisher:
    """이벤트 적재 + NotificationService로 비동기 전달."""

    def __init__(
        self,
        *,
        max_events: int = 500,
        service: NotificationService | None = None,
    ) -> None:
        self._events: deque[PublishedNotification] = deque(
            maxlen=max_events
        )
        self._service = service

    def set_service(self, service: NotificationService) -> None:
        self._service = service

    def publish(
        self,
        *,
        event_type: str,
        title: str,
        message: str,
        detail: dict[str, Any] | None = None,
        dispatch: bool = True,
    ) -> PublishedNotification:
        payload = detail or {}
        event = PublishedNotification(
            event_type=event_type,
            title=title,
            message=message,
            detail=payload,
            published_at=datetime.now(timezone.utc),
        )
        self._events.append(event)
        logger.info(
            "notification_published",
            event_type=event_type,
            title=title,
            message=message,
            detail=payload,
            telegram_ready=(
                event_type in TELEGRAM_READY_EXIT_EVENTS
                or event_type
                in {
                    item.value
                    for item in NotificationEventType
                }
            ),
        )
        if dispatch:
            self._schedule_dispatch(event)
        return event

    async def publish_async(
        self,
        *,
        event_type: str,
        title: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> PublishedNotification:
        event = self.publish(
            event_type=event_type,
            title=title,
            message=message,
            detail=detail,
            dispatch=False,
        )
        if self._service is not None:
            await self._service.dispatch(event)
        return event

    def recent_events(
        self,
        *,
        limit: int = 50,
    ) -> list[PublishedNotification]:
        items = list(self._events)
        if limit <= 0:
            return []
        return items[-limit:]

    def clear(self) -> None:
        self._events.clear()

    def _schedule_dispatch(
        self,
        event: PublishedNotification,
    ) -> None:
        if self._service is None:
            return

        service = self._service

        async def _run() -> None:
            try:
                await service.dispatch(event)
            except Exception as exc:
                logger.warning(
                    "notification_dispatch_failed",
                    event_type=event.event_type,
                    error=str(exc),
                )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run())
        except RuntimeError:
            # 동기 컨텍스트(ExitMonitor tick 등) — 백그라운드 전달
            threading.Thread(
                target=lambda: asyncio.run(_run()),
                name="notification-dispatch",
                daemon=True,
            ).start()


# 프로세스 전역 — ExitMonitor / Lifecycle / Telegram Ops 공유
exit_notification_publisher = NotificationPublisher()
notification_publisher = exit_notification_publisher
