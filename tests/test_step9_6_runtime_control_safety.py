"""Runtime 제어 안전 검증 — mock/거부 시나리오만 (실 LIVE/ARM/Scheduler ON 금지)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.live_arm_service import LiveArmError, LiveArmService
from stock_platform.trading.live_order_approval_service import (
    LiveOrderApprovalError,
    LiveOrderApprovalService,
)
from stock_platform.trading.runtime_control_gates import (
    assert_recovery_ready,
    assert_risk_account_not_paused,
    assert_uba_connection_ready,
)
from stock_platform.trading.trading_scheduler_control_service import (
    TradingSchedulerControlError,
    TradingSchedulerControlService,
)


def _uba(
    *,
    live: bool = False,
    armed: bool = False,
    active: bool = True,
    connection: str = "CONNECTED",
    user_id: int = 1,
):
    return SimpleNamespace(
        user_broker_account_id=1380,
        user_id=user_id,
        broker_code="UPBIT",
        is_active=active,
        live_order_enabled=live,
        live_armed=armed,
        connection_status=connection,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        arm_token_hash="hash",
        live_approved_at=None,
        live_approved_by=None,
        arm_armed_at=None,
        arm_armed_by=None,
    )


def _risk_ok():
    return SimpleNamespace(
        account_paused=False,
        max_order_amount=5000,
        max_order_quantity=1,
        daily_order_limit=10,
        daily_max_loss_amount=10000,
        arm_ttl_seconds=300,
    )


def _sched_paused():
    return SimpleNamespace(
        trading_scheduler_desired_state="PAUSE",
        trading_scheduler_actual_state="PAUSED",
    )


def _sched_running():
    return SimpleNamespace(
        trading_scheduler_desired_state="RUN",
        trading_scheduler_actual_state="RUNNING",
    )


def test_gate_connection_rejects_pending() -> None:
    with pytest.raises(Exception) as ei:
        assert_uba_connection_ready(
            _uba(connection="CREDENTIAL_PENDING"),
            raise_error=lambda c, m: LiveOrderApprovalError(c, m),
        )
    assert ei.value.code == "connection_not_connected"


def test_gate_recovery_rejects_manual_review() -> None:
    session = MagicMock()
    session.scalar.return_value = SimpleNamespace(
        trading_paused=False,
        recovery_status="MANUAL_REVIEW",
    )
    with pytest.raises(LiveOrderApprovalError) as ei:
        assert_recovery_ready(
            session,
            1380,
            raise_error=lambda c, m: LiveOrderApprovalError(c, m),
        )
    assert ei.value.code == "recovery_not_ready"


def test_gate_risk_rejects_account_paused() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.trading.runtime_control_gates.ResolvedRiskPolicyResolver"
    ) as resolver:
        resolver.return_value.resolve.return_value = SimpleNamespace(
            account_paused=True,
            arm_ttl_seconds=300,
        )
        with pytest.raises(LiveOrderApprovalError) as ei:
            assert_risk_account_not_paused(
                session,
                _uba(),
                raise_error=lambda c, m: LiveOrderApprovalError(c, m),
            )
    assert ei.value.code == "account_paused"


def test_live_on_rejected_when_trading_paused() -> None:
    session = MagicMock()
    session.get.return_value = _uba()
    svc = LiveOrderApprovalService(session)
    with (
        patch(
            "stock_platform.operation.runtime_preflight_service.RuntimePreflightService.assert_ready_for_live_on",
            return_value=None,
        ),
        patch.object(
            svc,
            "assert_live_enable_preconditions",
            side_effect=LiveOrderApprovalError(
                "trading_paused", "Account trading is paused"
            ),
        ),
    ):
        with pytest.raises(LiveOrderApprovalError) as ei:
            svc.set_live_enabled(
                1380,
                enabled=True,
                actor="admin:test",
                reason="TEST",
                correlation_id="corr-paused",
            )
    assert ei.value.code == "trading_paused"


def test_live_on_rejected_when_arm_on() -> None:
    session = MagicMock()
    session.get.return_value = _uba(armed=True)
    svc = LiveOrderApprovalService(session)
    with pytest.raises(LiveOrderApprovalError) as ei:
        svc.assert_live_enable_preconditions(1380)
    assert ei.value.code == "arm_must_be_off"


def test_arm_on_rejected_when_live_off() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=False)
    svc = LiveArmService(session)
    with pytest.raises(LiveArmError) as ei:
        svc.assert_arm_enable_preconditions(1380)
    assert ei.value.code == "live_required"


def test_arm_on_rejected_when_scheduler_running() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True)
    session.scalar.side_effect = [
        SimpleNamespace(trading_paused=False, recovery_status="SUCCESS"),
        0,  # active conflicts
        0,  # pending
    ]
    svc = LiveArmService(session)
    with (
        patch(
            "stock_platform.trading.runtime_control_gates.ResolvedRiskPolicyResolver"
        ) as risk,
        patch(
            "stock_platform.trading.live_arm_service.BrokerRecoveryConflictService"
        ) as conflicts,
        patch(
            "stock_platform.trading.live_arm_service.BrokerCredentialVaultService"
        ) as vault,
        patch(
            "stock_platform.trading.live_arm_service.KillSwitchService"
        ) as kill,
        patch(
            "stock_platform.trading.live_arm_service.evaluate_live_order_health",
            return_value={"live_orders_allowed": True, "status": "HEALTHY"},
        ),
        patch(
            "stock_platform.trading.live_arm_service.collect_scheduler_readiness",
            return_value=_sched_running(),
        ),
    ):
        risk.return_value.resolve.return_value = _risk_ok()
        conflicts.return_value.count_blocking_orders_for_uba.return_value = {
            "db_open": 0,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
        vault.return_value = type(
            "Vault",
            (),
            {"assert_live_order_allowed": staticmethod(lambda *a, **k: None)},
        )()
        kill.return_value.is_active_for_scopes.return_value = False
        with pytest.raises(LiveArmError) as ei:
            svc.assert_arm_enable_preconditions(1380)
    assert ei.value.code == "trading_scheduler_not_paused"


def test_scheduler_run_rejected_when_arm_off() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True, armed=False)
    svc = TradingSchedulerControlService(session)
    with pytest.raises(TradingSchedulerControlError) as ei:
        svc.assert_start_preconditions(user_broker_account_id=1380)
    assert ei.value.code == "arm_required"


def test_scheduler_run_rejected_when_live_off() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=False, armed=False)
    svc = TradingSchedulerControlService(session)
    with pytest.raises(TradingSchedulerControlError) as ei:
        svc.assert_start_preconditions(user_broker_account_id=1380)
    assert ei.value.code == "live_required"


def test_disarm_rejected_when_scheduler_running() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True, armed=True)
    svc = LiveArmService(session)
    with patch(
        "stock_platform.trading.live_arm_service.collect_scheduler_readiness",
        return_value=_sched_running(),
    ):
        with pytest.raises(LiveArmError) as ei:
            svc.disarm(
                1380,
                actor="admin:test",
                reason="TEST_DISARM",
                correlation_id="corr-disarm",
                require_correlation_id=True,
            )
    assert ei.value.code == "trading_scheduler_not_paused"


def test_live_off_rejected_when_arm_on() -> None:
    session = MagicMock()
    session.get.return_value = _uba(live=True, armed=True)
    svc = LiveOrderApprovalService(session)
    with (
        patch(
            "stock_platform.trading.live_order_approval_service.collect_scheduler_readiness",
            return_value=_sched_paused(),
        ),
    ):
        with pytest.raises(LiveOrderApprovalError) as ei:
            svc.set_live_enabled(
                1380,
                enabled=False,
                actor="admin:test",
                reason="TEST_OFF",
                correlation_id="corr-off",
            )
    assert ei.value.code == "arm_must_be_off"


def test_live_off_auto_pauses_scheduler_when_running() -> None:
    """Fail Closed: Scheduler RUN 중 LIVE OFF → 자동 PAUSE 후 LIVE OFF."""
    session = MagicMock()
    uba = _uba(live=True, armed=False)
    session.get.return_value = uba
    svc = LiveOrderApprovalService(session)
    paused = _sched_paused()
    running = _sched_running()
    readiness = [running, paused]  # pause 전/후

    def _ready():
        return readiness.pop(0) if readiness else paused

    with (
        patch(
            "stock_platform.trading.live_order_approval_service.collect_scheduler_readiness",
            side_effect=_ready,
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.TradingSchedulerControlService.pause",
            return_value={"scheduler_changed": True, "already_paused": False},
        ) as pause,
        patch(
            "stock_platform.trading.live_order_approval_service.emit_live_safety_audit"
        ),
        patch.object(
            svc,
            "get_status",
            return_value={
                "live_order_enabled": False,
                "live_armed": False,
                "user_broker_account_id": 1380,
            },
        ),
    ):
        out = svc.set_live_enabled(
            1380,
            enabled=False,
            actor="admin:test",
            reason="TEST_OFF_WHILE_RUN",
            correlation_id="corr-off-run",
        )
    assert uba.live_order_enabled is False
    assert out["scheduler_auto_paused"] is True
    pause.assert_called_once()


def test_arm_expire_pauses_scheduler() -> None:
    session = MagicMock()
    uba = _uba(live=True, armed=True)
    uba.arm_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    uba.arm_token_hash = "x"
    session.get.return_value = uba
    svc = LiveArmService(session)
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.TradingSchedulerControlService.pause",
            return_value={"already_paused": False, "scheduler_changed": True},
        ) as pause,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
    ):
        expired = svc._expire_if_needed(uba, actor="SYSTEM", commit=False)
    assert expired is True
    assert uba.live_order_enabled is False
    assert uba.live_armed is False
    pause.assert_called_once()


def test_scheduler_start_gate_fail_while_running_auto_pauses() -> None:
    """이미 RUN인데 LIVE OFF면 start 게이트 실패 시 PAUSE."""
    session = MagicMock()
    session.get.return_value = _uba(live=False, armed=False)
    svc = TradingSchedulerControlService(session)
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch(
            "stock_platform.trading.trading_scheduler_control_service.get_trading_scheduler_desired_state",
            return_value="RUN",
        ),
        patch.object(
            svc,
            "pause",
            return_value={"scheduler_changed": True},
        ) as pause,
    ):
        sched.scheduler.running = True
        with pytest.raises(TradingSchedulerControlError) as ei:
            svc.start(
                actor="admin:test",
                reason="retry",
                correlation_id="corr-start",
                user_broker_account_id=1380,
                enforce_gates=True,
            )
    assert ei.value.code == "live_required"
    pause.assert_called_once()


def test_live_on_idempotent_already_enabled() -> None:
    session = MagicMock()
    uba = _uba(live=True)
    session.get.return_value = uba
    svc = LiveOrderApprovalService(session)
    with patch.object(
        svc,
        "get_status",
        return_value={
            "live_order_enabled": True,
            "live_armed": False,
            "user_broker_account_id": 1380,
        },
    ):
        out = svc.set_live_enabled(
            1380,
            enabled=True,
            actor="admin:test",
            reason="IDEMPOTENT",
            correlation_id="corr-idem",
        )
    assert out["already_enabled"] is True
    assert out["live_changed"] is False


def test_live_on_success_path_mock_emits_live_on_audit() -> None:
    """정상 LIVE ON (mock) — Audit LIVE_ON + result SUCCESS. 실 DB 변경 없음."""
    session = MagicMock()
    uba = _uba(live=False)
    session.get.return_value = uba
    svc = LiveOrderApprovalService(session)
    with (
        patch(
            "stock_platform.operation.runtime_preflight_service.RuntimePreflightService.assert_ready_for_live_on",
            return_value=None,
        ),
        patch.object(svc, "assert_live_enable_preconditions", return_value={}),
        patch(
            "stock_platform.trading.live_order_approval_service.emit_live_safety_audit"
        ) as audit,
        patch.object(
            svc,
            "get_status",
            return_value={
                "live_order_enabled": True,
                "live_armed": False,
                "user_id": 1,
                "user_broker_account_id": 1380,
            },
        ),
    ):
        out = svc.set_live_enabled(
            1380,
            enabled=True,
            actor="admin:mock",
            reason="MOCK_LIVE_ON",
            correlation_id="corr-mock-live",
        )
    assert uba.live_order_enabled is True
    assert out["live_changed"] is True
    assert audit.call_args.kwargs["event_type"] == "LIVE_ON"
    assert audit.call_args.kwargs["detail"]["result"] == "SUCCESS"
    assert "access_key" not in audit.call_args.kwargs["detail"]
    assert "secret" not in audit.call_args.kwargs["detail"]


def test_arm_on_success_path_mock() -> None:
    session = MagicMock()
    uba = _uba(live=True, armed=False)
    session.get.return_value = uba
    svc = LiveArmService(session)
    with (
        patch.object(svc, "assert_arm_enable_preconditions", return_value={}),
        patch(
            "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
        ) as policy,
        patch(
            "stock_platform.trading.live_arm_service.collect_scheduler_readiness",
            return_value=_sched_paused(),
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
        patch.object(
            svc,
            "get_arm_status",
            return_value={
                "live_armed": True,
                "live_order_enabled": True,
                "user_id": 1,
                "user_broker_account_id": 1380,
                "arm_expires_at": datetime.now(timezone.utc).isoformat(),
            },
        ),
    ):
        policy.return_value.resolve.return_value = _risk_ok()
        out = svc.arm(
            1380,
            actor="admin:mock",
            reason="MOCK_ARM",
            correlation_id="corr-mock-arm",
            enforce_gates=True,
        )
    assert out["arm_changed"] is True
    assert audit.call_args.kwargs["event_type"] == "ARM_ON"
    assert "arm_token" not in (audit.call_args.kwargs.get("detail") or {})


def test_scheduler_pause_always_safe_mock() -> None:
    session = MagicMock()
    svc = TradingSchedulerControlService(session)
    with (
        patch(
            "stock_platform.trading.trading_scheduler_control_service.get_trading_scheduler_desired_state",
            return_value="PAUSE",
        ),
        patch(
            "stock_platform.trading.trading_scheduler_control_service.realtime_trading_scheduler"
        ) as sched,
        patch.object(
            svc,
            "status",
            return_value={
                "desired_state": "PAUSE",
                "actual_state": "PAUSED",
                "running": False,
            },
        ),
    ):
        sched.scheduler.running = False
        out = svc.pause(
            actor="admin:mock",
            reason="MOCK_PAUSE",
            correlation_id="corr-pause",
            user_broker_account_id=1380,
            require_correlation_id=True,
        )
    assert out.get("already_paused") is True or out.get("desired_state") == "PAUSE"


def test_user_accounts_has_no_runtime_mutation_routes() -> None:
    from pathlib import Path

    text = Path("src/stock_platform/api/v1/user_accounts.py").read_text(
        encoding="utf-8"
    )
    assert "@router.put" not in text or "live_order_enabled" not in text.split(
        "@router.put"
    )[0]
    # 사용자 라우터에 LIVE/ARM/Scheduler 변경 endpoint 문자열이 없어야 함
    forbidden = (
        "set_live_enabled",
        "/arm",
        "trading-scheduler/start",
        "live_order_enabled=True",
    )
    for token in forbidden:
        assert token not in text


def test_admin_ui_panel_has_tooltips_and_confirm() -> None:
    from pathlib import Path

    text = Path(
        "frontend/src/features/admin/accounts/AdminUpbitLiveUbaPanel.tsx"
    ).read_text(encoding="utf-8")
    assert "Tooltip" in text
    assert "runtimeGateBlockers" in text
    assert "실거래를 활성화하시겠습니까?" in text
    assert "invalidate" in text
    assert "optimistic" not in text.lower()


def test_audit_event_constants() -> None:
    from stock_platform.order.live_safety_audit import (
        ARM_OFF,
        ARM_ON,
        LIVE_OFF,
        LIVE_ON,
        SCHEDULER_PAUSE,
        SCHEDULER_RUN,
    )

    assert LIVE_ON == "LIVE_ON"
    assert LIVE_OFF == "LIVE_OFF"
    assert ARM_ON == "ARM_ON"
    assert ARM_OFF == "ARM_OFF"
    assert SCHEDULER_RUN == "SCHEDULER_RUN"
    assert SCHEDULER_PAUSE == "SCHEDULER_PAUSE"
