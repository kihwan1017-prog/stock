import asyncio
from datetime import datetime, timezone

import httpx

from stock_platform.brokers.kiwoom.auth import KiwoomTokenManager
from stock_platform.common.settings import Settings


def _settings() -> Settings:
    return Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        kiwoom_app_key="test-app-key",
        kiwoom_secret_key="test-secret-key",
        kiwoom_use_mock=True,
    )


def test_token_manager_issues_and_caches_token() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1

        assert request.url.path == "/oauth2/token"

        return httpx.Response(
            200,
            json={
                "token": "sample-token",
                "token_type": "Bearer",
                "expires_dt": "20991231235959",
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            transport=transport,
        ) as http_client:
            manager = KiwoomTokenManager(
                settings=_settings(),
                http_client=http_client,
            )

            first = await manager.get_token()
            second = await manager.get_token()

            assert first.value == "sample-token"
            assert second.value == "sample-token"
            assert first.expires_at > datetime.now(timezone.utc)

    asyncio.run(run())
    assert request_count == 1
