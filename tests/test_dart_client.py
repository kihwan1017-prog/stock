import asyncio

import httpx

from stock_platform.common.settings import Settings
from stock_platform.disclosure.dart_client import DartClient


def test_search_disclosures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/list.json")
        assert request.url.params["corp_code"] == "00126380"
        return httpx.Response(
            200,
            json={
                "status": "000",
                "message": "정상",
                "page_no": 1,
                "page_count": 100,
                "total_count": 1,
                "total_page": 1,
                "list": [],
            },
        )

    async def run() -> None:
        settings = Settings(
            db_host="localhost",
            db_name="stock_platform",
            db_user="stock_app",
            db_password="test",
            dart_api_key="x" * 40,
        )
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            transport=transport
        ) as http_client:
            client = DartClient(
                settings=settings,
                http_client=http_client,
            )
            result = await client.search_disclosures(
                corp_code="00126380",
                start_date=__import__("datetime").date(2026, 1, 1),
                end_date=__import__("datetime").date(2026, 7, 13),
            )
            assert result["status"] == "000"

    asyncio.run(run())
