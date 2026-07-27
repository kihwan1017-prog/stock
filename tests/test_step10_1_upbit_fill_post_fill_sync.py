"""STEP 10-1 — Upbit fill sync / Post-fill / order_id payload 회귀 (실주문 0)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.broker.upbit.fill_sync_service import UpbitFillSyncService
from stock_platform.broker.upbit.order_status import normalize_upbit_order_status
from stock_platform.order.models import OrderStatus
from stock_platform.trading.upbit_live_tracking_service import (
    map_broker_raw_status,
)

# STEP 9-6 fixture (실 UUID/자격증명 하드코딩 금지)
FIXTURE_MARKET = "KRW-BTC"
FIXTURE_VOLUME = Decimal("0.00005254")
FIXTURE_PRICE = Decimal("95150000")
FIXTURE_FUNDS = Decimal("4999.181")
FIXTURE_FEE = Decimal("2.4995905")


def _cancel_with_fill_remote() -> dict:
    return {
        "uuid": "test-uuid-fill-1",
        "market": FIXTURE_MARKET,
        "side": "bid",
        "ord_type": "price",
        "price": "5000",
        "state": "cancel",
        "executed_volume": str(FIXTURE_VOLUME),
        "remaining_volume": "0",
        "paid_fee": str(FIXTURE_FEE),
        "trades_count": 1,
        "identifier": "spu-test-identifier",
        "created_at": "2026-07-27T13:22:52+09:00",
        "trades": [
            {
                "uuid": "test-trade-1",
                "market": FIXTURE_MARKET,
                "price": str(FIXTURE_PRICE),
                "volume": str(FIXTURE_VOLUME),
                "funds": str(FIXTURE_FUNDS),
                "side": "bid",
                "created_at": "2026-07-27T13:22:53+09:00",
            }
        ],
    }


def test_normalize_done_with_fill() -> None:
    st = normalize_upbit_order_status(
        {"state": "done", "executed_volume": "0.01", "remaining_volume": "0"}
    )
    assert st == OrderStatus.FILLED


def test_normalize_cancel_with_fill_is_filled() -> None:
    st = normalize_upbit_order_status(_cancel_with_fill_remote())
    assert st == OrderStatus.FILLED


def test_normalize_cancel_without_fill_is_cancelled() -> None:
    st = normalize_upbit_order_status(
        {"state": "cancel", "executed_volume": "0"}
    )
    assert st == OrderStatus.CANCELLED


def test_normalize_wait_partial() -> None:
    st = normalize_upbit_order_status(
        {"state": "wait", "executed_volume": "0.001"}
    )
    assert st == OrderStatus.PARTIALLY_FILLED


def test_map_broker_raw_cancel_with_executed() -> None:
    assert (
        map_broker_raw_status("cancel", executed_volume="0.00005254")
        == "FILLED"
    )
    assert map_broker_raw_status("cancel", executed_volume="0") == "CANCELED"


def test_fill_sync_records_execution_and_post_fill() -> None:
    session = MagicMock()
    order = SimpleNamespace(
        order_id=250,
        broker_code="UPBIT",
        broker_order_id="test-uuid-fill-1",
        status_code=OrderStatus.ACCEPTED.value,
        symbol=FIXTURE_MARKET,
        side_code="BUY",
        order_quantity=Decimal("0.00001"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("0.00001"),
        average_fill_price=None,
        filled_amount=None,
        user_broker_account_id=58,
        user_id=7,
        upbit_client_identifier=None,
    )
    orders_repo = MagicMock()
    orders_repo.get.return_value = order
    orders_repo.change_status.side_effect = (
        lambda **kwargs: setattr(
            kwargs["entity"], "status_code", kwargs["new_status"].value
        )
        or kwargs["entity"]
    )
    exec_repo = MagicMock()
    exec_repo.exists.return_value = False
    created = SimpleNamespace(execution_id=99)
    exec_repo.create_raw.return_value = created

    svc = UpbitFillSyncService(session)
    svc._orders = orders_repo
    svc._executions = exec_repo

    with (
        patch(
            "stock_platform.broker.upbit.fill_sync_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.order.post_fill_runner.PostFillVerifyRunner"
        ) as runner_cls,
    ):
        runner = runner_cls.return_value
        runner.verify_after_order_fill.return_value = SimpleNamespace(
            ok=True, reason_code="OK", detail={}
        )
        result = svc.apply_remote(
            order=order,
            remote=_cancel_with_fill_remote(),
            actor="TEST",
        )

    assert result.new_executions == 1
    assert result.duplicate_executions == 0
    assert result.post_fill_enqueued is True
    assert order.status_code == OrderStatus.FILLED.value
    assert order.filled_quantity == FIXTURE_VOLUME
    assert order.average_fill_price == FIXTURE_PRICE
    exec_repo.create_raw.assert_called_once()
    runner.verify_after_order_fill.assert_called_once()


def test_fill_sync_duplicate_trade_is_idempotent() -> None:
    session = MagicMock()
    order = SimpleNamespace(
        order_id=250,
        broker_code="UPBIT",
        broker_order_id="test-uuid-fill-1",
        status_code=OrderStatus.FILLED.value,
        symbol=FIXTURE_MARKET,
        side_code="BUY",
        order_quantity=Decimal("0.00001"),
        filled_quantity=FIXTURE_VOLUME,
        remaining_quantity=Decimal("0"),
        average_fill_price=FIXTURE_PRICE,
        filled_amount=FIXTURE_FUNDS,
        user_broker_account_id=58,
        user_id=7,
        upbit_client_identifier=None,
    )
    orders_repo = MagicMock()
    orders_repo.get.return_value = order
    exec_repo = MagicMock()
    exec_repo.exists.return_value = True

    svc = UpbitFillSyncService(session)
    svc._orders = orders_repo
    svc._executions = exec_repo

    with (
        patch(
            "stock_platform.broker.upbit.fill_sync_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.order.post_fill_runner.PostFillVerifyRunner"
        ) as runner_cls,
    ):
        runner_cls.return_value.verify_after_order_fill.return_value = (
            SimpleNamespace(ok=True, reason_code="OK", detail={})
        )
        result = svc.apply_remote(
            order=order,
            remote=_cancel_with_fill_remote(),
            actor="TEST",
        )

    assert result.already_processed is True
    assert result.duplicate_executions == 1
    assert result.new_executions == 0
    assert result.post_fill_enqueued is True  # 수동 FILLED 후 Post-fill 보강
    exec_repo.create_raw.assert_not_called()
    orders_repo.change_status.assert_not_called()


def test_filled_path_still_enqueues_post_fill_without_new_execution() -> None:
    """이미 FILLED + 중복 체결이어도 Post-fill enqueue는 수행한다."""

    session = MagicMock()
    order = SimpleNamespace(
        order_id=250,
        broker_code="UPBIT",
        broker_order_id="test-uuid-fill-1",
        status_code=OrderStatus.FILLED.value,
        symbol=FIXTURE_MARKET,
        side_code="BUY",
        order_quantity=Decimal("0.00001"),
        filled_quantity=FIXTURE_VOLUME,
        remaining_quantity=Decimal("0"),
        average_fill_price=FIXTURE_PRICE,
        filled_amount=FIXTURE_FUNDS,
        user_broker_account_id=58,
        user_id=7,
        upbit_client_identifier=None,
    )
    svc = UpbitFillSyncService(session)
    svc._orders = MagicMock()
    svc._executions = MagicMock()
    svc._executions.exists.return_value = True

    with (
        patch(
            "stock_platform.broker.upbit.fill_sync_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.order.post_fill_runner.PostFillVerifyRunner"
        ) as runner_cls,
    ):
        result = svc.apply_remote(
            order=order,
            remote=_cancel_with_fill_remote(),
            actor="BACKFILL",
        )

    assert result.post_fill_enqueued is True
    runner_cls.return_value.verify_after_order_fill.assert_called_once()


def test_tracker_and_recovery_share_normalize() -> None:
    """Tracker map과 FillSync 정규화가 cancel+fill 을 동일하게 FILLED 처리."""

    remote = _cancel_with_fill_remote()
    assert normalize_upbit_order_status(remote) == OrderStatus.FILLED
    assert (
        map_broker_raw_status(
            remote["state"], executed_volume=remote["executed_volume"]
        )
        == "FILLED"
    )


def test_post_fill_failure_does_not_call_create_order() -> None:
    session = MagicMock()
    order = SimpleNamespace(
        order_id=1,
        broker_code="UPBIT",
        broker_order_id="u1",
        status_code=OrderStatus.ACCEPTED.value,
        symbol="KRW-BTC",
        side_code="BUY",
        order_quantity=Decimal("1"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("1"),
        average_fill_price=None,
        filled_amount=None,
        user_broker_account_id=1,
        user_id=1,
        upbit_client_identifier=None,
    )
    svc = UpbitFillSyncService(session)
    svc._orders = MagicMock()
    svc._orders.change_status.side_effect = (
        lambda **kwargs: setattr(
            kwargs["entity"], "status_code", kwargs["new_status"].value
        )
        or kwargs["entity"]
    )
    svc._executions = MagicMock()
    svc._executions.exists.return_value = False
    svc._executions.create_raw.return_value = SimpleNamespace(execution_id=1)

    with (
        patch(
            "stock_platform.broker.upbit.fill_sync_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.order.post_fill_runner.PostFillVerifyRunner",
            side_effect=RuntimeError("sync down"),
        ),
        patch(
            "stock_platform.broker.upbit.order_client.UpbitOrderRestClient.create_order"
        ) as create_order,
    ):
        result = svc.apply_remote(
            order=order,
            remote=_cancel_with_fill_remote(),
            actor="TEST",
        )
    assert result.post_fill_enqueued is False
    create_order.assert_not_called()


def test_outbox_submit_payload_includes_order_id() -> None:
    """STEP 9-6 회귀 — submit / enqueue_existing payload에 order_id 필수."""

    import inspect

    from stock_platform.order import execution_service as mod

    src = inspect.getsource(mod.OrderExecutionService.submit)
    src_existing = inspect.getsource(mod.OrderExecutionService)
    assert '"order_id": order.order_id' in src or (
        '"order_id": order.order_id' in src_existing
    )
    # enqueue_existing 경로
    assert "enqueue_existing" in src_existing or "def enqueue" in src_existing
    enqueue_src = inspect.getsource(mod.OrderExecutionService)
    # 두 enqueue payload 모두 order_id 포함
    assert enqueue_src.count('"order_id": order.order_id') >= 2


def test_outbox_worker_sets_order_id_default() -> None:
    import inspect

    from stock_platform.order import outbox_worker as mod

    src = inspect.getsource(mod.OrderOutboxWorker.run_once)
    assert "setdefault(\"order_id\"" in src or "setdefault('order_id'" in src


def test_fixture_decimal_math() -> None:
    avg = FIXTURE_FUNDS / FIXTURE_VOLUME
    assert abs(avg - FIXTURE_PRICE) < Decimal("0.01")
    notional = FIXTURE_VOLUME * FIXTURE_PRICE
    assert abs(notional - FIXTURE_FUNDS) < Decimal("0.01")


def test_fill_sync_does_not_create_order() -> None:
    """Post-fill/fill-sync는 create_order를 호출하지 않는다."""

    session = MagicMock()
    order = SimpleNamespace(
        order_id=1,
        broker_code="UPBIT",
        broker_order_id="u1",
        status_code=OrderStatus.ACCEPTED.value,
        symbol="KRW-BTC",
        side_code="BUY",
        order_quantity=Decimal("1"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("1"),
        average_fill_price=None,
        filled_amount=None,
        user_broker_account_id=1,
        user_id=1,
        upbit_client_identifier=None,
    )
    svc = UpbitFillSyncService(session)
    svc._orders = MagicMock()
    svc._orders.change_status.side_effect = (
        lambda **kwargs: setattr(
            kwargs["entity"], "status_code", kwargs["new_status"].value
        )
        or kwargs["entity"]
    )
    svc._executions = MagicMock()
    svc._executions.exists.return_value = False
    svc._executions.create_raw.return_value = SimpleNamespace(execution_id=1)

    with (
        patch(
            "stock_platform.broker.upbit.fill_sync_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.order.post_fill_runner.PostFillVerifyRunner"
        ),
        patch(
            "stock_platform.broker.upbit.order_client.UpbitOrderRestClient.create_order"
        ) as create_order,
    ):
        svc.apply_remote(
            order=order,
            remote=_cancel_with_fill_remote(),
            actor="TEST",
        )
    create_order.assert_not_called()
