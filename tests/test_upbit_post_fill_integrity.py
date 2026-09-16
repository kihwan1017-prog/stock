"""Upbit post-fill integrity — trade SoT / fee 제외 / LIVE_OFF READ (실 WRITE 0)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.broker.upbit.fill_sync_service import UpbitFillSyncService
from stock_platform.broker.upbit.order_status import upbit_fill_summary
from stock_platform.order.models import OrderStatus
from stock_platform.order.post_fill_runner import PostFillVerifyRunner


# 1685 실측 픽스처 (실 자격증명/재주문 금지)
QTY = Decimal("3.44827587")
PRICE = Decimal("1450")
FUNDS = Decimal("5000.0000115")
FEE = Decimal("2.50000000575")
TRADE_UUID = "3cd0b5dd-aaaa-bbbb-cccc-111122223333"
ORDER_UUID = "a0b431e3-4305-4547-9373-2be5a1fd61ca"


def _remote_single_trade(*, include_fee_inclusive_avg: bool = True) -> dict:
    remote = {
        "uuid": ORDER_UUID,
        "market": "KRW-XRP",
        "side": "bid",
        "ord_type": "limit",
        "price": "1450",
        "state": "done",
        "executed_volume": str(QTY),
        "remaining_volume": "0",
        "paid_fee": str(FEE),
        "trades_count": 1,
        "trades": [
            {
                "uuid": TRADE_UUID,
                "market": "KRW-XRP",
                "price": str(PRICE),
                "volume": str(QTY),
                "funds": str(FUNDS),
                "side": "bid",
                "created_at": "2026-08-08T11:11:50+09:00",
            }
        ],
    }
    if include_fee_inclusive_avg:
        # Upbit가 내려주는 fee-inclusive avg — 로컬은 무시해야 함
        remote["avg_price"] = "1450.725"
    return remote


def _remote_multi_trades() -> dict:
    t1_qty = Decimal("1.5")
    t2_qty = Decimal("1.94827587")
    t1_price = Decimal("1440")
    t2_price = Decimal("1460")
    t1_funds = t1_price * t1_qty
    t2_funds = t2_price * t2_qty
    return {
        "uuid": ORDER_UUID,
        "market": "KRW-XRP",
        "side": "bid",
        "ord_type": "limit",
        "price": "1450",
        "state": "done",
        "executed_volume": str(t1_qty + t2_qty),
        "remaining_volume": "0",
        "paid_fee": str(FEE),
        "avg_price": "9999",  # 무시 대상
        "trades_count": 2,
        "trades": [
            {
                "uuid": "trade-a",
                "price": str(t1_price),
                "volume": str(t1_qty),
                "funds": str(t1_funds),
                "created_at": "2026-08-08T11:11:50+09:00",
            },
            {
                "uuid": "trade-b",
                "price": str(t2_price),
                "volume": str(t2_qty),
                "funds": str(t2_funds),
                "created_at": "2026-08-08T11:11:51+09:00",
            },
        ],
    }


def _order(**kwargs):
    base = dict(
        order_id=1685,
        broker_code="UPBIT",
        broker_order_id=ORDER_UUID,
        status_code=OrderStatus.ACCEPTED.value,
        symbol="KRW-XRP",
        side_code="BUY",
        order_quantity=QTY,
        filled_quantity=Decimal("0"),
        remaining_quantity=QTY,
        average_fill_price=None,
        filled_amount=Decimal("0"),
        user_broker_account_id=1380,
        user_id=61,
        upbit_client_identifier=None,
        metadata_payload={"smoke_run_id": "uvs-test-fill"},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_fill_summary_excludes_fee_from_avg_and_amount() -> None:
    summary = upbit_fill_summary(_remote_single_trade())
    assert summary["avg_price"] == PRICE
    assert summary["funds"] == FUNDS
    assert summary["paid_fee"] == FEE
    assert summary["executed_volume"] == QTY
    # fee-inclusive Upbit avg_price 미사용
    assert summary["avg_price"] != Decimal("1450.725")


def test_fill_summary_ignores_fee_inclusive_avg_without_trades() -> None:
    remote = {
        "uuid": ORDER_UUID,
        "ord_type": "limit",
        "price": "1450",
        "state": "done",
        "executed_volume": str(QTY),
        "avg_price": "1450.725",
        "paid_fee": str(FEE),
        "trades_count": 1,
    }
    summary = upbit_fill_summary(remote)
    assert summary["avg_price"] == PRICE
    assert summary["funds"] == QTY * PRICE


def test_single_trade_sync_uses_trade_uuid_and_fee_excluded() -> None:
    session = MagicMock()
    order = _order()
    orders_repo = MagicMock()
    orders_repo.change_status.side_effect = (
        lambda **kwargs: setattr(
            kwargs["entity"], "status_code", kwargs["new_status"].value
        )
        or kwargs["entity"]
    )
    exec_repo = MagicMock()
    exec_repo.exists.return_value = False
    exec_repo.list_by_order_id.return_value = []
    created = SimpleNamespace(execution_id=101)
    exec_repo.create_raw.return_value = created

    run = SimpleNamespace(
        run_id="uvs-test-fill",
        filled_quantity=None,
        filled_amount=None,
        avg_fill_price=None,
        fee_amount=None,
        broker_order_uuid=None,
        broker_order_status=None,
        order_status=None,
        detail={},
        status_code="FILLED",
    )
    session.scalar.return_value = run

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
            remote=_remote_single_trade(),
            actor="TEST",
        )

    assert result.new_executions == 1
    assert order.average_fill_price == PRICE
    assert order.filled_amount == FUNDS
    assert order.filled_quantity == QTY
    assert order.metadata_payload["upbit_paid_fee"] == str(FEE)
    call_kwargs = exec_repo.create_raw.call_args.kwargs
    assert call_kwargs["broker_execution_id"] == TRADE_UUID
    assert call_kwargs["execution_price"] == PRICE
    assert run.avg_fill_price == PRICE
    assert run.filled_amount == FUNDS
    assert run.fee_amount == FEE
    assert run.filled_quantity == QTY


def test_duplicate_trade_uuid_is_idempotent() -> None:
    session = MagicMock()
    order = _order(
        status_code=OrderStatus.FILLED.value,
        filled_quantity=QTY,
        remaining_quantity=Decimal("0"),
        average_fill_price=Decimal("1450.725"),
        filled_amount=Decimal("5002.50001151"),
    )
    exec_repo = MagicMock()
    exec_repo.exists.return_value = True
    exec_repo.list_by_order_id.return_value = []

    svc = UpbitFillSyncService(session)
    svc._orders = MagicMock()
    svc._executions = exec_repo
    session.get.return_value = None

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
            remote=_remote_single_trade(),
            actor="RECONCILE",
        )

    assert result.duplicate_executions == 1
    assert result.new_executions == 0
    exec_repo.create_raw.assert_not_called()
    # 재동기화로 fee-excluded 값으로 정합화
    assert order.average_fill_price == PRICE
    assert order.filled_amount == FUNDS


def test_multiple_trades_weighted_average() -> None:
    remote = _remote_multi_trades()
    summary = upbit_fill_summary(remote)
    t1_qty = Decimal("1.5")
    t2_qty = Decimal("1.94827587")
    t1_price = Decimal("1440")
    t2_price = Decimal("1460")
    expected_avg = (t1_price * t1_qty + t2_price * t2_qty) / (t1_qty + t2_qty)
    assert summary["avg_price"] == expected_avg
    assert summary["funds"] == t1_price * t1_qty + t2_price * t2_qty

    session = MagicMock()
    order = _order()
    orders_repo = MagicMock()
    orders_repo.change_status.side_effect = (
        lambda **kwargs: setattr(
            kwargs["entity"], "status_code", kwargs["new_status"].value
        )
        or kwargs["entity"]
    )
    exec_repo = MagicMock()
    exec_repo.exists.return_value = False
    exec_repo.list_by_order_id.return_value = []
    exec_repo.create_raw.side_effect = [
        SimpleNamespace(execution_id=1),
        SimpleNamespace(execution_id=2),
    ]
    svc = UpbitFillSyncService(session)
    svc._orders = orders_repo
    svc._executions = exec_repo
    session.get.return_value = None

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
        result = svc.apply_remote(order=order, remote=remote, actor="TEST")

    assert result.new_executions == 2
    assert order.average_fill_price == expected_avg
    ids = [
        c.kwargs["broker_execution_id"]
        for c in exec_repo.create_raw.call_args_list
    ]
    assert ids == ["trade-a", "trade-b"]


def test_synthetic_superseded_when_real_trade_arrives() -> None:
    session = MagicMock()
    order = _order(status_code=OrderStatus.FILLED.value)
    synthetic = SimpleNamespace(
        broker_execution_id=f"{ORDER_UUID}:executed:{QTY}",
        raw_json={"source": "executed_volume", "synthetic": True},
    )
    exec_repo = MagicMock()
    # 첫 호출: trade insert 시 미존재, supersede list는 synthetic 포함
    exec_repo.exists.return_value = False
    exec_repo.list_by_order_id.return_value = [synthetic]
    exec_repo.create_raw.return_value = SimpleNamespace(execution_id=202)

    svc = UpbitFillSyncService(session)
    svc._orders = MagicMock()
    svc._executions = exec_repo
    session.get.return_value = None

    with (
        patch(
            "stock_platform.broker.upbit.fill_sync_service.emit_live_safety_audit"
        ),
        patch(
            "stock_platform.order.post_fill_runner.PostFillVerifyRunner"
        ),
    ):
        svc.apply_remote(
            order=order,
            remote=_remote_single_trade(),
            actor="RECONCILE",
        )

    assert synthetic.raw_json.get("superseded") is True
    assert TRADE_UUID in synthetic.raw_json.get("superseded_by", [])


def test_live_off_allows_post_fill_when_broker_uuid_present() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        live_order_enabled=False,
    )
    session.get.return_value = uba
    runner = PostFillVerifyRunner(session)

    with patch.object(
        runner._verifier, "verify", return_value=MagicMock(ok=True, reason_code="VERIFY_OK", detail={})
    ) as verify:
        # snapshot 경로 스킵을 위해 positions 주입
        result = runner.verify_uba_against_expected(
            user_broker_account_id=1380,
            user_id=61,
            broker_code="UPBIT",
            expected_positions=[{"symbol": "KRW-XRP", "quantity": str(QTY)}],
            expected_cash=None,
            broker_positions=[{"symbol": "KRW-XRP", "quantity": str(QTY)}],
            broker_cash=Decimal("100000"),
            allow_live_off_for_submitted=True,
        )
    assert result.reason_code != "LIVE_OFF_SKIP"
    verify.assert_called_once()


def test_live_off_blocks_when_no_submitted_flag() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=1380,
        live_order_enabled=False,
    )
    session.get.return_value = uba
    result = PostFillVerifyRunner(session).verify_uba_against_expected(
        user_broker_account_id=1380,
        user_id=61,
        broker_code="UPBIT",
        expected_positions=[],
        expected_cash=None,
        allow_live_off_for_submitted=False,
    )
    assert result.ok is True
    assert result.reason_code == "LIVE_OFF_SKIP"
