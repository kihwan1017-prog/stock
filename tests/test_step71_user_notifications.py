"""STEP71 — User Notification Center 계약·서비스 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids
from stock_platform.notification.inbox_service import (
    NotificationDispatcher,
    NotificationInboxService,
    UserNotificationError,
    map_event_category,
    map_severity_from_event,
)


def test_notification_openapi_registered() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/user/notifications" in paths
    assert "/api/v1/user/notifications/unread-count" in paths
    assert "/api/v1/user/notifications/subscriptions" in paths
    assert "/api/v1/user/notifications/read-all" in paths
    assert "/api/v1/user/notifications/{notification_id}" in paths
    assert "/api/v1/user/notifications/{notification_id}/read" in paths
    assert "/api/v1/user/notifications/{notification_id}/archive" in paths
    assert "/api/v1/user/notifications/{notification_id}/star" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_notification_apis_require_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/user/notifications").status_code == 401
    assert client.get("/api/v1/user/notifications/unread-count").status_code == 401
    assert client.post("/api/v1/user/notifications/read-all").status_code == 401
    assert client.get("/api/v1/user/notifications/1").status_code == 401
    assert client.post("/api/v1/user/notifications/1/read").status_code == 401
    assert client.delete("/api/v1/user/notifications/1").status_code == 401


def test_map_event_category_and_severity() -> None:
    assert map_event_category("AI_ANALYSIS_COMPLETE") == "AI_RECOMMENDATION"
    assert map_event_category("KILL_SWITCH") == "RISK"
    assert map_severity_from_event("KILL_SWITCH") == "CRITICAL"
    assert map_severity_from_event("ORDER_FILLED") == "SUCCESS"
    assert map_severity_from_event("ORDER_REJECTED") == "WARNING"
    assert map_severity_from_event("NEWS") == "INFO"


def test_get_detail_permission_denied() -> None:
    service = NotificationInboxService(MagicMock())
    service._repo = MagicMock()
    service._repo.get_owned.return_value = None
    with pytest.raises(UserNotificationError, match="찾을 수 없"):
        service.get_detail(user_id=1, notification_id=99)


def test_mark_read_archive_star_delete() -> None:
    service = NotificationInboxService(MagicMock())
    link = SimpleNamespace(
        is_read=False,
        read_at=None,
        is_archived=False,
        archived_at=None,
        is_starred=False,
        starred_at=None,
        is_deleted=False,
        deleted_at=None,
    )
    note = SimpleNamespace(notification_id=10)
    service._repo = MagicMock()
    service._repo.get_owned.return_value = (link, note)

    assert service.mark_read(1, 10, read=True)["is_read"] is True
    assert link.is_read is True
    assert link.read_at is not None

    assert service.mark_archived(1, 10, archived=True)["is_archived"] is True
    assert service.mark_starred(1, 10, starred=True)["is_starred"] is True
    assert service.soft_delete(1, 10)["is_deleted"] is True
    assert link.is_deleted is True
    assert service._repo.commit.call_count == 4


def test_read_all_updates_unread() -> None:
    service = NotificationInboxService(MagicMock())
    links = [
        SimpleNamespace(is_read=False, read_at=None),
        SimpleNamespace(is_read=False, read_at=None),
    ]
    service._repo = MagicMock()
    service._repo.list_unread_links.return_value = links
    result = service.read_all(7)
    assert result["updated_count"] == 2
    assert all(link.is_read for link in links)


def test_unread_count() -> None:
    service = NotificationInboxService(MagicMock())
    service._repo = MagicMock()
    service._repo.unread_count.return_value = 3
    assert service.unread_count(1) == {"unread_count": 3, "total": 3}


def test_list_subscriptions_defaults() -> None:
    service = NotificationInboxService(MagicMock())
    service._repo = MagicMock()
    service._repo.list_subscriptions.return_value = []
    items = service.list_subscriptions(1)["items"]
    assert any(row["event_type"] == "NEWS" for row in items)
    news = next(row for row in items if row["event_type"] == "NEWS")
    assert news["enabled"] is True
    assert news["web_enabled"] is True
    assert news["telegram_enabled"] is False


def test_dispatcher_skips_ops_without_user() -> None:
    dispatcher = NotificationDispatcher(MagicMock())
    dispatcher._inbox = MagicMock()
    result = dispatcher.dispatch_published(
        event_type="SCHEDULER_ERROR",
        title="job failed",
        message="x",
        detail={"job": "x"},
    )
    assert result is None
    dispatcher._inbox.dispatch_to_users.assert_not_called()


def test_dispatcher_routes_user_event() -> None:
    dispatcher = NotificationDispatcher(MagicMock())
    dispatcher._inbox = MagicMock()
    dispatcher._inbox.dispatch_to_users.return_value = {
        "notification_id": 1,
        "delivered_count": 1,
    }
    result = dispatcher.dispatch_published(
        event_type="AI_ANALYSIS_COMPLETE",
        title="추천 완료",
        message="ok",
        detail={"user_id": 42, "severity": "SUCCESS", "dedupe_key": "k1"},
    )
    assert result is not None
    kwargs = dispatcher._inbox.dispatch_to_users.call_args.kwargs
    assert kwargs["user_ids"] == [42]
    assert kwargs["dedupe_key"] == "k1"
    assert "user_id" not in kwargs["payload"]


def test_dispatch_to_users_respects_web_subscription() -> None:
    service = NotificationInboxService(MagicMock())
    service._repo = MagicMock()
    note = SimpleNamespace(notification_id=5)
    service._repo.find_by_dedupe.return_value = None
    service._repo.add_notification.side_effect = (
        lambda row: setattr(row, "notification_id", 5) or row
    )
    service._repo.user_link_exists.return_value = False
    # 웹 구독 OFF
    service._repo.get_subscription.return_value = SimpleNamespace(
        enabled=True,
        web_enabled=False,
        telegram_enabled=False,
    )
    result = service.dispatch_to_users(
        user_ids=[1],
        event_type="NEWS",
        title="t",
        message="m",
    )
    assert result["delivered_count"] == 0
    assert result["skipped_count"] == 1
    service._repo.add_user_notification.assert_not_called()


def test_dispatch_to_users_queues_telegram_when_enabled() -> None:
    service = NotificationInboxService(MagicMock())
    service._repo = MagicMock()
    service._repo.find_by_dedupe.return_value = None

    def _add_note(row):
        row.notification_id = 9
        return row

    service._repo.add_notification.side_effect = _add_note
    service._repo.user_link_exists.return_value = False
    service._repo.get_subscription.return_value = SimpleNamespace(
        enabled=True,
        web_enabled=True,
        telegram_enabled=True,
    )
    captured = {}

    def _add_link(row):
        captured["delivery_status"] = row.delivery_status
        return row

    service._repo.add_user_notification.side_effect = _add_link
    result = service.dispatch_to_users(
        user_ids=[3],
        event_type="ORDER_FILLED",
        title="체결",
        message="ok",
    )
    assert result["delivered_count"] == 1
    assert result["telegram_queued_count"] == 1
    assert captured["delivery_status"] == "TELEGRAM_QUEUED"


def test_item_dict_strips_secrets() -> None:
    link = SimpleNamespace(
        user_notification_id=1,
        is_read=False,
        is_archived=False,
        is_starred=False,
        read_at=None,
        delivery_status="WEB_DELIVERED",
    )
    note = SimpleNamespace(
        notification_id=1,
        event_type="SYSTEM",
        title="t",
        message="m",
        severity="INFO",
        created_at=datetime.now(timezone.utc),
        expires_at=None,
        payload_json={"token": "secret", "symbol": "005930"},
    )
    payload = NotificationInboxService._item_dict(
        link, note, include_payload=True
    )
    assert "token" not in payload["payload"]
    assert payload["payload"]["symbol"] == "005930"
