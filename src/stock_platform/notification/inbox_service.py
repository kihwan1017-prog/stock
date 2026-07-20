"""Notification Center 서비스·Dispatcher — STEP71.

흐름: Event → Dispatcher → Inbox(user_notification) → (구독 시) Telegram/Web
직접 Telegram 호출을 우회하지 않고 Inbox를 경유한다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from stock_platform.notification.inbox_models import (
    Notification,
    NotificationSubscription,
    UserNotification,
)
from stock_platform.notification.inbox_repository import (
    NotificationInboxRepository,
)


logger = logging.getLogger(__name__)

# 사용자 인박스에 노출하는 이벤트 카테고리 (구독 기본값)
DEFAULT_EVENT_TYPES: tuple[str, ...] = (
    "SYSTEM",
    "NEWS",
    "DISCLOSURE",
    "AI_RECOMMENDATION",
    "TRADE",
    "ORDER",
    "EXECUTION",
    "PORTFOLIO",
    "RISK",
    "TELEGRAM",
    "MARKET",
    "SCHEDULER",
    # 기존 ops 이벤트도 매핑 가능
    "KILL_SWITCH",
    "DAILY_LOSS",
    "STOP_LOSS",
    "TAKE_PROFIT",
    "ORDER_FILLED",
    "ORDER_REJECTED",
    "AI_ANALYSIS_COMPLETE",
    "SCHEDULER_ERROR",
)

SEVERITIES = {"INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}

# ops 이벤트 → 사용자 카테고리
EVENT_CATEGORY_MAP: dict[str, str] = {
    "SYSTEM_START": "SYSTEM",
    "SYSTEM_STOP": "SYSTEM",
    "ORDER_SUBMITTED": "ORDER",
    "ORDER_FILLED": "EXECUTION",
    "ORDER_REJECTED": "ORDER",
    "STOP_LOSS": "RISK",
    "TAKE_PROFIT": "TRADE",
    "TRAILING_STOP": "RISK",
    "RELATIVE_LOSS": "RISK",
    "KILL_SWITCH": "RISK",
    "DAILY_LOSS": "RISK",
    "AI_ANALYSIS_COMPLETE": "AI_RECOMMENDATION",
    "AI_TIMEOUT": "AI_RECOMMENDATION",
    "BACKTEST_COMPLETE": "SYSTEM",
    "BROKER_DISCONNECTED": "SYSTEM",
    "BROKER_RECONNECTED": "SYSTEM",
    "DATABASE_ERROR": "SYSTEM",
    "SCHEDULER_ERROR": "SCHEDULER",
    "TELEGRAM_FAILURE": "TELEGRAM",
    "MONITORING_ALERT": "SYSTEM",
}


class UserNotificationError(ValueError):
    pass


def map_event_category(event_type: str) -> str:
    upper = (event_type or "SYSTEM").upper()
    return EVENT_CATEGORY_MAP.get(upper, upper)


def map_severity_from_event(event_type: str) -> str:
    upper = (event_type or "").upper()
    if upper in {
        "KILL_SWITCH",
        "DAILY_LOSS",
        "DATABASE_ERROR",
        "BROKER_DISCONNECTED",
        "SCHEDULER_ERROR",
    }:
        return "CRITICAL"
    if upper in {
        "STOP_LOSS",
        "ORDER_REJECTED",
        "AI_TIMEOUT",
        "TELEGRAM_FAILURE",
        "MONITORING_ALERT",
        "TRAILING_STOP",
        "RELATIVE_LOSS",
    }:
        return "WARNING"
    if upper in {"TAKE_PROFIT", "ORDER_FILLED", "AI_ANALYSIS_COMPLETE"}:
        return "SUCCESS"
    return "INFO"


class NotificationInboxService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = NotificationInboxRepository(session)

    def list_notifications(
        self,
        user_id: int,
        *,
        event_type: str | None = None,
        severity: str | None = None,
        unread_only: bool = False,
        archived: bool | None = False,
        starred: bool | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size
        rows = self._repo.list_for_user(
            user_id=user_id,
            limit=page_size,
            offset=offset,
            event_type=event_type,
            severity=severity,
            unread_only=unread_only,
            archived=archived,
            starred=starred,
            keyword=keyword,
        )
        total = self._repo.count_for_user(
            user_id=user_id,
            event_type=event_type,
            severity=severity,
            unread_only=unread_only,
            archived=archived,
            starred=starred,
            keyword=keyword,
        )
        items = [
            self._item_dict(link, note) for link, note in rows
        ]
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total_count": total,
            "has_next": offset + page_size < total,
        }

    def get_detail(
        self, user_id: int, notification_id: int
    ) -> dict[str, Any]:
        owned = self._repo.get_owned(
            user_id=user_id, notification_id=notification_id
        )
        if owned is None:
            raise UserNotificationError("알림을 찾을 수 없습니다.")
        return self._item_dict(owned[0], owned[1], include_payload=True)

    def unread_count(self, user_id: int) -> dict[str, Any]:
        count = self._repo.unread_count(user_id)
        return {"unread_count": count, "total": count}

    def mark_read(
        self, user_id: int, notification_id: int, *, read: bool = True
    ) -> dict[str, Any]:
        owned = self._repo.get_owned(
            user_id=user_id, notification_id=notification_id
        )
        if owned is None:
            raise UserNotificationError("알림을 찾을 수 없습니다.")
        link = owned[0]
        link.is_read = read
        link.read_at = datetime.now(timezone.utc) if read else None
        self._repo.commit()
        return {
            "notification_id": notification_id,
            "is_read": link.is_read,
            "read_at": link.read_at,
        }

    def read_all(self, user_id: int) -> dict[str, Any]:
        updated = 0
        for link in self._repo.list_unread_links(user_id=user_id):
            link.is_read = True
            link.read_at = datetime.now(timezone.utc)
            updated += 1
        self._repo.commit()
        return {"updated_count": updated}

    def mark_archived(
        self, user_id: int, notification_id: int, *, archived: bool
    ) -> dict[str, Any]:
        owned = self._repo.get_owned(
            user_id=user_id, notification_id=notification_id
        )
        if owned is None:
            raise UserNotificationError("알림을 찾을 수 없습니다.")
        link = owned[0]
        link.is_archived = archived
        link.archived_at = (
            datetime.now(timezone.utc) if archived else None
        )
        self._repo.commit()
        return {
            "notification_id": notification_id,
            "is_archived": link.is_archived,
        }

    def mark_starred(
        self, user_id: int, notification_id: int, *, starred: bool
    ) -> dict[str, Any]:
        owned = self._repo.get_owned(
            user_id=user_id, notification_id=notification_id
        )
        if owned is None:
            raise UserNotificationError("알림을 찾을 수 없습니다.")
        link = owned[0]
        link.is_starred = starred
        link.starred_at = datetime.now(timezone.utc) if starred else None
        self._repo.commit()
        return {
            "notification_id": notification_id,
            "is_starred": link.is_starred,
        }

    def soft_delete(self, user_id: int, notification_id: int) -> dict[str, Any]:
        owned = self._repo.get_owned(
            user_id=user_id, notification_id=notification_id
        )
        if owned is None:
            raise UserNotificationError("알림을 찾을 수 없습니다.")
        link = owned[0]
        link.is_deleted = True
        link.deleted_at = datetime.now(timezone.utc)
        self._repo.commit()
        return {"notification_id": notification_id, "is_deleted": True}

    def list_subscriptions(self, user_id: int) -> dict[str, Any]:
        existing = {
            row.event_type: row for row in self._repo.list_subscriptions(user_id)
        }
        items = []
        for event_type in DEFAULT_EVENT_TYPES:
            row = existing.get(event_type)
            items.append(
                {
                    "event_type": event_type,
                    "enabled": True if row is None else bool(row.enabled),
                    "telegram_enabled": (
                        False if row is None else bool(row.telegram_enabled)
                    ),
                    "web_enabled": True if row is None else bool(row.web_enabled),
                    "email_enabled": (
                        False if row is None else bool(row.email_enabled)
                    ),
                    "quiet_time_start": (
                        None if row is None else row.quiet_time_start
                    ),
                    "quiet_time_end": None if row is None else row.quiet_time_end,
                }
            )
        return {"items": items}

    def update_subscription(
        self,
        user_id: int,
        *,
        event_type: str,
        enabled: bool = True,
        telegram_enabled: bool = False,
        web_enabled: bool = True,
        email_enabled: bool = False,
        quiet_time_start: str | None = None,
        quiet_time_end: str | None = None,
    ) -> dict[str, Any]:
        event = event_type.strip().upper()
        row = NotificationSubscription(
            user_id=user_id,
            event_type=event,
            enabled=enabled,
            telegram_enabled=telegram_enabled,
            web_enabled=web_enabled,
            email_enabled=email_enabled,
            quiet_time_start=quiet_time_start,
            quiet_time_end=quiet_time_end,
        )
        saved = self._repo.upsert_subscription(row)
        logger.info(
            "notification_subscription_updated user_id=%s event_type=%s "
            "enabled=%s",
            user_id,
            event,
            enabled,
        )
        return {
            "event_type": saved.event_type,
            "enabled": saved.enabled,
            "telegram_enabled": saved.telegram_enabled,
            "web_enabled": saved.web_enabled,
            "email_enabled": saved.email_enabled,
            "quiet_time_start": saved.quiet_time_start,
            "quiet_time_end": saved.quiet_time_end,
        }

    def _is_subscribed(
        self, user_id: int, event_type: str, *, channel: str = "web"
    ) -> bool:
        category = map_event_category(event_type)
        # 구체 타입과 카테고리 둘 다 확인
        for key in {event_type.upper(), category}:
            row = self._repo.get_subscription(user_id=user_id, event_type=key)
            if row is None:
                continue
            if not row.enabled:
                return False
            if channel == "web" and not row.web_enabled:
                return False
            if channel == "telegram" and not row.telegram_enabled:
                return False
            # Quiet Time: Telegram push만 억제 (CRITICAL 제외). Web Inbox는 유지.
            if (
                channel == "telegram"
                and self._in_quiet_time(
                    getattr(row, "quiet_time_start", None),
                    getattr(row, "quiet_time_end", None),
                )
                and map_severity_from_event(event_type) != "CRITICAL"
            ):
                return False
            return True
        # 구독 행 없으면 웹 기본 허용, 텔레그램 기본 거부
        return channel == "web"

    @staticmethod
    def _in_quiet_time(
        start: str | None, end: str | None, *, now: datetime | None = None
    ) -> bool:
        """HH:MM quiet window. start>end 이면 자정 넘어가는 구간."""

        if not start or not end:
            return False
        try:
            start_h, start_m = (int(x) for x in start.split(":", 1))
            end_h, end_m = (int(x) for x in end.split(":", 1))
        except (TypeError, ValueError):
            return False
        current = now or datetime.now(timezone.utc)
        # Asia/Seoul(UTC+9) 고정 오프셋 — 외부 tzdb 의존 없음
        from datetime import timedelta

        kst = current.astimezone(timezone(timedelta(hours=9)))
        minutes = kst.hour * 60 + kst.minute
        start_min = start_h * 60 + start_m
        end_min = end_h * 60 + end_m
        if start_min == end_min:
            return False
        if start_min < end_min:
            return start_min <= minutes < end_min
        # 예: 22:00 ~ 07:00
        return minutes >= start_min or minutes < end_min

    def dispatch_to_users(
        self,
        *,
        user_ids: Iterable[int],
        event_type: str,
        title: str,
        message: str,
        severity: str | None = None,
        payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        created_by: int | None = None,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Inbox 생성 후 구독 사용자에게 연결. Telegram은 구독 시 플래그만 기록."""

        event = event_type.strip().upper()
        sev = (severity or map_severity_from_event(event)).upper()
        if sev not in SEVERITIES:
            sev = "INFO"

        if dedupe_key:
            existing = self._repo.find_by_dedupe(dedupe_key)
            if existing is not None:
                note = existing
            else:
                note = Notification(
                    event_type=event,
                    title=title[:300],
                    message=message,
                    payload_json=payload or {},
                    severity=sev,
                    dedupe_key=dedupe_key,
                    created_by=created_by,
                    expires_at=expires_at,
                )
                self._repo.add_notification(note)
        else:
            note = Notification(
                event_type=event,
                title=title[:300],
                message=message,
                payload_json=payload or {},
                severity=sev,
                created_by=created_by,
                expires_at=expires_at,
            )
            self._repo.add_notification(note)

        delivered = 0
        skipped = 0
        telegram_requested = 0
        unique_ids = sorted({int(uid) for uid in user_ids if uid})
        for uid in unique_ids:
            if not self._is_subscribed(uid, event, channel="web"):
                skipped += 1
                continue
            if self._repo.user_link_exists(
                user_id=uid, notification_id=int(note.notification_id)
            ):
                skipped += 1
                continue
            delivery = "WEB_DELIVERED"
            if self._is_subscribed(uid, event, channel="telegram"):
                delivery = "TELEGRAM_QUEUED"
                telegram_requested += 1
            self._repo.add_user_notification(
                UserNotification(
                    user_id=uid,
                    notification_id=int(note.notification_id),
                    delivery_status=delivery,
                )
            )
            delivered += 1

        self._repo.commit()
        logger.info(
            "notification_dispatched notification_id=%s event=%s "
            "delivered=%s skipped=%s telegram_queued=%s",
            note.notification_id,
            event,
            delivered,
            skipped,
            telegram_requested,
        )
        return {
            "notification_id": note.notification_id,
            "delivered_count": delivered,
            "skipped_count": skipped,
            "telegram_queued_count": telegram_requested,
            "event_type": event,
        }

    @staticmethod
    def _item_dict(
        link: UserNotification,
        note: Notification,
        *,
        include_payload: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "notification_id": note.notification_id,
            "user_notification_id": link.user_notification_id,
            "event_type": note.event_type,
            "category": map_event_category(note.event_type),
            "title": note.title,
            "message": note.message,
            "severity": note.severity,
            "created_at": note.created_at,
            "expires_at": note.expires_at,
            "is_read": link.is_read,
            "is_archived": link.is_archived,
            "is_starred": link.is_starred,
            "read_at": link.read_at,
            "delivery_status": link.delivery_status,
        }
        if include_payload:
            # Secret 없는 페이로드만 노출
            safe = dict(note.payload_json or {})
            for key in list(safe.keys()):
                lower = key.lower()
                if any(
                    token in lower
                    for token in (
                        "secret",
                        "token",
                        "password",
                        "api_key",
                        "authorization",
                    )
                ):
                    safe.pop(key, None)
            payload["payload"] = safe
        return payload


