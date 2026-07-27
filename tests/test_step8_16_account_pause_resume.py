"""STEP 8-16 — Account Pause Resume 계약 테스트."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
    RecoveryConflictError,
)


def test_resume_idempotent_when_already_unpaused() -> None:
    session = MagicMock()
    svc = BrokerRecoveryConflictService(session)
    session.get.return_value = SimpleNamespace(is_active=True)
    svc.count_active_for_uba = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc.count_blocking_orders_for_uba = MagicMock(  # type: ignore[method-assign]
        return_value={
            "db_open": 0,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
    )
    state = SimpleNamespace(
        trading_paused=False,
        recovery_status="SUCCESS",
        last_error_summary=None,
        last_error_code=None,
        auto_retry_enabled=True,
        updated_at=None,
    )
    session.scalar.return_value = state

    class _Vault:
        def assert_live_order_allowed(self, *_a, **_k):
            return None

    import stock_platform.broker.recovery_conflict_service as mod

    original = mod.BrokerCredentialVaultService
    mod.BrokerCredentialVaultService = lambda _s: _Vault()  # type: ignore[misc,assignment]
    try:
        result = svc.resume_account(
            58,
            actor="admin:1",
            reason="RECOVERY_REVIEW_COMPLETED_HISTORY_PRESERVED_OPERATOR_APPROVED",
            correlation_id="corr-idem",
        )
    finally:
        mod.BrokerCredentialVaultService = original

    assert result["already_resumed"] is True
    assert result["resumed"] is False
    assert result["trading_paused"] is False
    assert state.trading_paused is False
    session.flush.assert_not_called()


def test_resume_success_clears_pause() -> None:
    session = MagicMock()
    svc = BrokerRecoveryConflictService(session)
    session.get.return_value = SimpleNamespace(is_active=True)
    svc.count_active_for_uba = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc.count_blocking_orders_for_uba = MagicMock(  # type: ignore[method-assign]
        return_value={
            "db_open": 0,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
    )
    state = SimpleNamespace(
        trading_paused=True,
        recovery_status="SUCCESS",
        last_error_summary="UPBIT_REMOTE_ONLY_ORDER_REVIEW",
        last_error_code="manual_review_required",
        auto_retry_enabled=False,
        updated_at=None,
    )
    session.scalar.return_value = state

    class _Vault:
        def assert_live_order_allowed(self, *_a, **_k):
            return None

    import stock_platform.broker.recovery_conflict_service as mod

    original = mod.BrokerCredentialVaultService
    mod.BrokerCredentialVaultService = lambda _s: _Vault()  # type: ignore[misc,assignment]
    try:
        result = svc.resume_account(
            58,
            actor="admin:1",
            reason="RECOVERY_REVIEW_COMPLETED_HISTORY_PRESERVED_OPERATOR_APPROVED",
            correlation_id="corr-ok",
        )
    finally:
        mod.BrokerCredentialVaultService = original

    assert result["resumed"] is True
    assert result["already_resumed"] is False
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
