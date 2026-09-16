"""Upbit recovery cancel — LIVE OFF + existing WAIT cancel, 신규 주문 block."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.upbit.recovery_order_cancel_service import (
    UpbitRecoveryOrderCancelError,
    UpbitRecoveryOrderCancelService,
)
from stock_platform.order.models import OrderStatus


def _live_buy_order(
    *,
    order_id: int = 1896,
    uba_id: int = 1380,
    broker_uuid: str = "44525ef2-90d3-4f41-8c99-b0379aa331ed",
    status: str = OrderStatus.ACCEPTED.value,
) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id,
        broker_code="UPBIT",
        broker_order_id=broker_uuid,
        status_code=status,
        symbol="KRW-XRP",
        side_code="BUY",
        order_quantity=Decimal("5.14403292"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("5.14403292"),
        user_broker_account_id=uba_id,
        user_id=61,
        strategy_id=17483,
        client_order_id="spu-test",
        metadata_payload={"environment": "LIVE"},
    )


def _wait_remote(**overrides) -> dict:
    base = {
        "uuid": "44525ef2-90d3-4f41-8c99-b0379aa331ed",
        "state": "wait",
        "executed_volume": "0",
        "remaining_volume": "5.14403292",
        "trades_count": 0,
        "paid_fee": "0",
    }
    base.update(overrides)
    return base


def _cancel_remote(**overrides) -> dict:
    base = {
        "uuid": "44525ef2-90d3-4f41-8c99-b0379aa331ed",
        "state": "cancel",
        "executed_volume": "0",
        "remaining_volume": "0",
        "trades_count": 0,
        "paid_fee": "0",
    }
    base.update(overrides)
    return base


def _svc_with_order(order: SimpleNamespace) -> UpbitRecoveryOrderCancelService:
    session = MagicMock()
    svc = UpbitRecoveryOrderCancelService(session)
    orders_repo = MagicMock()
    orders_repo.get.return_value = order
    orders_repo.change_status.side_effect = (
        lambda **kwargs: setattr(
            kwargs["entity"], "status_code", kwargs["new_status"].value
        )
        or kwargs["entity"]
    )
    svc._orders = orders_repo
    return svc


def test_a_live_off_existing_wait_cancel_allowed() -> None:
    order = _live_buy_order()
    svc = _svc_with_order(order)
    client = MagicMock()
    client.get_order.side_effect = [_wait_remote(), _cancel_remote()]
    client.cancel_order.return_value = _cancel_remote()
    svc._order_client = client

    sync_result = SimpleNamespace(
        order_status=OrderStatus.CANCELLED.value,
        new_executions=0,
        already_processed=False,
        detail={},
    )

    with (
        patch(
            "stock_platform.broker.upbit.recovery_order_cancel_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.broker.upbit.fill_sync_service.UpbitFillSyncService.sync_by_order_id",
            return_value=sync_result,
        ),
    ):
        result = svc.cancel_existing_order_for_recovery(
            1896,
            user_broker_account_id=1380,
            actor="TEST",
        )

    assert result.action == "SAFE_CANCEL"
    assert result.cancel_requested is True
    assert result.cancel_accepted is True
    client.cancel_order.assert_called_once()


def test_b_new_buy_still_blocked_via_normal_cancel_guard() -> None:
    """신규 주문 경로는 기존 resolve_broker_adapter_for_cancel LIVE gate 유지."""

    from stock_platform.broker.factory import BrokerAdapterFactory
    from stock_platform.broker.models import BrokerEnvironment

    session = MagicMock()
    with patch(
        "stock_platform.broker.factory.LiveTradingTransitionGuard"
    ) as guard_cls:
        guard_cls.return_value.require_active.side_effect = PermissionError(
            "No active live trading transition approval"
        )
        with pytest.raises(PermissionError):
            BrokerAdapterFactory.create(
                BrokerEnvironment.LIVE,
                "UPBIT",
                session=session,
                user_broker_account_id=1380,
            )


def test_c_wrong_uba_reject() -> None:
    order = _live_buy_order(uba_id=1380)
    svc = _svc_with_order(order)
    with pytest.raises(UpbitRecoveryOrderCancelError) as exc:
        svc.cancel_existing_order_for_recovery(
            1896,
            user_broker_account_id=9999,
        )
    assert exc.value.code == "UBA_MISMATCH"


def test_d_wrong_remote_uuid_reject() -> None:
    order = _live_buy_order()
    svc = _svc_with_order(order)
    with pytest.raises(UpbitRecoveryOrderCancelError) as exc:
        svc.cancel_existing_order_for_recovery(
            1896,
            user_broker_account_id=1380,
            expected_broker_order_id="wrong-uuid",
        )
    assert exc.value.code == "BROKER_UUID_MISMATCH"


def test_e_already_cancelled_idempotent() -> None:
    order = _live_buy_order()
    svc = _svc_with_order(order)
    client = MagicMock()
    client.get_order.return_value = _cancel_remote()
    svc._order_client = client

    sync_result = SimpleNamespace(
        order_status=OrderStatus.CANCELLED.value,
        new_executions=0,
        already_processed=True,
        detail={},
    )

    with (
        patch(
            "stock_platform.broker.upbit.recovery_order_cancel_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.broker.upbit.fill_sync_service.UpbitFillSyncService.sync_by_order_id",
            return_value=sync_result,
        ),
    ):
        result = svc.cancel_existing_order_for_recovery(
            1896,
            user_broker_account_id=1380,
        )

    assert result.action == "RECONCILE_CANCELLED"
    assert result.idempotent is True
    client.cancel_order.assert_not_called()


def test_f_fill_race_reconcile_done() -> None:
    order = _live_buy_order()
    svc = _svc_with_order(order)
    done = {
        "uuid": "44525ef2-90d3-4f41-8c99-b0379aa331ed",
        "state": "done",
        "executed_volume": "5.14403292",
        "remaining_volume": "0",
        "trades_count": 1,
        "paid_fee": "1",
        "trades": [{"price": "1940", "volume": "5.14403292"}],
    }
    client = MagicMock()
    client.get_order.side_effect = [_wait_remote(), done]
    client.cancel_order.return_value = done
    svc._order_client = client

    sync_result = SimpleNamespace(
        order_status=OrderStatus.FILLED.value,
        new_executions=1,
        already_processed=False,
        detail={},
    )

    def _sync_side_effect(*_args, **_kwargs):
        order.status_code = OrderStatus.FILLED.value
        return sync_result

    with (
        patch(
            "stock_platform.broker.upbit.recovery_order_cancel_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.broker.upbit.fill_sync_service.UpbitFillSyncService.sync_by_order_id",
            side_effect=_sync_side_effect,
        ),
    ):
        result = svc.cancel_existing_order_for_recovery(
            1896,
            user_broker_account_id=1380,
        )

    assert result.remote_status_after == "done"
    assert result.local_status_after == OrderStatus.FILLED.value


def test_g_remote_done_no_cancel_api() -> None:
    order = _live_buy_order()
    svc = _svc_with_order(order)
    done = {
        "uuid": "44525ef2-90d3-4f41-8c99-b0379aa331ed",
        "state": "done",
        "executed_volume": "5.14403292",
        "remaining_volume": "0",
        "trades_count": 1,
    }
    client = MagicMock()
    client.get_order.return_value = done
    svc._order_client = client

    sync_result = SimpleNamespace(
        order_status=OrderStatus.FILLED.value,
        new_executions=1,
        already_processed=False,
        detail={},
    )

    with (
        patch(
            "stock_platform.broker.upbit.recovery_order_cancel_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.broker.upbit.fill_sync_service.UpbitFillSyncService.sync_by_order_id",
            return_value=sync_result,
        ),
    ):
        result = svc.cancel_existing_order_for_recovery(
            1896,
            user_broker_account_id=1380,
        )

    assert result.action == "RECONCILE_DONE"
    client.cancel_order.assert_not_called()
