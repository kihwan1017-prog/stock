from decimal import Decimal

from stock_platform.broker.idempotency import (
    InMemoryIdempotencyStore,
)
from stock_platform.broker.kiwoom.adapter import (
    KiwoomBrokerAdapter,
)
from stock_platform.broker.kiwoom.config import (
    KiwoomOrderConfig,
)


class RestClient:
    def __init__(self):
        self.calls = 0
        self.requests = []

    def post(self, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        return (
            {
                "return_code": 0,
                "return_msg": "정상",
                "ord_no": "200",
            },
            {},
        )


def test_cancel_is_idempotent():
    rest = RestClient()
    adapter = KiwoomBrokerAdapter(
        config=KiwoomOrderConfig(
            base_url="https://mockapi.kiwoom.com",
            app_key="a",
            secret_key="s",
            use_mock=True,
            live_order_enabled=False,
        ),
        rest_client=rest,
        idempotency_store=(
            InMemoryIdempotencyStore()
        ),
    )

    for _ in range(2):
        result = adapter.cancel_order(
            "100",
            exchange_code="KRX",
            symbol="005930",
            cancel_quantity=Decimal("1"),
            idempotency_key="CANCEL-1",
        )

    assert result.accepted is True
    assert rest.calls == 1
    assert (
        rest.requests[0]["api_id"]
        == "kt10003"
    )
