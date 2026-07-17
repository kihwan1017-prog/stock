from __future__ import annotations

from datetime import datetime, timezone

from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.kiwoom.config import (
    KiwoomOrderConfig,
)
from stock_platform.broker.kiwoom.http_client import (
    KiwoomRestClient,
)
from stock_platform.broker.kiwoom.order_mapper import (
    KiwoomOrderMapper,
)
from stock_platform.broker.kiwoom.rate_limiter import (
    KiwoomRateLimiters,
)
from stock_platform.broker.kiwoom.token_cache import (
    KiwoomTokenCache,
)
from stock_platform.broker.kiwoom.token_client import (
    KiwoomTokenClient,
)
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerOrderStatus,
)


class KiwoomBrokerAdapter(BrokerAdapter):
    ORDER_PATH = "/api/dostk/ordr"

    def __init__(
        self,
        *,
        config: KiwoomOrderConfig | None = None,
        rest_client: KiwoomRestClient | None = None,
    ) -> None:
        self.config = (
            config or KiwoomOrderConfig.from_env()
        )

        if rest_client is None:
            token_client = KiwoomTokenClient(
                self.config
            )
            token_cache = KiwoomTokenCache(
                token_client
            )
            rest_client = KiwoomRestClient(
                config=self.config,
                token_cache=token_cache,
                rate_limiters=KiwoomRateLimiters(),
            )

        self._rest_client = rest_client

    def submit_order(
        self,
        request: BrokerOrderRequest,
    ) -> BrokerOrderResult:
        if (
            not self.config.use_mock
            and not self.config.live_order_enabled
        ):
            raise PermissionError(
                "Live Kiwoom order is disabled."
            )

        payload, _ = self._rest_client.post(
            path=self.ORDER_PATH,
            api_id=KiwoomOrderMapper.api_id(
                request.side
            ),
            body=KiwoomOrderMapper.body(request),
            request_type="ORDER",
        )

        accepted = (
            int(payload.get("return_code", -1))
            == 0
        )

        return BrokerOrderResult(
            accepted=accepted,
            status=(
                BrokerOrderStatus.ACCEPTED
                if accepted
                else BrokerOrderStatus.REJECTED
            ),
            broker_order_id=payload.get("ord_no"),
            submitted_at=datetime.now(
                timezone.utc
            ),
            reject_code=(
                None
                if accepted
                else str(
                    payload.get("return_code")
                )
            ),
            reject_message=(
                None
                if accepted
                else payload.get("return_msg")
            ),
        )

    def cancel_order(
        self,
        broker_order_id: str,
    ) -> BrokerOrderResult:
        raise NotImplementedError(
            "STEP32-6에서 취소 주문을 구현합니다."
        )

    def replace_order(
        self,
        broker_order_id: str,
        request: BrokerOrderRequest,
    ) -> BrokerOrderResult:
        raise NotImplementedError(
            "STEP32-6에서 정정 주문을 구현합니다."
        )

    def get_order(
        self,
        broker_order_id: str,
    ) -> BrokerOrderResult:
        raise NotImplementedError(
            "주문 조회는 KiwoomOrderInquiryClient를 "
            "사용하세요."
        )
