from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict

from stock_platform.notification.base import NotificationSender
from stock_platform.notification.models import (
    NotificationChannelResult,
    NotificationMessage,
    NotificationSendStatus,
)


class RetryingNotificationSender(NotificationSender):
    """일시 실패 시 짧은 backoff 재시도."""

    def __init__(
        self,
        inner: NotificationSender,
        *,
        max_attempts: int = 3,
        base_delay_seconds: float = 0.2,
    ) -> None:
        self._inner = inner
        self.channel = inner.channel
        self._max_attempts = max(1, max_attempts)
        self._base_delay_seconds = base_delay_seconds

    async def send(
        self,
        notification: NotificationMessage,
    ) -> NotificationChannelResult:
        last: NotificationChannelResult | None = None
        for attempt in range(1, self._max_attempts + 1):
            last = await self._inner.send(notification)
            if last.status != NotificationSendStatus.FAILED:
                return last
            if attempt < self._max_attempts:
                await asyncio.sleep(
                    self._base_delay_seconds * attempt
                )
        assert last is not None
        return last

    def status(self) -> dict:
        payload = self._inner.status()
        payload["retry_max_attempts"] = self._max_attempts
        return payload


class DedupingNotificationSender(NotificationSender):
    """동일 이벤트 TTL 내 중복 억제."""

    def __init__(
        self,
        inner: NotificationSender,
        *,
        ttl_seconds: int = 300,
        max_entries: int = 500,
    ) -> None:
        self._inner = inner
        self.channel = inner.channel
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._suppressed_count = 0

    async def send(
        self,
        notification: NotificationMessage,
    ) -> NotificationChannelResult:
        key = self._key(notification)
        now = time.monotonic()
        self._purge(now)
        if key in self._seen:
            self._suppressed_count += 1
            return NotificationChannelResult(
                channel=self.channel,
                status=NotificationSendStatus.SKIPPED,
                message="Duplicate notification suppressed",
                sent_at=__import__(
                    "datetime"
                ).datetime.now(
                    __import__("datetime").timezone.utc
                ),
            )
        result = await self._inner.send(notification)
        if result.status == NotificationSendStatus.SUCCESS:
            self._seen[key] = now
            if len(self._seen) > self._max_entries:
                self._seen.popitem(last=False)
        return result

    def status(self) -> dict:
        payload = self._inner.status()
        payload["dedupe_ttl_seconds"] = self._ttl_seconds
        payload["suppressed_count"] = self._suppressed_count
        return payload

    def _purge(self, now: float) -> None:
        expired = [
            key
            for key, stamped in self._seen.items()
            if now - stamped > self._ttl_seconds
        ]
        for key in expired:
            self._seen.pop(key, None)

    @staticmethod
    def _key(notification: NotificationMessage) -> str:
        payload = json.dumps(
            {
                "title": notification.title,
                "message": notification.message,
                "detail": notification.detail,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()
