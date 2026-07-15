from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any

import httpx

from stock_platform.notification.base import (
    NotificationSender,
)
from stock_platform.notification.models import (
    NotificationChannel,
    NotificationChannelResult,
    NotificationMessage,
    NotificationSendStatus,
)


class TelegramNotificationSender(NotificationSender):
    channel = NotificationChannel.TELEGRAM

    def __init__(
        self,
        *,
        enabled: bool,
        bot_token: str,
        chat_id: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._enabled = enabled
        self._bot_token = bot_token.strip()
        self._chat_id = chat_id.strip()
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
                message="Telegram notification is disabled",
                sent_at=now,
            )

        if not self._bot_token or not self._chat_id:
            self._failed_count += 1
            self._last_error = (
                "Telegram bot token or chat ID is missing"
            )
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

        try:
            response = await client.post(
                (
                    "https://api.telegram.org/bot"
                    f"{self._bot_token}/sendMessage"
                ),
                json={
                    "chat_id": self._chat_id,
                    "text": self._format_message(
                        notification
                    ),
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()
            payload = response.json()

            if not payload.get("ok"):
                raise RuntimeError(
                    str(
                        payload.get(
                            "description",
                            "Telegram API returned ok=false",
                        )
                    )
                )

            self._sent_count += 1
            self._last_sent_at = now
            self._last_error = None

            return NotificationChannelResult(
                channel=self.channel,
                status=NotificationSendStatus.SUCCESS,
                message="Telegram notification sent",
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
            "configured": bool(
                self._bot_token and self._chat_id
            ),
            "sent_count": self._sent_count,
            "failed_count": self._failed_count,
            "last_sent_at": self._last_sent_at,
            "last_error": self._last_error,
        }

    @staticmethod
    def _format_message(
        notification: NotificationMessage,
    ) -> str:
        detail_text = json.dumps(
            notification.detail,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

        return (
            f"<b>🚨 {html.escape(notification.title)}</b>\n\n"
            f"{html.escape(notification.message)}\n\n"
            f"<pre>{html.escape(detail_text)}</pre>"
        )
