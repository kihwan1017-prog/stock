from __future__ import annotations

from typing import Any

import httpx
import structlog

from stock_platform.broker.upbit.auth import authorization_header
from stock_platform.broker.common.async_rate_limiter import (
    AsyncSlidingWindowRateLimiter,
)
from stock_platform.broker.upbit.exceptions import (
    UpbitRateLimitError,
    UpbitRequestError,
)
from stock_platform.common.security_mask import mask_secret
from stock_platform.common.settings import Settings, get_settings


logger = structlog.get_logger(__name__)


# 로컬/CI용 mock 잔고 (실키 없이 연결 테스트·동기화 검증)
MOCK_ACCOUNTS: list[dict[str, Any]] = [
    {
        "currency": "KRW",
        "balance": "10000000",
        "locked": "0",
        "avg_buy_price": "0",
        "unit_currency": "KRW",
    },
    {
        "currency": "BTC",
        "balance": "0.01",
        "locked": "0",
        "avg_buy_price": "100000000",
        "unit_currency": "KRW",
    },
    {
        "currency": "ETH",
        "balance": "0.5",
        "locked": "0",
        "avg_buy_price": "4000000",
        "unit_currency": "KRW",
    },
]


class UpbitPrivateClient:
    """
    업비트 private REST (잔고 조회).

    주문 API는 STEP3 — 이 클라이언트에는 넣지 않는다.
    시크릿은 로그/예외에 남기지 않는다.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        *,
        user_broker_account_id: int | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._user_broker_account_id = user_broker_account_id
        self._rate_limiter = AsyncSlidingWindowRateLimiter(
            max_requests=self._settings.upbit_max_requests_per_second,
        )

    async def __aenter__(self) -> "UpbitPrivateClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    @property
    def use_mock(self) -> bool:
        return bool(self._settings.upbit_use_mock)

    @property
    def account_ref(self) -> str:
        ref = (self._settings.upbit_account_ref or "MAIN").strip()
        return ref or "MAIN"

    def connection_status(self) -> dict[str, Any]:
        """API 호출 없이 설정 상태만 반환 (시크릿 마스킹)."""

        access = self._settings.upbit_access_key.strip()
        secret = self._settings.upbit_secret_key.strip()
        return {
            "broker_code": "UPBIT",
            "use_mock": self.use_mock,
            "live_order_enabled": bool(
                self._settings.upbit_live_order_enabled
            ),
            "credentials_configured": bool(access and secret),
            "access_key_masked": mask_secret(access) if access else "",
            "account_ref": self.account_ref,
            "base_url": self._settings.upbit_base_url,
            "allowed_markets": sorted(
                self._settings.upbit_allowed_market_set()
            ),
        }

    async def test_connection(self) -> dict[str, Any]:
        """잔고 조회로 인증·연결을 검증한다 (주문 없음)."""

        accounts = await self.list_accounts()
        currencies = [
            str(row.get("currency") or "").upper()
            for row in accounts
            if isinstance(row, dict) and row.get("currency")
        ]
        status = self.connection_status()
        status.update(
            {
                "ok": True,
                "currency_count": len(currencies),
                "currencies": currencies[:50],
                "mode": "mock" if self.use_mock else "live",
            }
        )
        return status

    async def list_accounts(self) -> list[dict[str, Any]]:
        if self.use_mock:
            logger.info("upbit_private_mock_accounts")
            return [dict(row) for row in MOCK_ACCOUNTS]

        self._settings.validate_upbit_credentials()
        payload = await self._authorized_get("/v1/accounts")
        if not isinstance(payload, list):
            raise UpbitRequestError(
                "Upbit accounts response was not a list"
            )
        return [row for row in payload if isinstance(row, dict)]

    async def list_tickers(
        self,
        markets: list[str],
    ) -> list[dict[str, Any]]:
        """시세 보강용 public ticker (인증 불필요)."""

        if not markets:
            return []
        if self.use_mock:
            # mock: avg와 동일 가격으로 평가
            return [
                {
                    "market": market.upper(),
                    "trade_price": "0",
                }
                for market in markets
            ]

        params = {"markets": ",".join(markets)}
        await self._rate_limiter.acquire()
        client = await self._get_http_client()
        url = (
            f"{self._settings.upbit_base_url.rstrip('/')}"
            "/v1/ticker"
        )
        try:
            response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.warning(
                "upbit_ticker_transport_error",
                error_type=exc.__class__.__name__,
            )
            return []

        if response.is_error:
            logger.warning(
                "upbit_ticker_http_error",
                status_code=response.status_code,
            )
            return []

        try:
            body = response.json()
        except ValueError:
            return []
        if not isinstance(body, list):
            return []
        return [row for row in body if isinstance(row, dict)]

    async def _authorized_get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if not endpoint.startswith("/"):
            raise ValueError("endpoint must start with '/'")

        await self._rate_limiter.acquire()
        from stock_platform.broker.upbit.rate_limit_coordinator import (
            get_upbit_rate_limit_coordinator,
        )

        # 짧은 cooldown만 대기 — 긴 대기/418은 예외
        get_upbit_rate_limit_coordinator().wait_if_needed(
            user_broker_account_id=self._user_broker_account_id,
            endpoint_group="account",
            is_public=False,
            max_wait_seconds=2.0,
        )
        headers = {
            "Accept": "application/json",
            **authorization_header(
                access_key=self._settings.upbit_access_key,
                secret_key=self._settings.upbit_secret_key,
                params=params,
            ),
        }
        client = await self._get_http_client()
        url = (
            f"{self._settings.upbit_base_url.rstrip('/')}"
            f"{endpoint}"
        )

        try:
            response = await client.get(
                url,
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "upbit_private_transport_error",
                endpoint=endpoint,
                error_type=exc.__class__.__name__,
            )
            from stock_platform.broker.upbit.rate_limit_classifier import (
                UpbitErrorClassifier,
            )
            from stock_platform.broker.upbit.rate_limit_constants import (
                UpbitOperationType,
            )

            raise UpbitErrorClassifier().classify_transport(
                exc,
                operation=UpbitOperationType.PRIVATE_ACCOUNT_READ,
                endpoint_group="account",
            ) from exc

        from stock_platform.broker.upbit.rate_limit_classifier import (
            UpbitErrorClassifier,
        )
        from stock_platform.broker.upbit.rate_limit_constants import (
            UpbitOperationType,
        )
        from stock_platform.broker.upbit.rate_limit_coordinator import (
            get_upbit_rate_limit_coordinator,
        )

        op = (
            UpbitOperationType.CREDENTIAL_VERIFY
            if endpoint.endswith("/accounts")
            else UpbitOperationType.PRIVATE_ACCOUNT_READ
        )
        error, snapshot = UpbitErrorClassifier().classify_response(
            response, operation=op, endpoint_group="account"
        )
        get_upbit_rate_limit_coordinator().report_response(
            user_broker_account_id=self._user_broker_account_id,
            endpoint_group="account",
            http_status=response.status_code,
            snapshot=snapshot,
            error_code=error.error_code if error else None,
        )
        if error is not None:
            raise error

        try:
            payload = response.json()
        except ValueError as exc:
            raise UpbitRequestError(
                "Upbit private response was not valid JSON"
            ) from exc

        logger.info(
            "upbit_private_request_completed",
            endpoint=endpoint,
            remaining_req=snapshot.raw_remaining_masked,
        )
        return payload

    @staticmethod
    def _safe_error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return "non-json body"

        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                name = error.get("name") or ""
                message = error.get("message") or ""
                return f"{name}: {message}".strip(": ")
        return "request rejected"

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self._settings.upbit_timeout_seconds
                ),
            )
        return self._http_client
