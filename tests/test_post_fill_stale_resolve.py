"""Post-fill stale MISMATCH resolve (no LIVE/order mutation)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.order.post_fill_verification_constants import (
    CONFIRM_RESOLVE_STALE_POST_FILL_MISMATCH,
    PostFillVerifyStatus,
)
from stock_platform.order.post_fill_verification_service import (
    PostFillVerificationService,
)
from stock_platform.order.post_fill_verifier import PostFillVerifyResult


@pytest.mark.unit
def test_resolve_stale_mismatch_requires_confirmation() -> None:
    svc = PostFillVerificationService(MagicMock())
    out = svc.resolve_stale_mismatch(
        60, actor="admin", confirmation_text="WRONG"
    )
    assert out["ok"] is False
    assert out["code"] == "CONFIRMATION_REQUIRED"


@pytest.mark.unit
def test_resolve_stale_mismatch_marks_verified_when_current_ok() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        verification_id=60,
        order_id=1792,
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        symbol="KRW-XRP",
        status_code=PostFillVerifyStatus.MISMATCH.value,
        last_error_code="POSITION_MISMATCH",
        detail={"db_qty": "0", "broker_qty": "3.11"},
        verified_at=None,
        claimed_by=None,
        claim_expires_at=None,
        updated_at=None,
    )
    session.get.return_value = row
    svc = PostFillVerificationService(session)

    with (
        patch(
            "stock_platform.order.post_fill_runner.PostFillVerifyRunner"
        ) as Runner,
        patch(
            "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
        ) as Repo,
        patch.object(svc, "_mark_verified", return_value=row) as mark,
        patch.object(svc, "_audit"),
    ):
        Runner.return_value.build_expected_positions_from_orders.return_value = (
            []
        )
        Runner.return_value.verify_uba_against_expected.return_value = (
            PostFillVerifyResult(
                ok=True, reason_code="VERIFY_OK", detail={}
            )
        )
        Repo.return_value.get_active_by_uba.return_value = (None, [])
        out = svc.resolve_stale_mismatch(
            60,
            actor="admin",
            confirmation_text=CONFIRM_RESOLVE_STALE_POST_FILL_MISMATCH,
        )
    assert out["ok"] is True
    assert out["code"] == "RESOLVED"
    mark.assert_called_once()
    detail = mark.call_args.kwargs["detail"]
    assert detail["resolution"] == "STALE_RESOLVED_AFTER_RECONCILE"


@pytest.mark.unit
def test_resolve_stale_mismatch_blocks_genuine() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        verification_id=60,
        order_id=1792,
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        symbol="KRW-XRP",
        status_code=PostFillVerifyStatus.MISMATCH.value,
        last_error_code="POSITION_MISMATCH",
        detail={},
    )
    session.get.return_value = row
    svc = PostFillVerificationService(session)
    with (
        patch(
            "stock_platform.order.post_fill_runner.PostFillVerifyRunner"
        ) as Runner,
        patch(
            "stock_platform.broker.account_repository.BrokerAccountSnapshotRepository"
        ) as Repo,
    ):
        Runner.return_value.build_expected_positions_from_orders.return_value = (
            []
        )
        Runner.return_value.verify_uba_against_expected.return_value = (
            PostFillVerifyResult(
                ok=False,
                reason_code="POSITION_MISMATCH",
                detail={"broker_qty": "1", "db_qty": "0"},
            )
        )
        Repo.return_value.get_active_by_uba.return_value = (None, [])
        out = svc.resolve_stale_mismatch(
            60,
            actor="admin",
            confirmation_text=CONFIRM_RESOLVE_STALE_POST_FILL_MISMATCH,
        )
    assert out["ok"] is False
    assert out["code"] == "GENUINE_CURRENT_MISMATCH"
