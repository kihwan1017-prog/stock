"""Broker 주문·계좌·WS·시세 통합 패키지 (canonical).

- 주문/계좌/WS: `broker.kiwoom`, `broker.upbit`, `broker.paper`
- 시세 REST: `broker.kiwoom.market`, `broker.upbit.market`
- 호환: 구경로 `stock_platform.brokers` 는 re-export 래퍼

STEP6: 시세 구현을 broker 트리로 이전. brokers 폴더는 삭제하지 않고 유지.
"""

from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    BrokerError,
    BrokerOrderRejectedError,
    UnsupportedBrokerFeatureError,
)
from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.models import (
    BrokerEnvironment,
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerOrderStatus,
)

__all__ = [
    "BrokerAdapter",
    "BrokerAdapterFactory",
    "BrokerAuthenticationError",
    "BrokerConnectionError",
    "BrokerEnvironment",
    "BrokerError",
    "BrokerOrderRejectedError",
    "BrokerOrderRequest",
    "BrokerOrderResult",
    "BrokerOrderStatus",
    "UnsupportedBrokerFeatureError",
]
