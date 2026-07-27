"""STEP 8-14 — HISTORICAL_PRESERVED 상태 모델 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_platform.broker.recovery_conflict_constants import (
    ACTIVE_REVIEW_STATUSES,
    REVIEW_COMPLETE_STATUSES,
    TERMINAL_REVIEW_STATUSES,
    RecoveryConflictResolution,
    RecoveryConflictReviewStatus,
)
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
    RecoveryConflictError,
)


def test_historical_preserved_not_active_review() -> None:
    assert (
        RecoveryConflictReviewStatus.HISTORICAL_PRESERVED
        not in ACTIVE_REVIEW_STATUSES
    )
    assert (
        RecoveryConflictReviewStatus.HISTORICAL_PRESERVED
        in TERMINAL_REVIEW_STATUSES
    )
    assert (
        RecoveryConflictReviewStatus.HISTORICAL_PRESERVED
        in REVIEW_COMPLETE_STATUSES
    )
    assert RecoveryConflictReviewStatus.PENDING_REVIEW in ACTIVE_REVIEW_STATUSES


def test_preserve_history_sets_status() -> None:
    session = MagicMock()
    row = MagicMock()
    row.review_status = RecoveryConflictReviewStatus.PENDING_REVIEW
    row.external_order_id_masked = "abcd…wxyz"
    row.user_broker_account_id = 58

    svc = BrokerRecoveryConflictService(session)
    svc.get = MagicMock(return_value=row)  # type: ignore[method-assign]

    out = svc.preserve_history(
        5,
        actor="admin:0",
        note="HISTORY_PRESERVE_STEP8_14_DESIGN",
    )
    assert out.review_status == (
        RecoveryConflictReviewStatus.HISTORICAL_PRESERVED
    )
    assert out.resolution_type == (
        RecoveryConflictResolution.PRESERVE_HISTORY
    )
    assert out.resolved_by == "admin:0"
    session.flush.assert_called()


def test_preserve_history_idempotent() -> None:
    session = MagicMock()
    row = MagicMock()
    row.review_status = RecoveryConflictReviewStatus.HISTORICAL_PRESERVED
    svc = BrokerRecoveryConflictService(session)
    svc.get = MagicMock(return_value=row)  # type: ignore[method-assign]
    out = svc.preserve_history(5, actor="admin:0", note="again")
    assert out.review_status == (
        RecoveryConflictReviewStatus.HISTORICAL_PRESERVED
    )


def test_preserve_blocks_ignored() -> None:
    session = MagicMock()
    row = MagicMock()
    row.review_status = RecoveryConflictReviewStatus.IGNORED
    svc = BrokerRecoveryConflictService(session)
    svc.get = MagicMock(return_value=row)  # type: ignore[method-assign]
    with pytest.raises(RecoveryConflictError) as exc:
        svc.preserve_history(5, actor="admin:0", note="nope")
    assert exc.value.code == "already_resolved"


def test_preserve_requires_note() -> None:
    session = MagicMock()
    svc = BrokerRecoveryConflictService(session)
    with pytest.raises(RecoveryConflictError) as exc:
        svc.preserve_history(5, actor="admin:0", note="  ")
    assert exc.value.code == "note_required"


def test_pending_review_still_active() -> None:
    """기존 PENDING은 ACTIVE_REVIEW에 남아 Dashboard Review Required."""

    assert RecoveryConflictReviewStatus.PENDING_REVIEW in ACTIVE_REVIEW_STATUSES
    assert (
        RecoveryConflictReviewStatus.PENDING_REVIEW
        not in REVIEW_COMPLETE_STATUSES
    )
