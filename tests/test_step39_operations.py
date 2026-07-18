import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from stock_platform.api.deps_admin import hash_account, require_admin
from stock_platform.notification.models import (
    NotificationMessage,
    NotificationSendStatus,
)
from stock_platform.notification.resilience import (
    DedupingNotificationSender,
    RetryingNotificationSender,
)
from stock_platform.operation.health_service import SystemHealthService


class _FlakySender:
    channel = SimpleNamespace(value="LOG")

    def __init__(self) -> None:
        self.calls = 0

    async def send(self, notification):
        self.calls += 1
        from datetime import datetime, timezone

        from stock_platform.notification.models import (
            NotificationChannel,
            NotificationChannelResult,
        )

        if self.calls < 2:
            return NotificationChannelResult(
                channel=NotificationChannel.LOG,
                status=NotificationSendStatus.FAILED,
                message="temporary",
                sent_at=datetime.now(timezone.utc),
            )
        return NotificationChannelResult(
            channel=NotificationChannel.LOG,
            status=NotificationSendStatus.SUCCESS,
            message="ok",
            sent_at=datetime.now(timezone.utc),
        )

    def status(self) -> dict:
        return {"calls": self.calls}


def test_require_admin_open_when_key_empty(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        assert require_admin(x_admin_api_key=None) == "DEV_OPEN"
    finally:
        get_settings.cache_clear()


def test_require_admin_rejects_wrong_key(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "secret-admin")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(HTTPException) as exc:
            require_admin(x_admin_api_key="wrong")
        assert exc.value.status_code == 401
    finally:
        get_settings.cache_clear()


def test_hash_account_is_stable() -> None:
    assert hash_account("12345678") == hash_account("12345678")
    assert hash_account("12345678") != hash_account("87654321")


def test_notification_retry_and_dedupe() -> None:
    flaky = _FlakySender()
    sender = DedupingNotificationSender(
        RetryingNotificationSender(flaky, max_attempts=3),
        ttl_seconds=60,
    )
    message = NotificationMessage(
        title="t",
        message="m",
        detail={"k": 1},
    )
    first = asyncio.run(sender.send(message))
    second = asyncio.run(sender.send(message))
    assert first.status == NotificationSendStatus.SUCCESS
    assert second.status == NotificationSendStatus.SKIPPED
    assert flaky.calls == 2


def test_system_health_service_shape(monkeypatch) -> None:
    service = SystemHealthService()

    async def _fake_build_parts():
        return await service.build()

    # DB may be up in this environment; just assert schema.
    payload = asyncio.run(_fake_build_parts())
    assert "status" in payload
    assert "components" in payload
    assert "database" in payload["components"]
    assert "live_trading" in payload["components"]
