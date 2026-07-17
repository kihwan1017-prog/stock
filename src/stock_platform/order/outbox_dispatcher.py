from __future__ import annotations

from decimal import Decimal
from typing import Any

from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.models import (
    BrokerOrderRequest,
)
from stock_platform.order.outbox_models import (
    OutboxEventType,
)


class OrderOutboxDispatcher:
    def __init__(
        self,
        adapter: BrokerAdapter,
    ) -> None:
        self._adapter = adapter

    def dispatch(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        event = OutboxEventType(event_type)

        if event == OutboxEventType.SUBMIT_ORDER:
            result = self._adapter.submit_order(
                self._to_order_request(payload)
            )
        elif event == OutboxEventType.CANCEL_ORDER:
            result = self._adapter.cancel_order(
                str(payload["broker_order_id"]),
                exchange_code=str(
                    payload.get(
                        "exchange_code",
                        "KRX",
                    )
                ),
                symbol=str(payload["symbol"]),
                cancel_quantity=Decimal(
                    str(payload["cancel_quantity"])
                ),
                idempotency_key=idempotency_key,
            )
        elif event == OutboxEventType.REPLACE_ORDER:
            result = self._adapter.replace_order(
                str(payload["broker_order_id"]),
                self._to_order_request(payload),
                idempotency_key=idempotency_key,
            )
        else:
            raise ValueError(
                f"Unsupported outbox event: {event_type}"
            )

        return {
            "accepted": result.accepted,
            "status": result.status.value,
            "broker_order_id": (
                result.broker_order_id
            ),
            "reject_code": result.reject_code,
            "reject_message": result.reject_message,
            "submitted_at": (
                result.submitted_at.isoformat()
            ),
        }

    @staticmethod
    def _to_order_request(
        payload: dict[str, Any],
    ) -> BrokerOrderRequest:
        price = payload.get("price")
        return BrokerOrderRequest(
            client_order_id=str(
                payload["client_order_id"]
            ),
            account_id=int(payload["account_id"]),
            exchange_code=str(
                payload.get("exchange_code", "KRX")
            ),
            symbol=str(payload["symbol"]),
            side=str(payload["side"]),
            order_type=str(payload["order_type"]),
            quantity=Decimal(
                str(payload["quantity"])
            ),
            price=(
                None
                if price in (None, "")
                else Decimal(str(price))
            ),
            time_in_force=str(
                payload.get("time_in_force", "DAY")
            ),
        )
