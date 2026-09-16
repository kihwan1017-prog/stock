"""Synthetic tests — ARM lease pre-expiry renew reliability (A–H)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.live_arm_service import LiveArmError, LiveArmService
from stock_platform.trading.live_unattended_authorization_service import (
    STATUS_ACTIVE,
    LiveUnattendedAuthorizationService,
)


def _uba(*, armed: bool = True, live: bool = True, remaining: int = 300):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=live,
        live_armed=armed,
        arm_expires_at=(now + timedelta(seconds=remaining)) if armed else None,
        trading_paused=False,
        arm_token_hash="x" * 64 if armed else None,
    )


def _lease(*, margin: int = 600, ttl: int = 3600, until_hours: int = 12):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        live_unattended_authorization_id=6,
        user_broker_account_id=1380,
        status_code=STATUS_ACTIVE,
        enabled=True,
        entry_authorized=True,
        protective_exit_authorized=True,
        authorized_until=now + timedelta(hours=until_hours),
        renewal_margin_seconds=margin,
        arm_lease_ttl_seconds=ttl,
        activation_renew_hours=8,
        source_activation_id=110,
        last_renewed_at=None,
        last_renewal_actor=None,
        last_renewal_detail={},
        updated_at=None,
        auto_renew_enabled=True,
    )


def _arm_precond_ctx(scheduler_actual: str = "RUNNING", desired: str = "RUN"):
    session = MagicMock()
    session.scalar.return_value = 0
    uba = _uba()
    session.get.return_value = uba
    svc = LiveArmService(session)
    cred = MagicMock()
    cred.assert_live_order_allowed = MagicMock()
    return session, uba, svc, cred, scheduler_actual, desired


def test_a_preexpiry_renew_due_within_margin() -> None:
    """TEST A: TTL 3600 / margin 600 → expiry 10분 전 renew 발생."""
    now = datetime.now(timezone.utc)
    uba = _uba(remaining=500)
    row = _lease()
    session = MagicMock()
    session.get.return_value = uba
    act = SimpleNamespace(
        live_trading_transition_id=110,
        expires_at=now + timedelta(hours=8),
    )
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(
            svc,
            "evaluate_renewal_gates",
            return_value={"ok": True, "blockers": []},
        ),
        patch.object(
            svc, "_try_horizon_auto_renew", return_value={"horizon_renewed": False}
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as lts,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService.arm",
            return_value={
                "arm_changed": True,
                "arm_expires_at": (now + timedelta(seconds=3600)).isoformat(),
            },
        ) as arm_mock,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
    ):
        lts.return_value.peek_active.return_value = act
        out = svc.renew_due_for_uba(1380, actor="SYSTEM_UNATTENDED")
    assert out["renewed"] is True
    assert out["detail"]["arm_renewed"] is True
    assert arm_mock.call_args.kwargs.get("force_renew") is True
    assert arm_mock.call_args.kwargs.get("ttl_seconds") == 3600


def test_b_renew_extends_expires_at() -> None:
    """TEST B: renew 성공 → expires_at 연장 인자 전달."""
    now = datetime.now(timezone.utc)
    uba = _uba(remaining=200)
    row = _lease()
    session = MagicMock()
    session.get.return_value = uba
    act = SimpleNamespace(
        live_trading_transition_id=110, expires_at=now + timedelta(hours=8)
    )
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(
            svc, "evaluate_renewal_gates", return_value={"ok": True, "blockers": []}
        ),
        patch.object(
            svc, "_try_horizon_auto_renew", return_value={"horizon_renewed": False}
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as lts,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService.arm",
            return_value={
                "arm_changed": True,
                "arm_expires_at": (now + timedelta(hours=1)).isoformat(),
            },
        ) as arm_mock,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
    ):
        lts.return_value.peek_active.return_value = act
        out = svc.renew_due_for_uba(1380)
    assert out["renewed"] is True
    assert int(arm_mock.call_args.kwargs["ttl_seconds"]) == 3600
    assert row.last_renewed_at is not None


def test_c_renew_failure_keeps_lease_then_expiry_path() -> None:
    """TEST C: renew 실패 → lease 유지, arm 미연장(기존 expiry fail-closed 유지)."""
    now = datetime.now(timezone.utc)
    uba = _uba(remaining=100)
    old_exp = uba.arm_expires_at
    row = _lease()
    session = MagicMock()
    session.get.return_value = uba
    act = SimpleNamespace(
        live_trading_transition_id=110, expires_at=now + timedelta(hours=8)
    )
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(
            svc, "evaluate_renewal_gates", return_value={"ok": True, "blockers": []}
        ),
        patch.object(
            svc, "_try_horizon_auto_renew", return_value={"horizon_renewed": False}
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as lts,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService.arm",
            side_effect=LiveArmError("broker_unhealthy", "down"),
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
    ):
        lts.return_value.peek_active.return_value = act
        out = svc.renew_due_for_uba(1380)
    assert out["renewed"] is False
    assert uba.arm_expires_at == old_exp
    assert row.status_code == STATUS_ACTIVE
    assert (row.last_renewal_detail or {}).get("last_arm_renew_attempt", {}).get(
        "result"
    ) == "FAILED_OR_SKIPPED"


def test_d_duplicate_renew_tick_idempotent() -> None:
    """TEST D: 중복 renew tick → NO_MEANINGFUL_EXTENSION이면 arm() 미호출."""
    now = datetime.now(timezone.utc)
    until = now + timedelta(seconds=90)
    uba = _uba(remaining=50)
    uba.arm_expires_at = until - timedelta(seconds=5)
    row = _lease()
    row.authorized_until = until
    session = MagicMock()
    session.get.return_value = uba
    act = SimpleNamespace(
        live_trading_transition_id=110, expires_at=now + timedelta(hours=1)
    )
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(
            svc, "evaluate_renewal_gates", return_value={"ok": True, "blockers": []}
        ),
        patch.object(
            svc, "_try_horizon_auto_renew", return_value={"horizon_renewed": False}
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as lts,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService.arm"
        ) as arm_mock,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
    ):
        lts.return_value.peek_active.return_value = act
        out1 = svc.renew_due_for_uba(1380)
        out2 = svc.renew_due_for_uba(1380)
    assert out1["renewed"] is False
    assert out2["renewed"] is False
    arm_mock.assert_not_called()


def test_e_force_renew_allows_running_scheduler() -> None:
    """TEST E: force_renew 시 Scheduler RUNNING이어도 precondition 통과."""
    session, uba, svc, cred, _, _ = _arm_precond_ctx()
    with (
        patch.object(
            svc,
            "_require_session_activation",
            return_value=SimpleNamespace(
                expires_at=datetime.now(timezone.utc) + timedelta(hours=5),
                live_trading_transition_id=1,
            ),
        ),
        patch("stock_platform.trading.live_arm_service.assert_uba_connection_ready"),
        patch(
            "stock_platform.trading.live_arm_service.assert_recovery_ready",
            return_value={"recovery_status": "SUCCESS", "trading_paused": False},
        ),
        patch(
            "stock_platform.trading.live_arm_service.assert_risk_account_not_paused",
            return_value={"account_paused": False},
        ),
        patch(
            "stock_platform.trading.live_arm_service.BrokerRecoveryConflictService"
        ) as brc,
        patch(
            "stock_platform.trading.live_arm_service.BrokerCredentialVaultService",
            return_value=cred,
        ),
        patch("stock_platform.trading.live_arm_service.KillSwitchService") as ks,
        patch(
            "stock_platform.trading.live_arm_service.evaluate_live_order_health",
            return_value={"live_orders_allowed": True, "status": "HEALTHY"},
        ),
        patch(
            "stock_platform.trading.live_arm_service.collect_scheduler_readiness"
        ) as sch,
    ):
        brc.return_value.count_blocking_orders_for_uba.return_value = {
            "db_open": 0,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
        ks.return_value.is_active_for_scopes.return_value = False
        sch.return_value = SimpleNamespace(
            trading_scheduler_actual_state="RUNNING",
            trading_scheduler_desired_state="RUN",
        )
        out = svc.assert_arm_enable_preconditions(
            1380,
            allow_auto_protective_open_orders=True,
            require_scheduler_paused=False,
        )
    assert out["require_scheduler_paused"] is False
    assert out["trading_scheduler_actual"] == "RUNNING"


def test_f_live_off_skips_unnecessary_renew_via_restore_branch() -> None:
    """TEST F: LIVE OFF → renew 대신 lease restore 경로."""
    uba = _uba(live=False, armed=False)
    row = _lease()
    session = MagicMock()
    session.get.return_value = uba
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(
            svc,
            "restore_from_active_lease",
            return_value={"restored": False, "reason": "SAFETY_GATES_FAILED"},
        ) as restore,
        patch.object(
            svc, "_try_horizon_auto_renew", return_value={"horizon_renewed": False}
        ),
    ):
        out = svc.renew_due_for_uba(1380)
    assert out["reason"] in {"SAFETY_GATES_FAILED", "RESTORED_FROM_LEASE"}
    restore.assert_called_once()


def test_g_force_renew_flag_skips_paused_requirement_in_arm() -> None:
    """TEST G: arm(force_renew=True)는 require_scheduler_paused=False 전달."""
    session = MagicMock()
    uba = _uba(remaining=200)
    session.get.return_value = uba
    svc = LiveArmService(session)
    with (
        patch.object(svc, "assert_arm_enable_preconditions") as pre,
        patch.object(
            svc,
            "_clamp_arm_ttl",
            return_value=(
                3600,
                datetime.now(timezone.utc) + timedelta(seconds=3600),
                SimpleNamespace(
                    live_trading_transition_id=1,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
                ),
            ),
        ),
        patch(
            "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
        ) as pol,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
    ):
        pol.return_value.resolve.return_value = SimpleNamespace(arm_ttl_seconds=3600)
        pre.return_value = {}
        svc.arm(
            1380,
            actor="SYSTEM_UNATTENDED",
            ttl_seconds=3600,
            reason="UNATTENDED_ARM_RENEWAL",
            correlation_id="unatt-6",
            enforce_gates=True,
            force_renew=True,
            allow_auto_protective_open_orders=True,
        )
    assert pre.call_args.kwargs.get("require_scheduler_paused") is False


def test_h_manual_arm_still_requires_paused_scheduler() -> None:
    """TEST H: 수동 ARM( force_renew=False )은 Scheduler PAUSED 유지."""
    session, uba, svc, cred, _, _ = _arm_precond_ctx()
    with (
        patch.object(
            svc,
            "_require_session_activation",
            return_value=SimpleNamespace(
                expires_at=datetime.now(timezone.utc) + timedelta(hours=5),
                live_trading_transition_id=1,
            ),
        ),
        patch("stock_platform.trading.live_arm_service.assert_uba_connection_ready"),
        patch(
            "stock_platform.trading.live_arm_service.assert_recovery_ready",
            return_value={"recovery_status": "SUCCESS", "trading_paused": False},
        ),
        patch(
            "stock_platform.trading.live_arm_service.assert_risk_account_not_paused",
            return_value={"account_paused": False},
        ),
        patch(
            "stock_platform.trading.live_arm_service.BrokerRecoveryConflictService"
        ) as brc,
        patch(
            "stock_platform.trading.live_arm_service.BrokerCredentialVaultService",
            return_value=cred,
        ),
        patch("stock_platform.trading.live_arm_service.KillSwitchService") as ks,
        patch(
            "stock_platform.trading.live_arm_service.evaluate_live_order_health",
            return_value={"live_orders_allowed": True, "status": "HEALTHY"},
        ),
        patch(
            "stock_platform.trading.live_arm_service.collect_scheduler_readiness"
        ) as sch,
    ):
        brc.return_value.count_blocking_orders_for_uba.return_value = {
            "db_open": 0,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
        ks.return_value.is_active_for_scopes.return_value = False
        sch.return_value = SimpleNamespace(
            trading_scheduler_actual_state="RUNNING",
            trading_scheduler_desired_state="RUN",
        )
        with pytest.raises(LiveArmError) as ei:
            svc.assert_arm_enable_preconditions(
                1380, require_scheduler_paused=True
            )
    assert ei.value.code == "trading_scheduler_not_paused"
