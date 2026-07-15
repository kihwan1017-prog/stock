from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from stock_platform.notification.base import (
    NotificationSender,
)
from stock_platform.notification.models import (
    NotificationMessage,
    NotificationSendResult,
    NotificationSendStatus,
)


class CompositeNotificationSender:
    """
    한 채널이 실패해도 다른 채널 전송을 계속한다.
    """

    def __init__(
        self,
        senders: list[NotificationSender],
    ) -> None:
        self._senders = senders

    async def send(
        self,
        *,
        title: str,
        message: str,
        detail: dict,
    ) -> NotificationSendResult:
        notification = NotificationMessage(
            title=title,
            message=message,
            detail=detail,
        )

        results = await asyncio.gather(
            *[
                sender.send(notification)
                for sender in self._senders
            ],
            return_exceptions=True,
        )

        normalized = []

        for sender, result in zip(
            self._senders,
            results,
            strict=True,
        ):
            if isinstance(result, Exception):
                from stock_platform.notification.models import (
                    NotificationChannelResult,
                )

                normalized.append(
                    NotificationChannelResult(
                        channel=sender.channel,
                        status=NotificationSendStatus.FAILED,
                        message=str(result),
                        sent_at=datetime.now(timezone.utc),
                    )
                )
            else:
                normalized.append(result)

        success = any(
            item.status == NotificationSendStatus.SUCCESS
            for item in normalized
        )

        return NotificationSendResult(
            success=success,
            results=normalized,
            sent_at=datetime.now(timezone.utc),
        )

    def status(self) -> dict:
        return {
            "channels": [
                sender.status()
                for sender in self._senders
            ]
        }
