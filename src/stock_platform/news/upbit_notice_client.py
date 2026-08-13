"""STEP N2 — Upbit 공식 공지 HTTP 클라이언트 (api-manager public)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from stock_platform.common.settings import Settings, get_settings


class UpbitNoticeClientError(RuntimeError):
    """Upbit notice API 실패 (수집 isolation용)."""


class UpbitNoticeClient:
    """공식 웹 공지 JSON API — 비공식 HTML scraping 없음."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._owns_client = http_client is None

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def list_announcements(
        self,
        *,
        page: int = 1,
        per_page: int = 20,
        category: str = "all",
    ) -> dict[str, Any]:
        params = {
            "os": "web",
            "page": page,
            "per_page": per_page,
            "category": category,
        }
        return await self._request_json(
            "GET",
            "/announcements",
            params=params,
        )

    async def get_announcement(self, notice_id: int | str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"/announcements/{notice_id}",
            params={"os": "web"},
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = str(
            getattr(
                self._settings,
                "upbit_notice_api_base_url",
                "https://api-manager.upbit.com/api/v1",
            )
        ).rstrip("/")
        url = f"{base}{path}"
        timeout = float(
            getattr(self._settings, "upbit_notice_timeout_seconds", 15.0)
        )
        max_retries = max(
            0,
            int(getattr(self._settings, "upbit_notice_max_retries", 3)),
        )
        client = await self._get_client(timeout=timeout)

        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": (
                            "stock-platform-upbit-notice-collector/0.1"
                        ),
                    },
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                await self._backoff(attempt)
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else (2 ** attempt)
                await asyncio.sleep(min(max(wait, 1.0), 60.0))
                last_error = UpbitNoticeClientError(
                    f"rate_limited HTTP 429 path={path}"
                )
                continue

            if response.is_error:
                detail = response.text[:300]
                raise UpbitNoticeClientError(
                    f"Upbit notice HTTP {response.status_code}: {detail}"
                )

            try:
                body = response.json()
            except ValueError as exc:
                raise UpbitNoticeClientError(
                    "Upbit notice response was not valid JSON"
                ) from exc

            if not isinstance(body, dict):
                raise UpbitNoticeClientError(
                    "Upbit notice response must be an object"
                )
            return body

        raise UpbitNoticeClientError(
            f"Upbit notice request failed after retries: {last_error}"
        )

    async def _backoff(self, attempt: int) -> None:
        delay = min(2 ** attempt, 30.0)
        await asyncio.sleep(delay)

    async def _get_client(self, *, timeout: float) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout),
            )
        return self._http_client
