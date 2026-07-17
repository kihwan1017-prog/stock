from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.execution_models import (
    KiwoomExecutionEvent,
)
from stock_platform.order.models import (
    OrderStatus,
)
from stock_platform.order.repository import (
    TradingOrderRepository,
)
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
    def __init__(self, session: Session) -> None:
        self._session = session
        self._orders = TradingOrderRepository(
            session
        )
        self._executions = (
            TradingExecutionRepository(session)
        )

    def synchronize(
        self,
        event: KiwoomExecutionEvent,
        *,
        actor: str = "KIWOOM_WEBSOCKET",
    ) -> ExecutionSyncResult:
        if self._executions.exists(
            broker_code="KIWOOM",
            broker_execution_id=(
                event.broker_execution_id
            ),
        ):
            return ExecutionSyncResult(
                duplicate=True,
                order_found=True,
                execution_id=None,
                order_status=None,
            )

        order = (
            self._orders.get_by_broker_order_id(
                broker_code="KIWOOM",
                broker_order_id=(
                    event.broker_order_id
                ),
            )
        )

        if order is None:
            return ExecutionSyncResult(
                duplicate=False,
                order_found=False,
                execution_id=None,
                order_status=None,
            )

        execution = self._executions.create(
            order_id=order.order_id,
            event=event,
        )

        order.filled_quantity = (
            Decimal(str(order.filled_quantity))
            + event.execution_quantity
        )

        if event.remaining_quantity is not None:
            order.remaining_quantity = (
                event.remaining_quantity
            )
        else:
            order.remaining_quantity = max(
                Decimal("0"),
                Decimal(str(order.order_quantity))
                - Decimal(
                    str(order.filled_quantity)
                ),
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
            reason_code=(
                "EXECUTION_RECEIVED"
            ),
            message=(
                f"execution_id="
                f"{event.broker_execution_id}"
            ),
        )

        self._session.flush()

        return ExecutionSyncResult(
            duplicate=False,
            order_found=True,
            execution_id=(
                execution.execution_id
            ),
            order_status=new_status.value,
        )
