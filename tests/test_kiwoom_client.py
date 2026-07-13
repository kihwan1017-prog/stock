import asyncio

import httpx

from stock_platform.brokers.kiwoom.client import KiwoomRestClient
from stock_platform.brokers.kiwoom.token import KiwoomAccessToken
from stock_platform.common.settings import Settings

from datetime import datetime, timedelta, timezone


class FakeTokenManager:
    async def get_token(self, force_refresh: bool = False):
        return KiwoomAccessToken(
            value="sample-token",
            token_type="Bearer",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    async def aclose(self) -> None:
        return None


def _settings() -> Settings:
    return Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        kiwoom_app_key="test-app-key",
        kiwoom_secret_key="test-secret-key",
        kiwoom_use_mock=True,
        kiwoom_max_requests_per_second=5,
    )


def test_client_builds_required_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sample-token"
        assert request.headers["api-id"] == "ka10004"

        return httpx.Response(
            200,
            headers={
                "cont-yn": "Y",
                "next-key": "next-value",
                "api-id": "ka10004",
            },
            json={"return_code": 0},
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            transport=transport,
        ) as http_client:
            client = KiwoomRestClient(
                settings=_settings(),
                http_client=http_client,
                token_manager=FakeTokenManager(),
            )

            response = await client.request(
                api_id="ka10004",
                endpoint="/api/dostk/mrkcond",
                body={"stk_cd": "005930"},
            )

            assert response.body == {"return_code": 0}
            assert response.has_more is True
            assert response.next_key == "next-value"

    asyncio.run(run())
