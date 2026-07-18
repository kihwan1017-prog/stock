from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from stock_platform.notification.base import NotificationSender
from stock_platform.notification.models import (
    NotificationChannel,
    NotificationChannelResult,
    NotificationMessage,
    NotificationSendStatus,
)


class DiscordNotificationSender(NotificationSender):
    channel = NotificationChannel.DISCORD

    def __init__(
        self,
        *,
        enabled: bool,
        webhook_url: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._enabled = enabled
        self._webhook_url = webhook_url.strip()
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._sent_count = 0
        self._failed_count = 0
        self._last_sent_at: datetime | None = None
        self._last_error: str | None = None

    async def send(
        self,
        notification: NotificationMessage,
    ) -> NotificationChannelResult:
        now = datetime.now(timezone.utc)
        if not self._enabled:
            return NotificationChannelResult(
                channel=self.channel,
                status=NotificationSendStatus.SKIPPED,
                message="Discord notification is disabled",
                sent_at=now,
            )
        if not self._webhook_url:
            self._failed_count += 1
            self._last_error = "Discord webhook URL is missing"
            return NotificationChannelResult(
                channel=self.channel,
                status=NotificationSendStatus.FAILED,
                message=self._last_error,
                sent_at=now,
            )

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout_seconds
        )
        content = (
            f"**{notification.title}**\n"
            f"{notification.message}\n"
            f"```json\n"
            f"{json.dumps(notification.detail, ensure_ascii=False, default=str)[:1500]}"
            f"\n```"
        )
        try:
            response = await client.post(
                self._webhook_url,
                json={"content": content[:1900]},
            )
            response.raise_for_status()
            self._sent_count += 1
            self._last_sent_at = now
            self._last_error = None
            return NotificationChannelResult(
                channel=self.channel,
                status=NotificationSendStatus.SUCCESS,
                message="Discord notification sent",
                sent_at=now,
            )
        except Exception as exc:
            self._failed_count += 1
            self._last_error = str(exc)
            return NotificationChannelResult(
                channel=self.channel,
                status=NotificationSendStatus.FAILED,
                message=self._last_error,
                sent_at=now,
            )
        finally:
            if owns_client:
                await client.aclose()

    def status(self) -> dict:
        return {
            "channel": self.channel.value,
            "enabled": self._enabled,
            "configured": bool(self._webhook_url),
            "sent_count": self._sent_count,
            "failed_count": self._failed_count,
            "last_sent_at": self._last_sent_at,
            "last_error": self._last_error,
        }