class NotificationDispatcher:
    """Publisher 이벤트를 Inbox로 전달."""

    def __init__(self, session: Session) -> None:
        self._inbox = NotificationInboxService(session)

    def dispatch_published(
        self,
        *,
        event_type: str,
        title: str,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        payload = detail or {}
        user_ids: list[int] = []
        if payload.get("user_id") is not None:
            user_ids.append(int(payload["user_id"]))
        raw_ids = payload.get("user_ids") or payload.get("notify_user_ids")
        if isinstance(raw_ids, (list, tuple)):
            user_ids.extend(int(x) for x in raw_ids if x is not None)
        user_ids = sorted(set(user_ids))
        if not user_ids:
            # 운영 전용 이벤트 — Inbox 생략 (기존 Telegram 경로 유지)
            return None
        dedupe = payload.get("dedupe_key")
        if isinstance(dedupe, str):
            dedupe_key = dedupe
        else:
            dedupe_key = None
        return self._inbox.dispatch_to_users(
            user_ids=user_ids,
            event_type=event_type,
            title=title,
            message=message,
            severity=payload.get("severity"),
            payload={
                k: v
                for k, v in payload.items()
                if k
                not in {
                    "user_id",
                    "user_ids",
                    "notify_user_ids",
                    "dedupe_key",
                }
            },
            dedupe_key=dedupe_key,
        )
