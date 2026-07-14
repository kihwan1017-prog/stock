from __future__ import annotations

from decimal import Decimal

from stock_platform.trading.models import (
    OrderSide,
    OrderStatus,
    OrderType,
    PaperOrder,
)


ZERO = Decimal("0")


class PaperOrderValidationError(ValueError):
    pass


class PaperOrderEngine:
    """실제 브로커 전송 없이 주문 상태를 시뮬레이션한다."""

    def create_order(
        self,
        *,
        exchange_code: str,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Decimal | None,
        position_plan_id: int | None = None,
    ) -> PaperOrder:
        if quantity <= ZERO:
            raise PaperOrderValidationError(
                "quantity must be greater than zero"
            )

        if (
            order_type == OrderType.LIMIT
            and (price is None or price <= ZERO)
        ):
            raise PaperOrderValidationError(
                "price is required for LIMIT order"
            )

        return PaperOrder(
            position_plan_id=position_plan_id,
            exchange_code=exchange_code.upper(),
            symbol=symbol.upper(),
            side=side.value,
            order_type=order_type.value,
            status_code=OrderStatus.CREATED.value,
            requested_quantity=quantity,
            requested_price=price,
            filled_quantity=ZERO,
            average_fill_price=None,
            rejection_reason=None,
        )

    def accept(self, order: PaperOrder) -> PaperOrder:
        self._assert_status(
            order,
            allowed={OrderStatus.CREATED},
        )
        order.status_code = OrderStatus.ACCEPTED.value
        return order

    def fill(
        self,
        order: PaperOrder,
        *,
        fill_quantity: Decimal,
        fill_price: Decimal,
    ) -> PaperOrder:
        self._assert_status(
            order,
            allowed={
                OrderStatus.CREATED,
                OrderStatus.ACCEPTED,
                OrderStatus.PARTIALLY_FILLED,
            },
        )

        if fill_quantity <= ZERO:
            raise PaperOrderValidationError(
                "fill_quantity must be greater than zero"
            )
        if fill_price <= ZERO:
            raise PaperOrderValidationError(
                "fill_price must be greater than zero"
            )

        remaining = (
            order.requested_quantity
            - order.filled_quantity
        )

        if fill_quantity > remaining:
            raise PaperOrderValidationError(
                "fill_quantity exceeds remaining quantity"
            )

        previous_value = (
            order.filled_quantity
            * (
                order.average_fill_price
                or ZERO
            )
        )
        new_value = fill_quantity * fill_price
        new_total_quantity = (
            order.filled_quantity + fill_quantity
        )

        order.average_fill_price = (
            (previous_value + new_value)
            / new_total_quantity
        ).quantize(Decimal("0.00000001"))

        order.filled_quantity = new_total_quantity

        if order.filled_quantity == order.requested_quantity:
            order.status_code = OrderStatus.FILLED.value
        else:
            order.status_code = (
                OrderStatus.PARTIALLY_FILLED.value
            )

        return order

    def cancel(self, order: PaperOrder) -> PaperOrder:
        self._assert_status(
            order,
            allowed={
                OrderStatus.CREATED,
                OrderStatus.ACCEPTED,
                OrderStatus.PARTIALLY_FILLED,
            },
        )
        order.status_code = OrderStatus.CANCELLED.value
        return order

    def reject(
        self,
        order: PaperOrder,
        *,
        reason: str,
    ) -> PaperOrder:
        self._assert_status(
            order,
            allowed={
                OrderStatus.CREATED,
                OrderStatus.ACCEPTED,
            },
        )
        order.status_code = OrderStatus.REJECTED.value
        order.rejection_reason = reason
        return order

    @staticmethod
    def _assert_status(
        order: PaperOrder,
        *,
        allowed: set[OrderStatus],
    ) -> None:
        current = OrderStatus(order.status_code)
        if current not in allowed:
            raise PaperOrderValidationError(
                f"Invalid order status transition: "
                f"{current.value}"
            )
