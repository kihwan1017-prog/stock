from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.adapter import (
    KiwoomBrokerAdapter,
)
from stock_platform.broker.models import (
    BrokerOrderRequest,
)
from stock_platform.order.models import (
    OrderStatus,
)
from stock_platform.order.repository import (
    TradingOrderRepository,
)


class OrderCancelReplaceService:
    def __init__(
        self,
        *,
        session: Session,
        adapter: KiwoomBrokerAdapter,
    ) -> None:
        self._repository = TradingOrderRepository(
            session
        )
        self._adapter = adapter

    def cancel(
        self,
        *,
        order_id: int,
        quantity: Decimal | None = None,
        actor: str = "ORDER_CANCEL_SERVICE",
    ):
        entity = self._require_order(order_id)

        if not entity.broker_order_id:
            raise ValueError(
                "broker_order_id is missing"
            )

        cancel_qty = (
            quantity
            if quantity is not None
            else entity.remaining_quantity
        )

        self._repository.change_status(
            entity=entity,
            new_status=(
                OrderStatus.CANCEL_REQUESTED
            ),
            actor=actor,
            reason_code="CANCEL_REQUESTED",
        )

        result = self._adapter.cancel_order(
            entity.broker_order_id,
            exchange_code=entity.exchange_code,
            symbol=entity.symbol,
            cancel_quantity=cancel_qty,
            idempotency_key=(
                f"CANCEL:{entity.order_id}:"
                f"{entity.version_no}:{cancel_qty}"
            ),
        )

        entity = self._require_order(order_id)

        if result.accepted:
            return self._repository.change_status(
                entity=entity,
                new_status=OrderStatus.CANCELLED,
                actor=actor,
                reason_code="BROKER_CANCEL_ACCEPTED",
            )

        entity.reject_code = result.reject_code
        entity.reject_message = result.reject_message
        return self._repository.change_status(
            entity=entity,
            new_status=OrderStatus.FAILED,
            actor=actor,
            reason_code=(
                result.reject_code
                or "BROKER_CANCEL_REJECTED"
            ),
            message=result.reject_message,
        )

    def replace(
        self,
        *,
        order_id: int,
        quantity: Decimal,
        price: Decimal,
        actor: str = "ORDER_REPLACE_SERVICE",
    ):
        entity = self._require_order(order_id)

        if not entity.broker_order_id:
            raise ValueError(
                "broker_order_id is missing"
            )

        self._repository.change_status(
            entity=entity,
            new_status=(
                OrderStatus.REPLACE_REQUESTED
            ),
            actor=actor,
            reason_code="REPLACE_REQUESTED",
        )

        result = self._adapter.replace_order(
            entity.broker_order_id,
            BrokerOrderRequest(
                client_order_id=(
                    entity.client_order_id
                ),
                account_id=entity.account_id,
                exchange_code=(
                    entity.exchange_code
                ),
                symbol=entity.symbol,
                side=entity.side_code,
                order_type="LIMIT",
                quantity=quantity,
                price=price,
                time_in_force=(
                    entity.time_in_force_code
                ),
            ),
            idempotency_key=(
                f"REPLACE:{entity.order_id}:"
                f"{entity.version_no}:"
                f"{quantity}:{price}"
            ),
        )

        entity = self._require_order(order_id)

        if result.accepted:
            entity.order_quantity = quantity
            entity.order_price = price
            entity.remaining_quantity = quantity
            return self._repository.change_status(
                entity=entity,
                new_status=OrderStatus.REPLACED,
                actor=actor,
                reason_code=(
                    "BROKER_REPLACE_ACCEPTED"
                ),
            )

        entity.reject_code = result.reject_code
        entity.reject_message = result.reject_message
        return self._repository.change_status(
            entity=entity,
            new_status=OrderStatus.FAILED,
            actor=actor,
            reason_code=(
                result.reject_code
                or "BROKER_REPLACE_REJECTED"
            ),
            message=result.reject_message,
        )

    def _require_order(self, order_id: int):
        entity = self._repository.get(
            order_id=order_id
        )
        if entity is None:
            raise LookupError("Order not found")
        return entity
