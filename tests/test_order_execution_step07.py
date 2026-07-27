"""STEP7 — 주문·Outbox·체결 정합성 단위 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderSide,
    BrokerOrderType,
)
from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.order.models import (
    OrderStatus,
    TERMINAL_ORDER_STATUSES,
)
from stock_platform.order.outbox_models import OutboxEventType
from stock_platform.order.outbox_worker import OrderOutboxWorker
from stock_platform.trading.execution_sync_service import (
    ExecutionSyncService,
)


def test_terminal_statuses_include_failed_and_replaced() -> None:
    assert OrderStatus.FAILED in TERMINAL_ORDER_STATUSES
    assert OrderStatus.REPLACED in TERMINAL_ORDER_STATUSES


def test_paper_submit_stable_broker_order_id() -> None:
    adapter = PaperBrokerAdapter()
    request = BrokerOrderRequest(
        client_order_id="CLI-ABC-12345",
        exchange_code="KRX",
        symbol="005930",
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("70000"),
        account_id=1,
    )
    first = adapter.submit_order(request)
    second = adapter.submit_order(request)
    assert first.broker_order_id == second.broker_order_id
    assert first.broker_order_id.startswith("PAPER-")


def test_execution_sync_partial_fill_recomputes_remaining() -> None:
    service = ExecutionSyncService.__new__(ExecutionSyncService)
    order = SimpleNamespace(
        order_id=1,
        status_code=OrderStatus.ACCEPTED.value,
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("10"),
        order_quantity=Decimal("10"),
        average_fill_price=None,
        filled_amount=Decimal("0"),
    )
    orders = MagicMock()
    orders.get_by_broker_order_id.return_value = order

    def change_status(*, entity, new_status, **_kwargs):
        entity.status_code = new_status.value
        return entity

    orders.change_status.side_effect = change_status
    executions = MagicMock()
    executions.exists.return_value = False
    executions.create.return_value = SimpleNamespace(execution_id=1)
    service._orders = orders
    service._executions = executions
    service._session = MagicMock()

    from stock_platform.broker.kiwoom.execution_models import (
        KiwoomExecutionEvent,
    )

    result = service.synchronize(
        KiwoomExecutionEvent(
            broker_order_id="B1",
            broker_execution_id="E-partial",
            symbol="005930",
            side_code="BUY",
            execution_quantity=Decimal("4"),
            execution_price=Decimal("70000"),
            remaining_quantity=Decimal("0"),  # 잘못된 remaining 무시
            executed_at=datetime.now(timezone.utc),
            raw_payload={},
        )
    )
    assert result.duplicate is False
    assert order.filled_quantity == Decimal("4")
    assert order.remaining_quantity == Decimal("6")
    assert result.order_status == OrderStatus.PARTIALLY_FILLED.value


def test_execution_sync_out_of_order_remaining_not_early_fill() -> None:
    """remaining=0 이벤트가 와도 누적 filled 기준으로만 FILLED 판정."""

    service = ExecutionSyncService.__new__(ExecutionSyncService)
    order = SimpleNamespace(
        order_id=1,
        status_code=OrderStatus.ACCEPTED.value,
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("10"),
        order_quantity=Decimal("10"),
        average_fill_price=None,
        filled_amount=Decimal("0"),
    )
    orders = MagicMock()
    orders.get_by_broker_order_id.return_value = order

    def change_status(*, entity, new_status, **_kwargs):
        entity.status_code = new_status.value
        return entity

    orders.change_status.side_effect = change_status
    executions = MagicMock()
    executions.exists.return_value = False
    executions.create.return_value = SimpleNamespace(execution_id=2)
    service._orders = orders
    service._executions = executions
    service._session = MagicMock()

    from stock_platform.broker.kiwoom.execution_models import (
        KiwoomExecutionEvent,
    )

    result = service.synchronize(
        KiwoomExecutionEvent(
            broker_order_id="B1",
            broker_execution_id="E-late",
            symbol="005930",
            side_code="BUY",
            execution_quantity=Decimal("3"),
            execution_price=Decimal("71000"),
            remaining_quantity=Decimal("0"),
            executed_at=datetime.now(timezone.utc),
            raw_payload={},
        )
    )
    assert result.order_status == OrderStatus.PARTIALLY_FILLED.value
    assert order.remaining_quantity == Decimal("7")


def test_outbox_worker_completed_reapplies_without_dispatch(
    monkeypatch,
) -> None:
    worker = OrderOutboxWorker(
        session_factory=MagicMock(),
        dispatcher=MagicMock(),
        worker_id="w1",
    )
    session = MagicMock()
    order = SimpleNamespace(
        order_id=7,
        status_code=OrderStatus.PENDING.value,
        broker_order_id=None,
    )
    repo = MagicMock()
    repo.get.return_value = order

    def change_status(*, entity, new_status, **_kwargs):
        entity.status_code = new_status.value
        return entity

    repo.change_status.side_effect = change_status
    monkeypatch.setattr(
        "stock_platform.order.repository.TradingOrderRepository",
        lambda _s: repo,
    )
    worker._apply_order_broker_result(
        session=session,
        order_id=7,
        result={
            "accepted": True,
            "broker_order_id": "BRK-1",
        },
        event_type=OutboxEventType.SUBMIT_ORDER.value,
    )

    assert order.broker_order_id == "BRK-1"
    assert order.status_code == OrderStatus.ACCEPTED.value


def test_outbox_worker_fail_open_order_from_pending(
    monkeypatch,
) -> None:
    worker = OrderOutboxWorker(
        session_factory=MagicMock(),
        dispatcher=MagicMock(),
        worker_id="w1",
    )
    order = SimpleNamespace(
        order_id=3,
        status_code=OrderStatus.PENDING.value,
        reject_message=None,
    )
    repo = MagicMock()
    repo.get.return_value = order

    def change_status(*, entity, new_status, **_kwargs):
        entity.status_code = new_status.value
        return entity

    repo.change_status.side_effect = change_status
    monkeypatch.setattr(
        "stock_platform.order.repository.TradingOrderRepository",
        lambda _s: repo,
    )
    worker._fail_open_order(
        session=MagicMock(),
        order_id=3,
        error_message="broker down",
        event_type=OutboxEventType.SUBMIT_ORDER.value,
    )

    assert order.status_code == OrderStatus.FAILED.value
    assert order.reject_message == "broker down"


def test_reclaim_stale_processing_resets_rows() -> None:
    from stock_platform.order.outbox_repository import (
        OrderOutboxRepository,
    )
    from stock_platform.order.outbox_models import OutboxStatus

    session = MagicMock()
    now = datetime.now(timezone.utc)
    stale = SimpleNamespace(
        status_code=OutboxStatus.PROCESSING.value,
        locked_at=now - timedelta(minutes=10),
        locked_by="dead-worker",
        next_retry_at=None,
        last_error=None,
    )
    session.scalars.return_value = [stale]
    repo = OrderOutboxRepository(session)
    count = repo.reclaim_stale_processing(
        stale_after=timedelta(minutes=5),
        now=now,
    )
    assert count == 1
    assert stale.status_code == OutboxStatus.RETRY.value
    assert stale.locked_at is None
    assert stale.locked_by is None
