from __future__ import annotations

from abc import ABC, abstractmethod

from stock_platform.notification.models import (
    NotificationChannel,
    NotificationChannelResult,
    NotificationMessage,
)


class NotificationSender(ABC):
    channel: NotificationChannel

    @abstractmethod
    async def send(
        self,
        notification: NotificationMessage,
    ) -> NotificationChannelResult:
        raise NotImplementedError

    @abstractmethod
    def status(self) -> dict:
        raise NotImplementedError
