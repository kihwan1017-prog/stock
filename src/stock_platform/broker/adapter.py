from abc import ABC, abstractmethod
from stock_platform.broker.models import BrokerOrderRequest, BrokerOrderResult

class BrokerAdapter(ABC):
    @abstractmethod
    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        raise NotImplementedError

    @abstractmethod
    def replace_order(self, broker_order_id: str, request: BrokerOrderRequest) -> BrokerOrderResult:
        raise NotImplementedError

    @abstractmethod
    def get_order(self, broker_order_id: str) -> BrokerOrderResult:
        raise NotImplementedError
