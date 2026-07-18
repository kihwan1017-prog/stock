from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.execution_models import (
    KiwoomExecutionEvent,
)
from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.trading.execution_repository import (
    TradingExecutionRepository,
)


@dataclass(frozen=True, slots=True)
class ExecutionSyncResult:
    duplicate: bool
    order_found: bool
    execution_id: int | None
    order_status: str | None


class ExecutionSyncService:
    """체결 이벤트를 주문 상태와 실행 이력에 반영한다."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._orders = TradingOrderRepository(session)
        self._executions = TradingExecutionRepository(session)

    def synchronize(
        self,
        event: KiwoomExecutionEvent,
        *,
        actor: str = "KIWOOM_WEBSOCKET",
    ) -> ExecutionSyncResult:
        if self._executions.exists(
            broker_code="KIWOOM",
            broker_execution_id=event.broker_execution_id,
        ):
            return ExecutionSyncResult(
                duplicate=True,
                order_found=True,
                execution_id=None,
                order_status=None,
            )

        order = self._orders.get_by_broker_order_id(
            broker_code="KIWOOM",
            broker_order_id=event.broker_order_id,
        )
        if order is None:
            return ExecutionSyncResult(
                duplicate=False,
                order_found=False,
                execution_id=None,
                order_status=None,
            )

        # WS ACCEPTED 누락 대비: 체결 전 상태로 정규화
        self._ensure_accepted(order=order, actor=actor)

        try:
            execution = self._executions.create(
                order_id=order.order_id,
                event=event,
            )
            self._session.flush()
        except IntegrityError:
            self._session.rollback()
            return ExecutionSyncResult(
                duplicate=True,
                order_found=True,
                execution_id=None,
                order_status=order.status_code,
            )

        order.filled_quantity = (
            Decimal(str(order.filled_quantity))
            + event.execution_quantity
        )
        if event.remaining_quantity is not None:
            order.remaining_quantity = event.remaining_quantity
        else:
            order.remaining_quantity = max(
                Decimal("0"),
                Decimal(str(order.order_quantity))
                - Decimal(str(order.filled_quantity)),
            )

        if order.average_fill_price is None:
            order.average_fill_price = event.execution_price
        else:
            filled_before = (
                Decimal(str(order.filled_quantity))
                - event.execution_quantity
            )
            if filled_before > 0:
                order.average_fill_price = (
                    (
                        Decimal(str(order.average_fill_price))
                        * filled_before
                    )
                    + (
                        event.execution_price
                        * event.execution_quantity
                    )
                ) / Decimal(str(order.filled_quantity))
            else:
                order.average_fill_price = event.execution_price

        order.filled_amount = (
            Decimal(str(order.filled_quantity))
            * Decimal(str(order.average_fill_price))
        )

        new_status = (
            OrderStatus.FILLED
            if order.remaining_quantity <= 0
            else OrderStatus.PARTIALLY_FILLED
        )
        self._orders.change_status(
            entity=order,
            new_status=new_status,
            actor=actor,
            reason_code="EXECUTION_RECEIVED",
            message=f"execution_id={event.broker_execution_id}",
            commit=False,
        )
        self._session.commit()

        return ExecutionSyncResult(
            duplicate=False,
            order_found=True,
            execution_id=execution.execution_id,
            order_status=new_status.value,
        )

    def _ensure_accepted(
        self,
        *,
        order,
        actor: str,
    ) -> None:
        status = OrderStatus(order.status_code)
        if status in {
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
        }:
            return

        if status == OrderStatus.CREATED:
            self._orders.change_status(
                entity=order,
                new_status=OrderStatus.PENDING,
                actor=actor,
                reason_code="EXECUTION_NORMALIZE",
                commit=False,
            )
            status = OrderStatus.PENDING

        if status == OrderStatus.PENDING:
            self._orders.change_status(
                entity=order,
                new_status=OrderStatus.SENT,
                actor=actor,
                reason_code="EXECUTION_NORMALIZE",
                commit=False,
            )
            status = OrderStatus.SENT

        if status == OrderStatus.SENT:
            self._orders.change_status(
                entity=order,
                new_status=OrderStatus.ACCEPTED,
                actor=actor,
                reason_code="EXECUTION_NORMALIZE",
                commit=False,
            )
