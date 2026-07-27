"""STEP62 — Security hardening smoke tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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


# Critical 무인증 mutate 차단 매트릭스 (P0 보안 게이트)
_CRITICAL_UNAUTH_MUTATE_PATHS: list[tuple[str, dict | None]] = [
    ("/api/v1/paper-executions/fills", {
        "account_id": 1,
        "order_id": 1,
        "fill_quantity": "1",
        "fill_price": "1000",
    }),
    ("/api/v1/realtime-execution/start", None),
    ("/api/v1/sync/kiwoom/daily", {
        "symbol": "005930",
        "start_date": "2024-01-01",
        "end_date": "2024-01-02",
    }),
    ("/api/v1/pipelines/daily-strategy", {}),
    ("/api/v1/guarded-pipelines/daily-strategy", {}),
    ("/api/v1/upbit/instruments/sync", None),
    ("/api/v1/dart/sync", {
        "start_date": "2024-01-01",
        "end_date": "2024-01-02",
    }),
    ("/api/v1/news/sync", {
        "exchange_code": "KRX",
        "symbol": "005930",
        "query": "삼성",
    }),
    ("/api/v1/backtests/moving-average", {
        "exchange_code": "KRX",
        "symbol": "005930",
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "initial_capital": "1000000",
    }),
    ("/api/v1/strategy-runtime-switch", {
        "target_deployment_id": 1,
        "requested_by": "security-test",
    }),
    ("/api/v1/ai-analysis/KRX", {"symbol": "005930"}),
    ("/api/v1/strategy-policy/evaluate", {
        "market_code": "KRX",
        "requested_by": "security-test",
    }),
    ("/api/v1/broker/live-transition/validate", {
        "max_order_amount": "1000000",
        "max_daily_loss": "100000",
        "paper_validation_approved": False,
    }),
]


def test_unauthenticated_order_mutate_rejected(monkeypatch) -> None:
    # 실 DB 없이 인증 거부만 검증
    def _fake_db():
        yield MagicMock()

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
    from stock_platform.database.session import get_db_session

    app.dependency_overrides[get_db_session] = _fake_db

    with TestClient(app) as client:
        for path, body in _CRITICAL_UNAUTH_MUTATE_PATHS:
            if body is None:
                response = client.post(path)
            else:
                response = client.post(path, json=body)
            assert response.status_code in {401, 403}, (
                f"{path} expected 401/403, got {response.status_code}"
            )
        # Kill Switch 조회도 로그인 필요 (미인증 401)
        assert client.get(
            "/api/v1/risk/kill-switch"
        ).status_code in {401, 403}
        assert client.get("/api/v1/jobs").status_code in {
            401,
            403,
        }
        # deprecated step32 paper fill 우회 경로 — 라우터 언마운트 → 404
        assert client.post(
            "/api/v1/positions/executions",
            json={
                "account_id": 1,
                "market": "KRX",
                "symbol": "005930",
                "side": "BUY",
                "quantity": "1",
                "price": "1000",
            },
        ).status_code == 404
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


def test_telegram_webhook_rejects_when_secret_empty(
    monkeypatch,
) -> None:
    """KI-SEC-15 — Secret 미설정 시 Fail Closed."""

    app = _app(
        monkeypatch,
        APP_ENV="local",
        JWT_DEV_AUTO_SECRET="true",
        DB_HOST="localhost",
        DB_NAME="stock_platform",
        DB_USER="stock_app",
        DB_PASSWORD="change-me",
        TELEGRAM_WEBHOOK_SECRET="",
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
        body = denied.json()
        assert body.get("ok") is False
        assert body.get("error") == "webhook_secret_required"
    _clear_settings_cache()


def test_telegram_webhook_accepts_valid_secret(monkeypatch) -> None:
    app = _app(
        monkeypatch,
        APP_ENV="local",
        JWT_DEV_AUTO_SECRET="true",
        DB_HOST="localhost",
        DB_NAME="stock_platform",
        DB_USER="stock_app",
        DB_PASSWORD="change-me",
        TELEGRAM_WEBHOOK_SECRET="valid-webhook-secret-value",
    )
    with TestClient(app) as client:
        ok = client.post(
            "/api/v1/telegram/webhook",
            headers={
                "X-Telegram-Bot-Api-Secret-Token": (
                    "valid-webhook-secret-value"
                )
            },
            json={
                "update_id": 2,
                "message": {"text": "hi", "chat": {"id": 1}},
            },
        )
        assert ok.status_code == 200
        body = ok.json()
        assert body.get("ok") is True
        assert "valid-webhook-secret-value" not in str(body)
    _clear_settings_cache()
