"""STEP59 RC1 — 운영 준비 최소 보안/설정 스모크."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def _clear_settings_cache() -> None:
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()


def _patch_lifecycle(monkeypatch) -> None:
    monkeypatch.setattr(
        "stock_platform.api.lifecycle.application_lifecycle.startup",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "stock_platform.api.lifecycle.application_lifecycle.shutdown",
        AsyncMock(),
    )


def test_production_hides_openapi_docs(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "unit-test-jwt-secret-32chars!!")
    monkeypatch.setenv("ADMIN_API_KEY", "unit-test-admin-key")
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        "https://admin.example.com",
    )
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "stock_platform")
    monkeypatch.setenv("DB_USER", "stock_app")
    monkeypatch.setenv("DB_PASSWORD", "change-me")
    _clear_settings_cache()
    _patch_lifecycle(monkeypatch)

    from stock_platform.api.main import create_app

    application = create_app()
    assert application.docs_url is None
    assert application.openapi_url is None

    with TestClient(application) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404

    _clear_settings_cache()


def test_production_signup_forbidden(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "unit-test-jwt-secret-32chars!!")
    monkeypatch.setenv("ADMIN_API_KEY", "unit-test-admin-key")
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        "https://admin.example.com",
    )
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "stock_platform")
    monkeypatch.setenv("DB_USER", "stock_app")
    monkeypatch.setenv("DB_PASSWORD", "change-me")
    _clear_settings_cache()
    _patch_lifecycle(monkeypatch)

    from stock_platform.api.main import create_app

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/v1/auth/signup",
            json={
                "name": "RC User",
                "username": "rcuser",
                "email": "rc@example.com",
                "password": "Password1!",
                "password_confirm": "Password1!",
                "terms_accepted": True,
            },
        )
    assert response.status_code == 403
    body = response.json()
    assert body.get("code") == "HTTP_403"
    _clear_settings_cache()


def test_broker_orders_require_admin(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("JWT_DEV_AUTO_SECRET", "true")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "stock_platform")
    monkeypatch.setenv("DB_USER", "stock_app")
    monkeypatch.setenv("DB_PASSWORD", "change-me")
    _clear_settings_cache()
    _patch_lifecycle(monkeypatch)

    from stock_platform.api.main import create_app

    with TestClient(create_app()) as client:
        response = client.post("/api/v1/broker/live-approval")
    assert response.status_code in {401, 403}
    _clear_settings_cache()
