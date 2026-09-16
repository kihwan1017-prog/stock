"""STEP 11-2 — AI Provider 공통 HTTP Client (재시도는 Manager 전담)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from stock_platform.ai.providers.errors import (
    AIProviderError,
    ProviderTimeoutError,
)
from stock_platform.ai.providers.security import mask_secret, sanitize_for_log

DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0
MAX_ERROR_BODY_CHARS = 500
USER_AGENT = "stock-platform-ai-provider/11.2"


@dataclass(slots=True)
class HttpResult:
    status_code: int
    headers: dict[str, str]
    json_body: dict[str, Any] | list[Any] | None
    text: str
    request_id: str | None = None


def _header_dict(headers: httpx.Headers) -> dict[str, str]:
    return {k: v for k, v in headers.items()}


def sanitize_headers_for_log(headers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        key_l = key.lower()
        if key_l in {
            "authorization",
            "x-api-key",
            "api-key",
            "x-goog-api-key",
        }:
            out[key] = mask_secret(value)
        else:
            out[key] = value
    return out


class AIProviderHttpClient:
    """httpx 래퍼 — Adapter 내부 자동 재시도 없음 (Manager와 중복 방지)."""

    def __init__(
        self,
        *,
        provider_id: str,
        timeout_seconds: float = 30.0,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.timeout_seconds = timeout_seconds
        self.connect_timeout = connect_timeout
        self._http_client = http_client
        self._owns_client = http_client is None

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            timeout = httpx.Timeout(
                timeout=self.timeout_seconds,
                connect=self.connect_timeout,
            )
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
            )
        return self._http_client

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> HttpResult:
        try:
            response = await self._client().request(
                method,
                url,
                headers=headers,
                json=json_body,
                params=params,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                self.provider_id,
                "HTTP timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(
                f"HTTP connection error: {type(exc).__name__}",
                code="HTTP_CONNECTION_ERROR",
                provider_id=self.provider_id,
                retryable=True,
            ) from exc

        text = (response.text or "")[:MAX_ERROR_BODY_CHARS]
        json_payload: dict[str, Any] | list[Any] | None
        try:
            json_payload = response.json()
        except Exception:  # noqa: BLE001
            json_payload = None

        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("request-id")
            or response.headers.get("cf-ray")
        )
        return HttpResult(
            status_code=response.status_code,
            headers=_header_dict(response.headers),
            json_body=json_payload,
            text=text,
            request_id=request_id,
        )

    async def stream_lines(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ):
        """SSE/NDJSON 라인 스트리밍."""

        try:
            async with self._client().stream(
                method,
                url,
                headers=headers,
                json=json_body,
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread())[:MAX_ERROR_BODY_CHARS]
                    raise map_http_status_error(
                        provider_id=self.provider_id,
                        status_code=response.status_code,
                        body=body.decode("utf-8", errors="replace"),
                        headers=_header_dict(response.headers),
                    )
                async for line in response.aiter_lines():
                    yield line
        except ProviderTimeoutError:
            raise
        except AIProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(self.provider_id) from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(
                f"HTTP stream error: {type(exc).__name__}",
                code="HTTP_CONNECTION_ERROR",
                provider_id=self.provider_id,
                retryable=True,
            ) from exc


def map_http_status_error(
    *,
    provider_id: str,
    status_code: int,
    body: str,
    headers: dict[str, str] | None = None,
) -> AIProviderError:
    headers = headers or {}
    retry_after = headers.get("retry-after") or headers.get("Retry-After")
    detail = {"status_code": status_code, "body": body[:MAX_ERROR_BODY_CHARS]}
    if retry_after:
        detail["retry_after"] = retry_after

    if status_code in {401, 403}:
        return AIProviderError(
            "Authentication failed",
            code="AUTH_FAILED",
            provider_id=provider_id,
            retryable=False,
        )
    if status_code == 404:
        return AIProviderError(
            "Model or endpoint not found",
            code="MODEL_NOT_FOUND",
            provider_id=provider_id,
            retryable=False,
        )
    if status_code == 429:
        return AIProviderError(
            "Rate limited",
            code="RATE_LIMITED",
            provider_id=provider_id,
            retryable=True,
        )
    if status_code in {408, 502, 503, 504}:
        return AIProviderError(
            f"Transient HTTP {status_code}",
            code="HTTP_TRANSIENT",
            provider_id=provider_id,
            retryable=True,
        )
    if status_code == 400:
        return AIProviderError(
            "Bad request",
            code="BAD_REQUEST",
            provider_id=provider_id,
            retryable=False,
        )
    return AIProviderError(
        f"HTTP {status_code}",
        code="HTTP_ERROR",
        provider_id=provider_id,
        retryable=status_code >= 500,
    )


def ensure_success(result: HttpResult, *, provider_id: str) -> HttpResult:
    if result.status_code >= 400:
        raise map_http_status_error(
            provider_id=provider_id,
            status_code=result.status_code,
            body=result.text,
            headers=result.headers,
        )
    return result


def safe_error_log_context(**kwargs: Any) -> dict[str, Any]:
    return sanitize_for_log(dict(kwargs))
