"""STEP72 — User Preferences / Settings 계약·서비스 테스트."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids
from stock_platform.auth.preference_service import (
    DEFAULTS,
    UserPreferenceError,
    UserPreferenceService,
)


def test_user_settings_openapi() -> None:
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/user/settings" in paths
    assert "/api/v1/user/settings/reset" in paths
    assert collect_duplicate_operation_ids(app.router) == []


def test_user_settings_require_auth() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/v1/user/settings").status_code == 401
    assert client.put("/api/v1/user/settings", json={}).status_code == 401
    assert client.patch("/api/v1/user/settings", json={"theme": "dark"}).status_code == 401
    assert client.post("/api/v1/user/settings/reset").status_code == 401


def test_get_or_create_defaults() -> None:
    service = UserPreferenceService(MagicMock())
    service._repo = MagicMock()
    service._repo.get.return_value = None

    created = {}

    def _add(row):
        created.update(
            {
                "user_id": row.user_id,
                "theme": row.theme,
                "language": row.language,
            }
        )
        return row

    service._repo.add.side_effect = _add
    result = service.get_or_create(10)
    assert result["user_id"] == 10
    assert result["theme"] == DEFAULTS["theme"]
    assert result["language"] == "KO"
    assert created["theme"] == "system"


def test_patch_theme_validation() -> None:
    service = UserPreferenceService(MagicMock())
    service._repo = MagicMock()
    row = SimpleNamespace(user_id=1, **DEFAULTS, created_at=None, updated_at=None)
    service._repo.get.return_value = row
    service._assert_account_ownership = MagicMock()
    service._assert_watchlist_ownership = MagicMock()

    with pytest.raises(UserPreferenceError, match="theme"):
        service.update(1, {"theme": "neon"}, replace=False)

    result = service.update(1, {"theme": "dark"}, replace=False)
    assert result["theme"] == "dark"
    assert row.theme == "dark"


def test_patch_rejects_unknown_field() -> None:
    service = UserPreferenceService(MagicMock())
    with pytest.raises(UserPreferenceError, match="허용되지 않는"):
        service.update(1, {"ollama_host": "http://x"}, replace=False)


def test_account_ownership_denied() -> None:
    service = UserPreferenceService(MagicMock())
    service._repo = MagicMock()
    row = SimpleNamespace(user_id=1, **DEFAULTS, created_at=None, updated_at=None)
    service._repo.get.return_value = row
    foreign = SimpleNamespace(account_id=99, user_id=2)
    service._paper = MagicMock()
    service._paper.get_account.return_value = foreign

    with pytest.raises(UserPreferenceError, match="본인 소유"):
        service.update(1, {"default_account_id": 99}, replace=False)


def test_account_ownership_ok_syncs_default() -> None:
    service = UserPreferenceService(MagicMock())
    service._repo = MagicMock()
    row = SimpleNamespace(user_id=1, **DEFAULTS, created_at=None, updated_at=None)
    service._repo.get.return_value = row
    owned = SimpleNamespace(account_id=5, user_id=1)
    other = SimpleNamespace(account_id=6, user_id=1, is_default=True)
    owned.is_default = False
    service._paper = MagicMock()
    service._paper.get_account.return_value = owned
    service._paper.list_accounts.return_value = [owned, other]
    service._assert_watchlist_ownership = MagicMock()

    result = service.update(1, {"default_account_id": 5}, replace=False)
    assert result["default_account_id"] == 5
    assert owned.is_default is True
    assert other.is_default is False


def test_watchlist_ownership_denied() -> None:
    service = UserPreferenceService(MagicMock())
    service._repo = MagicMock()
    row = SimpleNamespace(user_id=1, **DEFAULTS, created_at=None, updated_at=None)
    service._repo.get.return_value = row
    service._assert_account_ownership = MagicMock()
    service._session = MagicMock()
    service._session.scalar.return_value = None

    with pytest.raises(UserPreferenceError, match="관심종목"):
        service.update(1, {"default_watchlist_id": 7}, replace=False)


def test_reset_restores_defaults() -> None:
    service = UserPreferenceService(MagicMock())
    service._repo = MagicMock()
    row = SimpleNamespace(
        user_id=3,
        theme="dark",
        language="EN",
        timezone="UTC",
        date_format="MM/DD/YYYY",
        number_format="1.234,56",
        currency="USD",
        default_market="NASDAQ",
        default_account_id=9,
        default_watchlist_id=1,
        default_dashboard="AI",
        items_per_page=50,
        ai_enabled=False,
        ai_auto_summary=False,
        ai_recommendation_enabled=False,
        notification_enabled=False,
        telegram_enabled=True,
        email_enabled=True,
        web_enabled=False,
        created_at=None,
        updated_at=None,
    )
    service._repo.get.return_value = row
    result = service.reset(3)
    assert result["theme"] == "system"
    assert result["language"] == "KO"
    assert result["default_account_id"] is None
    assert result["telegram_enabled"] is False


def test_put_replace_fills_missing_with_defaults() -> None:
    service = UserPreferenceService(MagicMock())
    service._repo = MagicMock()
    row = SimpleNamespace(user_id=1, **DEFAULTS, created_at=None, updated_at=None)
    row.theme = "dark"
    row.language = "EN"
    service._repo.get.return_value = row
    service._assert_account_ownership = MagicMock()
    service._assert_watchlist_ownership = MagicMock()

    result = service.update(1, {"theme": "light"}, replace=True)
    assert result["theme"] == "light"
    assert result["language"] == "KO"  # 미지정 → 기본값
