from __future__ import annotations

from stock_platform.notification.composite import (
    CompositeNotificationSender,
)
from stock_platform.notification.discord_sender import (
    DiscordNotificationSender,
)
from stock_platform.notification.logging_sender import (
    LoggingNotificationSender,
)
from stock_platform.notification.publisher import (
    notification_publisher,
)
from stock_platform.notification.resilience import (
    DedupingNotificationSender,
    RetryingNotificationSender,
)
from stock_platform.notification.service import (
    NotificationService,
)
from stock_platform.notification.slack_sender import (
    SlackNotificationSender,
)
from stock_platform.notification.telegram_sender import (
    TelegramNotificationSender,
)


def build_risk_notification_sender() -> CompositeNotificationSender:
    # get_settings 는 빌드 시점에만 호출 (모듈 import 부작용 방지)
    from stock_platform.common.settings import get_settings

    settings = get_settings()
    senders = [
        LoggingNotificationSender(),
        DedupingNotificationSender(
            RetryingNotificationSender(
                TelegramNotificationSender(
                    enabled=settings.telegram_enabled,
                    bot_token=settings.telegram_bot_token,
                    chat_id=settings.telegram_chat_id,
                )
            )
        ),
        DedupingNotificationSender(
            RetryingNotificationSender(
                SlackNotificationSender(
                    enabled=settings.slack_enabled,
                    webhook_url=settings.slack_webhook_url,
                )
            )
        ),
        DedupingNotificationSender(
            RetryingNotificationSender(
                DiscordNotificationSender(
                    enabled=settings.discord_enabled,
                    webhook_url=settings.discord_webhook_url,
                )
            )
        ),
    ]
    return CompositeNotificationSender(senders)


_risk_notification_sender: CompositeNotificationSender | None = None
_notification_service: NotificationService | None = None


def get_risk_notification_sender() -> CompositeNotificationSender:
    """지연 초기화 — import 만으로 Settings/외부 설정을 읽지 않는다."""

    global _risk_notification_sender, _notification_service
    if _risk_notification_sender is None:
        _risk_notification_sender = build_risk_notification_sender()
        _notification_service = NotificationService(
            sender=_risk_notification_sender,
        )
        notification_publisher.set_service(_notification_service)
    return _risk_notification_sender


def get_notification_service() -> NotificationService:
    get_risk_notification_sender()
    assert _notification_service is not None
    return _notification_service


def reset_notification_runtime() -> None:
    """테스트용 런타임 재설정."""

    global _risk_notification_sender, _notification_service
    _risk_notification_sender = None
    _notification_service = None


def __getattr__(name: str):
    # from runtime import risk_notification_sender 호환 (지연 로드)
    if name == "risk_notification_sender":
        return get_risk_notification_sender()
    if name == "notification_service":
        return get_notification_service()
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )
