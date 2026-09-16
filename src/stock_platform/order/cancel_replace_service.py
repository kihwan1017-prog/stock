from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.models import (
    BrokerOrderRequest,
)
from stock_platform.order.models import (
    OrderStatus,
)
from stock_platform.order.repository import (
    TradingOrderRepository,
)
from stock_platform.order.trading_guards import (
    require_kill_switch_allows_order,
)


class OrderCancelReplaceService:
    def __init__(
        self,
        *,
        session: Session,
        adapter: BrokerAdapter,
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
        """취소는 Kill Switch 활성 시에도 허용한다 (리스크 축소)."""

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

        # 정정은 신규 노출 가능 → Kill Switch 검사
        require_kill_switch_allows_order(
            self._repository.session,
            side=str(entity.side_code),
            allow_sell=True,
            exchange_code=str(entity.exchange_code),
        )

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
                user_broker_account_id=(
                    entity.user_broker_account_id
                ),
                broker_code=entity.broker_code,
                account_type=str(
                    (entity.metadata_payload or {}).get(
                        "environment"
                    )
                    or "PAPER"
                ).upper(),
                external_account_ref=None,
                credential_ref=(
                    f"USER_BROKER_ACCOUNT:{entity.user_broker_account_id}"
                    if entity.user_broker_account_id
                    else None
                ),
                uses_system_shared_credential=False,
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
            filled = Decimal(str(entity.filled_quantity or 0))
            entity.order_quantity = quantity
            entity.order_price = price
            # 부분체결 후 정정: remaining = 신규수량 - 기체결
            entity.remaining_quantity = max(
                Decimal("0"),
                quantity - filled,
            )
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
