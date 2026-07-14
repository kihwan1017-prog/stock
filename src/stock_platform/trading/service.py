from __future__ import annotations

from decimal import Decimal

from stock_platform.trading.models import (
    OrderSide,
    OrderType,
    PaperOrder,
)
from stock_platform.trading.paper_engine import (
    PaperOrderEngine,
)
from stock_platform.trading.repository import (
    PaperOrderRepository,
)


class PaperOrderService:
    def __init__(
        self,
        repository: PaperOrderRepository,
        engine: PaperOrderEngine | None = None,
    ) -> None:
        self._repository = repository
        self._engine = engine or PaperOrderEngine()

    def create(
        self,
        *,
        exchange_code: str,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None,
        position_plan_id: int | None = None,
        auto_accept: bool = True,
    ) -> PaperOrder:
        order = self._engine.create_order(
            exchange_code=exchange_code,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            position_plan_id=position_plan_id,
        )

        if auto_accept:
            self._engine.accept(order)

        return self._repository.save(order)

    def fill(
        self,
        *,
        order_id: int,
        fill_quantity: Decimal,
        fill_price: Decimal,
    ) -> PaperOrder:
        order = self._get_required(order_id)
        self._engine.fill(
            order,
            fill_quantity=fill_quantity,
            fill_price=fill_price,
        )
        return self._repository.save(order)

    def cancel(self, *, order_id: int) -> PaperOrder:
        order = self._get_required(order_id)
        self._engine.cancel(order)
        return self._repository.save(order)

    def reject(
        self,
        *,
        order_id: int,
        reason: str,
    ) -> PaperOrder:
        order = self._get_required(order_id)
        self._engine.reject(
            order,
            reason=reason,
        )
        return self._repository.save(order)

    def _get_required(self, order_id: int) -> PaperOrder:
        order = self._repository.get(order_id)
        if order is None:
            raise LookupError(
                f"Paper order not found: {order_id}"
            )
        return order
