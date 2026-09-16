"""EXIT missing UUID — identifier lookup + fill-sync (no new orders)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.trading.exit_order_supervisor import (
    ExitOrderSupervisor,
    reset_supervisor_idempotency_for_tests,
)


def _pending_no_uuid_order(*, minutes_ago: float = 30) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=2999,
        symbol="KRW-ENA",
        status_code="PENDING",
        side_code="SELL",
        broker_order_id=None,
        filled_quantity="0",
        remaining_quantity="40",
        order_quantity="40",
        order_price="250",
        order_type_code="LIMIT",
        order_source="AUTO",
        client_order_identifier=None,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_code="MA_DEAD_CROSS",
        source_signal_id="sig_test",
        submission_generation=1,
        metadata_payload={
            "order_source": "AUTO",
            "signal_reason": "MA_DEAD_CROSS",
            "environment": "LIVE",
        },
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


def test_missing_uuid_done_remote_fill_syncs() -> None:
    reset_supervisor_idempotency_for_tests()
    session = MagicMock()
    order = _pending_no_uuid_order()
    client = MagicMock()
    client.get_order.return_value = {
        "uuid": "d0970e36-0574-4a57-8407-5c4067b22690",
        "identifier": "spu-test",
        "state": "done",
        "executed_volume": "40",
        "remaining_volume": "0",
        "paid_fee": "5",
    }
    sync_inst = MagicMock()
    sync_inst.sync_by_order_id.return_value = SimpleNamespace(
        order_status="FILLED",
        new_executions=1,
        duplicate_executions=0,
        post_fill_enqueued=False,
        detail={},
    )
    svc = ExitOrderSupervisor(session, order_client=client)
    with patch.object(svc, "list_open_sells", return_value=[order]), patch(
        "stock_platform.broker.upbit.fill_sync_service.UpbitFillSyncService",
        return_value=sync_inst,
    ), patch(
        "stock_platform.broker.upbit.ambiguous_resolver.UpbitAmbiguousOrderResolver"
    ) as resolver_cls, patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync."
        "reconcile_portfolio_slot_lifecycle",
        return_value={"transitions": []},
    ), patch(
        "stock_platform.trading.exit_order_supervisor.emit_live_safety_audit"
    ):
        resolver_cls.return_value.ensure_identifier.return_value = "spu-test"
        out = svc.supervise_uba(1380, allow_safe_cancel=True)

    assert out["new_real_buy"] == 0
    assert out["new_real_sell"] == 0
    assert out["remote_cancel_request_count"] == 0
    assert out["items"][0]["action"] == "FILL_SYNC_DONE"
    assert out["items"][0]["self_heal_status"] == "RECONCILED"
    sync_inst.sync_by_order_id.assert_called()
    # cancel 경로 미호출
    assert client.cancel_order.call_count == 0 if hasattr(client, "cancel_order") else True


def test_missing_uuid_not_found_fail_closed() -> None:
    reset_supervisor_idempotency_for_tests()
    session = MagicMock()
    order = _pending_no_uuid_order()
    client = MagicMock()
    from stock_platform.broker.upbit.exceptions import UpbitOrderNotFoundError

    client.get_order.side_effect = UpbitOrderNotFoundError("not found")
    svc = ExitOrderSupervisor(session, order_client=client)
    with patch.object(svc, "list_open_sells", return_value=[order]), patch(
        "stock_platform.broker.upbit.fill_sync_service.UpbitFillSyncService"
    ), patch(
        "stock_platform.broker.upbit.ambiguous_resolver.UpbitAmbiguousOrderResolver"
    ) as resolver_cls, patch(
        "stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync."
        "reconcile_portfolio_slot_lifecycle",
        return_value={"transitions": []},
    ), patch(
        "stock_platform.trading.exit_order_supervisor.emit_live_safety_audit"
    ):
        resolver_cls.return_value.ensure_identifier.return_value = "spu-missing"
        out = svc.supervise_uba(1380)

    assert out["items"][0]["action"] == "FAIL_CLOSED_NO_BROKER_UUID"
    assert out["items"][0]["self_heal_status"] == "IDENTIFIER_NOT_FOUND"
    assert out["new_real_buy"] == 0 and out["new_real_sell"] == 0
    assert out["remote_cancel_request_count"] == 0


def test_pending_can_transition_to_ambiguous() -> None:
    from stock_platform.order.models import OrderStatus
    from stock_platform.order.state_machine import OrderStateMachine

    assert OrderStateMachine.can_transition(
        OrderStatus.PENDING, OrderStatus.AMBIGUOUS_SUBMISSION
    )
