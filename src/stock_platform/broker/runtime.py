from __future__ import annotations

from decimal import Decimal

from stock_platform.broker.live_approval import (
    LiveTradingApprovalService,
)
from stock_platform.broker.paper_adapter import (
    PaperBrokerOrderAdapter,
)
from stock_platform.broker.service import (
    BrokerOrderService,
)


live_trading_approval_service = (
    LiveTradingApprovalService(
        ttl_seconds=300
    )
)

broker_order_adapter = PaperBrokerOrderAdapter(
    account_key="PAPER-1",
    initial_cash=Decimal("10000000"),
)

broker_order_service = BrokerOrderService(
    adapter=broker_order_adapter,
    approval_service=(
        live_trading_approval_service
    ),
    live_mode=False,
)
