import asyncio
from datetime import datetime, timezone

from stock_platform.notification.composite import (
    CompositeNotificationSender,
)
from stock_platform.notification.models import (
    NotificationChannel,
    NotificationChannelResult,
    NotificationSendStatus,
)


class SuccessSender:
    channel = NotificationChannel.LOG

    async def send(self, notification):
        return NotificationChannelResult(
            channel=self.channel,
            status=NotificationSendStatus.SUCCESS,
            message="ok",
            sent_at=datetime.now(timezone.utc),
        )

    def status(self):
        return {"enabled": True}


class FailureSender:
    channel = NotificationChannel.SLACK

    async def send(self, notification):
        raise RuntimeError("failed")

    def status(self):
        return {"enabled": True}


def test_one_failure_does_not_stop_other_channels() -> None:
    result = asyncio.run(
        CompositeNotificationSender(
            [FailureSender(), SuccessSender()]
        ).send(
            title="Test",
            message="Message",
            detail={},
        )
    )

    assert result.success is True
    assert len(result.results) == 2
    assert any(
        item.status == NotificationSendStatus.FAILED
        for item in result.results
    )
    assert any(
        item.status == NotificationSendStatus.SUCCESS
        for item in result.results
    )
