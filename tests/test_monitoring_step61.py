"""STEP61 — Health live/ready + monitoring overview 스모크."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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


def test_health_live_ready(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("JWT_DEV_AUTO_SECRET", "true")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "stock_platform")
    monkeypatch.setenv("DB_USER", "stock_app")
    monkeypatch.setenv("DB_PASSWORD", "change-me")
    _clear_settings_cache()
    _patch_lifecycle(monkeypatch)

    monkeypatch.setattr(
        "stock_platform.api.v1.health.measure_db_latency_ms",
        lambda: ("UP", 1.2, None),
    )

    from stock_platform.api.main import create_app

    with TestClient(create_app()) as client:
        live = client.get("/health/live")
        assert live.status_code == 200
        assert live.json()["status"] == "UP"
        assert live.json()["check"] == "live"

        ready = client.get("/health/ready")
        assert ready.status_code == 200
        body = ready.json()
        assert body["status"] == "UP"
        assert body["check"] == "ready"

        version = client.get("/version")
        assert version.status_code == 200
        assert "version" in version.json()
        assert "uptime_seconds" in version.json()

    _clear_settings_cache()


def test_health_ready_returns_503_when_db_down(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("JWT_DEV_AUTO_SECRET", "true")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "stock_platform")
    monkeypatch.setenv("DB_USER", "stock_app")
    monkeypatch.setenv("DB_PASSWORD", "change-me")
    _clear_settings_cache()
    _patch_lifecycle(monkeypatch)

    monkeypatch.setattr(
        "stock_platform.api.v1.health.measure_db_latency_ms",
        lambda: ("DOWN", 5.0, "connection refused"),
    )

    from stock_platform.api.main import create_app

    with TestClient(create_app()) as client:
        ready = client.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json()["status"] == "DOWN"

    _clear_settings_cache()


def test_monitoring_overview_requires_admin(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("JWT_DEV_AUTO_SECRET", "true")
    monkeypatch.setenv("ADMIN_API_KEY", "step61-admin-key")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "stock_platform")
    monkeypatch.setenv("DB_USER", "stock_app")
    monkeypatch.setenv("DB_PASSWORD", "change-me")
    _clear_settings_cache()
    _patch_lifecycle(monkeypatch)

    from stock_platform.api.main import create_app

    with TestClient(create_app()) as client:
        denied = client.get("/api/v1/monitoring/overview")
        assert denied.status_code in {401, 403}

        monkeypatch.setattr(
            "stock_platform.api.v1.monitoring.build_monitoring_overview",
            AsyncMock(
                return_value={
                    "status": "UP",
                    "system": {"version": "1.0.0"},
                    "alerts": {"fired_now": []},
                }
            ),
        )
        ok = client.get(
            "/api/v1/monitoring/overview",
            headers={"X-Admin-API-Key": "step61-admin-key"},
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "UP"

    _clear_settings_cache()


def test_evaluate_alert_db_down_writes_rule(monkeypatch) -> None:
    from stock_platform.operation.monitoring_snapshot import (
        evaluate_alert_rules,
    )
    from stock_platform.common.ttl_cache import process_ttl_cache

    process_ttl_cache.clear()
    session = MagicMock()
    repo_create = MagicMock()

    class _Repo:
        def create(self, **kwargs):
            return repo_create(**kwargs)

    monkeypatch.setattr(
        "stock_platform.operation.audit_repository.AuditEventRepository",
        lambda _session: _Repo(),
    )
    monkeypatch.setattr(
        "stock_platform.notification.publisher.notification_publisher.publish",
        MagicMock(),
    )

    fired = evaluate_alert_rules(
        {
            "database": {"status": "DOWN"},
            "broker": {"status": "UP", "use_mock": True},
            "scheduler": {"failure_count": 0},
            "ai": {"status": "UP", "response_time_ms": 10},
            "telegram": {"enabled": False, "status": "DISABLED"},
            "risk": {"kill_switch": {"status": "INACTIVE"}},
            "exception_rate": {"rate_per_minute": 0},
        },
        session=session,
        dispatch=True,
    )
    assert any(item["rule_id"] == "DB_DOWN" for item in fired)
    assert repo_create.called
