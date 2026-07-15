import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from stock_platform.broker.live_approval import (
    LiveTradingApprovalService,
)
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderResponse,
    BrokerOrderSide,
    BrokerOrderStatus,
    BrokerOrderType,
)
from stock_platform.broker.service import (
    BrokerOrderService,
)


class FakeAdapter:
    async def place_order(self, request):
        now = datetime.now(timezone.utc)
        return BrokerOrderResponse(
            broker_order_id="1",
            client_order_id=request.client_order_id,
            status=BrokerOrderStatus.ACCEPTED,
            accepted_quantity=request.quantity,
            filled_quantity=Decimal("0"),
            average_fill_price=None,
            message=None,
            requested_at=now,
            updated_at=now,
        )


def _request():
    return BrokerOrderRequest(
        exchange_code="KRX",
        symbol="005930",
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.MARKET,
        quantity=Decimal("1"),
        price=None,
        client_order_id="client-1",
    )


def test_paper_mode_does_not_require_approval() -> None:
    service = BrokerOrderService(
        adapter=FakeAdapter(),
        approval_service=(
            LiveTradingApprovalService()
        ),
        live_mode=False,
    )

    result = asyncio.run(
        service.place_order(
            request=_request()
        )
    )

    assert result.status == (
        BrokerOrderStatus.ACCEPTED
    )


def test_live_mode_requires_approval() -> None:
    approval_service = (
        LiveTradingApprovalService()
    )
    service = BrokerOrderService(
        adapter=FakeAdapter(),
        approval_service=approval_service,
        live_mode=True,
    )

    issued = approval_service.issue()

    result = asyncio.run(
        service.place_order(
            request=_request(),
            approval_id=issued["approval_id"],
            approval_token=(
                issued["approval_token"]
            ),
        )
    )

    assert result.status == (
        BrokerOrderStatus.ACCEPTED
    )
