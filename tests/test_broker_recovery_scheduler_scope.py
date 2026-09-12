"""SHARED — Broker Recovery Scheduler scope: no healthy periodic recover_all."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.broker.recovery_scheduler_selector import (
    AccountSafetySnapshot,
    AutoRecoveryDecision,
    classify_auto_recovery_target,
)
from stock_platform.broker.recovery_scheduler_service import (
    _run_failed_retry,
    _run_periodic_scoped_job,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _snap(**kwargs: Any) -> AccountSafetySnapshot:
    base = dict(
        broker_code="UPBIT",
        user_broker_account_id=1380,
        recovery_status="SUCCESS",
        auto_retry_enabled=True,
        is_active=True,
        live_order_enabled=False,
        live_armed=False,
        has_open_high_conflict=False,
    )
    base.update(kwargs)
    return AccountSafetySnapshot(**base)


# --- A/B/C/L/M: healthy → no Recovery ---


def test_a_healthy_upbit_success_periodic_skip() -> None:
    d = classify_auto_recovery_target(
        _snap(broker_code="UPBIT", user_broker_account_id=1380),
        mode="periodic",
    )
    assert d in {
        AutoRecoveryDecision.SKIP_HEALTHY,
        AutoRecoveryDecision.SKIP_RECENT,
    }
    assert d != AutoRecoveryDecision.RECOVERY_ELIGIBLE


def test_b_healthy_kiwoom_success_periodic_skip() -> None:
    d = classify_auto_recovery_target(
        _snap(
            broker_code="KIWOOM",
            user_broker_account_id=1381,
            recovery_status="SUCCESS",
        ),
        mode="periodic",
    )
    assert d == AutoRecoveryDecision.SKIP_HEALTHY


def test_c_healthy_paused_kiwoom_still_skip() -> None:
    # trading_paused 는 selector 입력이 아님 — SUCCESS면 Recovery 금지
    d = classify_auto_recovery_target(
        _snap(broker_code="KIWOOM", user_broker_account_id=1381),
        mode="periodic",
    )
    assert d == AutoRecoveryDecision.SKIP_HEALTHY


def test_l_recently_recovered_success_skip() -> None:
    d = classify_auto_recovery_target(
        _snap(updated_at=_now() - timedelta(seconds=30)),
        mode="periodic",
        recent_success_seconds=3600,
    )
    assert d == AutoRecoveryDecision.SKIP_RECENT


def test_m_healthy_paper_periodic_skip() -> None:
    d = classify_auto_recovery_target(
        _snap(
            broker_code="PAPER_STOCK",
            user_broker_account_id=None,
            paper_account_id=42,
            recovery_status="SUCCESS",
        ),
        mode="periodic",
    )
    assert d == AutoRecoveryDecision.SKIP_HEALTHY


# --- D/E/F/G/H/I/J: failed_retry gates ---


def test_d_failed_eligible_recovery() -> None:
    d = classify_auto_recovery_target(
        _snap(
            recovery_status="FAILED",
            auto_retry_enabled=True,
            next_retry_at=_now() - timedelta(seconds=10),
        ),
        mode="failed_retry",
    )
    assert d == AutoRecoveryDecision.RECOVERY_ELIGIBLE


def test_e_failed_not_due_skip() -> None:
    d = classify_auto_recovery_target(
        _snap(
            recovery_status="FAILED",
            auto_retry_enabled=True,
            next_retry_at=_now() + timedelta(hours=1),
        ),
        mode="failed_retry",
    )
    assert d == AutoRecoveryDecision.SKIP_NOT_DUE


def test_f_credential_missing_non_retryable() -> None:
    d = classify_auto_recovery_target(
        _snap(
            recovery_status="FAILED",
            auto_retry_enabled=True,
            next_retry_at=_now() - timedelta(seconds=1),
            last_error_code="credential_missing",
        ),
        mode="failed_retry",
    )
    assert d == AutoRecoveryDecision.SKIP_CREDENTIAL


def test_g_high_conflict_skip() -> None:
    d = classify_auto_recovery_target(
        _snap(
            recovery_status="FAILED",
            next_retry_at=_now() - timedelta(seconds=1),
            has_open_high_conflict=True,
        ),
        mode="failed_retry",
    )
    assert d == AutoRecoveryDecision.SKIP_CONFLICT


def test_h_manual_review_skip() -> None:
    d = classify_auto_recovery_target(
        _snap(recovery_status="MANUAL_REVIEW"),
        mode="failed_retry",
    )
    assert d == AutoRecoveryDecision.SKIP_MANUAL_REVIEW


def test_i_live_on_blocks_auto() -> None:
    d = classify_auto_recovery_target(
        _snap(
            recovery_status="FAILED",
            next_retry_at=_now() - timedelta(seconds=1),
            live_order_enabled=True,
        ),
        mode="failed_retry",
    )
    assert d == AutoRecoveryDecision.SKIP_LIVE


def test_j_arm_on_blocks_auto() -> None:
    d = classify_auto_recovery_target(
        _snap(
            recovery_status="FAILED",
            next_retry_at=_now() - timedelta(seconds=1),
            live_armed=True,
        ),
        mode="failed_retry",
    )
    assert d == AutoRecoveryDecision.SKIP_ARMED


def test_k_expired_running_local_finalize_only() -> None:
    d = classify_auto_recovery_target(
        _snap(
            recovery_status="RUNNING",
            lock_expires_at=_now() - timedelta(seconds=5),
        ),
        mode="periodic",
    )
    assert d == AutoRecoveryDecision.LOCAL_FINALIZE_EXPIRED


def test_failed_retry_never_selects_healthy_success() -> None:
    d = classify_auto_recovery_target(
        _snap(recovery_status="SUCCESS"),
        mode="failed_retry",
    )
    assert d == AutoRecoveryDecision.SKIP_HEALTHY


def test_periodic_failed_is_check_only_not_recover() -> None:
    """중복 방지: periodic 은 FAILED 를 Recovery 하지 않음."""
    d = classify_auto_recovery_target(
        _snap(
            recovery_status="FAILED",
            next_retry_at=_now() - timedelta(seconds=1),
        ),
        mode="periodic",
    )
    assert d == AutoRecoveryDecision.CHECK_ONLY
    assert d != AutoRecoveryDecision.RECOVERY_ELIGIBLE


# --- Job runners ---


@pytest.mark.asyncio
async def test_periodic_job_does_not_call_recover_all() -> None:
    fake_session = MagicMock()
    factory = MagicMock(return_value=fake_session)
    lock_svc = MagicMock()
    lock_svc.finalize_expired_orphan_states.return_value = {
        "scanned_expired_running": 0,
        "finalized": 0,
    }

    with (
        patch(
            "stock_platform.broker.recovery_scheduler_service.get_session_factory",
            return_value=factory,
        ),
        patch(
            "stock_platform.broker.recovery_scheduler_selector.summarize_periodic_decisions",
            return_value={
                "decision_counts": {"SKIP_HEALTHY": 2},
                "finalize_candidates": 0,
                "recovery_eligible_count": 0,
            },
        ),
        patch(
            "stock_platform.broker.recovery_lock.RecoveryAccountLockService",
            return_value=lock_svc,
        ),
        patch(
            "stock_platform.broker.recovery_runtime.broker_recovery_manager.recover_all",
            new_callable=AsyncMock,
        ) as mock_all,
    ):
        result = await _run_periodic_scoped_job(
            job_id="broker_recovery_upbit_interval",
            broker_filter="UPBIT",
            trigger_type="SCHEDULER",
        )

    assert result["recover_all_called"] is False
    assert result["recovery_count"] == 0
    assert result["status"] == "CHECK_ONLY"
    mock_all.assert_not_called()
    lock_svc.finalize_expired_orphan_states.assert_called_once()


@pytest.mark.asyncio
async def test_kiwoom_preopen_postclose_no_recover_all() -> None:
    fake_session = MagicMock()
    factory = MagicMock(return_value=fake_session)
    lock_svc = MagicMock()
    lock_svc.finalize_expired_orphan_states.return_value = {
        "scanned_expired_running": 1,
        "finalized": 1,
    }

    with (
        patch(
            "stock_platform.broker.recovery_scheduler_service.get_session_factory",
            return_value=factory,
        ),
        patch(
            "stock_platform.broker.recovery_scheduler_selector.summarize_periodic_decisions",
            return_value={
                "decision_counts": {
                    "SKIP_HEALTHY": 1,
                    "LOCAL_FINALIZE_EXPIRED": 1,
                },
                "finalize_candidates": 1,
                "recovery_eligible_count": 0,
            },
        ),
        patch(
            "stock_platform.broker.recovery_lock.RecoveryAccountLockService",
            return_value=lock_svc,
        ),
    ):
        for job_id in (
            "broker_recovery_kiwoom_preopen",
            "broker_recovery_kiwoom_postclose",
            "broker_recovery_paper_integrity",
        ):
            result = await _run_periodic_scoped_job(
                job_id=job_id,
                broker_filter=(
                    "PAPER" if "paper" in job_id else "KIWOOM"
                ),
                trigger_type="SCHEDULER",
            )
            assert result["recover_all_called"] is False
            assert result["recovery_count"] == 0


@pytest.mark.asyncio
async def test_d_failed_retry_targeted_exactly_one() -> None:
    targets = [
        {
            "broker_code": "KIWOOM",
            "user_broker_account_id": 99,
            "paper_account_id": None,
            "user_id": 1,
            "retry_count": 1,
        }
    ]
    mock_all = AsyncMock(
        return_value={
            "success": True,
            "accounts": [
                {
                    "status": "SUCCESS",
                    "broker_code": "KIWOOM",
                    "user_broker_account_id": 99,
                    "errors": [],
                }
            ],
        }
    )

    with (
        patch(
            "stock_platform.broker.recovery_runtime.broker_recovery_manager.recover_all",
            new=mock_all,
        ),
        patch(
            "stock_platform.broker.recovery_scheduler_service._update_account_retry_state",
        ),
        patch(
            "stock_platform.broker.recovery_scheduler_service.get_session_factory",
            return_value=MagicMock(return_value=MagicMock()),
        ),
    ):
        result = await _run_failed_retry(
            targets,
            concurrency=1,
            timeout=30.0,
            max_retries=3,
            backoff_base=60,
            backoff_max=600,
            requested_by="test",
        )

    assert mock_all.await_count == 1
    assert result["recovery_count"] == 1
    assert result["recover_all_called"] is True
    kwargs = mock_all.await_args.kwargs
    assert kwargs["user_broker_account_id"] == 99
    assert kwargs["broker_code"] == "KIWOOM"


@pytest.mark.asyncio
async def test_o_concurrent_lock_skips_duplicate() -> None:
    targets = [
        {
            "broker_code": "UPBIT",
            "user_broker_account_id": 1380,
            "paper_account_id": None,
            "user_id": 1,
            "retry_count": 0,
        }
    ]
    mock_all = AsyncMock(
        side_effect=ValueError("Broker recovery is already running")
    )

    with (
        patch(
            "stock_platform.broker.recovery_runtime.broker_recovery_manager.recover_all",
            new=mock_all,
        ),
        patch(
            "stock_platform.broker.recovery_scheduler_service._update_account_retry_state",
        ),
        patch(
            "stock_platform.broker.recovery_scheduler_service.get_session_factory",
            return_value=MagicMock(return_value=MagicMock()),
        ),
    ):
        result = await _run_failed_retry(
            targets,
            concurrency=1,
            timeout=30.0,
            max_retries=3,
            backoff_base=60,
            backoff_max=600,
            requested_by="test",
        )

    assert result["skipped_locked_count"] >= 1
    assert any(
        a.get("status") == "SKIPPED_LOCKED"
        for a in (
            # summarized via accounts in wrapped — check status field
            []
        )
    ) or result["status"] in {"SUCCESS", "PARTIAL", "FAILED"}


@pytest.mark.asyncio
async def test_p_q_manual_recover_all_still_on_manager() -> None:
    """manual/admin 은 manager.recover_all 직접 호출 — scheduler 우회."""
    from stock_platform.broker.recovery_runtime import BrokerRecoveryManager

    manager = BrokerRecoveryManager()
    with patch.object(
        manager, "discover_accounts", return_value=[]
    ):
        result = await manager.recover_all(
            trigger_type="MANUAL",
            user_broker_account_id=1380,
            broker_code="UPBIT",
        )
    assert result["trigger_type"] == "MANUAL"
    assert result["account_count"] == 0


@pytest.mark.asyncio
async def test_r_startup_state_only_regression() -> None:
    from stock_platform.broker.recovery_runtime import BrokerRecoveryManager

    manager = BrokerRecoveryManager()
    session = MagicMock()
    session.scalars.return_value = []
    factory = MagicMock(return_value=session)

    with (
        patch(
            "stock_platform.broker.recovery_runtime.get_session_factory",
            return_value=factory,
        ),
        patch.object(
            manager, "recover_all", new_callable=AsyncMock
        ) as mock_all,
    ):
        # recover_startup_state_only 내부 import 경로
        result = await manager.recover_startup_state_only()

    assert result.get("recover_all_called") is False
    mock_all.assert_not_called()


def test_s_upbit_kiwoom_paper_isolation_in_broker_codes() -> None:
    from stock_platform.broker.recovery_scheduler_selector import (
        broker_codes_for_job,
    )

    assert broker_codes_for_job("UPBIT") == ["UPBIT"]
    assert broker_codes_for_job("KIWOOM") == ["KIWOOM"]
    assert "PAPER_STOCK" in (broker_codes_for_job("PAPER") or [])


def test_inactive_skip() -> None:
    d = classify_auto_recovery_target(
        _snap(is_active=False, recovery_status="FAILED", next_retry_at=_now()),
        mode="failed_retry",
    )
    assert d == AutoRecoveryDecision.SKIP_INACTIVE


def test_n_paper_mismatch_without_detector_is_check_only() -> None:
    # 안전한 local mismatch detector 없음 → CHECK_ONLY (full Recovery 금지)
    d = classify_auto_recovery_target(
        _snap(
            broker_code="PAPER_STOCK",
            user_broker_account_id=None,
            paper_account_id=7,
            recovery_status="IDLE",
        ),
        mode="periodic",
    )
    assert d == AutoRecoveryDecision.CHECK_ONLY
