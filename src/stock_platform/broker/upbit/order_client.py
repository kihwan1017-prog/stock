from __future__ import annotations

from typing import Any

import httpx
import structlog

from stock_platform.broker.upbit.auth import authorization_header
from stock_platform.broker.upbit.exceptions import (
    UpbitRequestError,
)
from stock_platform.broker.upbit.rate_limit_constants import (
    UpbitOperationType,
)
from stock_platform.broker.upbit.rate_limit_http import (
    execute_upbit_http_with_policy,
    infer_operation,
)
from stock_platform.common.settings import Settings, get_settings


logger = structlog.get_logger(__name__)


class UpbitOrderRestClient:
    """
    업비트 주문 private REST (동기).

    STEP 8-5-8 — Rate Limit / Retry-After / 주문 재전송 금지 정책 적용.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
        *,
        user_broker_account_id: int | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._user_broker_account_id = user_broker_account_id

    def close(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def create_order(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/orders",
            params=body,
            json_body=body,
            operation=UpbitOperationType.ORDER_CREATE,
        )

    def cancel_order(
        self,
        *,
        uuid: str | None = None,
        identifier: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if uuid:
            params["uuid"] = uuid
        elif identifier:
            params["identifier"] = identifier
        else:
            raise ValueError("uuid or identifier required")
        return self._request(
            "DELETE",
            "/v1/order",
            params=params,
            operation=UpbitOperationType.ORDER_CANCEL,
        )

    def get_order(
        self,
        *,
        uuid: str | None = None,
        identifier: str | None = None,
    ) -> dict[str, Any]:
        """uuid 또는 identifier로 단건 조회 (공식 API 지원)."""

        params: dict[str, Any] = {}
        if uuid:
            params["uuid"] = uuid
        elif identifier:
            params["identifier"] = identifier
        else:
            raise ValueError("uuid or identifier required")
        return self._request(
            "GET",
            "/v1/order",
            params=params,
            operation=UpbitOperationType.ORDER_QUERY,
        )

    def list_orders(
        self,
        *,
        state: str = "wait",
        market: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "state": state,
            "limit": limit,
        }
        if market:
            params["market"] = market
        payload = self._request(
            "GET",
            "/v1/orders",
            params=params,
            operation=UpbitOperationType.ORDER_QUERY,
        )
        if not isinstance(payload, list):
            raise UpbitRequestError("Upbit orders response was not a list")
        return [row for row in payload if isinstance(row, dict)]

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        operation: UpbitOperationType | None = None,
    ) -> Any:
        self._settings.validate_upbit_credentials()
        auth_params = params or json_body
        headers = {
            "Accept": "application/json",
            **authorization_header(
                access_key=self._settings.upbit_access_key,
                secret_key=self._settings.upbit_secret_key,
                params=auth_params,
            ),
        }
        client = self._get_client()
        url = (
            f"{self._settings.upbit_base_url.rstrip('/')}"
            f"{endpoint}"
        )
        op = operation or infer_operation(method, endpoint)

        def _send() -> httpx.Response:
            return client.request(
                method,
                url,
                params=params if method in {"GET", "DELETE"} else None,
                json=json_body if method == "POST" else None,
                headers=headers,
            )

        return execute_upbit_http_with_policy(
            send=_send,
            method=method,
            endpoint=endpoint,
            operation=op,
            user_broker_account_id=self._user_broker_account_id,
            is_public=False,
        )

    def _get_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=httpx.Timeout(
                    self._settings.upbit_timeout_seconds
                ),
            )
        return self._http_client
