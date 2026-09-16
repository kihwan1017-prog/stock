"""STEP 8-16 — Account Pause Resume 계약 테스트."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
    RecoveryConflictError,
)


def _uba(**extra: object) -> SimpleNamespace:
    base = {
        "is_active": True,
        "broker_code": "UPBIT",
        "connection_status": "CONNECTED",
        "live_order_enabled": False,
        "live_armed": False,
    }
    base.update(extra)
    return SimpleNamespace(**base)


_EMPTY_BLOCKING = {
    "db_open": 0,
    "submission_unknown": 0,
    "cancel_pending": 0,
    "replace_pending": 0,
}


def _wire_resume_stubs(svc: BrokerRecoveryConflictService) -> None:
    """production resume_account는 resume_check를 호출하지 않는다."""

    svc.count_active_for_uba = MagicMock(return_value=0)
    svc.count_blocking_orders_for_uba = MagicMock(return_value=_EMPTY_BLOCKING)


def test_resume_idempotent_when_already_unpaused() -> None:
    session = MagicMock()
    svc = BrokerRecoveryConflictService(session)
    _wire_resume_stubs(svc)
    session.get.return_value = _uba()
    state = SimpleNamespace(
        trading_paused=False,
        recovery_status="SUCCESS",
        last_error_summary=None,
        last_error_code=None,
        auto_retry_enabled=True,
        updated_at=None,
    )
    session.scalar.return_value = state

    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ):
        result = svc.resume_account(
            58,
            actor="admin:1",
            reason="RECOVERY_REVIEW_COMPLETED_HISTORY_PRESERVED_OPERATOR_APPROVED",
            correlation_id="corr-idem",
        )

    assert result["already_resumed"] is True
    assert result["resumed"] is False
    assert result["trading_paused"] is False
    assert result["broker_code"] == "UPBIT"
    assert result["live_arm_unchanged"] is True
    assert result["scheduler_unchanged"] is True
    assert state.trading_paused is False
    session.flush.assert_not_called()


def test_resume_success_clears_pause() -> None:
    session = MagicMock()
    svc = BrokerRecoveryConflictService(session)
    _wire_resume_stubs(svc)
    session.get.return_value = _uba()
    state = SimpleNamespace(
        trading_paused=True,
        recovery_status="SUCCESS",
        last_error_summary="UPBIT_REMOTE_ONLY_ORDER_REVIEW",
        last_error_code="manual_review_required",
        auto_retry_enabled=False,
        updated_at=None,
    )
    session.scalar.return_value = state

    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ):
        result = svc.resume_account(
            58,
            actor="admin:1",
            reason="RECOVERY_REVIEW_COMPLETED_HISTORY_PRESERVED_OPERATOR_APPROVED",
            correlation_id="corr-ok",
        )

    assert result["resumed"] is True
    assert result["already_resumed"] is False
    assert result["live_order_enabled"] is False
    assert result["live_armed"] is False
    assert result["live_arm_unchanged"] is True
    assert result["scheduler_unchanged"] is True
    assert state.trading_paused is False
    assert state.last_error_code is None
    session.flush.assert_called()


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"reason": "", "correlation_id": "c"}, "reason_required"),
        ({"reason": "r", "correlation_id": ""}, "correlation_id_required"),
    ],
)
def test_resume_requires_reason_correlation(
    kwargs: dict, code: str
) -> None:
    svc = BrokerRecoveryConflictService(MagicMock())
    with pytest.raises(RecoveryConflictError) as exc:
        svc.resume_account(58, actor="admin:1", **kwargs)
    assert exc.value.code == code
