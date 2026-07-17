from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from stock_platform.brokers.kiwoom.auth import KiwoomTokenManager
from stock_platform.brokers.kiwoom.constants import (
    HEADER_API_ID,
    HEADER_AUTHORIZATION,
    HEADER_CONTINUE,
    HEADER_NEXT_KEY,
)
from stock_platform.brokers.kiwoom.exceptions import (
    KiwoomRateLimitError,
    KiwoomRequestError,
)
from stock_platform.brokers.kiwoom.rate_limiter import (
    AsyncSlidingWindowRateLimiter,
)
from stock_platform.common.settings import Settings, get_settings


logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class KiwoomResponse:
    """Normalized Kiwoom REST response."""

    body: dict[str, Any]
    api_id: str | None
    has_more: bool
    next_key: str | None


class _RetryableKiwoomError(KiwoomRequestError):
    """Internal exception for transient request failures."""


class KiwoomRestClient:
    """Async Kiwoom REST client with token and rate-limit handling."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        token_manager: KiwoomTokenManager | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._token_manager = token_manager or KiwoomTokenManager(
            settings=self._settings,
            http_client=http_client,
        )
        self._owns_token_manager = token_manager is None

        self._rate_limiter = AsyncSlidingWindowRateLimiter(
            max_requests=self._settings.kiwoom_max_requests_per_second,
        )

    async def __aenter__(self) -> "KiwoomRestClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_token_manager:
            await self._token_manager.aclose()

        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def request(
        self,
        *,
        api_id: str,
        endpoint: str,
        body: dict[str, Any],
        continue_yn: str | None = None,
        next_key: str | None = None,
    ) -> KiwoomResponse:
        """Send a Kiwoom POST request."""

        if not api_id.strip():
            raise ValueError("api_id is required")

        if not endpoint.startswith("/"):
            raise ValueError("endpoint must start with '/'")

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(
                multiplier=1.0,
                min=1.0,
                max=8.0,
            ),
            retry=retry_if_exception_type(
                (_RetryableKiwoomError, KiwoomRateLimitError)
            ),
            reraise=True,
        ):
            with attempt:
                return await self._request_once(
                    api_id=api_id,
                    endpoint=endpoint,
                    body=body,
                    continue_yn=continue_yn,
                    next_key=next_key,
                )

        raise AssertionError("unreachable")

    async def _request_once(
        self,
        *,
        api_id: str,
        endpoint: str,
        body: dict[str, Any],
        continue_yn: str | None,
        next_key: str | None,
    ) -> KiwoomResponse:
        await self._rate_limiter.acquire()

        token = await self._token_manager.get_token()
        client = await self._get_http_client()

        headers = {
            HEADER_AUTHORIZATION: f"{token.token_type} {token.value}",
            HEADER_API_ID: api_id,
            "Content-Type": "application/json;charset=UTF-8",
        }

        if continue_yn:
            headers[HEADER_CONTINUE] = continue_yn

        if next_key:
            headers[HEADER_NEXT_KEY] = next_key

        url = f"{self._settings.kiwoom_base_url}{endpoint}"

        try:
            response = await client.post(
                url,
                json=body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "kiwoom_request_transport_error",
                api_id=api_id,
                error_type=exc.__class__.__name__,
            )
            raise _RetryableKiwoomError(
                "Kiwoom transport error"
            ) from exc

        if response.status_code == 401:
            token = await self._token_manager.get_token(
                force_refresh=True
            )
            headers[HEADER_AUTHORIZATION] = (
                f"{token.token_type} {token.value}"
            )

            response = await client.post(
                url,
                json=body,
                headers=headers,
            )

        if response.status_code == 429:
            raise KiwoomRateLimitError(
                "Kiwoom rate limit exceeded"
            )

        if 500 <= response.status_code:
            raise _RetryableKiwoomError(
                f"Kiwoom server error: HTTP {response.status_code}"
            )

        if response.is_error:
            raise KiwoomRequestError(
                f"Kiwoom request failed: HTTP {response.status_code}"
            )

        try:
            response_body = response.json()
        except ValueError as exc:
            raise KiwoomRequestError(
                "Kiwoom response was not valid JSON"
            ) from exc

        continuation = (
            response.headers.get(HEADER_CONTINUE, "").upper() == "Y"
        )

        logger.info(
            "kiwoom_request_completed",
            api_id=api_id,
            endpoint=endpoint,
            has_more=continuation,
        )

        return KiwoomResponse(
            body=response_body,
            api_id=response.headers.get(HEADER_API_ID),
            has_more=continuation,
            next_key=response.headers.get(HEADER_NEXT_KEY),
        )

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self._settings.kiwoom_timeout_seconds
                ),
            )

        return self._http_client
