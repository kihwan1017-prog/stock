from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.broker.base import BrokerOrderAdapter
from stock_platform.broker.models import (
    BrokerAccountSnapshot,
    BrokerOrderRequest,
    BrokerOrderResponse,
    BrokerOrderStatus,
)


class PaperBrokerOrderAdapter(BrokerOrderAdapter):
    """실거래 전환 구조 검증용 메모리 기반 Broker Adapter."""

    def __init__(
        self,
        *,
        account_key: str = "PAPER-1",
        initial_cash: Decimal = Decimal("10000000"),
    ) -> None:
        self._account_key = account_key
        self._cash = initial_cash
        self._orders: dict[str, BrokerOrderResponse] = {}

    async def place_order(
        self,
        request: BrokerOrderRequest,
    ) -> BrokerOrderResponse:
        now = datetime.now(timezone.utc)
        broker_order_id = (
            f"PAPER-{len(self._orders) + 1:08d}"
        )

        response = BrokerOrderResponse(
            broker_order_id=broker_order_id,
            client_order_id=request.client_order_id,
            status=BrokerOrderStatus.ACCEPTED,
            accepted_quantity=request.quantity,
            filled_quantity=Decimal("0"),
            average_fill_price=None,
            message="Paper broker accepted order",
            requested_at=now,
            updated_at=now,
        )

        self._orders[broker_order_id] = response
        return response

    async def cancel_order(
        self,
        broker_order_id: str,
    ) -> BrokerOrderResponse:
        current = await self.get_order(broker_order_id)
        now = datetime.now(timezone.utc)

        updated = BrokerOrderResponse(
            broker_order_id=current.broker_order_id,
            client_order_id=current.client_order_id,
            status=BrokerOrderStatus.CANCELLED,
            accepted_quantity=current.accepted_quantity,
            filled_quantity=current.filled_quantity,
            average_fill_price=current.average_fill_price,
            message="Paper broker cancelled order",
            requested_at=current.requested_at,
            updated_at=now,
        )
        self._orders[broker_order_id] = updated
        return updated

    async def get_order(
        self,
        broker_order_id: str,
    ) -> BrokerOrderResponse:
        try:
            return self._orders[broker_order_id]
        except KeyError as exc:
            raise LookupError(
                f"Broker order not found: {broker_order_id}"
            ) from exc

    async def get_account_snapshot(
        self,
    ) -> BrokerAccountSnapshot:
        return BrokerAccountSnapshot(
            account_key=self._account_key,
            cash_balance=self._cash,
            available_cash=self._cash,
            total_asset_value=self._cash,
            currency_code="KRW",
            fetched_at=datetime.now(timezone.utc),
        )
