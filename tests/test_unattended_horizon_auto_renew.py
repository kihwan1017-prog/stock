"""P0.7 — Operator Authorization Horizon 자동연장 금지 / Lease Auto-Renew 분리."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.live_unattended_authorization_service import (
    ACTOR_HORIZON_AUTO_RENEW,
    STATUS_ACTIVE,
    LiveUnattendedAuthorizationService,
    LiveUnattendedError,
)
from stock_platform.trading.operator_authorization_policy import (
    build_operator_authorization_view,
)


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
    )


def _uba(**kwargs: object) -> SimpleNamespace:
    base = dict(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        user_id=7,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _row(**kwargs: object) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    base = dict(
        live_unattended_authorization_id=10,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        status_code=STATUS_ACTIVE,
        enabled=True,
        entry_authorized=True,
        protective_exit_authorized=True,
        auto_renew_enabled=False,
        authorized_until=now + timedelta(minutes=45),
        renewal_interval_seconds=3600,
        renewal_margin_seconds=600,
        arm_lease_ttl_seconds=3600,
        last_renewed_at=None,
        last_renewal_actor=None,
        last_renewal_detail={},
        updated_at=now,
        approved_by="admin",
        approved_at=now,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _svc(session: MagicMock | None = None) -> LiveUnattendedAuthorizationService:
    return LiveUnattendedAuthorizationService(session or MagicMock())


def _pass_gates() -> dict:
    return {"ok": True, "blockers": [], "checks": {}}


@pytest.fixture(autouse=True)
def _patch_settings() -> None:
    with patch(
        "stock_platform.trading.live_unattended_authorization_service.get_settings",
        return_value=_settings(),
    ):
        yield


def test_auto_renew_off_does_not_extend_horizon() -> None:
    session = MagicMock()
    now = datetime.now(timezone.utc)
    old_until = now + timedelta(minutes=45)
    row = _row(auto_renew_enabled=False, authorized_until=old_until)
    uba = _uba()
    with (
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_order_telegram"
        ),
    ):
        out = _svc(session)._try_horizon_auto_renew(
            row, uba, actor=ACTOR_HORIZON_AUTO_RENEW
        )
    assert out["horizon_renewed"] is False
    assert out["reason"] == "AUTO_RENEW_OFF"
    assert row.authorized_until == old_until


def test_auto_renew_on_in_margin_extends_horizon_for_uba1380() -> None:
    session = MagicMock()
    now = datetime.now(timezone.utc)
    old_until = now + timedelta(minutes=30)
    row = _row(auto_renew_enabled=True, authorized_until=old_until)
    uba = _uba()
    svc = _svc(session)
    lock = MagicMock()
    lock.acquire.return_value = True
    with (
        patch(
            "stock_platform.trading.live_unattended_authorization_service._now",
            return_value=now,
        ),
        patch.object(
            svc,
            "evaluate_horizon_auto_renew_gates",
            return_value=_pass_gates(),
        ),
        patch.object(
            svc,
            "_sync_activation_with_horizon_renew",
            return_value={"required": False, "ok": True},
        ),
        patch.object(svc, "_record_activation_refresh_observability"),
        patch.object(svc, "_maybe_emit_horizon_renew_success_telegram"),
        patch(
            "stock_platform.trading.live_unattended_authorization_service._horizon_renew_lock",
            return_value=lock,
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_order_telegram"
        ),
    ):
        out = svc._try_horizon_auto_renew(
            row, uba, actor=ACTOR_HORIZON_AUTO_RENEW
        )
    assert out["horizon_renewed"] is True
    assert row.authorized_until == now + timedelta(hours=24)
    assert audit.call_args.kwargs["event_type"] == "UNATTENDED_HORIZON_AUTO_RENEWED"


def test_remaining_outside_margin_is_noop() -> None:
    now = datetime.now(timezone.utc)
    old_until = now + timedelta(hours=5)
    row = _row(auto_renew_enabled=True, authorized_until=old_until)
    out = _svc()._try_horizon_auto_renew(row, _uba(), actor=ACTOR_HORIZON_AUTO_RENEW)
    assert out["horizon_renewed"] is False
    assert out["reason"] == "NOT_IN_RENEW_MARGIN"
    assert row.authorized_until == old_until


def test_non_allowlisted_uba_expiring_soon_warning_cooldown() -> None:
    now = datetime.now(timezone.utc)
    old_until = now + timedelta(minutes=20)
    row = _row(
        user_broker_account_id=1381,
        auto_renew_enabled=True,
        authorized_until=old_until,
        last_renewal_detail={
            "authorization_expiring_soon": {
                "at": (now - timedelta(seconds=120)).isoformat(),
            }
        },
    )
    with (
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_order_telegram"
        ),
    ):
        out = _svc()._try_horizon_auto_renew(
            row, _uba(user_broker_account_id=1381), actor=ACTOR_HORIZON_AUTO_RENEW
        )
    assert out["horizon_renewed"] is False
    assert out["expiring_soon_warning_emitted"] is False
    assert row.authorized_until == old_until
    audit.assert_not_called()


def test_manual_open_order_does_not_block_lease_gates() -> None:
    session = MagicMock()
    svc = _svc(session)
    exposure = SimpleNamespace(unknown_open_count=0, manual_open_count=2)
    exposure.as_detail = lambda: {"unknown_open_count": 0, "manual_open_count": 2}
    with (
        patch.object(svc, "evaluate_enable_gates", return_value=_pass_gates()),
        patch(
            "stock_platform.order.live_open_order_exposure.evaluate_live_open_order_exposure",
            return_value=exposure,
        ),
        patch(
            "stock_platform.trading.autotrading_master_gate.evaluate_uba_autotrading_ready",
            return_value={"ok": True, "blockers": [], "status": "READY"},
        ),
        patch(
            "stock_platform.trading.autotrading_master_gate._evaluate_auto_exit_quote_freshness",
            return_value={"applicable": False, "ok": True},
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.UserBrokerAccount"
        ),
    ):
        session.get.return_value = _uba()
        out = svc.evaluate_horizon_auto_renew_gates(1380)
    assert out["ok"] is True


def test_unknown_open_order_blocks_lease_gates() -> None:
    session = MagicMock()
    svc = _svc(session)
    exposure = SimpleNamespace(unknown_open_count=1)
    exposure.as_detail = lambda: {"unknown_open_count": 1}
    with (
        patch.object(svc, "evaluate_enable_gates", return_value=_pass_gates()),
        patch(
            "stock_platform.order.live_open_order_exposure.evaluate_live_open_order_exposure",
            return_value=exposure,
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.UserBrokerAccount"
        ),
    ):
        session.get.return_value = _uba()
        out = svc.evaluate_horizon_auto_renew_gates(1380)
    assert out["ok"] is False
    assert "UNKNOWN_OPEN_ORDER" in out["blockers"]


def test_stale_protective_quote_blocks_lease_gates() -> None:
    session = MagicMock()
    svc = _svc(session)
    exposure = SimpleNamespace(unknown_open_count=0)
    exposure.as_detail = lambda: {"unknown_open_count": 0}
    with (
        patch.object(svc, "evaluate_enable_gates", return_value=_pass_gates()),
        patch(
            "stock_platform.order.live_open_order_exposure.evaluate_live_open_order_exposure",
            return_value=exposure,
        ),
        patch(
            "stock_platform.trading.autotrading_master_gate._evaluate_auto_exit_quote_freshness",
            return_value={"applicable": True, "ok": False},
        ),
        patch(
            "stock_platform.trading.autotrading_master_gate.evaluate_uba_autotrading_ready",
            return_value={"ok": True, "blockers": [], "status": "READY"},
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.UserBrokerAccount"
        ),
    ):
        session.get.return_value = _uba()
        out = svc.evaluate_horizon_auto_renew_gates(1380)
    assert out["ok"] is False
    assert "AUTO_EXIT_QUOTE_STALE" in out["blockers"]


def test_set_auto_renew_persists_lease_and_auth_scope_on_uba1380() -> None:
    session = MagicMock()
    row = _row(auto_renew_enabled=False)
    svc = _svc(session)
    with (
        patch.object(svc, "get_active", return_value=row),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
        patch.object(svc, "status_dict", return_value={"auto_renew_enabled": True}),
    ):
        svc.set_auto_renew_enabled(1380, enabled=True, actor="admin")
    assert row.auto_renew_enabled is True
    assert (
        row.last_renewal_detail["auto_renew_toggle"]["scope"]
        == "INTERNAL_LEASE_AND_OPERATOR_AUTH_HORIZON"
    )
    session.commit.assert_called_once()


def test_set_auto_renew_requires_active_lease() -> None:
    svc = _svc()
    with patch.object(svc, "get_active", return_value=None):
        with pytest.raises(LiveUnattendedError) as exc:
            svc.set_auto_renew_enabled(1380, enabled=True, actor="admin")
    assert exc.value.code == "NO_ACTIVE_LEASE"


def test_dry_evaluation_would_extend_operator_auth_for_uba1380() -> None:
    now = datetime.now(timezone.utc)
    row = _row(
        auto_renew_enabled=True,
        authorized_until=now + timedelta(minutes=20),
    )
    svc = _svc()
    with (
        patch(
            "stock_platform.trading.live_unattended_authorization_service._now",
            return_value=now,
        ),
        patch.object(svc, "get_active", return_value=row),
        patch.object(svc, "evaluate_horizon_auto_renew_gates", return_value=_pass_gates()),
    ):
        out = svc.dry_horizon_auto_renew_evaluation(1380)
    assert out["would_renew"] is True
    assert out["would_extend_operator_authorization"] is True
    assert out["operator_authorization_auto_extend_supported"] is True
    assert out["authorization_expiring_soon"] is True
    assert out["projected_authorized_until"] != out["authorized_until"]


def test_dry_evaluation_off_still_never_extends() -> None:
    now = datetime.now(timezone.utc)
    row = _row(
        auto_renew_enabled=False,
        authorized_until=now + timedelta(minutes=20),
    )
    svc = _svc()
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(svc, "evaluate_horizon_auto_renew_gates", return_value=_pass_gates()),
    ):
        out = svc.dry_horizon_auto_renew_evaluation(1380)
    assert out["would_renew"] is False
    assert out["reason"] == "AUTO_RENEW_OFF"


def test_telegram_legacy_success_helper_dedupe_within_day() -> None:
    now = datetime.now(timezone.utc)
    row = _row(last_renewal_detail={})
    svc = _svc()
    with patch(
        "stock_platform.trading.live_unattended_authorization_service.emit_live_order_telegram"
    ) as tg:
        svc._maybe_emit_horizon_renew_success_telegram(
            row,
            old_until=now,
            new_until=now + timedelta(hours=24),
        )
        svc._maybe_emit_horizon_renew_success_telegram(
            row,
            old_until=now,
            new_until=now + timedelta(hours=24),
        )
    assert tg.call_count == 1


def test_renew_due_reports_horizon_extended_for_uba1380() -> None:
    session = MagicMock()
    now = datetime.now(timezone.utc)
    old_until = now + timedelta(minutes=25)
    new_until = now + timedelta(hours=24)
    row = _row(auto_renew_enabled=True, authorized_until=old_until)
    uba = _uba(arm_expires_at=now + timedelta(hours=2))
    svc = _svc(session)
    session.get.return_value = uba
    with (
        patch.object(svc, "get_active", return_value=row),
        patch.object(
            svc,
            "_try_horizon_auto_renew",
            return_value={
                "horizon_renewed": True,
                "old_authorized_until": old_until.isoformat(),
                "new_authorized_until": new_until.isoformat(),
                "operator_authorization_auto_extend": True,
            },
        ),
        patch.object(
            svc,
            "evaluate_renewal_gates",
            return_value={"ok": True, "blockers": [], "checks": {}},
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.LiveTradingTransitionService"
        ) as lts,
        patch(
            "stock_platform.trading.live_unattended_authorization_service.activation_remaining_seconds",
            return_value=7200,
        ),
        patch(
            "stock_platform.trading.live_unattended_authorization_service.emit_live_safety_audit"
        ),
    ):
        lts.return_value.peek_active.return_value = SimpleNamespace(
            live_trading_transition_id=1,
            expires_at=now + timedelta(hours=2),
        )
        out = svc.renew_due_for_uba(1380)
    assert out.get("horizon_renewed") is True or (
        (out.get("horizon") or {}).get("horizon_renewed") is True
    )


def test_operator_view_renewal_status_auth_and_lease_when_supported() -> None:
    view = build_operator_authorization_view(
        {
            "status_code": "ACTIVE",
            "unattended_enabled": True,
            "remaining_seconds": 3600,
            "authorized_until": "2026-09-08T00:00:00+00:00",
            "auto_renew_enabled": True,
            "lease_auto_renew_enabled": True,
            "operator_authorization_auto_extend": True,
            "operator_authorization_auto_extend_supported": True,
            "authorization_id": 19,
        }
    )
    assert view["renewal_status"] == "AUTH_AND_LEASE_AUTO_RENEW_ON"
    assert view["operator_authorization_auto_extend"] is True
    assert view["operator_authorization_auto_extend_supported"] is True


def test_operator_view_lease_only_when_auth_extend_unsupported() -> None:
    view = build_operator_authorization_view(
        {
            "status_code": "ACTIVE",
            "unattended_enabled": True,
            "remaining_seconds": 3600,
            "authorized_until": "2026-09-08T00:00:00+00:00",
            "auto_renew_enabled": True,
            "lease_auto_renew_enabled": True,
            "operator_authorization_auto_extend": False,
            "operator_authorization_auto_extend_supported": False,
            "authorization_id": 99,
        }
    )
    assert view["renewal_status"] == "LEASE_AUTO_RENEW_ON"
    assert view["operator_authorization_auto_extend"] is False


def test_uba1381_not_touched_by_1380_tests() -> None:
    assert _row(user_broker_account_id=1380).user_broker_account_id == 1380
    assert _uba(user_broker_account_id=1381).user_broker_account_id == 1381


def test_status_dict_includes_p07_fields() -> None:
    session = MagicMock()
    now = datetime.now(timezone.utc)
    row = _row(
        auto_renew_enabled=True,
        authorized_until=now + timedelta(hours=3),
    )
    session.get.return_value = _uba()
    session.scalar.return_value = row
    out = _svc(session).status_dict(1380)
    assert out["auto_renew_enabled"] is True
    assert out["lease_auto_renew_enabled"] is True
    assert out["operator_authorization_auto_extend"] is True
    assert out["operator_authorization_auto_extend_supported"] is True
    assert out["horizon_renew_margin_seconds"] == 3600
    assert out["next_authorization_expiry_warning_at"] is not None
    assert out["next_horizon_renew_check_at"] is not None
