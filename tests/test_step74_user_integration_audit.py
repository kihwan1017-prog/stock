"""STEP74 — 사용자 API 권한·소유권·경계 스모크 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.notification.inbox_service import NotificationInboxService


def test_admin_settings_and_ollama_require_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/settings").status_code == 401
    assert client.put("/api/v1/settings", json={"items": []}).status_code == 401
    assert client.get("/api/v1/ollama/status").status_code == 401
    assert client.get("/api/v1/ollama/models").status_code == 401


def test_user_self_apis_require_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    paths = [
        "/api/v1/user/accounts",
        "/api/v1/user/watchlist",
        "/api/v1/user/news",
        "/api/v1/user/disclosures",
        "/api/v1/user/ai/status",
        "/api/v1/user/notifications",
        "/api/v1/user/settings",
        "/api/v1/user/profile",
        "/api/v1/user/profile/sessions",
        "/api/v1/user/profile/connections",
    ]
    for path in paths:
        assert client.get(path).status_code == 401, path


def test_quiet_time_window_same_day() -> None:
    now = datetime(2026, 7, 21, 14, 30, tzinfo=timezone(timedelta(hours=9)))
    assert (
        NotificationInboxService._in_quiet_time("14:00", "15:00", now=now)
        is True
    )
    assert (
        NotificationInboxService._in_quiet_time("15:00", "16:00", now=now)
        is False
    )


def test_quiet_time_window_overnight() -> None:
    late = datetime(2026, 7, 21, 23, 0, tzinfo=timezone(timedelta(hours=9)))
    early = datetime(2026, 7, 22, 6, 0, tzinfo=timezone(timedelta(hours=9)))
    noon = datetime(2026, 7, 22, 12, 0, tzinfo=timezone(timedelta(hours=9)))
    assert (
        NotificationInboxService._in_quiet_time("22:00", "07:00", now=late)
        is True
    )
    assert (
        NotificationInboxService._in_quiet_time("22:00", "07:00", now=early)
        is True
    )
    assert (
        NotificationInboxService._in_quiet_time("22:00", "07:00", now=noon)
        is False
    )


def test_telegram_suppressed_in_quiet_time_non_critical() -> None:
    service = NotificationInboxService(MagicMock())
    service._repo = MagicMock()
    service._repo.get_subscription.return_value = SimpleNamespace(
        enabled=True,
        web_enabled=True,
        telegram_enabled=True,
        quiet_time_start="00:00",
        quiet_time_end="23:59",
    )
    # 거의 항상 quiet
    assert service._is_subscribed(1, "NEWS", channel="web") is True
    assert service._is_subscribed(1, "NEWS", channel="telegram") is False
    # CRITICAL 예외
    assert (
        service._is_subscribed(1, "KILL_SWITCH", channel="telegram") is True
    )
