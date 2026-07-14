from __future__ import annotations

from typing import Any

import httpx

from stock_platform.common.settings import Settings, get_settings


class NaverNewsError(RuntimeError):
    """Base exception for Naver News Search API failures."""


class NaverNewsClient:
    """Async client for Naver Search API news endpoint."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._owns_client = http_client is None

    async def __aenter__(self) -> "NaverNewsClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def search(
        self,
        *,
        query: str,
        display: int = 100,
        start: int = 1,
        sort: str = "date",
    ) -> dict[str, Any]:
        self._settings.validate_naver_credentials()

        if not query.strip():
            raise ValueError("query is required")
        if not 1 <= display <= 100:
            raise ValueError("display must be between 1 and 100")
        if not 1 <= start <= 1000:
            raise ValueError("start must be between 1 and 1000")
        if sort not in {"date", "sim"}:
            raise ValueError("sort must be 'date' or 'sim'")

        client = await self._get_client()

        response = await client.get(
            self._settings.naver_news_base_url,
            params={
                "query": query,
                "display": display,
                "start": start,
                "sort": sort,
            },
            headers={
                "X-Naver-Client-Id": (
                    self._settings.naver_client_id
                ),
                "X-Naver-Client-Secret": (
                    self._settings.naver_client_secret
                ),
            },
        )

        if response.is_error:
            detail = response.text[:300]
            raise NaverNewsError(
                f"Naver News request failed: "
                f"HTTP {response.status_code}, {detail}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise NaverNewsError(
                "Naver News response was not valid JSON"
            ) from exc

        if not isinstance(body, dict):
            raise NaverNewsError(
                "Naver News response must be an object"
            )

        return body

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self._settings.naver_news_timeout_seconds
                )
            )

        return self._http_client
