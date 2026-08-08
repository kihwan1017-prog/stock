"""Smoke one-shot grant dispatch TTL (Design A) — ARM deadline 분리.

실 adapter / Upbit /v1/orders 호출 금지.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.trading.smoke_one_shot_dispatch_grant import (
    GRANT_VERSION,
    SmokeOneShotGrantError,
    assert_smoke_one_shot_dispatch_allowed,
    build_smoke_one_shot_grant,
    dry_run_order_reusable_with_grant,
    issue_grant_on_run,
)
from stock_platform.trading.upbit_live_smoke_service import (
    UpbitLiveSmokeError,
    UpbitLiveSmokeService,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_dispatch_expires_after_issued_at() -> None:
    issued = _now()
    grant = build_smoke_one_shot_grant(
        run_id="uvs-a",
        order_id=1,
        outbox_id=2,
        uba_id=1380,
        owner_user_id=1,
        arm_snapshot_expires_at=issued + timedelta(seconds=30),
        dispatch_ttl_seconds=90,
        issued_at=issued,
        idempotency_key="smoke:uvs-a",
    )
    assert grant["version"] == GRANT_VERSION
    dispatched = datetime.fromisoformat(grant["dispatch_expires_at"])
    assert dispatched > issued
    assert abs((dispatched - issued).total_seconds() - 90) < 0.01
    # ARM snapshot은 더 짧아도 dispatch TTL과 독립
    arm_snap = datetime.fromisoformat(grant["arm_deadline_at"])
    assert arm_snap < dispatched


def test_issue_grant_uses_settings_ttl_not_arm_copy() -> None:
    session = MagicMock()
    arm_exp = _now() + timedelta(seconds=10)  # ARM 곧 만료
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        is_active=True,
        deleted_at=None,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=arm_exp,
    )
    session.get.return_value = uba
    run = SimpleNamespace(
        run_id="uvs-ttl",
        order_id=None,
        user_broker_account_id=1380,
        user_id=61,
        detail={},
    )
    with (
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_safety_audit"
        ),
        patch.object(UpbitLiveSmokeService, "_safe_flush", return_value=True),
        patch(
            "stock_platform.common.settings.get_settings",
            return_value=SimpleNamespace(
                smoke_one_shot_dispatch_ttl_seconds=90
            ),
        ),
    ):
        grant = UpbitLiveSmokeService(session)._issue_one_shot_dispatch_grant(
            run=run,  # type: ignore[arg-type]
            order_id=2001,
            outbox_id=3001,
            user_broker_account_id=1380,
            actor="t",
        )
    issued = datetime.fromisoformat(grant["issued_at"])
    dispatch = datetime.fromisoformat(grant["dispatch_expires_at"])
    assert abs((dispatch - issued).total_seconds() - 90) < 1.0
    # ARM snapshot은 복사되지만 Worker TTL이 아님
    assert datetime.fromisoformat(grant["arm_deadline_at"]) == arm_exp.astimezone(
        timezone.utc
    )


def test_confirm_arm_expired_blocks_grant() -> None:
    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        user_broker_account_id=1380,
        user_id=61,
        live_order_enabled=True,
        live_armed=True,
        arm_expires_at=_now() - timedelta(seconds=1),
    )
    with pytest.raises(UpbitLiveSmokeError) as ei:
        UpbitLiveSmokeService(session)._issue_one_shot_dispatch_grant(
            run=SimpleNamespace(run_id="r", detail={}),  # type: ignore[arg-type]
            order_id=1,
            outbox_id=2,
            user_broker_account_id=1380,
            actor="t",
        )
    assert "LIVE_ARM_EXPIRED" in ei.value.code


def test_dry_run_reusable_uses_dispatch_expires() -> None:
    assert (
        dry_run_order_reusable_with_grant(
            has_grant_issued=True,
            broker_order_id=None,
            submission_attempt_count=0,
            dispatch_expires_at=_now() + timedelta(seconds=30),
        )
        == "REUSABLE"
    )
    assert (
        dry_run_order_reusable_with_grant(
            has_grant_issued=True,
            broker_order_id=None,
            submission_attempt_count=0,
            dispatch_expires_at=_now() - timedelta(seconds=1),
        )
        == "MUST_RETIRE"
    )


def test_other_order_blocked() -> None:
    grant = build_smoke_one_shot_grant(
        run_id="uvs-test",
        order_id=1680,
        outbox_id=1117,
        uba_id=1380,
        owner_user_id=1,
        arm_snapshot_expires_at=_now() + timedelta(minutes=5),
        dispatch_ttl_seconds=90,
        idempotency_key="smoke:uvs-test",
    )
    run = SimpleNamespace(
        run_id="uvs-test",
        order_id=1680,
        user_broker_account_id=1380,
        user_id=1,
        execute_live=True,
        detail={"smoke_one_shot_dispatch_grant": grant},
    )
    order = SimpleNamespace(
        order_id=9999,
        user_broker_account_id=1380,
        broker_order_id=None,
        submission_attempt_count=0,
        metadata_payload={"smoke_run_id": "uvs-test"},
    )
    session = MagicMock()
    with (
        patch(
            "stock_platform.order.repository.TradingOrderRepository"
        ) as OR,
        patch(
            "stock_platform.trading.smoke_one_shot_dispatch_grant._load_smoke_run_for_order",
            return_value=run,
        ),
    ):
        OR.return_value.get.return_value = order
        with pytest.raises(SmokeOneShotGrantError, match="ORDER_MISMATCH"):
            assert_smoke_one_shot_dispatch_allowed(
                session,
                {
                    "order_id": 9999,
                    "user_broker_account_id": 1380,
                    "owner_user_id": 1,
                    "broker_code": "UPBIT",
                },
                outbox_id=1117,
            )


def test_issue_grant_on_run_writes_dispatch_field() -> None:
    run = SimpleNamespace(run_id="uvs-x", detail={})
    grant = issue_grant_on_run(
        run,
        order_id=10,
        outbox_id=20,
        uba_id=1380,
        owner_user_id=1,
        arm_snapshot_expires_at=_now() + timedelta(minutes=1),
        dispatch_ttl_seconds=60,
        idempotency_key="smoke:uvs-x",
    )
    assert "dispatch_expires_at" in run.detail["smoke_one_shot_dispatch_grant"]
    assert grant["dispatch_expires_at"] == run.detail[
        "smoke_one_shot_dispatch_grant"
    ]["dispatch_expires_at"]
