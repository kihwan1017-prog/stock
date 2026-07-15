from __future__ import annotations

from datetime import datetime, timezone

import structlog

from stock_platform.notification.base import (
    NotificationSender,
)
from stock_platform.notification.models import (
    NotificationChannel,
    NotificationChannelResult,
    NotificationMessage,
    NotificationSendStatus,
)


logger = structlog.get_logger(__name__)


class LoggingNotificationSender(NotificationSender):
    channel = NotificationChannel.LOG

    async def send(
        self,
        notification: NotificationMessage,
    ) -> NotificationChannelResult:
        logger.critical(
            "risk_notification",
            title=notification.title,
            message=notification.message,
            detail=notification.detail,
        )

        return NotificationChannelResult(
            channel=self.channel,
            status=NotificationSendStatus.SUCCESS,
            message="Notification written to application log",
            sent_at=datetime.now(timezone.utc),
        )

    def status(self) -> dict:
        return {
            "channel": self.channel.value,
            "enabled": True,
        }
