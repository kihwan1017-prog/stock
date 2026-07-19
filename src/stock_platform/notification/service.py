"""NotificationService — Publisher와 TelegramSender 사이의 단일 전달 계층."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

from stock_platform.notification.events import (
    should_dispatch_event,
)
from stock_platform.notification.history import (
    NotificationHistory,
    NotificationHistoryRecord,
    NotificationSettings,
    notification_history,
)
from stock_platform.notification.models import (
    NotificationSendResult,
)

if TYPE_CHECKING:
    from stock_platform.notification.composite import (
        CompositeNotificationSender,
    )
    from stock_platform.notification.publisher import (
        PublishedNotification,
    )


logger = structlog.get_logger(__name__)


class NotificationService:
    """
    Publisher → Service → CompositeNotificationSender(Telegram 포함).

    Service/도메인은 TelegramSender를 직접 호출하지 않는다.
    """

    def __init__(
        self,
        *,
        sender: CompositeNotificationSender,
        history: NotificationHistory | None = None,
    ) -> None:
        self._sender = sender
        self._history = history or notification_history

    async def dispatch(
        self,
        event: PublishedNotification,
        *,
        audit: bool = True,
    ) -> NotificationSendResult | None:
        settings = NotificationSettings.from_env()
        if not should_dispatch_event(
            event.event_type,
            settings.notification_level,
        ):
            logger.debug(
                "notification_dispatch_skipped_level",
                event_type=event.event_type,
                configured_level=(
                    settings.notification_level.name
                ),
            )
            return None

        result = await self._sender.send(
            title=event.title,
            message=event.message,
            detail={
                "event_type": event.event_type,
                **event.detail,
            },
        )

        self._history.append(
            NotificationHistoryRecord(
                event_type=event.event_type,
                title=event.title,
                message=event.message,
                channel_results=[
                    {
                        "channel": item.channel.value,
                        "status": item.status.value,
                        "message": item.message,
                    }
                    for item in result.results
                ],
                success=result.success,
                created_at=datetime.now(timezone.utc),
            )
        )

        logger.debug(
            "notification_dispatched",
            event_type=event.event_type,
            success=result.success,
            channels=[
                item.channel.value for item in result.results
            ],
        )

        if audit:
            self._record_audit(
                event_type="TELEGRAM_SEND"
                if any(
                    item.channel.value == "TELEGRAM"
                    for item in result.results
                )
                else "NOTIFICATION_SEND",
                actor="NOTIFICATION_SERVICE",
                detail={
                    "event_type": event.event_type,
                    "title": event.title,
                    "success": result.success,
                    "results": [
                        {
                            "channel": item.channel.value,
                            "status": item.status.value,
                            "message": item.message,
                        }
                        for item in result.results
                    ],
                },
            )

        return result

    def status(self) -> dict[str, Any]:
        settings = NotificationSettings.from_env()
        return {
            "settings": settings.to_dict(),
            "channels": self._sender.status(),
            "history_count": len(
                self._history.recent(limit=10_000)
            ),
            "recent_history": [
                {
                    "event_type": item.event_type,
                    "title": item.title,
                    "success": item.success,
                    "created_at": item.created_at.isoformat(),
                }
                for item in self._history.recent(limit=20)
            ],
        }

    @staticmethod
    def _record_audit(
        *,
        event_type: str,
        actor: str,
        detail: dict[str, Any],
    ) -> None:
        try:
            from stock_platform.api.deps_admin import (
                AuditLogService,
            )
            from stock_platform.database.session import (
                get_session_factory,
            )

            session = get_session_factory()()
            try:
                AuditLogService(session).record(
                    event_type=event_type,
                    actor=actor,
                    detail=detail,
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        except Exception as exc:
            logger.warning(
                "notification_audit_failed",
                error=str(exc),
            )
