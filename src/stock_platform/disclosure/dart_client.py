from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from stock_platform.common.settings import Settings, get_settings


class DartError(RuntimeError):
    pass


class DartClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._owns_client = http_client is None

    async def __aenter__(self) -> "DartClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def search_disclosures(
        self,
        *,
        corp_code: str,
        start_date: date,
        end_date: date,
        page_no: int = 1,
        page_count: int = 100,
    ) -> dict[str, Any]:
        self._settings.validate_dart_credentials()

        params = {
            "crtfc_key": self._settings.dart_api_key,
            "corp_code": corp_code,
            "bgn_de": start_date.strftime("%Y%m%d"),
            "end_de": end_date.strftime("%Y%m%d"),
            "page_no": page_no,
            "page_count": page_count,
        }

        client = await self._get_client()
        response = await client.get(
            f"{self._settings.dart_base_url.rstrip('/')}/list.json",
            params=params,
        )

        if response.is_error:
            raise DartError(
                f"DART request failed: HTTP {response.status_code}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise DartError("DART response was not valid JSON") from exc

        status = str(body.get("status", ""))
        if status == "013":
            return {
                "status": status,
                "message": body.get("message"),
                "list": [],
                "total_page": 0,
            }

        if status != "000":
            raise DartError(
                f"DART API error {status}: {body.get('message')}"
            )

        return body

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self._settings.dart_timeout_seconds
                )
            )
        return self._http_client
