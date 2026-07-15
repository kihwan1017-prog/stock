from __future__ import annotations

import os

from stock_platform.notification.composite import (
    CompositeNotificationSender,
)
from stock_platform.notification.logging_sender import (
    LoggingNotificationSender,
)
from stock_platform.notification.slack_sender import (
    SlackNotificationSender,
)
from stock_platform.notification.telegram_sender import (
    TelegramNotificationSender,
)


risk_notification_sender = CompositeNotificationSender(
    [
        LoggingNotificationSender(),
        TelegramNotificationSender(
            enabled=(
                os.getenv(
                    "TELEGRAM_ENABLED",
                    "false",
                ).lower()
                == "true"
            ),
            bot_token=os.getenv(
                "TELEGRAM_BOT_TOKEN",
                "",
            ),
            chat_id=os.getenv(
                "TELEGRAM_CHAT_ID",
                "",
            ),
        ),
        SlackNotificationSender(
            enabled=(
                os.getenv(
                    "SLACK_ENABLED",
                    "false",
                ).lower()
                == "true"
            ),
            webhook_url=os.getenv(
                "SLACK_WEBHOOK_URL",
                "",
            ),
        ),
    ]
)
