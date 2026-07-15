from __future__ import annotations

from stock_platform.broker.base import BrokerOrderAdapter
from stock_platform.broker.live_approval import (
    LiveTradingApprovalService,
)
from stock_platform.broker.models import (
    BrokerOrderRequest,
)


class BrokerOrderService:
    """Broker Adapter 호출 전 실거래 승인 여부를 확인한다."""

    def __init__(
        self,
        *,
        adapter: BrokerOrderAdapter,
        approval_service: LiveTradingApprovalService,
        live_mode: bool,
    ) -> None:
        self._adapter = adapter
        self._approval_service = approval_service
        self._live_mode = live_mode

    async def place_order(
        self,
        *,
        request: BrokerOrderRequest,
        approval_id: str | None = None,
        approval_token: str | None = None,
    ):
        if self._live_mode:
            if not approval_id or not approval_token:
                raise PermissionError(
                    "Live trading approval is required"
                )

            approved = self._approval_service.consume(
                approval_id=approval_id,
                approval_token=approval_token,
            )
            if not approved:
                raise PermissionError(
                    "Live trading approval is invalid, "
                    "expired, or already used"
                )

        return await self._adapter.place_order(request)
