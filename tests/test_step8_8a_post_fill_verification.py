"""STEP 8-8A — Post-Fill 재검증 / ARM token 보안 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.order.post_fill_verification_constants import (
    PostFillVerifyStatus,
)
from stock_platform.order.post_fill_verification_service import (
    make_idempotency_key,
    parse_retry_delays,
    PostFillVerificationService,
)
from stock_platform.trading.live_arm_service import LiveArmService


def test_parse_retry_delays_from_settings() -> None:
    assert parse_retry_delays("2,5,10,20") == [2, 5, 10, 20]
    assert parse_retry_delays("") == [2, 5, 10, 20]


def test_idempotency_key_stable() -> None:
    a = make_idempotency_key(order_id=10, execution_id=5)
    b = make_idempotency_key(order_id=10, execution_id=5)
    c = make_idempotency_key(order_id=10, execution_id=None)
    assert a == b
    assert a != c
    assert a == "order:10:exec:5"


def test_stale_is_not_terminal_success() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        verification_id=1,
        order_id=10,
        execution_id=5,
        user_id=1,
        user_broker_account_id=7,
        broker_code="KIWOOM",
        symbol="005930",
        status_code=PostFillVerifyStatus.PENDING.value,
        retry_count=0,
        max_attempts=5,
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
        expected_position=[],
        expected_cash_delta=None,
    )
    svc = PostFillVerificationService(session)
    with (
        patch.object(svc, "_audit"),
        patch.object(svc, "_try_sync_best_effort"),
        patch.object(
            svc,
            "_next_retry_at",
            return_value=datetime.now(timezone.utc) + timedelta(seconds=2),
        ),
    ):
        out = svc.handle_immediate_result(
            row=row,
            reason_code="SNAPSHOT_STALE",
            detail={"symbol": "005930"},
            actor="test",
        )
    assert out.status_code == PostFillVerifyStatus.WAITING_SNAPSHOT.value
    assert out.last_error_code == "SNAPSHOT_STALE"
    assert out.status_code != PostFillVerifyStatus.VERIFIED.value


def test_expired_fail_closed_kills() -> None:
    session = MagicMock()
    row = SimpleNamespace(
        verification_id=2,
        order_id=10,
        execution_id=5,
        user_id=1,
        user_broker_account_id=7,
        broker_code="KIWOOM",
        symbol="005930",
        status_code=PostFillVerifyStatus.WAITING_SNAPSHOT.value,
        retry_count=5,
        max_attempts=5,
        next_retry_at=None,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
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
        expected_position=[],
        expected_cash_delta=None,
    )
    svc = PostFillVerificationService(session)
    with (
        patch.object(svc, "_audit"),
        patch(
            "stock_platform.order.post_fill_verification_service.emit_live_order_telegram"
        ),
        patch.object(svc, "_fail_closed_kill") as kill,
    ):
        svc._mark_expired(row, actor="test", reason="TTL_EXPIRED")
    assert row.status_code == PostFillVerifyStatus.EXPIRED.value
    kill.assert_called_once()


def test_arm_token_hash_only_and_compare_digest() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=10,
        user_id=1,
        broker_code="KIWOOM",
        is_active=True,
        live_order_enabled=True,
        live_armed=False,
        arm_token_hash=None,
        arm_expires_at=None,
        arm_armed_by=None,
        arm_armed_at=None,
    )
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
        ) as R,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ) as audit,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
    ):
        from stock_platform.risk_engine.resolved_policy import (
            ResolvedRiskPolicy,
        )

        R.return_value.resolve.return_value = ResolvedRiskPolicy(
            max_order_amount=Decimal("50000"),
            daily_max_order_amount=Decimal("200000"),
            max_total_investment_amount=Decimal("1000000"),
            max_position_amount=Decimal("200000"),
            max_position_count=5,
            max_position_weight=Decimal("0.2"),
            allow_duplicate_buy=True,
            daily_max_loss_amount=Decimal("30000"),
            daily_max_loss_rate=Decimal("0.05"),
            stop_loss_rate=Decimal("0.05"),
            take_profit_rate=Decimal("0.1"),
            trailing_stop_rate=Decimal("0.03"),
            auto_trading_enabled=True,
            buy_enabled=True,
            sell_enabled=True,
            sell_only=False,
            account_paused=False,
            max_order_quantity=Decimal("100"),
            daily_order_limit=20,
            duplicate_order_window_seconds=5,
            max_open_orders=20,
            max_slippage_rate=Decimal("0.01"),
            anomaly_orders_per_minute=10,
            loop_detect_window_seconds=60,
            arm_ttl_seconds=300,
            source_layers=("system",),
        )
        result = LiveArmService(session).arm(10, actor="admin")
        token = result["arm_token"]
        assert token
        assert uba.arm_token_hash == LiveArmService.hash_token(token)
        assert token not in str(uba.arm_token_hash)
        status = LiveArmService(session).get_arm_status(10)
        assert "arm_token" not in status
        assert status["arm_token_present"] is True
        # audit detail에 원문 토큰 없어야 함
        for call in audit.call_args_list:
            detail = call.kwargs.get("detail") or {}
            assert "arm_token" not in detail
            blob = str(detail)
            assert token not in blob


def test_rearm_invalidates_previous_token() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=10,
        user_id=1,
        broker_code="KIWOOM",
        is_active=True,
        live_order_enabled=True,
        live_armed=False,
        arm_token_hash=None,
        arm_expires_at=None,
        arm_armed_by=None,
        arm_armed_at=None,
    )
    session.get.return_value = uba
    with (
        patch(
            "stock_platform.trading.live_arm_service.ResolvedRiskPolicyResolver"
        ) as R,
        patch(
            "stock_platform.trading.live_arm_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.trading.live_arm_service.emit_live_order_telegram"
        ),
    ):
        from stock_platform.risk_engine.resolved_policy import (
            ResolvedRiskPolicy,
        )

        R.return_value.resolve.return_value = ResolvedRiskPolicy(
            max_order_amount=Decimal("50000"),
            daily_max_order_amount=Decimal("200000"),
            max_total_investment_amount=Decimal("1000000"),
            max_position_amount=Decimal("200000"),
            max_position_count=5,
            max_position_weight=Decimal("0.2"),
            allow_duplicate_buy=True,
            daily_max_loss_amount=Decimal("30000"),
            daily_max_loss_rate=Decimal("0.05"),
            stop_loss_rate=Decimal("0.05"),
            take_profit_rate=Decimal("0.1"),
            trailing_stop_rate=Decimal("0.03"),
            auto_trading_enabled=True,
            buy_enabled=True,
            sell_enabled=True,
            sell_only=False,
            account_paused=False,
            max_order_quantity=Decimal("100"),
            daily_order_limit=20,
            duplicate_order_window_seconds=5,
            max_open_orders=20,
            max_slippage_rate=Decimal("0.01"),
            anomaly_orders_per_minute=10,
            loop_detect_window_seconds=60,
            arm_ttl_seconds=300,
            source_layers=("system",),
        )
        first = LiveArmService(session).arm(10, actor="admin")["arm_token"]
        second = LiveArmService(session).arm(10, actor="admin")["arm_token"]
        ok1, _ = LiveArmService(session).validate_arm_token(10, first)
        ok2, _ = LiveArmService(session).validate_arm_token(10, second)
    assert first != second
    assert ok1 is False
    assert ok2 is True
