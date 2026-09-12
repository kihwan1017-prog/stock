"""STEP 9-7 — Runtime Pre-flight 정책·살균·최신성 계약 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.operation.runtime_preflight_service import (
    PREFLIGHT_TTL_SECONDS,
    RuntimePreflightService,
    _check_redis,
    _check_strategy,
    _item,
    evaluate_preflight_freshness,
    sanitize_preflight_payload,
)


def test_item_includes_blocking_and_remediation() -> None:
    row = _item(
        code="BROKER",
        name="Broker",
        status="FAIL",
        message="down",
        remediation="fix it",
        detail={"secret_key": "SHOULD_STRIP", "ok": 1},
    )
    assert row["blocking"] is True
    assert row["remediation"] == "fix it"
    assert "checked_at" in row
    assert "secret_key" not in row["detail"]
    assert row["detail"]["ok"] == 1


def test_sanitize_strips_secrets() -> None:
    payload = {
        "access_key": "AK",
        "secret_key": "SK",
        "arm_token": "tok",
        "authorization": "Bearer x",
        "ciphertext": "enc",
        "traceback": "Traceback...",
        "safe": "yes",
        "nested": {"api_secret": "x", "count": 2},
    }
    cleaned = sanitize_preflight_payload(payload)
    assert "access_key" not in cleaned
    assert "secret_key" not in cleaned
    assert "arm_token" not in cleaned
    assert "authorization" not in cleaned
    assert "ciphertext" not in cleaned
    assert "traceback" not in cleaned
    assert cleaned["safe"] == "yes"
    assert "api_secret" not in cleaned["nested"]
    assert cleaned["nested"]["count"] == 2


def test_redis_not_configured_is_not_applicable() -> None:
    with patch(
        "stock_platform.operation.runtime_preflight_service.get_settings"
    ) as settings:
        settings.return_value = SimpleNamespace(redis_url="", REDIS_URL="")
        out = _check_redis()
    assert out["status"] == "NOT_APPLICABLE"
    assert out["blocking"] is False


def test_strategy_zero_warn_for_live_on_fail_for_scheduler() -> None:
    with (
        patch(
            "stock_platform.realtime.runtime.realtime_strategy_runner.status",
            return_value={"active_scopes": 0, "running": False},
        ),
        patch(
            "stock_platform.strategy_deployment.runtime_manager."
            "dynamic_strategy_runtime_manager.status",
            return_value={"scoped_runtime_count": 0},
        ),
    ):
        live = _check_strategy(mode="LIVE_ON")
        sched = _check_strategy(mode="SCHEDULER_RUN")
    assert live["status"] == "WARN"
    assert live["blocking"] is False
    assert sched["status"] == "FAIL"
    assert sched["blocking"] is True


def test_freshness_stale_after_ttl() -> None:
    now = datetime(2026, 8, 3, 15, 0, 0, tzinfo=timezone.utc)
    checked = (now - timedelta(seconds=PREFLIGHT_TTL_SECONDS + 1)).isoformat()
    out = evaluate_preflight_freshness(checked, now=now)
    assert out["status"] == "STALE"
    assert out["fresh"] is False


def test_freshness_fresh_within_ttl() -> None:
    now = datetime(2026, 8, 3, 15, 0, 0, tzinfo=timezone.utc)
    checked = (now - timedelta(seconds=10)).isoformat()
    out = evaluate_preflight_freshness(checked, now=now)
    assert out["status"] == "FRESH"
    assert out["fresh"] is True


def _pass(code: str, name: str) -> dict:
    return _item(code=code, name=name, status="PASS", message="ok")


def _patch_all_checks(**overrides):
    defaults = {
        "_check_broker": _pass("BROKER", "Broker"),
        "_check_credential": _pass("CREDENTIAL", "Credential"),
        "_check_connection": _pass("CONNECTION", "Connection"),
        "_check_recovery": _pass("RECOVERY", "Recovery"),
        "_check_conflict": _pass("CONFLICT", "Conflict"),
        "_check_runtime": _pass("RUNTIME", "Runtime"),
        "_check_scheduler": _item(
            code="SCHEDULER",
            name="Scheduler",
            status="WARN",
            message="PAUSE",
        ),
        "_check_live_arm_flags": _item(
            code="LIVE_ARM_STATE",
            name="LIVE/ARM",
            status="WARN",
            message="OFF",
        ),
        "_check_risk": _pass("RISK", "Risk"),
        "_check_strategy": _item(
            code="STRATEGY",
            name="Strategy",
            status="WARN",
            message="0",
        ),
        "_check_telegram": _item(
            code="TELEGRAM",
            name="Telegram",
            status="WARN",
            message="off",
        ),
        "_check_database": _pass("DATABASE", "Database"),
        "_check_redis": _item(
            code="REDIS",
            name="Redis",
            status="NOT_APPLICABLE",
            message="n/a",
        ),
        "_check_api_health": _pass("API_HEALTH", "API Health"),
        "_check_sync_freshness": _pass("SYNC_FRESHNESS", "Sync"),
    }
    defaults.update(overrides)
    return [
        patch(
            f"stock_platform.operation.runtime_preflight_service.{name}",
            return_value=value,
        )
        for name, value in defaults.items()
    ]


def test_overall_blocked_on_any_fail() -> None:
    session = MagicMock()
    patches = _patch_all_checks(
        _check_recovery=_item(
            code="RECOVERY",
            name="Recovery",
            status="FAIL",
            message="paused",
        )
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[
        5
    ], patches[6], patches[7], patches[8], patches[9], patches[10], patches[
        11
    ], patches[12], patches[13], patches[14]:
        out = RuntimePreflightService(session).run(mode="LIVE_ON")

    assert out["overall_status"] == "BLOCKED"
    assert out["estimated_ready"] is None
    assert out["live_on_allowed"] is False
    assert any(b["code"] == "RECOVERY" for b in out["blockers"])
    assert out["freshness"]["status"] == "FRESH"
    assert out["freshness"]["ttl_seconds"] == PREFLIGHT_TTL_SECONDS


def test_overall_ready_with_warns_only() -> None:
    session = MagicMock()
    patches = _patch_all_checks()
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[
        5
    ], patches[6], patches[7], patches[8], patches[9], patches[10], patches[
        11
    ], patches[12], patches[13], patches[14]:
        out = RuntimePreflightService(session).run(mode="LIVE_ON")

    assert out["overall_status"] == "READY_FOR_LIVE"
    assert out["estimated_ready"] == "NOW"
    assert out["live_on_allowed"] is True
    assert out["blockers"] == []
    assert len(out["warnings"]) >= 1
    # NOT_APPLICABLE 은 warnings 에 넣지 않음
    assert all(w["status"] == "WARN" for w in out["warnings"])
    for check in out["checks"]:
        assert "blocking" in check
        assert "checked_at" in check
        assert "code" in check
        assert "name" in check
        assert "status" in check
        assert "message" in check
        assert "detail" in check
        assert "remediation" in check or check.get("remediation") is None


def test_live_on_server_revalidates_preflight() -> None:
    from stock_platform.trading.live_order_approval_service import (
        LiveOrderApprovalError,
        LiveOrderApprovalService,
    )

    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=1,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=False,
        live_armed=False,
        connection_status="CONNECTED",
        live_approved_at=None,
        live_approved_by=None,
    )
    session.get.return_value = uba
    svc = LiveOrderApprovalService(session)
    with patch(
        "stock_platform.operation.runtime_preflight_service.RuntimePreflightService.run_for_uba",
        return_value={
            "overall_status": "BLOCKED",
            "blockers": [{"code": "CONFLICT", "message": "x"}],
        },
    ):
        try:
            svc.set_live_enabled(
                1380,
                enabled=True,
                actor="admin",
                reason="TEST",
                correlation_id="c1",
                enforce_enable_gates=True,
            )
            raised = False
        except LiveOrderApprovalError as exc:
            raised = True
            assert exc.code == "preflight_blocked"
    assert raised is True


def test_recovery_null_uba_id_no_typeerror() -> None:
    """paper/null user_broker_account_id 행에서도 TypeError 없이 WARN/PASS."""
    from stock_platform.operation.runtime_preflight_service import (
        _check_recovery,
    )

    session = MagicMock()
    rows = [
        SimpleNamespace(
            trading_paused=False,
            recovery_status="SUCCESS",
            user_broker_account_id=1380,
            paper_account_id=None,
        ),
        SimpleNamespace(
            trading_paused=False,
            recovery_status="MANUAL_REVIEW",
            user_broker_account_id=None,  # TypeError 유발 후보
            paper_account_id=99,
        ),
    ]
    session.scalars.return_value = rows
    out = _check_recovery(session)
    assert out["status"] == "WARN"
    assert out["blocking"] is False
    sample = out["detail"]["abnormal_sample"]
    assert sample[0]["uba_id"] is None
    assert sample[0]["paper_account_id"] == 99


def test_assert_ready_for_live_on_uses_uba_scope() -> None:
    session = MagicMock()
    with patch.object(
        RuntimePreflightService,
        "run_for_uba",
        return_value={
            "overall_status": "READY_FOR_LIVE",
            "blockers": [],
            "user_broker_account_id": 1380,
        },
    ) as run_uba:
        out = RuntimePreflightService(session).assert_ready_for_live_on(1380)
    run_uba.assert_called_once()
    assert out["overall_status"] == "READY_FOR_LIVE"
    assert run_uba.call_args.kwargs["user_broker_account_id"] == 1380
