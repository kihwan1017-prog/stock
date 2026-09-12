"""STEP 8-15A — Recovery auto-unpause 제거 계약 테스트."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.recovery_adapter import AdapterRecoveryResult
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
    RecoveryConflictError,
)
from stock_platform.broker.recovery_lock import RecoveryAccountLockService


def test_adapter_default_remain_paused_fail_closed() -> None:
    result = AdapterRecoveryResult(status="SUCCESS", broker_code="UPBIT")
    assert result.trading_should_remain_paused is True


def test_lock_release_never_clears_without_paused_before() -> None:
    """paused_before 없으면 keep_paused=False 여도 False로 내리지 않는다."""
    session = MagicMock()
    svc = RecoveryAccountLockService(session)
    row = SimpleNamespace(
        recovery_status="RUNNING",
        trading_paused=True,
        lock_holder="h",
        lock_expires_at="x",
        last_recovery_run_id=None,
        last_error_summary="old",
        updated_at=None,
    )
    svc._find = MagicMock(return_value=row)  # noqa: SLF001
    ctx = SimpleNamespace(
        broker_code="UPBIT",
        user_broker_account_id=58,
        paper_account_id=None,
        scope_key="uba:58",
    )
    svc.release(
        ctx,
        status_code="SUCCESS",
        keep_paused=False,
        run_id=999,
        error_summary=None,
    )
    assert row.trading_paused is True
    assert row.recovery_status == "SUCCESS"
    assert row.lock_holder is None
    session.flush.assert_called()


def test_lock_release_restores_paused_before_false() -> None:
    """SUCCESS + paused_before=False → Admin Resume 상태 유지."""
    session = MagicMock()
    svc = RecoveryAccountLockService(session)
    row = SimpleNamespace(
        recovery_status="RUNNING",
        trading_paused=True,
        lock_holder="h",
        lock_expires_at="x",
        last_recovery_run_id=None,
        last_error_summary=None,
        updated_at=None,
    )
    svc._find = MagicMock(return_value=row)  # noqa: SLF001
    ctx = SimpleNamespace(
        broker_code="UPBIT",
        user_broker_account_id=58,
        paper_account_id=None,
        scope_key="uba:58",
    )
    svc.release(
        ctx,
        status_code="SUCCESS",
        keep_paused=False,
        run_id=1,
        paused_before=False,
    )
    assert row.trading_paused is False


def test_lock_release_restores_paused_before_true() -> None:
    """SUCCESS + paused_before=True → 자동 Resume 금지."""
    session = MagicMock()
    svc = RecoveryAccountLockService(session)
    row = SimpleNamespace(
        recovery_status="RUNNING",
        trading_paused=True,
        lock_holder="h",
        lock_expires_at="x",
        last_recovery_run_id=None,
        last_error_summary=None,
        updated_at=None,
    )
    svc._find = MagicMock(return_value=row)  # noqa: SLF001
    ctx = SimpleNamespace(
        broker_code="UPBIT",
        user_broker_account_id=58,
        paper_account_id=None,
        scope_key="uba:58",
    )
    svc.release(
        ctx,
        status_code="SUCCESS",
        keep_paused=False,
        run_id=1,
        paused_before=True,
    )
    assert row.trading_paused is True


def test_lock_release_keep_paused_true_sets_paused() -> None:
    session = MagicMock()
    svc = RecoveryAccountLockService(session)
    row = SimpleNamespace(
        recovery_status="RUNNING",
        trading_paused=False,
        lock_holder="h",
        lock_expires_at="x",
        last_recovery_run_id=None,
        last_error_summary=None,
        updated_at=None,
    )
    svc._find = MagicMock(return_value=row)  # noqa: SLF001
    ctx = SimpleNamespace(
        broker_code="UPBIT",
        user_broker_account_id=58,
        paper_account_id=None,
        scope_key="uba:58",
    )
    svc.release(
        ctx,
        status_code="SUCCESS",
        keep_paused=True,
        run_id=1,
        error_summary=None,
    )
    assert row.trading_paused is True


def test_resume_requires_reason_and_correlation() -> None:
    session = MagicMock()
    svc = BrokerRecoveryConflictService(session)
    with pytest.raises(RecoveryConflictError) as exc:
        svc.resume_account(
            58,
            actor="admin:1",
            reason="",
            correlation_id="c1",
        )
    assert exc.value.code == "reason_required"

    with pytest.raises(RecoveryConflictError) as exc2:
        svc.resume_account(
            58,
            actor="admin:1",
            reason="ok",
            correlation_id="",
        )
    assert exc2.value.code == "correlation_id_required"


def test_resume_blocked_when_active_conflicts() -> None:
    session = MagicMock()
    svc = BrokerRecoveryConflictService(session)
    session.get.return_value = SimpleNamespace(
        is_active=True,
        broker_code="UPBIT",
        connection_status="CONNECTED",
        live_order_enabled=False,
        live_armed=False,
    )
    svc.count_active_for_uba = MagicMock(return_value=1)
    with pytest.raises(RecoveryConflictError) as exc:
        svc.resume_account(
            58,
            actor="admin:1",
            reason="OPERATOR_RESUME",
            correlation_id="corr-1",
        )
    assert exc.value.code == "unresolved_conflicts"


def test_resume_blocked_when_kill_switch() -> None:
    session = MagicMock()
    svc = BrokerRecoveryConflictService(session)
    session.get.return_value = SimpleNamespace(
        is_active=True,
        broker_code="UPBIT",
        connection_status="CONNECTED",
        live_order_enabled=False,
        live_armed=False,
    )
    svc.count_active_for_uba = MagicMock(return_value=0)
    svc.count_blocking_orders_for_uba = MagicMock(
        return_value={
            "db_open": 0,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
    )
    with patch(
        "stock_platform.broker.recovery_conflict_service."
        "BrokerCredentialVaultService.assert_live_order_allowed",
        return_value=None,
    ):
        with pytest.raises(RecoveryConflictError) as exc:
            svc.resume_account(
                58,
                actor="admin:1",
                reason="OPERATOR_RESUME",
                correlation_id="corr-1",
                kill_switch_active=True,
            )
    assert exc.value.code == "kill_switch_active"


def test_resume_blocked_when_db_open_orders() -> None:
    session = MagicMock()
    svc = BrokerRecoveryConflictService(session)
    session.get.return_value = SimpleNamespace(
        is_active=True,
        broker_code="UPBIT",
        connection_status="CONNECTED",
        live_order_enabled=False,
        live_armed=False,
    )
    svc.count_active_for_uba = MagicMock(return_value=0)
    svc.count_blocking_orders_for_uba = MagicMock(
        return_value={
            "db_open": 2,
            "submission_unknown": 0,
            "cancel_pending": 0,
            "replace_pending": 0,
        }
    )
    with pytest.raises(RecoveryConflictError) as exc:
        svc.resume_account(
            58,
            actor="admin:1",
            reason="OPERATOR_RESUME",
            correlation_id="corr-1",
        )
    assert exc.value.code == "db_open_orders"


def test_only_resume_account_sets_trading_paused_false_in_service_source() -> None:
    """운영 서비스에서 trading_paused=False 대입은 resume_account 본문에만 존재."""
    from pathlib import Path

    text = Path(
        "src/stock_platform/broker/recovery_conflict_service.py"
    ).read_text(encoding="utf-8")
    # release/pause 경로에 False 대입 금지 — resume_account 내 1회만
    assert text.count("trading_paused = False") == 1
    assert "def resume_account(" in text


def test_runtime_source_never_auto_resume_runtimes() -> None:
    from pathlib import Path

    text = Path("src/stock_platform/broker/recovery_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "resume_account_runtimes(" not in text
    assert "paused_before" in text
    assert "recovery_success_runtime_held" in text


def test_lock_source_never_blindly_assigns_trading_paused_false() -> None:
    from pathlib import Path

    text = Path("src/stock_platform/broker/recovery_lock.py").read_text(
        encoding="utf-8"
    )
    assert "trading_paused = keep_paused" not in text
    assert "trading_paused = False" not in text
    assert "paused_before" in text
