import asyncio

import httpx

from stock_platform.common.settings import Settings
from stock_platform.news.naver_client import NaverNewsClient


def test_search_news() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/search/news.json"
        assert request.url.params["query"] == "삼성전자"
        assert request.headers["X-Naver-Client-Id"] == "id"
        assert request.headers["X-Naver-Client-Secret"] == "secret"

        return httpx.Response(
            200,
            json={
                "total": 1,
                "start": 1,
                "display": 1,
                "items": [],
            },
        )

    async def run() -> None:
        settings = Settings(
            db_host="localhost",
            db_name="stock_platform",
            db_user="stock_app",
            db_password="test",
            naver_client_id="id",
            naver_client_secret="secret",
        )
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            transport=transport
        ) as http_client:
            client = NaverNewsClient(
                settings=settings,
                http_client=http_client,
            )

            result = await client.search(
                query="삼성전자",
                display=1,
            )

            assert result["total"] == 1

    asyncio.run(run())
