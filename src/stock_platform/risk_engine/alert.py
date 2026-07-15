from __future__ import annotations

from typing import Protocol

from stock_platform.notification.runtime import (
    risk_notification_sender,
)


class RiskAlertNotifier(Protocol):
    async def send(
        self,
        *,
        title: str,
        message: str,
        detail: dict,
    ) -> None:
        ...


class CompositeRiskAlertNotifier:
    async def send(
        self,
        *,
        title: str,
        message: str,
        detail: dict,
    ) -> None:
        await risk_notification_sender.send(
            title=title,
            message=message,
            detail=detail,
        )


class LoggingRiskAlertNotifier(
    CompositeRiskAlertNotifier
):
    """
    하위 호환용 이름.

    STEP29-6부터 로그·Telegram·Slack 복합 알림을 사용한다.
    """
