from __future__ import annotations

from typing import Protocol


class RiskAlertNotifier(Protocol):
    async def send(
        self,
        *,
        title: str,
        message: str,
        detail: dict,
    ) -> None:
        ...


class LoggingRiskAlertNotifier:
    """
    STEP29-4 기본 알림 구현.

    현재는 애플리케이션 로그에만 기록한다.
    STEP29-6에서 Telegram·Slack Notifier를 연결한다.
    """

    async def send(
        self,
        *,
        title: str,
        message: str,
        detail: dict,
    ) -> None:
        import structlog

        structlog.get_logger(__name__).critical(
            "risk_alert",
            title=title,
            message=message,
            detail=detail,
        )
