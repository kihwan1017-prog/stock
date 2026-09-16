"""Release v1.2 operation readiness — Configuration / Health / Fail-Closed."""

from __future__ import annotations

import pytest


def test_validate_environment_and_broker_flags(monkeypatch) -> None:
    from stock_platform.common.settings import get_settings
    from stock_platform.operation import release_operation_readiness as mod

    get_settings.cache_clear()
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    get_settings.cache_clear()

    env = mod.validate_environment()
    assert env["status"] in {"PASS", "WARN", "FAIL"}
    assert "jwt_secret_configured" in env

    broker = mod.validate_broker()
    assert broker["status"] == "PASS"
    assert broker["kiwoom_live_order_enabled"] is False
    assert broker["upbit_live_order_enabled"] is False


def test_fail_closed_blocks_live_submit() -> None:
    from stock_platform.database.session import get_session_factory
    from stock_platform.operation.release_operation_readiness import (
        evaluate_fail_closed,
    )

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        result = evaluate_fail_closed(session)

    assert result["live_submit_blocked"] is True
    assert result["gates"]["submit_mutate_allowed"] is False
    assert result["gates"]["live_flags"]["kiwoom"] is False
    assert result["gates"]["live_flags"]["upbit"] is False


def test_release_lifecycle_hooks_present() -> None:
    from stock_platform.operation.release_operation_readiness import (
        validate_release_lifecycle,
    )

    result = validate_release_lifecycle()
    assert result["status"] == "PASS"
    assert result["checks"]["startup"]["has_startup"] is True
    assert result["checks"]["startup"]["has_shutdown"] is True
    assert result["checks"]["graceful_stop"]["market_open"] is True
    assert result["checks"]["graceful_stop"]["market_close"] is True


def test_startup_configuration_validation_runs() -> None:
    from stock_platform.operation.release_operation_readiness import (
        get_last_startup_validation,
        run_startup_configuration_validation,
    )

    result = run_startup_configuration_validation()
    assert result["release"] == "v1.2"
    assert result["overall"] in {"PASS", "WARN", "FAIL"}
    for key in (
        "environment",
        "credential",
        "runtime",
        "scheduler",
        "broker",
        "database",
        "recovery",
        "dashboard",
        "telegram",
        "notification",
    ):
        assert key in result["checks"]
        assert result["checks"][key]["status"] in {"PASS", "WARN", "FAIL"}

    assert result["fail_closed"]["live_submit_blocked"] is True
    assert result["lifecycle"]["status"] == "PASS"
    cached = get_last_startup_validation()
    assert cached is not None
    assert cached["checked_at"] == result["checked_at"]


def test_operation_health_components() -> None:
    from stock_platform.operation.release_operation_readiness import (
        build_operation_health,
    )

    health = build_operation_health()
    assert health["status"] in {"UP", "DEGRADED", "CRITICAL"}
    for key in (
        "api",
        "dashboard",
        "runtime",
        "scheduler",
        "recovery",
        "broker",
        "database",
        "outbox",
        "worker",
        "queue",
        "websocket",
        "connection",
    ):
        assert key in health["components"]
    assert health["components"]["live_order_flags"]["submit_allowed"] is False


def test_operation_dashboard_slice() -> None:
    from stock_platform.database.session import get_session_factory
    from stock_platform.operation.release_operation_readiness import (
        build_operation_dashboard_slice,
    )

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        slice_ = build_operation_dashboard_slice(session)

    assert slice_["release"] == "v1.2"
    for key in (
        "runtime",
        "worker",
        "recovery",
        "scheduler",
        "broker",
        "queue",
        "fill",
        "pending",
        "position",
        "pnl",
        "memory",
        "cpu",
        "error",
    ):
        assert key in slice_
    assert slice_["fail_closed"]["live_submit_blocked"] is True


def test_release_readiness_report_no_live_mutate() -> None:
    from stock_platform.database.session import get_session_factory
    from stock_platform.operation.release_operation_readiness import (
        build_release_readiness_report,
    )

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        report = build_release_readiness_report(session)

    assert report["release"] == "v1.2"
    assert report["validation"]["fail_closed"]["live_submit_blocked"] is True
    assert report["validation"]["fail_closed"]["gates"]["submit_mutate_allowed"] is False


def test_health_ops_endpoint_shape() -> None:
    from fastapi.testclient import TestClient

    from stock_platform.api.main import create_app

    client = TestClient(create_app())
    response = client.get("/health/ops")
    assert response.status_code == 200
    body = response.json()
    assert "components" in body
    assert "runtime" in body["components"]
    assert "scheduler" in body["components"]
    assert body["components"]["live_order_flags"]["submit_allowed"] is False


def test_broker_live_flag_warn(monkeypatch) -> None:
    from stock_platform.common.settings import get_settings
    from stock_platform.operation.release_operation_readiness import (
        validate_broker,
    )

    settings = get_settings()
    monkeypatch.setattr(settings, "kiwoom_live_order_enabled", True)
    monkeypatch.setattr(settings, "kiwoom_use_mock", False)
    monkeypatch.setattr(settings, "upbit_live_order_enabled", False)
    monkeypatch.setattr(settings, "global_live_order_enabled", True)

    result = validate_broker()
    assert result["status"] == "WARN"
    assert result["code"] == "LIVE_ORDER_FLAG_ON"
