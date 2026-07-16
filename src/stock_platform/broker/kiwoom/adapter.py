from datetime import datetime, timezone
import httpx
from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.exceptions import BrokerConnectionError
from stock_platform.broker.kiwoom.config import KiwoomOrderConfig
from stock_platform.broker.kiwoom.order_mapper import KiwoomOrderMapper
from stock_platform.broker.kiwoom.token_client import KiwoomTokenClient
from stock_platform.broker.models import (
    BrokerOrderRequest,
    BrokerOrderResult,
    BrokerOrderStatus,
)

class KiwoomBrokerAdapter(BrokerAdapter):
    ORDER_PATH = "/api/dostk/ordr"

    def __init__(
        self,
        config: KiwoomOrderConfig | None = None,
        client: httpx.Client | None = None,
        token_client: KiwoomTokenClient | None = None,
    ):
        self.config = config or KiwoomOrderConfig.from_env()
        self.client = client or httpx.Client(timeout=self.config.timeout_seconds)
        self.token_client = token_client or KiwoomTokenClient(
            self.config, self.client
        )

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrderResult:
        if not self.config.use_mock and not self.config.live_order_enabled:
            raise PermissionError(
                "Live Kiwoom order is disabled. "
                "Set KIWOOM_LIVE_ORDER_ENABLED=true only after mock validation."
            )

        token = self.token_client.issue()
        api_id = KiwoomOrderMapper.api_id(request.side)

        try:
            response = self.client.post(
                f"{self.config.base_url}{self.ORDER_PATH}",
                json=KiwoomOrderMapper.body(request),
                headers={
                    "authorization": f"Bearer {token.token}",
                    "api-id": api_id,
                    "Content-Type": "application/json;charset=UTF-8",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except PermissionError:
            raise
        except Exception as exc:
            raise BrokerConnectionError(str(exc)) from exc

        accepted = int(payload.get("return_code", -1)) == 0
        return BrokerOrderResult(
            accepted=accepted,
            status=(
                BrokerOrderStatus.ACCEPTED
                if accepted
                else BrokerOrderStatus.REJECTED
            ),
            broker_order_id=payload.get("ord_no"),
            submitted_at=datetime.now(timezone.utc),
            reject_code=(
                None if accepted else str(payload.get("return_code"))
            ),
            reject_message=(
                None if accepted else payload.get("return_msg")
            ),
        )

    def cancel_order(self, broker_order_id: str) -> BrokerOrderResult:
        raise NotImplementedError("STEP32-6에서 실제 취소 주문을 연결합니다.")

    def replace_order(
        self,
        broker_order_id: str,
        request: BrokerOrderRequest,
    ) -> BrokerOrderResult:
        raise NotImplementedError("STEP32-6에서 실제 정정 주문을 연결합니다.")

    def get_order(self, broker_order_id: str) -> BrokerOrderResult:
        raise NotImplementedError("STEP32-5에서 주문 조회를 연결합니다.")
