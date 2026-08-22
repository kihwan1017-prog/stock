"""Upbit ACCEPTED→FILLED sync + binding close + poller (실주문 0)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.broker.upbit.fill_sync_service import UpbitFillSyncService
from stock_platform.broker.upbit.open_order_fill_poller import (
    UpbitOpenOrderFillPoller,
)
from stock_platform.order.models import OrderStatus
from stock_platform.risk_engine.strategy_owned_risk_service import (
    StrategyOwnedRiskService,
)


def _sell_done_remote(
    *,
    uuid: str = "test-sell-uuid-1",
    volume: str = "14.4092219",
    price: str = "350",
    fee: str = "2.5216138325",
) -> dict:
    return {
        "uuid": uuid,
        "market": "KRW-GEOD",
        "side": "ask",
        "ord_type": "limit",
        "state": "done",
        "volume": volume,
        "executed_volume": volume,
        "remaining_volume": "0",
        "avg_price": price,
        "paid_fee": fee,
        "trades_count": 1,
        "created_at": "2026-08-22T12:14:52+09:00",
        "trades": [
            {
                "uuid": "test-sell-trade-1",
                "market": "KRW-GEOD",
                "price": price,
                "volume": volume,
                "funds": "5043.227665",
                "side": "ask",
                "created_at": "2026-08-22T12:14:53+09:00",
            }
        ],
    }


def _buy_done_remote() -> dict:
    return {
        "uuid": "test-buy-uuid-1",
        "market": "KRW-GEOD",
        "side": "bid",
        "ord_type": "price",
        "state": "done",
        "executed_volume": "14.4092219",
        "remaining_volume": "0",
        "avg_price": "347",
        "paid_fee": "2.5",
        "trades_count": 1,
        "trades": [
            {
                "uuid": "test-buy-trade-1",
                "price": "347",
                "volume": "14.4092219",
                "funds": "5000",
                "side": "bid",
                "created_at": "2026-08-22T11:00:00+09:00",
            }
        ],
    }


def test_accepted_buy_to_broker_filled_local_filled() -> None:
    session = MagicMock()
    order = SimpleNamespace(
        order_id=1800,
        broker_code="UPBIT",
        broker_order_id="test-buy-uuid-1",
        status_code=OrderStatus.ACCEPTED.value,
        symbol="KRW-GEOD",
        side_code="BUY",
        order_quantity=Decimal("14.4092219"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("14.4092219"),
        average_fill_price=None,
        filled_amount=None,
        filled_at=None,
        user_broker_account_id=1380,
        user_id=1,
        strategy_id=17483,
        strategy_deployment_id=None,
        metadata_payload={},
        upbit_client_identifier=None,
    )
    orders_repo = MagicMock()
    orders_repo.change_status.side_effect = (
        lambda **kwargs: setattr(
            kwargs["entity"], "status_code", kwargs["new_status"].value
        )
        or kwargs["entity"]
    )
    exec_repo = MagicMock()
    exec_repo.exists.return_value = False
    exec_repo.create_raw.return_value = SimpleNamespace(execution_id=1)

    svc = UpbitFillSyncService(session)
    svc._orders = orders_repo
    svc._executions = exec_repo

    with (
        patch(
            "stock_platform.broker.upbit.fill_sync_service.emit_live_safety_audit"
        ),
        patch.object(svc, "_apply_live_fill_ledger"),
        patch.object(svc, "_enqueue_post_fill", return_value=True),
    ):
        result = svc.apply_remote(
            order=order, remote=_buy_done_remote(), actor="TEST"
        )

    assert result.new_executions == 1
    assert order.status_code == OrderStatus.FILLED.value
    assert order.filled_quantity == Decimal("14.4092219")


def test_accepted_sell_to_broker_filled_local_filled() -> None:
    session = MagicMock()
    order = SimpleNamespace(
        order_id=1801,
        broker_code="UPBIT",
        broker_order_id="test-sell-uuid-1",
        status_code=OrderStatus.ACCEPTED.value,
        symbol="KRW-GEOD",
        side_code="SELL",
        order_quantity=Decimal("14.4092219"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("14.4092219"),
        average_fill_price=None,
        filled_amount=None,
        filled_at=None,
        user_broker_account_id=1380,
        user_id=1,
        strategy_id=17483,
        strategy_deployment_id=None,
        metadata_payload={"signal_reason": "MA_DEAD_CROSS"},
        upbit_client_identifier=None,
    )
    orders_repo = MagicMock()
    orders_repo.change_status.side_effect = (
        lambda **kwargs: setattr(
            kwargs["entity"], "status_code", kwargs["new_status"].value
        )
        or kwargs["entity"]
    )
    exec_repo = MagicMock()
    exec_repo.exists.return_value = False
    exec_repo.create_raw.return_value = SimpleNamespace(execution_id=2)

    svc = UpbitFillSyncService(session)
    svc._orders = orders_repo
    svc._executions = exec_repo

    with (
        patch(
            "stock_platform.broker.upbit.fill_sync_service.emit_live_safety_audit"
        ),
        patch.object(svc, "_apply_live_fill_ledger"),
        patch.object(svc, "_enqueue_post_fill", return_value=True),
    ):
        result = svc.apply_remote(
            order=order, remote=_sell_done_remote(), actor="TEST"
        )

    assert result.new_executions == 1
    assert order.status_code == OrderStatus.FILLED.value
    assert Decimal(str(order.filled_quantity)) == Decimal("14.4092219")
    assert Decimal(str(order.average_fill_price)) == Decimal("350")


def test_ensure_binding_sell_closes_and_pnl() -> None:
    """전량 SELL → binding CLOSED + realized_pnl."""

    open_row = SimpleNamespace(
        binding_id=1,
        owned_quantity=Decimal("14.4092219"),
        entry_price=Decimal("347"),
        fees=Decimal("2.5"),
        realized_pnl=Decimal("0"),
        status="OPEN",
        closed_at=None,
        meta_json={},
    )
    session = MagicMock()
    session.scalars.return_value = [open_row]

    svc = StrategyOwnedRiskService(session)
    closed = svc.ensure_binding_from_fill(
        user_broker_account_id=1380,
        broker_code="UPBIT",
        strategy_id=17483,
        deployment_id=None,
        symbol="KRW-GEOD",
        entry_order_id=None,
        broker_order_id="test-sell-uuid-1",
        quantity=Decimal("14.4092219"),
        entry_price=None,
        side="SELL",
        fees=Decimal("2.5216138325"),
        fill_price=Decimal("350"),
        exit_order_id=1801,
        filled_at=datetime(2026, 8, 22, 3, 14, 53, tzinfo=timezone.utc),
    )

    assert closed is open_row
    assert open_row.status == "CLOSED"
    assert open_row.owned_quantity == Decimal("0")
    assert open_row.meta_json.get("exit_order_id") == 1801
    # gross (350-347)*qty
    expected_gross = (Decimal("350") - Decimal("347")) * Decimal(
        "14.4092219"
    )
    assert open_row.realized_pnl == expected_gross
    assert open_row.fees == Decimal("2.5") + Decimal("2.5216138325")


def test_fill_sync_sell_calls_binding_close() -> None:
    session = MagicMock()
    order = SimpleNamespace(
        order_id=1801,
        broker_code="UPBIT",
        broker_order_id="test-sell-uuid-1",
        status_code=OrderStatus.ACCEPTED.value,
        symbol="KRW-GEOD",
        side_code="SELL",
        order_quantity=Decimal("14.4092219"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("14.4092219"),
        average_fill_price=None,
        filled_amount=None,
        filled_at=None,
        user_broker_account_id=1380,
        user_id=1,
        strategy_id=17483,
        strategy_deployment_id=None,
        metadata_payload={"signal_reason": "MA_DEAD_CROSS"},
        upbit_client_identifier=None,
    )
    orders_repo = MagicMock()
    orders_repo.change_status.side_effect = (
        lambda **kwargs: setattr(
            kwargs["entity"], "status_code", kwargs["new_status"].value
        )
        or kwargs["entity"]
    )
    exec_repo = MagicMock()
    exec_repo.exists.return_value = False
    exec_repo.create_raw.return_value = SimpleNamespace(execution_id=3)

    svc = UpbitFillSyncService(session)
    svc._orders = orders_repo
    svc._executions = exec_repo
    binding = SimpleNamespace(
        binding_id=1,
        status="CLOSED",
        realized_pnl=Decimal("43.2276657"),
        fees=Decimal("5.0216138325"),
        entry_price=Decimal("347"),
    )

    with (
        patch(
            "stock_platform.broker.upbit.fill_sync_service.emit_live_safety_audit"
        ),
        patch.object(svc, "_enqueue_post_fill", return_value=True),
        patch(
            "stock_platform.broker.live_fill_ledger_service.LiveFillLedgerService"
        ),
        patch(
            "stock_platform.risk_engine.strategy_owned_risk_service."
            "StrategyOwnedRiskService"
        ) as risk_cls,
        patch(
            "stock_platform.order.live_safety_audit.emit_live_order_telegram"
        ) as tg,
    ):
        risk = risk_cls.return_value
        risk.ensure_binding_from_fill.return_value = binding
        result = svc.apply_remote(
            order=order, remote=_sell_done_remote(), actor="TEST"
        )

    assert result.new_executions == 1
    risk.ensure_binding_from_fill.assert_called()
    call_kw = risk.ensure_binding_from_fill.call_args.kwargs
    assert call_kw["side"] == "SELL"
    assert call_kw["exit_order_id"] == 1801
    assert call_kw["fill_price"] == Decimal("350")
    # ORDER_FILLED + POSITION_CLOSED + REALIZED_PNL
    assert tg.call_count == 3
    assert order.metadata_payload.get("fill_lifecycle_notified") is True


def test_duplicate_reconcile_idempotent_no_extra_execution() -> None:
    session = MagicMock()
    order = SimpleNamespace(
        order_id=1801,
        broker_code="UPBIT",
        broker_order_id="test-sell-uuid-1",
        status_code=OrderStatus.FILLED.value,
        symbol="KRW-GEOD",
        side_code="SELL",
        order_quantity=Decimal("14.4092219"),
        filled_quantity=Decimal("14.4092219"),
        remaining_quantity=Decimal("0"),
        average_fill_price=Decimal("350"),
        filled_amount=None,
        filled_at=datetime.now(timezone.utc),
        user_broker_account_id=1380,
        user_id=1,
        strategy_id=17483,
        strategy_deployment_id=None,
        metadata_payload={"fill_lifecycle_notified": True},
        upbit_client_identifier=None,
    )
    exec_repo = MagicMock()
    exec_repo.exists.return_value = True
    svc = UpbitFillSyncService(session)
    svc._orders = MagicMock()
    svc._executions = exec_repo

    with (
        patch(
            "stock_platform.broker.upbit.fill_sync_service.emit_live_safety_audit"
        ),
        patch.object(svc, "_enqueue_post_fill", return_value=True),
        patch.object(svc, "_apply_strategy_owned_binding") as bind,
        patch(
            "stock_platform.order.live_safety_audit.emit_live_order_telegram"
        ) as tg,
    ):
        r1 = svc.apply_remote(
            order=order, remote=_sell_done_remote(), actor="TEST"
        )
        r2 = svc.apply_remote(
            order=order, remote=_sell_done_remote(), actor="TEST"
        )

    assert r1.already_processed and r2.already_processed
    assert r1.new_executions == 0 and r2.new_executions == 0
    exec_repo.create_raw.assert_not_called()
    assert bind.call_count == 2  # repair 경로 재호출(멱등)
    tg.assert_not_called()  # fill_lifecycle_notified


def test_open_order_fill_poller_syncs_accepted() -> None:
    session = MagicMock()
    poller = UpbitOpenOrderFillPoller(session)
    with patch.object(
        poller, "select_due_order_ids", return_value=[1801]
    ):
        with patch(
            "stock_platform.broker.upbit.fill_sync_service.UpbitFillSyncService"
        ) as sync_cls:
            sync_cls.return_value.sync_by_order_id.return_value = (
                SimpleNamespace(
                    order_id=1801,
                    order_status=OrderStatus.FILLED.value,
                    new_executions=1,
                    already_processed=False,
                )
            )
            session.get.return_value = SimpleNamespace(
                status_code=OrderStatus.ACCEPTED.value
            )
            out = poller.poll_once(limit=10, actor="TEST_POLLER")

    assert out["checked"] == 1
    assert out["updated"] == 1
    sync_cls.return_value.sync_by_order_id.assert_called_once_with(
        1801, actor="TEST_POLLER"
    )


def test_partial_fill_keeps_non_terminal_until_done() -> None:
    session = MagicMock()
    order = SimpleNamespace(
        order_id=99,
        broker_code="UPBIT",
        broker_order_id="partial-uuid",
        status_code=OrderStatus.ACCEPTED.value,
        symbol="KRW-GEOD",
        side_code="SELL",
        order_quantity=Decimal("10"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("10"),
        average_fill_price=None,
        filled_amount=None,
        filled_at=None,
        user_broker_account_id=1380,
        user_id=1,
        strategy_id=17483,
        strategy_deployment_id=None,
        metadata_payload={},
        upbit_client_identifier=None,
    )
    orders_repo = MagicMock()
    orders_repo.change_status.side_effect = (
        lambda **kwargs: setattr(
            kwargs["entity"], "status_code", kwargs["new_status"].value
        )
        or kwargs["entity"]
    )
    exec_repo = MagicMock()
    exec_repo.exists.return_value = False
    exec_repo.create_raw.return_value = SimpleNamespace(execution_id=9)

    remote = {
        "uuid": "partial-uuid",
        "market": "KRW-GEOD",
        "side": "ask",
        "state": "wait",
        "executed_volume": "4",
        "remaining_volume": "6",
        "paid_fee": "1",
        "trades_count": 1,
        "trades": [
            {
                "uuid": "t-partial",
                "price": "350",
                "volume": "4",
                "funds": "1400",
                "side": "ask",
                "created_at": "2026-08-22T12:00:00+09:00",
            }
        ],
    }
    svc = UpbitFillSyncService(session)
    svc._orders = orders_repo
    svc._executions = exec_repo
    with (
        patch(
            "stock_platform.broker.upbit.fill_sync_service.emit_live_safety_audit"
        ),
        patch.object(svc, "_apply_live_fill_ledger"),
        patch.object(svc, "_enqueue_post_fill", return_value=True),
    ):
        result = svc.apply_remote(order=order, remote=remote, actor="TEST")

    assert order.status_code == OrderStatus.PARTIALLY_FILLED.value
    assert result.new_executions == 1
