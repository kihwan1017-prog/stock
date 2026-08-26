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

        detail = {
            "event_type": event.event_type,
            **event.detail,
        }

        # 시장 라우팅 + ANALYSIS suppression (Telegram output only)
        try:
            from stock_platform.notification.telegram_policy import (
                evaluate_telegram_policy,
                resolve_telegram_chat_id,
            )

            decision = evaluate_telegram_policy(
                event_type=event.event_type,
                detail=detail,
            )
            detail["telegram_market"] = decision.market
            detail["telegram_category"] = decision.category
            detail["telegram_chat_route"] = decision.chat_route
            chat_id, _route = resolve_telegram_chat_id(decision.market)
            if chat_id:
                detail["telegram_chat_id"] = chat_id
            if not decision.allowed:
                logger.info(
                    "telegram_policy_suppressed",
                    event_type=event.event_type,
                    market=decision.market,
                    category=decision.category,
                    reason=decision.reason,
                )
                return None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telegram_policy_eval_failed",
                event_type=event.event_type,
                error=type(exc).__name__,
            )

        rendered = self._render_korean(event.event_type, event.title, event.message, detail)
        if rendered is not None and rendered.suppressed:
            logger.info(
                "notification_suppressed",
                event_type=event.event_type,
                reason=rendered.suppress_reason,
            )
            return None

        send_kwargs: dict[str, Any] = {
            "title": event.title,
            "message": event.message,
            "detail": detail,
        }
        if rendered is not None:
            send_kwargs.update(
                {
                    "title": rendered.title,
                    "message": rendered.body,
                    "rendered_title": rendered.title,
                    "rendered_body": rendered.body,
                    "include_raw_json": False,
                    "original_payload": rendered.original_payload,
                    "template_id": rendered.template_id,
                    "template_version": rendered.template_version,
                    "locale": rendered.locale,
                    "missing_variables": tuple(rendered.missing_variables),
                    "category": rendered.category,
                    "severity": rendered.severity,
                }
            )

        result = await self._sender.send(**send_kwargs)

        display_title = (
            rendered.title if rendered is not None else event.title
        )
        display_message = (
            rendered.body if rendered is not None else event.message
        )

        self._history.append(
            NotificationHistoryRecord(
                event_type=event.event_type,
                title=display_title,
                message=display_message,
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

        self._persist_delivery_log(
            event_type=event.event_type,
            rendered=rendered,
            result=result,
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
                    "title": display_title,
                    "template_id": (
                        rendered.template_id if rendered else None
                    ),
                    "missing_variables": (
                        list(rendered.missing_variables) if rendered else []
                    ),
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

    @staticmethod
    def _render_korean(
        event_type: str,
        title: str,
        message: str,
        detail: dict[str, Any],
    ):
        """DB/builtin 한글 템플릿 렌더. 실패 시 None → 기존 title/message."""

        try:
            from stock_platform.notification.template_cache import (
                ensure_cache_loaded,
                get_cached_template,
            )
            from stock_platform.notification.template_pipeline import (
                render_notification,
            )

            session = None
            try:
                from stock_platform.database.session import (
                    get_session_factory,
                )

                session = get_session_factory()()
                ensure_cache_loaded(session)
            except Exception:  # noqa: BLE001
                pass
            finally:
                if session is not None:
                    session.close()

            db_tpl = get_cached_template(
                event_type=event_type,
                channel="TELEGRAM",
                locale="ko-KR",
            ) or get_cached_template(
                event_type=event_type,
                channel="COMMON",
                locale="ko-KR",
            )
            return render_notification(
                event_type=event_type,
                title=title,
                message=message,
                detail=detail,
                channel="TELEGRAM",
                locale="ko-KR",
                db_template=db_tpl,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "notification_korean_render_failed",
                event_type=event_type,
                error=type(exc).__name__,
            )
            return None

    @staticmethod
    def _persist_delivery_log(
        *,
        event_type: str,
        rendered: Any,
        result: NotificationSendResult,
    ) -> None:
        """채널 전송 결과 + 원본 JSON 보존 (실패해도 전송에 영향 없음)."""

        try:
            from stock_platform.database.session import get_session_factory
            from stock_platform.notification.template_entities import (
                ChannelDeliveryLogEntity,
            )

            session = get_session_factory()()
            try:
                for item in result.results:
                    session.add(
                        ChannelDeliveryLogEntity(
                            event_type=str(event_type).upper(),
                            channel=item.channel.value,
                            recipient=None,
                            rendered_title=(
                                rendered.title if rendered else None
                            ),
                            rendered_message=(
                                rendered.body if rendered else None
                            ),
                            original_payload_json=(
                                rendered.original_payload
                                if rendered
                                else {}
                            ),
                            status=item.status.value,
                            error_message=(
                                item.message
                                if item.status.value == "FAILED"
                                else (
                                    (
                                        f"{rendered.diagnostic_code}:"
                                        f"{','.join(rendered.required_missing)}"
                                    )
                                    if rendered
                                    and getattr(
                                        rendered,
                                        "diagnostic_code",
                                        None,
                                    )
                                    else None
                                )
                            ),
                            template_id=(
                                rendered.template_id if rendered else None
                            ),
                            template_version=(
                                rendered.template_version
                                if rendered
                                else None
                            ),
                            locale=(
                                rendered.locale if rendered else "ko-KR"
                            ),
                            missing_variables_json=(
                                {
                                    "missing": list(
                                        rendered.missing_variables or []
                                    ),
                                    "required_missing": list(
                                        getattr(
                                            rendered,
                                            "required_missing",
                                            [],
                                        )
                                        or []
                                    ),
                                    "diagnostic_code": getattr(
                                        rendered,
                                        "diagnostic_code",
                                        None,
                                    ),
                                }
                                if rendered
                                else None
                            ),
                            sent_at=item.sent_at,
                        )
                    )
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "notification_delivery_log_skipped",
                error=type(exc).__name__,
            )

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
