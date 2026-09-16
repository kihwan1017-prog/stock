from __future__ import annotations

from datetime import datetime, timezone

from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.exceptions import (
    UnsupportedBrokerFeatureError,
)
from stock_platform.broker.idempotency import (
    InMemoryIdempotencyStore,
)
from stock_platform.broker.kiwoom.cancel_replace_mapper import (
    KiwoomCancelReplaceMapper,
)
from stock_platform.broker.kiwoom.cancel_replace_models import (
    KiwoomCancelOrderRequest,
    KiwoomReplaceOrderRequest,
)
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
from stock_platform.broker.order_account_context import (
    require_user_broker_context_for_live,
)


class KiwoomBrokerAdapter(BrokerAdapter):
    ORDER_PATH = "/api/dostk/ordr"

    def __init__(
        self,
        *,
        config: KiwoomOrderConfig | None = None,
        rest_client: KiwoomRestClient | None = None,
        idempotency_store: (
            InMemoryIdempotencyStore[
                BrokerOrderResult
            ]
            | None
        ) = None,
    ) -> None:
        self.config = (
            config or KiwoomOrderConfig.from_env()
        )

        if rest_client is None:
            token_client = KiwoomTokenClient(
                self.config
            )
            rest_client = KiwoomRestClient(
                config=self.config,
                token_cache=KiwoomTokenCache(
                    token_client
                ),
                rate_limiters=KiwoomRateLimiters(),
            )

        self._rest_client = rest_client
        self._idempotency = (
            idempotency_store
            or InMemoryIdempotencyStore()
        )

    def submit_order(
        self,
        request: BrokerOrderRequest,
        **kwargs,
    ) -> BrokerOrderResult:
        self._assert_live_allowed()
        # LIVE 사용자 주문은 UBA 필수 — env 계좌를 사용자 계좌로 취급 금지
        require_user_broker_context_for_live(request)

        idempotency_key = str(
            kwargs.get("idempotency_key")
            or f"SUBMIT:{request.client_order_id}"
        )

        def _send() -> BrokerOrderResult:
            payload, _ = self._rest_client.post(
                path=self.ORDER_PATH,
                api_id=KiwoomOrderMapper.api_id(
                    request.side
                ),
                body=KiwoomOrderMapper.body(request),
                request_type="ORDER",
            )
            return self._to_result(payload)

        return self._idempotency.execute_once(
            key=idempotency_key,
            operation=_send,
        )

    def cancel_order(
        self,
        broker_order_id: str,
        *,
        exchange_code: str = "KRX",
        symbol: str,
        cancel_quantity,
        idempotency_key: str,
    ) -> BrokerOrderResult:
        self._assert_live_allowed()

        request = KiwoomCancelOrderRequest(
            broker_order_id=broker_order_id,
            exchange_code=exchange_code,
            symbol=symbol,
            cancel_quantity=cancel_quantity,
        )

        return self._idempotency.execute_once(
            key=idempotency_key,
            operation=lambda: self._send_cancel(
                request
            ),
        )

    def replace_order(
        self,
        broker_order_id: str,
        request: BrokerOrderRequest,
        *,
        idempotency_key: str | None = None,
    ) -> BrokerOrderResult:
        self._assert_live_allowed()
        require_user_broker_context_for_live(request)

        if request.price is None:
            raise ValueError(
                "Replace order requires price"
            )

        mapped = KiwoomReplaceOrderRequest(
            broker_order_id=broker_order_id,
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            replace_quantity=request.quantity,
            replace_price=request.price,
        )

        key = (
            idempotency_key
            or (
                f"REPLACE:{broker_order_id}:"
                f"{request.quantity}:{request.price}"
            )
        )

        return self._idempotency.execute_once(
            key=key,
            operation=lambda: self._send_replace(
                mapped
            ),
        )

    def get_order(
        self,
        broker_order_id: str,
    ) -> BrokerOrderResult:
        raise UnsupportedBrokerFeatureError(
            "KiwoomBrokerAdapter.get_order is not supported; "
            "use KiwoomOrderInquiryClient"
        )

    def _send_cancel(
        self,
        request: KiwoomCancelOrderRequest,
    ) -> BrokerOrderResult:
        payload, _ = self._rest_client.post(
            path=self.ORDER_PATH,
            api_id=(
                KiwoomCancelReplaceMapper
                .CANCEL_API_ID
            ),
            body=(
                KiwoomCancelReplaceMapper
                .cancel_body(request)
            ),
            request_type="ORDER",
        )
        return self._to_result(payload)

    def _send_replace(
        self,
        request: KiwoomReplaceOrderRequest,
    ) -> BrokerOrderResult:
        payload, _ = self._rest_client.post(
            path=self.ORDER_PATH,
            api_id=(
                KiwoomCancelReplaceMapper
                .REPLACE_API_ID
            ),
            body=(
                KiwoomCancelReplaceMapper
                .replace_body(request)
            ),
            request_type="ORDER",
        )
        return self._to_result(payload)

    def _assert_live_allowed(self) -> None:
        from stock_platform.common.settings import get_settings

        if self.config.use_mock:
            return
        settings = get_settings()
        if not settings.global_live_order_enabled:
            raise PermissionError(
                "Global live order is disabled."
            )
        if not self.config.live_order_enabled:
            raise PermissionError(
                "Live Kiwoom order is disabled."
            )

    @staticmethod
    def _to_result(
        payload: dict,
    ) -> BrokerOrderResult:
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
            broker_order_id=(
                payload.get("ord_no")
                or payload.get("order_no")
            ),
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
