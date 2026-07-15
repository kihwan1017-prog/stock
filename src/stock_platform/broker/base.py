from __future__ import annotations

from abc import ABC, abstractmethod

from stock_platform.broker.models import (
    BrokerAccountSnapshot,
    BrokerOrderRequest,
    BrokerOrderResponse,
)


class BrokerOrderAdapter(ABC):
    @abstractmethod
    async def place_order(
        self,
        request: BrokerOrderRequest,
    ) -> BrokerOrderResponse:
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(
        self,
        broker_order_id: str,
    ) -> BrokerOrderResponse:
        raise NotImplementedError

    @abstractmethod
    async def get_order(
        self,
        broker_order_id: str,
    ) -> BrokerOrderResponse:
        raise NotImplementedError

    @abstractmethod
    async def get_account_snapshot(
        self,
    ) -> BrokerAccountSnapshot:
        raise NotImplementedError
