"""Unattended authorization — focused unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.live_unattended_authorization_service import (
    APPROVAL_MODEL_UNATTENDED_LEASE,
    CONFIRM_DISABLE,
    CONFIRM_ENABLE,
    SOURCE_ADMIN_UI,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_PROTECTIVE,
    LiveUnattendedAuthorizationService,
    LiveUnattendedError,
)


def test_enable_requires_exact_confirmation() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    with pytest.raises(LiveUnattendedError) as exc:
        svc.enable(
            1380,
            actor="admin",
            confirmation_text="yes",
            reason="test",
            source=SOURCE_ADMIN_UI,
        )
    assert exc.value.code == "CONFIRMATION_REQUIRED"


def test_status_dict_off_when_missing() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    uba = SimpleNamespace(broker_code="UPBIT")
    session.get.return_value = uba
    out = LiveUnattendedAuthorizationService(session).status_dict(1380)
    assert out["unattended_enabled"] is False
    assert out["status_code"] == "OFF"
    assert out["required_confirmation_text"] == CONFIRM_ENABLE
    assert out["requires_live_approval_phrase"] is False
    assert out["required_approval_phrase"] is None
    assert out["approval_model"] == APPROVAL_MODEL_UNATTENDED_LEASE


def test_enable_rejects_invalid_source() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    with pytest.raises(LiveUnattendedError) as exc:
        svc.enable(
            1380,
            actor="admin",
            confirmation_text=CONFIRM_ENABLE,
            reason="test",
            source="RANDOM",
        )
    assert exc.value.code == "INVALID_SOURCE"


def test_enable_fail_closed_when_gates_fail() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        user_id=7,
        is_active=True,
        live_order_enabled=True,
    )
    session.get.return_value = uba
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(
            svc,
            "evaluate_enable_gates",
            return_value={"ok": False, "blockers": ["ARM_OFF", "LIVE_OFF"]},
        ),
        patch.object(svc, "get_active", return_value=None),
        pytest.raises(LiveUnattendedError) as exc,
    ):
        svc.enable(
            1380,
            actor="admin",
            confirmation_text=CONFIRM_ENABLE,
            reason="test",
            source=SOURCE_ADMIN_UI,
        )
    assert exc.value.code == "SAFETY_GATES_FAILED"
    assert "ARM_OFF" in exc.value.message


def test_evaluate_enable_gates_requires_arm_and_live() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        user_id=7,
        is_active=True,
        live_order_enabled=False,
        live_armed=False,
        arm_expires_at=None,
        connection_status="CONNECTED",
        trading_paused=False,
    )
    session.get.return_value = uba
    session.scalar.return_value = 0

    with (
        patch(
            "stock_platform.broker.live_config_gate.evaluate_live_flag_consistency",
            return_value=SimpleNamespace(
                allowed=True, code="UPBIT_FLAGS_OK", status="HEALTHY"
            ),
        ),
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        ) as vault_cls,
        patch(
            "stock_platform.trading.runtime_control_gates.assert_recovery_ready",
            return_value={
                "trading_paused": False,
                "recovery_status": "SUCCESS",
            },
        ),
        patch(
            "stock_platform.trading.runtime_control_gates.assert_risk_account_not_paused",
            return_value={"account_paused": False},
        ),
        patch(
            "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
        ) as kill_cls,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as lts_cls,
    ):
        vault_cls.return_value.status.return_value = SimpleNamespace(
            verification_status="VERIFIED"
        )
        kill_cls.return_value.is_active.return_value = False
        lts_cls.return_value.peek_active.return_value = None
        out = LiveUnattendedAuthorizationService(session).evaluate_enable_gates(
            1380
        )

    assert out["ok"] is False
    assert "LIVE_OFF" in out["blockers"]
    assert "ARM_OFF" in out["blockers"]
    assert "ACTIVATION_INACTIVE" in out["blockers"]


def test_enable_does_not_accept_live_approval_phrase_kwarg() -> None:
    """LIVE phrase는 enable 시그니처에서 제거됨 (계약 분리)."""

    import inspect

    params = inspect.signature(
        LiveUnattendedAuthorizationService.enable
    ).parameters
    assert "approval_phrase" not in params
    assert "source" in params


def test_evaluate_restore_gates_ignores_live_arm_activation() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    with patch.object(
        svc,
        "evaluate_enable_gates",
        return_value={
            "ok": False,
            "blockers": [
                "LIVE_OFF",
                "ARM_OFF",
                "ACTIVATION_INACTIVE",
                "KILL_SWITCH_ACTIVE",
            ],
            "checks": {},
            "live": "OFF",
            "arm": "OFF",
            "activation_id": None,
            "activation_expires_at": None,
            "execution_env": "REAL",
        },
    ):
        out = svc.evaluate_restore_gates(1380)
    assert out["ok"] is False
    assert out["blockers"] == ["KILL_SWITCH_ACTIVE"]


def test_renew_routes_to_restore_when_live_off() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        live_order_enabled=False,
        live_armed=False,
    )
    row = SimpleNamespace(
        live_unattended_authorization_id=4,
        user_broker_account_id=1380,
        status_code=STATUS_ACTIVE,
        enabled=True,
        authorized_until=datetime.now(timezone.utc) + timedelta(hours=12),
    )
    session.get.return_value = uba
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(
            svc,
            "restore_from_active_lease",
            return_value={"restored": True, "detail": {"live_restored": True}},
        ) as restore,
    ):
        out = svc.renew_due_for_uba(1380, actor="SYSTEM_UNATTENDED_RENEWAL")
    assert out["renewed"] is True
    assert out["reason"] == "RESTORED_FROM_LEASE"
    restore.assert_called_once()


def test_is_entry_authorized_true_without_lease() -> None:
    session = MagicMock()
    session.scalar.return_value = None
    assert (
        LiveUnattendedAuthorizationService(session).is_entry_authorized(1380)
        is True
    )


def test_is_entry_authorized_false_when_protective() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        enabled=True,
        status_code=STATUS_PROTECTIVE,
        entry_authorized=False,
        authorized_until=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.scalar.return_value = row
    assert (
        LiveUnattendedAuthorizationService(session).is_entry_authorized(1380)
        is False
    )


def test_expire_sets_protective_when_position() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        live_unattended_authorization_id=1,
        user_broker_account_id=1380,
        enabled=True,
        status_code=STATUS_ACTIVE,
        entry_authorized=True,
        protective_exit_authorized=True,
        authorized_until=datetime.now(timezone.utc) - timedelta(seconds=1),
        revoked_at=None,
        revoked_by=None,
        revoke_reason=None,
        updated_at=None,
    )
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "_has_open_position", return_value=True),
        patch.object(svc, "_fail_closed_on_expiry"),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
    ):
        svc._expire_authorization(row, actor="SYSTEM", reason="HORIZON_EXPIRED")
    assert row.status_code == STATUS_PROTECTIVE
    assert row.entry_authorized is False
    assert row.protective_exit_authorized is True
    assert row.enabled is True


def test_expire_full_when_flat() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        live_unattended_authorization_id=1,
        user_broker_account_id=1380,
        enabled=True,
        status_code=STATUS_ACTIVE,
        entry_authorized=True,
        protective_exit_authorized=True,
        authorized_until=datetime.now(timezone.utc) - timedelta(seconds=1),
        revoked_at=None,
        revoked_by=None,
        revoke_reason=None,
        updated_at=None,
    )
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "_has_open_position", return_value=False),
        patch.object(svc, "_fail_closed_on_expiry"),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
    ):
        svc._expire_authorization(row, actor="SYSTEM", reason="HORIZON_EXPIRED")
    assert row.status_code == STATUS_EXPIRED
    assert row.enabled is False


def test_renew_skips_arm_when_no_meaningful_extension() -> None:
    """lease ceiling에 이미 붙었으면 15초마다 arm()/Telegram 금지."""

    now = datetime.now(timezone.utc)
    until = now + timedelta(seconds=90)
    arm_exp = until - timedelta(seconds=5)
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        user_id=7,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=arm_exp,
    )
    row = SimpleNamespace(
        live_unattended_authorization_id=4,
        user_broker_account_id=1380,
        status_code=STATUS_ACTIVE,
        enabled=True,
        authorized_until=until,
        renewal_margin_seconds=600,
        arm_lease_ttl_seconds=3600,
        activation_renew_hours=8,
        source_activation_id=30,
        last_renewed_at=None,
        last_renewal_actor=None,
        last_renewal_detail=None,
        updated_at=None,
    )
    session = MagicMock()
    session.get.return_value = uba
    act = SimpleNamespace(
        live_trading_transition_id=30,
        expires_at=now + timedelta(hours=1),
    )
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(
            svc,
            "evaluate_renewal_gates",
            return_value={"ok": True, "blockers": []},
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as lts_cls,
        patch(
            "stock_platform.trading.live_arm_service.LiveArmService.arm"
        ) as arm_mock,
    ):
        lts_cls.return_value.peek_active.return_value = act
        out = svc.renew_due_for_uba(1380, actor="SYSTEM_UNATTENDED")
    assert out["renewed"] is False
    assert out["reason"] == "NOT_DUE"
    assert out["detail"]["arm_renew_skipped"] == "NO_MEANINGFUL_EXTENSION"
    arm_mock.assert_not_called()


def test_renew_arms_once_when_extension_meaningful() -> None:
    now = datetime.now(timezone.utc)
    until = now + timedelta(hours=12)
    arm_exp = now + timedelta(seconds=120)  # margin 600 이내
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        user_id=7,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=arm_exp,
    )
    row = SimpleNamespace(
        live_unattended_authorization_id=4,
        user_broker_account_id=1380,
        status_code=STATUS_ACTIVE,
        enabled=True,
        authorized_until=until,
        renewal_margin_seconds=600,
        arm_lease_ttl_seconds=3600,
        activation_renew_hours=8,
        source_activation_id=30,
        last_renewed_at=None,
        last_renewal_actor=None,
        last_renewal_detail={},
        updated_at=None,
    )
    session = MagicMock()
    session.get.return_value = uba
    act = SimpleNamespace(
        live_trading_transition_id=30,
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
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as lts_cls,
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
        lts_cls.return_value.peek_active.return_value = act
        out = svc.renew_due_for_uba(1380, actor="SYSTEM_UNATTENDED")
    assert out["renewed"] is True
    assert out["detail"]["arm_renewed"] is True
    arm_mock.assert_called_once()
    assert arm_mock.call_args.kwargs.get("force_renew") is True


def test_arm_force_renew_noop_without_meaningful_extension() -> None:
    from stock_platform.trading.live_arm_service import LiveArmService

    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=80)
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=7,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=expires,
        arm_token_hash="x",
        arm_armed_by="SYSTEM",
        arm_armed_at=now,
    )
    session = MagicMock()
    session.get.return_value = uba
    act = SimpleNamespace(
        live_trading_transition_id=1,
        expires_at=now + timedelta(hours=2),
        status="APPROVED",
    )
    svc = LiveArmService(session)
    with (
        patch.object(svc, "_require_uba", return_value=uba),
        patch.object(svc, "assert_arm_enable_preconditions"),
        patch.object(
            svc,
            "_clamp_arm_ttl",
            return_value=(80, expires + timedelta(seconds=5), act),
        ),
        patch.object(
            svc,
            "get_arm_status",
            return_value={"live_armed": True, "arm_expires_at": expires.isoformat()},
        ),
        patch(
            "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
        ) as pol,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ) as tg,
    ):
        pol.return_value.resolve.return_value = SimpleNamespace(
            arm_ttl_seconds=3600
        )
        out = svc.arm(
            1380,
            actor="SYSTEM_UNATTENDED",
            ttl_seconds=80,
            reason="UNATTENDED_ARM_RENEWAL",
            correlation_id="unatt-4",
            enforce_gates=True,
            force_renew=True,
        )
    assert out["arm_changed"] is False
    assert out["skipped_reason"] == "NO_MEANINGFUL_EXTENSION"
    tg.assert_not_called()


def test_status_dict_protective_needs_reauthorize() -> None:
    session = MagicMock()
    uba = SimpleNamespace(broker_code="UPBIT")
    row = SimpleNamespace(
        live_unattended_authorization_id=4,
        status_code=STATUS_PROTECTIVE,
        enabled=True,
        entry_authorized=False,
        protective_exit_authorized=True,
        authorized_until=datetime.now(timezone.utc) - timedelta(minutes=1),
        renewal_interval_seconds=3600,
        renewal_margin_seconds=600,
        arm_lease_ttl_seconds=3600,
        last_renewed_at=None,
        last_renewal_actor=None,
        last_renewal_detail={},
        approved_by="admin",
        approved_at=datetime.now(timezone.utc),
        broker_code="UPBIT",
    )
    session.get.return_value = uba
    session.scalar.return_value = row
    out = LiveUnattendedAuthorizationService(session).status_dict(1380)
    assert out["unattended_enabled"] is False
    assert out["needs_reauthorize"] is True
    assert out["entry_authorized"] is False
    assert out["status_code"] == STATUS_PROTECTIVE


def test_reauthorize_supersedes_protective_and_restores() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        user_id=7,
        live_order_enabled=False,
        live_armed=False,
    )
    existing = SimpleNamespace(
        live_unattended_authorization_id=4,
        status_code=STATUS_PROTECTIVE,
        enabled=True,
        entry_authorized=False,
        source_activation_id=30,
        authorized_until=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    act = SimpleNamespace(
        live_trading_transition_id=30,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.get.return_value = uba

    def _assign_id_on_flush() -> None:
        for call in session.add.call_args_list:
            obj = call.args[0]
            if getattr(obj, "live_unattended_authorization_id", None) is None:
                obj.live_unattended_authorization_id = 5

    session.flush.side_effect = _assign_id_on_flush
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch.object(svc, "get_active", side_effect=[existing, None]),
        patch.object(
            svc,
            "evaluate_restore_gates",
            return_value={"ok": True, "blockers": [], "live": "OFF"},
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as lts_cls,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_order_telegram"
        ),
        patch.object(
            svc,
            "restore_from_active_lease",
            return_value={"restored": True, "detail": {"live_restored": True}},
        ) as restore,
        patch.object(
            svc,
            "status_dict",
            return_value={
                "unattended_enabled": True,
                "status_code": STATUS_ACTIVE,
                "authorization_id": 5,
                "entry_authorized": True,
            },
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.get_settings",
            return_value=SimpleNamespace(
                live_unattended_default_horizon_hours=24,
                live_unattended_max_horizon_hours=168,
                live_unattended_renewal_interval_seconds=3600,
                live_unattended_renewal_margin_seconds=600,
                live_unattended_arm_lease_ttl_seconds=3600,
                live_unattended_activation_renew_hours=8,
            ),
        ),
    ):
        lts_cls.return_value.peek_active.return_value = act
        out = svc.reauthorize(
            1380,
            actor="admin",
            confirmation_text=CONFIRM_ENABLE,
            reason="test_reauth",
            source=SOURCE_ADMIN_UI,
            horizon_hours=24,
            correlation_id="test-corr",
        )
    assert out["reauthorized"] is True
    assert out["restore"]["restored"] is True
    assert existing.status_code == STATUS_EXPIRED
    assert existing.enabled is False
    session.add.assert_called()
    restore.assert_called_once()
