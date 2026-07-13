from __future__ import annotations

from typing import Any

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from stock_platform.brokers.kiwoom.rate_limiter import (
    AsyncSlidingWindowRateLimiter,
)
from stock_platform.brokers.upbit.exceptions import (
    UpbitRateLimitError,
    UpbitRequestError,
)
from stock_platform.common.settings import Settings, get_settings


logger = structlog.get_logger(__name__)


class _RetryableUpbitError(UpbitRequestError):
    """Internal exception for transient Upbit failures."""


class UpbitQuotationClient:
    """Async client for public Upbit quotation APIs."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._owns_http_client = http_client is None

        self._rate_limiter = AsyncSlidingWindowRateLimiter(
            max_requests=self._settings.upbit_max_requests_per_second,
        )

    async def __aenter__(self) -> "UpbitQuotationClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def get_json(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if not endpoint.startswith("/"):
            raise ValueError("endpoint must start with '/'")

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(
                multiplier=0.5,
                min=0.5,
                max=3.0,
            ),
            retry=retry_if_exception_type(_RetryableUpbitError),
            reraise=True,
        ):
            with attempt:
                return await self._get_json_once(
                    endpoint=endpoint,
                    params=params,
                )

        raise AssertionError("unreachable")

    async def list_markets(
        self,
        *,
        is_details: bool = False,
    ) -> list[dict[str, Any]]:
        result = await self.get_json(
            "/v1/market/all",
            params={"is_details": str(is_details).lower()},
        )

        if not isinstance(result, list):
            raise UpbitRequestError(
                "Upbit market response was not a list"
            )

        return result

    async def list_day_candles(
        self,
        *,
        market: str,
        to: str | None = None,
        count: int = 200,
    ) -> list[dict[str, Any]]:
        if not 1 <= count <= 200:
            raise ValueError("count must be between 1 and 200")

        params: dict[str, Any] = {
            "market": market.upper(),
            "count": count,
        }

        if to:
            params["to"] = to

        result = await self.get_json(
            "/v1/candles/days",
            params=params,
        )

        if not isinstance(result, list):
            raise UpbitRequestError(
                "Upbit daily candle response was not a list"
            )

        return result

    async def _get_json_once(
        self,
        *,
        endpoint: str,
        params: dict[str, Any] | None,
    ) -> Any:
        await self._rate_limiter.acquire()

        client = await self._get_http_client()
        url = f"{self._settings.upbit_base_url.rstrip('/')}{endpoint}"

        try:
            response = await client.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "upbit_transport_error",
                endpoint=endpoint,
                error_type=exc.__class__.__name__,
            )
            raise _RetryableUpbitError(
                "Upbit transport error"
            ) from exc

        if response.status_code in (418, 429):
            raise UpbitRateLimitError(
                f"Upbit rate limit exceeded: HTTP "
                f"{response.status_code}"
            )

        if 500 <= response.status_code:
            raise _RetryableUpbitError(
                f"Upbit server error: HTTP {response.status_code}"
            )

        if response.is_error:
            detail = self._extract_error_message(response)
            raise UpbitRequestError(
                f"Upbit request failed: HTTP "
                f"{response.status_code}, {detail}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise UpbitRequestError(
                "Upbit response was not valid JSON"
            ) from exc

        logger.info(
            "upbit_request_completed",
            endpoint=endpoint,
            remaining_req=response.headers.get("Remaining-Req"),
        )

        return payload

    @staticmethod
    def _extract_error_message(
        response: httpx.Response,
    ) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:200]

        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                return str(
                    error.get("message")
                    or error.get("name")
                    or error
                )

        return str(body)[:200]

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self._settings.upbit_timeout_seconds
                ),
            )

        return self._http_client
