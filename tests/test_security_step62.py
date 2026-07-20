"""STEP62 — Security hardening smoke tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from stock_platform.common.rate_limit import rate_limiter
from stock_platform.common.security_mask import (
    mask_account_number,
    mask_email,
    redact_mapping,
)


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


def _app(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _clear_settings_cache()
    _patch_lifecycle(monkeypatch)
    from stock_platform.api.main import create_app

    return create_app()


def test_unauthenticated_order_mutate_rejected(monkeypatch) -> None:
    app = _app(
        monkeypatch,
        APP_ENV="local",
        JWT_DEV_AUTO_SECRET="true",
        DB_HOST="localhost",
        DB_NAME="stock_platform",
        DB_USER="stock_app",
        DB_PASSWORD="change-me",
        ADMIN_API_KEY="step62-key",
    )
    with TestClient(app) as client:
        assert client.post(
            "/api/v1/paper-executions/fills",
            json={
                "account_id": 1,
                "order_id": 1,
                "fill_quantity": "1",
                "fill_price": "1000",
            },
        ).status_code in {401, 403}
        assert client.post(
            "/api/v1/realtime-execution/start"
        ).status_code in {401, 403}
        assert client.get(
            "/api/v1/risk/kill-switch"
        ).status_code in {401, 403}
        assert client.get("/api/v1/jobs").status_code in {
            401,
            403,
        }
    _clear_settings_cache()


def test_security_headers_present(monkeypatch) -> None:
    app = _app(
        monkeypatch,
        APP_ENV="local",
        JWT_DEV_AUTO_SECRET="true",
        DB_HOST="localhost",
        DB_NAME="stock_platform",
        DB_USER="stock_app",
        DB_PASSWORD="change-me",
    )
    with TestClient(app) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
    _clear_settings_cache()


def test_login_rate_limit() -> None:
    rate_limiter.clear()
    for _ in range(20):
        rate_limiter.check("auth_login:test-ip", limit=20, window_seconds=60)
    try:
        rate_limiter.check("auth_login:test-ip", limit=20, window_seconds=60)
        raised = False
    except Exception as exc:
        raised = True
        from fastapi import HTTPException

        assert isinstance(exc, HTTPException)
        assert exc.status_code == 429
    assert raised
    rate_limiter.clear()


def test_masking_helpers() -> None:
    assert mask_account_number("1234567890").startswith("12")
    assert "***" in mask_account_number("1234567890")
    assert "@" in mask_email("admin@example.com")
    redacted = redact_mapping(
        {"password": "secret", "nested": {"api_key": "abc"}}
    )
    assert redacted["password"] != "secret"
    assert redacted["nested"]["api_key"] != "abc"


def test_telegram_webhook_secret_required_when_configured(
    monkeypatch,
) -> None:
    app = _app(
        monkeypatch,
        APP_ENV="local",
        JWT_DEV_AUTO_SECRET="true",
        DB_HOST="localhost",
        DB_NAME="stock_platform",
        DB_USER="stock_app",
        DB_PASSWORD="change-me",
        TELEGRAM_WEBHOOK_SECRET="webhook-secret",
    )
    with TestClient(app) as client:
        denied = client.post(
            "/api/v1/telegram/webhook",
            json={
                "update_id": 1,
                "message": {
                    "text": "/status",
                    "chat": {"id": 1},
                },
            },
        )
        assert denied.status_code == 200
        assert denied.json().get("ok") is False
    _clear_settings_cache()
