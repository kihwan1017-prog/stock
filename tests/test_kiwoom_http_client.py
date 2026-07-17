from datetime import datetime, timedelta

from stock_platform.broker.kiwoom.config import (
    KiwoomOrderConfig,
)
from stock_platform.broker.kiwoom.http_client import (
    KiwoomRestClient,
)
from stock_platform.broker.kiwoom.rate_limiter import (
    KiwoomRateLimiters,
)
from stock_platform.broker.kiwoom.token_client import (
    KiwoomAccessToken,
)


class Cache:
    def __init__(self):
        self.invalidations = 0

    def get(self):
        return KiwoomAccessToken(
            "TOKEN",
            "bearer",
            datetime.now() + timedelta(hours=1),
        )

    def invalidate(self):
        self.invalidations += 1


class Response:
    status_code = 200
    headers = {"cont-yn": "N"}

    def raise_for_status(self):
        pass

    def json(self):
        return {
            "return_code": 0,
            "ord_no": "100",
        }


class Client:
    def post(self, *args, **kwargs):
        return Response()


def test_post():
    config = KiwoomOrderConfig(
        base_url="https://mockapi.kiwoom.com",
        app_key="a",
        secret_key="s",
        use_mock=True,
        live_order_enabled=False,
    )

    rest = KiwoomRestClient(
        config=config,
        token_cache=Cache(),
        rate_limiters=KiwoomRateLimiters(),
        client=Client(),
    )

    payload, headers = rest.post(
        path="/test",
        api_id="test",
        body={},
        request_type="INQUIRY",
    )

    assert payload["return_code"] == 0
    assert headers["cont-yn"] == "N"
