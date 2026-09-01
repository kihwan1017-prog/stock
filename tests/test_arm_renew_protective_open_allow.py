"""ARM renew while 24H lease ACTIVE — protective AUTO SELL must not block."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
)
from stock_platform.trading.live_arm_service import (
    MIN_MEANINGFUL_ARM_EXTENSION_SECONDS,
    LiveArmService,
)


def test_exclude_auto_protective_sell_from_db_open_count() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.broker.open_order_gate_classification.evaluate_open_order_gate_for_uba"
    ) as ev:
        ev.return_value = SimpleNamespace(
            blocking_dict=lambda: {
                "db_open": 1,
                "submission_unknown": 0,
                "cancel_pending": 0,
                "replace_pending": 0,
                "auto_protective_open_excluded": 1,
                "auto_entry_buy_excluded": 0,
            },
            class_counts={},
            arm_renew_block_reason="db_open_orders:MANUAL_OPEN:100",
        )
        out = BrokerRecoveryConflictService(session).count_blocking_orders_for_uba(
            1380, exclude_auto_protective_exits=True
        )
    assert out["db_open"] == 1
    assert out["auto_protective_open_excluded"] == 1


def test_exclude_only_auto_sell_leaves_zero_when_only_protective() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.broker.open_order_gate_classification.evaluate_open_order_gate_for_uba"
    ) as ev:
        ev.return_value = SimpleNamespace(
            blocking_dict=lambda: {
                "db_open": 0,
                "submission_unknown": 0,
                "cancel_pending": 0,
                "replace_pending": 0,
                "auto_protective_open_excluded": 1,
                "auto_entry_buy_excluded": 0,
            },
            class_counts={},
            arm_renew_block_reason=None,
        )
        out = BrokerRecoveryConflictService(session).count_blocking_orders_for_uba(
            1380, exclude_auto_protective_exits=True
        )
    assert out["db_open"] == 0
    assert out["auto_protective_open_excluded"] == 1


def test_unknown_orders_still_block_even_with_exclude() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.broker.open_order_gate_classification.evaluate_open_order_gate_for_uba"
    ) as ev:
        ev.return_value = SimpleNamespace(
            blocking_dict=lambda: {
                "db_open": 0,
                "submission_unknown": 1,
                "cancel_pending": 0,
                "replace_pending": 0,
                "auto_protective_open_excluded": 0,
                "auto_entry_buy_excluded": 0,
            },
            class_counts={},
            arm_renew_block_reason="submission_unknown:1",
        )
        out = BrokerRecoveryConflictService(session).count_blocking_orders_for_uba(
            1380, exclude_auto_protective_exits=True
        )
    assert out["db_open"] == 0
    assert out["submission_unknown"] == 1


def test_arm_renew_math_lease_23h_arm_9m() -> None:
    """lease remaining 23h, ARM remaining 9m → renew to now+1h."""
    now = datetime(2026, 8, 23, 3, 35, tzinfo=timezone.utc)
    arm_exp = now + timedelta(minutes=9)
    lease_until = now + timedelta(hours=23)
    margin = 600
    arm_ttl = 3600
    arm_remaining = int((arm_exp - now).total_seconds())
    assert arm_remaining <= margin
    lease_remaining = int((lease_until - now).total_seconds())
    effective_ttl = min(arm_ttl, lease_remaining)
    intended = now + timedelta(seconds=effective_ttl)
    if intended > lease_until:
        intended = lease_until
    extension = (intended - arm_exp).total_seconds()
    assert extension >= float(MIN_MEANINGFUL_ARM_EXTENSION_SECONDS)
    assert intended == now + timedelta(hours=1)


def test_arm_renew_math_outside_margin_noop() -> None:
    now = datetime(2026, 8, 23, 3, 0, tzinfo=timezone.utc)
    arm_exp = now + timedelta(minutes=30)
    margin = 600
    arm_remaining = int((arm_exp - now).total_seconds())
    assert arm_remaining > margin


def test_arm_renew_math_lease_ceiling() -> None:
    now = datetime(2026, 8, 23, 3, 35, tzinfo=timezone.utc)
    arm_exp = now + timedelta(minutes=9)
    lease_until = now + timedelta(minutes=30)
    arm_ttl = 3600
    lease_remaining = max(60, int((lease_until - now).total_seconds()))
    effective_ttl = min(arm_ttl, lease_remaining)
    intended = now + timedelta(seconds=effective_ttl)
    if intended > lease_until:
        intended = lease_until
    assert intended == lease_until
    extension = (intended - arm_exp).total_seconds()
    assert extension >= 60


def test_arm_renew_math_extension_under_60s_noop() -> None:
    now = datetime(2026, 8, 23, 3, 35, tzinfo=timezone.utc)
    arm_exp = now + timedelta(seconds=50)
    lease_until = now + timedelta(seconds=80)
    intended = min(now + timedelta(seconds=3600), lease_until)
    extension = (intended - arm_exp).total_seconds()
    assert extension < float(MIN_MEANINGFUL_ARM_EXTENSION_SECONDS)


def test_scan_renew_isolates_uba_errors() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        user_broker_account_id=1380,
        authorized_until=datetime.now(timezone.utc) + timedelta(hours=20),
        enabled=True,
        status_code="ACTIVE",
    )
    session.scalars = MagicMock(return_value=[row])
    from stock_platform.trading.live_unattended_authorization_service import (
        LiveUnattendedAuthorizationService,
    )

    svc = LiveUnattendedAuthorizationService(session)
    svc.renew_due_for_uba = MagicMock(side_effect=RuntimeError("db_open"))  # type: ignore[method-assign]
    out = svc.scan_renew_and_expire(actor="TEST")
    assert out["scanned"] == 1
    assert out["skipped"] == 1
    assert len(out["errors"]) == 1
    assert out["errors"][0]["error"] == "RuntimeError"


def test_arm_passes_allow_auto_protective_flag() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        arm_token_hash="x",
        arm_armed_by="t",
        arm_armed_at=datetime.now(timezone.utc),
    )
    session.get = MagicMock(return_value=uba)
    svc = LiveArmService(session)
    seen: dict = {}

    def _assert(uid, **kwargs):  # noqa: ANN001
        seen.update(kwargs)
        return {"blocking": {}}

    svc.assert_arm_enable_preconditions = _assert  # type: ignore[method-assign]
    svc._clamp_arm_ttl = MagicMock(  # type: ignore[method-assign]
        return_value=(
            3600,
            datetime.now(timezone.utc) + timedelta(hours=1),
            SimpleNamespace(live_trading_transition_id=1, expires_at=None),
        )
    )
    with patch(
        "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
    ) as pol:
        pol.return_value.resolve.return_value = SimpleNamespace(
            arm_ttl_seconds=3600
        )
        with patch(
            "stock_platform.trading.live_arm_service.collect_scheduler_readiness",
            return_value=SimpleNamespace(
                trading_scheduler_actual_state="PAUSED",
                trading_scheduler_desired_state="PAUSE",
            ),
        ):
            with patch(
                "stock_platform.trading.live_arm_service.emit_live_safety_audit"
            ):
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
    assert seen.get("allow_auto_protective_open_orders") is True
    assert seen.get("allow_known_auto_entry_buys") is True
