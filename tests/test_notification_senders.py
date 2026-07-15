import asyncio

import httpx

from stock_platform.notification.models import (
    NotificationMessage,
    NotificationSendStatus,
)
from stock_platform.notification.slack_sender import (
    SlackNotificationSender,
)
from stock_platform.notification.telegram_sender import (
    TelegramNotificationSender,
)


def test_telegram_sender_success() -> None:
    async def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={"ok": True, "result": {}},
        )

    async def run():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        sender = TelegramNotificationSender(
            enabled=True,
            bot_token="token",
            chat_id="123",
            client=client,
        )

        result = await sender.send(
            NotificationMessage(
                title="Test",
                message="Message",
                detail={"loss": 300000},
            )
        )
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result.status == (
        NotificationSendStatus.SUCCESS
    )


def test_slack_sender_success() -> None:
    async def handler(request: httpx.Request):
        return httpx.Response(
            200,
            text="ok",
        )

    async def run():
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )
        sender = SlackNotificationSender(
            enabled=True,
            webhook_url="https://hooks.slack.com/test",
            client=client,
        )

        result = await sender.send(
            NotificationMessage(
                title="Test",
                message="Message",
                detail={"loss": 300000},
            )
        )
        await client.aclose()
        return result

    result = asyncio.run(run())

    assert result.status == (
        NotificationSendStatus.SUCCESS
    )
