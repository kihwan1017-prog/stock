"""Post-fill eventual consistency — POSITION_SYNC_PENDING race fix."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.order.post_fill_runner import (
    PostFillVerifyResult,
    PostFillVerifyRunner,
)
from stock_platform.order.post_fill_verification_constants import (
    POSITION_SYNC_PENDING,
    PostFillVerifyStatus,
)
from stock_platform.order.post_fill_verification_service import (
    PostFillVerificationService,
)


def _row(*, retry_count: int = 0, max_attempts: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        verification_id=1,
        order_id=10,
        execution_id=5,
        user_id=1,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        symbol="KRW-XRP",
        status_code=PostFillVerifyStatus.PENDING.value,
        retry_count=retry_count,
        max_attempts=max_attempts,
        next_retry_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        last_error_code=None,
        last_error_summary=None,
        detail={},
        run_id="r1",
        correlation_id="c1",
        claimed_by=None,
        claim_expires_at=None,
        broker_down_notified=False,
        verified_at=None,
        updated_at=None,
        expected_position=[{"symbol": "KRW-XRP", "quantity": "0"}],
        expected_cash_delta=None,
    )


def test_immediate_mismatch_becomes_sync_pending_no_kill() -> None:
    session = MagicMock()
    row = _row()
    svc = PostFillVerificationService(session)
    with (
        patch.object(svc, "_audit"),
        patch.object(svc, "_try_sync_best_effort") as sync_mock,
        patch.object(
            svc,
            "_next_retry_at",
            return_value=datetime.now(timezone.utc) + timedelta(seconds=2),
        ),
        patch.object(svc, "_mark_mismatch") as mismatch_mock,
    ):
        out = svc.handle_immediate_result(
            row=row,
            reason_code=POSITION_SYNC_PENDING,
            detail={
                "symbol": "KRW-XRP",
                "broker_qty": "3.1",
                "db_qty": "0",
            },
            actor="OUTBOX_UPBIT_FILL_SYNC",
            request_sync=True,
        )
    assert out.status_code == PostFillVerifyStatus.WAITING_SNAPSHOT.value
    assert out.last_error_code == POSITION_SYNC_PENDING
    assert out.detail.get("sync_pending") is True
    sync_mock.assert_called_once()
    mismatch_mock.assert_not_called()


def test_verify_after_order_fill_defers_kill_on_mismatch() -> None:
    session = MagicMock()
    order = SimpleNamespace(
        order_id=1797,
        user_broker_account_id=1380,
        user_id=7,
        broker_code="UPBIT",
        symbol="KRW-XRP",
        broker_order_id="uuid-1",
        side_code="SELL",
    )
    runner = PostFillVerifyRunner(session)
    mismatch = PostFillVerifyResult(
        ok=False,
        reason_code="POSITION_MISMATCH",
        detail={"symbol": "KRW-XRP", "broker_qty": "3.1", "db_qty": "0"},
    )
    enqueue_row = _row()
    with (
        patch.object(
            runner,
            "build_expected_positions_from_orders",
            return_value=[{"symbol": "KRW-XRP", "quantity": "0"}],
        ),
        patch(
            "stock_platform.order.post_fill_verification_service."
            "PostFillVerificationService.enqueue_from_order",
            return_value=enqueue_row,
        ),
        patch(
            "stock_platform.broker.account_repository."
            "BrokerAccountSnapshotRepository.get_active_by_uba",
            return_value=(
                object(),
                [SimpleNamespace(symbol="KRW-XRP", quantity="3.1")],
            ),
        ),
        patch.object(
            runner,
            "verify_uba_against_expected",
            return_value=mismatch,
        ) as verify_mock,
        patch(
            "stock_platform.order.post_fill_verification_service."
            "PostFillVerificationService.handle_immediate_result",
            return_value=enqueue_row,
        ) as handle_mock,
    ):
        result = runner.verify_after_order_fill(
            order=order,
            execution_id=99,
            actor="OUTBOX_UPBIT_FILL_SYNC",
        )
    assert result.reason_code == POSITION_SYNC_PENDING
    assert result.detail.get("deferred_kill") is True
    assert verify_mock.call_args.kwargs["activate_kill_on_mismatch"] is False
    assert handle_mock.call_args.kwargs["reason_code"] == POSITION_SYNC_PENDING
    assert handle_mock.call_args.kwargs["request_sync"] is True


def test_reverify_defers_kill_until_final_attempt() -> None:
    session = MagicMock()
    row = _row(retry_count=1, max_attempts=5)
    svc = PostFillVerificationService(session)
    mismatch = PostFillVerifyResult(
        ok=False,
        reason_code="POSITION_MISMATCH",
        detail={"symbol": "KRW-XRP", "broker_qty": "1", "db_qty": "0"},
    )
    with (
        patch.object(svc, "_audit"),
        patch.object(
            svc,
            "_next_retry_at",
            return_value=datetime.now(timezone.utc) + timedelta(seconds=2),
        ),
        patch.object(svc, "_mark_mismatch") as mismatch_mock,
        patch.object(svc, "_mark_expired") as expired_mock,
        patch(
            "stock_platform.order.post_fill_runner.PostFillVerifyRunner."
            "verify_uba_against_expected",
            return_value=mismatch,
        ) as verify_mock,
    ):
        out = svc._reverify(row)
    assert out["status"] == PostFillVerifyStatus.WAITING_SNAPSHOT.value
    assert row.last_error_code == POSITION_SYNC_PENDING
    assert verify_mock.call_args.kwargs["activate_kill_on_mismatch"] is False
    mismatch_mock.assert_not_called()
    expired_mock.assert_not_called()


def test_reverify_final_attempt_marks_mismatch_with_kill() -> None:
    session = MagicMock()
    row = _row(retry_count=4, max_attempts=5)
    svc = PostFillVerificationService(session)
    mismatch = PostFillVerifyResult(
        ok=False,
        reason_code="POSITION_MISMATCH",
        detail={"symbol": "KRW-XRP", "broker_qty": "1", "db_qty": "0"},
    )
    with (
        patch.object(svc, "_audit"),
        patch.object(svc, "_mark_mismatch", return_value=row) as mismatch_mock,
        patch(
            "stock_platform.order.post_fill_runner.PostFillVerifyRunner."
            "verify_uba_against_expected",
            return_value=mismatch,
        ) as verify_mock,
    ):
        out = svc._reverify(row)
    assert out["status"] == PostFillVerifyStatus.MISMATCH.value
    assert verify_mock.call_args.kwargs["activate_kill_on_mismatch"] is True
    assert mismatch_mock.call_args.kwargs["already_killed"] is True
    assert mismatch_mock.call_args.kwargs["reason"] == "POSITION_MISMATCH"


def test_uba_symbol_isolation_in_pending_detail() -> None:
    """다른 UBA/심볼 detail은 서로 덮어쓰지 않는다 (단위 수준)."""
    session = MagicMock()
    svc = PostFillVerificationService(session)
    row_a = _row()
    row_a.user_broker_account_id = 1380
    row_a.symbol = "KRW-XRP"
    row_b = _row()
    row_b.verification_id = 2
    row_b.user_broker_account_id = 1381
    row_b.symbol = "005930"
    with (
        patch.object(svc, "_audit"),
        patch.object(svc, "_try_sync_best_effort"),
        patch.object(
            svc,
            "_next_retry_at",
            return_value=datetime.now(timezone.utc) + timedelta(seconds=2),
        ),
    ):
        a = svc.handle_immediate_result(
            row=row_a,
            reason_code=POSITION_SYNC_PENDING,
            detail={"symbol": "KRW-XRP", "uba": 1380},
            request_sync=False,
        )
        b = svc.handle_immediate_result(
            row=row_b,
            reason_code=POSITION_SYNC_PENDING,
            detail={"symbol": "005930", "uba": 1381},
            request_sync=False,
        )
    assert a.detail["uba"] == 1380
    assert b.detail["uba"] == 1381
    assert a.detail["symbol"] != b.detail["symbol"]
