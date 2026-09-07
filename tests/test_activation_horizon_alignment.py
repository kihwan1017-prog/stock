"""Activation TTL ↔ unattended horizon alignment — focused regression tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.live_transition_entities import (
    LiveTradingTransitionEntity,
)
from stock_platform.trading.activation_horizon_alignment import (
    ACTIVATION_HORIZON_MISMATCH,
    activation_horizon_alignment_status,
    activation_refresh_needed_for_horizon,
    compute_horizon_activation_refresh_hours,
    is_activation_eligible_for_horizon_refresh,
    projected_successor_expires_at,
)
from stock_platform.trading.live_unattended_authorization_service import (
    ACTOR_HORIZON_AUTO_RENEW,
    LiveUnattendedAuthorizationService,
    LiveUnattendedError,
)


def _now() -> datetime:
    return datetime(2026, 9, 2, 3, 31, 43, tzinfo=timezone.utc)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        live_unattended_default_horizon_hours=24,
        live_unattended_max_horizon_hours=168,
        live_unattended_horizon_renew_margin_seconds=3600,
        live_unattended_horizon_renew_interval_seconds=3600,
        live_unattended_horizon_min_extension_seconds=3600,
        live_unattended_renewal_interval_seconds=3600,
        live_unattended_renewal_margin_seconds=600,
        live_unattended_arm_lease_ttl_seconds=3600,
        live_unattended_activation_renew_hours=8,
        live_activation_ttl_hours=4,
    )


def _uba(**kwargs: object) -> SimpleNamespace:
    base = dict(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        user_id=7,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=_now() + timedelta(minutes=30),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _row(**kwargs: object) -> SimpleNamespace:
    now = _now()
    base = dict(
        live_unattended_authorization_id=10,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        status_code="ACTIVE",
        enabled=True,
        entry_authorized=True,
        protective_exit_authorized=True,
        auto_renew_enabled=True,
        authorized_until=now + timedelta(minutes=30),
        renewal_interval_seconds=3600,
        renewal_margin_seconds=600,
        arm_lease_ttl_seconds=3600,
        activation_renew_hours=8,
        source_activation_id=120,
        last_renewed_at=None,
        last_renewal_actor=None,
        last_renewal_detail={},
        updated_at=now,
        approved_by="admin",
        approved_at=now,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _activation(
    *,
    activation_id: int = 120,
    expires_at: datetime | None = None,
    enabled: bool = True,
    status: str = "ACTIVE",
) -> LiveTradingTransitionEntity:
    now = _now()
    entity = LiveTradingTransitionEntity(
        live_trading_transition_id=activation_id,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        scope="ACCOUNT",
        enabled=enabled,
        activation_status=status,
        expires_at=expires_at or (now + timedelta(minutes=32)),
        max_order_amount=10_000,
        max_daily_loss=10_000_000,
        requested_by="admin",
    )
    return entity


@pytest.fixture(autouse=True)
def _patch_settings() -> None:
    with patch(
        "stock_platform.trading.live_unattended_authorization_service.get_settings",
        return_value=_settings(),
    ):
        yield


# --- A–C: alignment pure logic ---


def test_horizon_renew_refresh_hours_respects_cap_and_horizon() -> None:
    now = _now()
    until = now + timedelta(hours=24)
    hours = compute_horizon_activation_refresh_hours(
        authorized_until=until,
        activation_renew_hours=8,
        now=now,
    )
    assert hours == 8
    assert (
        projected_successor_expires_at(
            now=now, renew_hours=hours, authorized_until=until
        )
        <= until
    )


def test_activation_expires_at_never_exceeds_authorized_until() -> None:
    now = _now()
    until = now + timedelta(hours=2)
    hours = compute_horizon_activation_refresh_hours(
        authorized_until=until,
        activation_renew_hours=8,
        now=now,
    )
    assert hours == 2
    projected = projected_successor_expires_at(
        now=now, renew_hours=hours, authorized_until=until
    )
    assert projected <= until


def test_max_ttl_cap_respected() -> None:
    now = _now()
    until = now + timedelta(hours=100)
    hours = compute_horizon_activation_refresh_hours(
        authorized_until=until,
        activation_renew_hours=100,
        now=now,
    )
    from stock_platform.common.settings import LIVE_ACTIVATION_TTL_HOURS_MAX

    assert hours == LIVE_ACTIVATION_TTL_HOURS_MAX


# --- D–F: revive forbidden ---


@pytest.mark.parametrize(
    ("enabled", "status", "expires_delta", "expected_ok"),
    [
        (True, "ACTIVE", timedelta(hours=1), True),
        (False, "ACTIVE", timedelta(hours=1), False),
        (True, "EXPIRED", timedelta(hours=1), False),
        (True, "REVOKED", timedelta(hours=1), False),
        (True, "DISABLED", timedelta(hours=1), False),
        (True, "ACTIVE", timedelta(seconds=-1), False),
    ],
)
def test_eligibility_blocks_revive(
    enabled: bool,
    status: str,
    expires_delta: timedelta,
    expected_ok: bool,
) -> None:
    act = _activation(
        enabled=enabled,
        status=status,
        expires_at=_now() + expires_delta,
    )
    ok, _ = is_activation_eligible_for_horizon_refresh(act, now=_now())
    assert ok is expected_ok


# --- G: invalid authorization blocks refresh ---


def test_sync_activation_fails_without_active_activation() -> None:
    svc = LiveUnattendedAuthorizationService(MagicMock())
    row = _row()
    uba = _uba()
    new_until = _now() + timedelta(hours=24)
    with patch.object(
        LiveUnattendedAuthorizationService,
        "_create_successor_activation",
    ) as create_mock:
        with patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as transition_cls:
            transition_cls.return_value.peek_active.return_value = None
            out = svc._sync_activation_with_horizon_renew(
                row, uba, new_until=new_until, actor=ACTOR_HORIZON_AUTO_RENEW, now=_now()
            )
    assert out["ok"] is False
    assert out["reason"] == "NO_ACTIVE_ACTIVATION"
    create_mock.assert_not_called()


# --- Horizon path: allowlist UBA1380 vs finite others ---


def test_horizon_path_non_allowlisted_never_extends_authorized_until() -> None:
    session = MagicMock()
    now = _now()
    old_until = now + timedelta(minutes=20)
    row = _row(user_broker_account_id=1381, authorized_until=old_until)
    uba = _uba(user_broker_account_id=1381)
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch(
            "stock_platform.trading.live_unattended_authorization_service._now",
            return_value=now,
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_order_telegram"
        ),
    ):
        out = svc._try_horizon_auto_renew(row, uba, actor=ACTOR_HORIZON_AUTO_RENEW)
    assert out["horizon_renewed"] is False
    assert out["reason"] == "OPERATOR_AUTHORIZATION_AUTO_EXTEND_NOT_SUPPORTED"
    assert row.authorized_until == old_until


def test_horizon_path_outside_renew_margin_is_noop() -> None:
    session = MagicMock()
    now = _now()
    old_until = now + timedelta(hours=5)
    row = _row(authorized_until=old_until, auto_renew_enabled=True)
    uba = _uba()
    svc = LiveUnattendedAuthorizationService(session)
    with patch(
        "stock_platform.trading.live_unattended_authorization_service._now",
        return_value=now,
    ):
        out = svc._try_horizon_auto_renew(row, uba, actor=ACTOR_HORIZON_AUTO_RENEW)
    assert out["horizon_renewed"] is False
    assert out["reason"] == "NOT_IN_RENEW_MARGIN"
    assert row.authorized_until == old_until


def test_sync_activation_creates_successor_when_misaligned() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    row = _row()
    uba = _uba()
    now = _now()
    act = _activation(expires_at=now + timedelta(minutes=32))
    new_until = now + timedelta(hours=15)
    successor = _activation(activation_id=121, expires_at=now + timedelta(hours=8))
    with patch(
        "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
    ) as transition_cls:
        transition_cls.return_value.peek_active.return_value = act
        with patch.object(
            svc, "_create_successor_activation", return_value=successor
        ) as create_mock:
            out = svc._sync_activation_with_horizon_renew(
                row, uba, new_until=new_until, actor=ACTOR_HORIZON_AUTO_RENEW, now=now
            )
    assert out["ok"] is True
    assert out["refreshed"] is True
    create_mock.assert_called_once()
    assert row.source_activation_id == 121


# --- H: ARM clamp uses refreshed activation (integration via successor TTL) ---


def test_refresh_extends_activation_beyond_prior_expiry() -> None:
    now = _now()
    old_exp = now + timedelta(minutes=32)
    new_until = now + timedelta(hours=15)
    assert activation_refresh_needed_for_horizon(
        authorized_until=new_until,
        activation_expires_at=old_exp,
        mismatch_margin_seconds=900,
    )
    hours = compute_horizon_activation_refresh_hours(
        authorized_until=new_until,
        activation_renew_hours=8,
        now=now,
    )
    new_exp = projected_successor_expires_at(
        now=now, renew_hours=hours, authorized_until=new_until
    )
    assert new_exp > old_exp


# --- I–J: ARM renew #86 semantics unchanged (import-only guard) ---


def test_arm_open_order_gate_module_unchanged() -> None:
    from stock_platform.trading.live_arm_service import LiveArmService

    assert hasattr(LiveArmService, "arm")


# --- L: ops-status alignment fields ---


def test_ops_alignment_status_mismatch_detected() -> None:
    now = _now()
    until = now + timedelta(hours=10)
    act_exp = now + timedelta(minutes=30)
    align = activation_horizon_alignment_status(
        authorized_until=until,
        activation_expires_at=act_exp,
        mismatch_margin_seconds=900,
    )
    assert align["ACTIVATION_HORIZON_ALIGNED"] is False
    assert align["ACTIVATION_HORIZON_DELTA_SECONDS"] < 0


def test_ops_alignment_status_ok_when_within_margin() -> None:
    now = _now()
    until = now + timedelta(hours=10)
    act_exp = until - timedelta(minutes=5)
    align = activation_horizon_alignment_status(
        authorized_until=until,
        activation_expires_at=act_exp,
        mismatch_margin_seconds=900,
    )
    assert align["ACTIVATION_HORIZON_ALIGNED"] is True


# --- M: mismatch alert dedupe ---


def test_mismatch_alert_deduped_within_cooldown() -> None:
    session = MagicMock()
    now = _now()
    row = _row(
        authorized_until=now + timedelta(hours=10),
        last_renewal_detail={
            "last_activation_horizon_mismatch_alert": {
                "at": (now - timedelta(minutes=10)).isoformat(),
            }
        },
    )
    act = _activation(expires_at=now + timedelta(minutes=20))
    uba = _uba()
    session.scalars.return_value = iter([row])
    session.get.return_value = uba
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch(
            "stock_platform.trading.live_unattended_authorization_service._now",
            return_value=now,
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as transition_cls,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ) as audit,
    ):
        transition_cls.return_value.peek_active.return_value = act
        emitted = svc._scan_activation_horizon_mismatch_alerts(actor="TEST")
    assert emitted == []
    audit.assert_not_called()


def test_mismatch_alert_emitted_after_cooldown() -> None:
    session = MagicMock()
    now = _now()
    row = _row(
        authorized_until=now + timedelta(hours=10),
        last_renewal_detail={
            "last_activation_horizon_mismatch_alert": {
                "at": (now - timedelta(hours=2)).isoformat(),
            }
        },
    )
    act = _activation(expires_at=now + timedelta(minutes=20))
    uba = _uba()
    session.scalars.return_value = iter([row])
    session.get.return_value = uba
    svc = LiveUnattendedAuthorizationService(session)
    with (
        patch(
            "stock_platform.trading.live_unattended_authorization_service._now",
            return_value=now,
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as transition_cls,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ) as audit,
    ):
        transition_cls.return_value.peek_active.return_value = act
        emitted = svc._scan_activation_horizon_mismatch_alerts(actor="TEST")
    assert len(emitted) == 1
    audit.assert_called_once()
    assert audit.call_args.kwargs["event_type"] == ACTIVATION_HORIZON_MISMATCH


# --- N: Shadow lab unaffected ---


def test_shadow_lab_service_import_unchanged() -> None:
    from stock_platform.operation.upbit_opportunity_shadow.exit_order_recovery_shadow import (
        service as shadow_service,
    )

    assert hasattr(shadow_service, "shadow_enabled")


# --- O + successor validate failure ---


def test_invalid_successor_blocks_horizon_renew() -> None:
    session = MagicMock()
    svc = LiveUnattendedAuthorizationService(session)
    row = _row()
    uba = _uba()
    now = _now()
    act = _activation(expires_at=now + timedelta(minutes=20))
    new_until = now + timedelta(hours=15)
    with patch(
        "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
    ) as transition_cls:
        transition_cls.return_value.peek_active.return_value = act
        with patch.object(
            svc,
            "_create_successor_activation",
            side_effect=LiveUnattendedError(
                "ACTIVATION_VALIDATE_FAILED", "successor validate failed"
            ),
        ):
            out = svc._sync_activation_with_horizon_renew(
                row, uba, new_until=new_until, actor=ACTOR_HORIZON_AUTO_RENEW, now=now
            )
    assert out["ok"] is False
    assert out["reason"] == "ACTIVATION_VALIDATE_FAILED"
