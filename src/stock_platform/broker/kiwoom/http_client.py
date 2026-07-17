from __future__ import annotations

from typing import Any

import httpx

from stock_platform.broker.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
)
from stock_platform.broker.kiwoom.config import (
    KiwoomOrderConfig,
)
from stock_platform.broker.kiwoom.rate_limiter import (
    KiwoomRateLimiters,
)
from stock_platform.broker.kiwoom.token_cache import (
    KiwoomTokenCache,
)


class KiwoomRestClient:
    def __init__(
        self,
        *,
        config: KiwoomOrderConfig,
        token_cache: KiwoomTokenCache,
        rate_limiters: KiwoomRateLimiters,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._token_cache = token_cache
        self._rate_limiters = rate_limiters
        self._client = client or httpx.Client(
            timeout=config.timeout_seconds
        )

    def post(
        self,
        *,
        path: str,
        api_id: str,
        body: dict[str, Any],
        request_type: str,
        continuation_key: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        limiter = (
            self._rate_limiters.order
            if request_type == "ORDER"
            else self._rate_limiters.inquiry
        )
        limiter.acquire()

        return self._post_once(
            path=path,
            api_id=api_id,
            body=body,
            continuation_key=continuation_key,
            retry_auth=True,
        )

    def _post_once(
        self,
        *,
        path: str,
        api_id: str,
        body: dict[str, Any],
        continuation_key: str | None,
        retry_auth: bool,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        token = self._token_cache.get()

        headers = {
            "authorization": f"Bearer {token.token}",
            "api-id": api_id,
            "Content-Type": (
                "application/json;charset=UTF-8"
            ),
        }

        if continuation_key:
            headers["cont-yn"] = "Y"
            headers["next-key"] = continuation_key

        try:
            response = self._client.post(
                f"{self._config.base_url}{path}",
                json=body,
                headers=headers,
            )
        except Exception as exc:
            raise BrokerConnectionError(str(exc)) from exc

        if response.status_code in (401, 403):
            if retry_auth:
                self._token_cache.invalidate()
                return self._post_once(
                    path=path,
                    api_id=api_id,
                    body=body,
                    continuation_key=continuation_key,
                    retry_auth=False,
                )

            raise BrokerAuthenticationError(
                "Kiwoom authentication failed"
            )

        try:
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise BrokerConnectionError(str(exc)) from exc

        response_headers = {
            key.lower(): value
            for key, value in response.headers.items()
        }
        return payload, response_headers
