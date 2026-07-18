from __future__ import annotations

from stock_platform.common.settings import get_settings
from stock_platform.notification.composite import (
    CompositeNotificationSender,
)
from stock_platform.notification.discord_sender import (
    DiscordNotificationSender,
)
from stock_platform.notification.logging_sender import (
    LoggingNotificationSender,
)
from stock_platform.notification.resilience import (
    DedupingNotificationSender,
    RetryingNotificationSender,
)
from stock_platform.notification.slack_sender import (
    SlackNotificationSender,
)
from stock_platform.notification.telegram_sender import (
    TelegramNotificationSender,
)


def build_risk_notification_sender() -> CompositeNotificationSender:
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


risk_notification_sender = build_risk_notification_sender()
