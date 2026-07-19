"""STEP52 — DEV_OPEN 제거 · ensure_admin_api_key."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from stock_platform.api.deps_admin import require_admin
from stock_platform.common.settings import Settings, get_settings


def test_require_admin_rejects_when_key_empty(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "")
    monkeypatch.setenv("APP_ENV", "local")
    get_settings.cache_clear()
    try:
        with pytest.raises(HTTPException) as exc:
            require_admin(x_admin_api_key=None)
        assert exc.value.status_code == 401
        assert "DEV_OPEN" not in str(exc.value.detail)
    finally:
        get_settings.cache_clear()


def test_ensure_admin_api_key_required_in_production() -> None:
    settings = Settings(
        app_env="production",
        admin_api_key="",
        jwt_secret="test-secret-at-least-32-chars-long!!",
    )
    with pytest.raises(ValueError, match="ADMIN_API_KEY"):
        settings.ensure_admin_api_key()


def test_ensure_admin_api_key_optional_in_local() -> None:
    settings = Settings(
        app_env="local",
        admin_api_key="",
        jwt_secret="test-secret-at-least-32-chars-long!!",
    )
    settings.ensure_admin_api_key()  # no raise
