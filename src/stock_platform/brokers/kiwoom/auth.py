import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

from stock_platform.brokers.kiwoom.constants import (
    TOKEN_ENDPOINT,
    TOKEN_GRANT_TYPE,
)
from stock_platform.brokers.kiwoom.exceptions import (
    KiwoomAuthenticationError,
    KiwoomConfigurationError,
)
from stock_platform.brokers.kiwoom.token import KiwoomAccessToken
from stock_platform.common.settings import Settings, get_settings


logger = structlog.get_logger(__name__)


def _parse_expiration(value: Any) -> datetime:
    """Parse Kiwoom expires_dt with safe fallback."""

    now = datetime.now(timezone.utc)

    if value is None:
        return now + timedelta(hours=23)

    raw = str(value).strip()

    formats = (
        "%Y%m%d%H%M%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    )

    for date_format in formats:
        try:
            parsed = datetime.strptime(raw, date_format)

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)

            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue

    logger.warning(
        "kiwoom_token_expiration_parse_failed",
        expires_dt=raw,
    )

    return now + timedelta(hours=23)


class KiwoomTokenManager:
    """Issue and cache Kiwoom access tokens in memory."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._token: KiwoomAccessToken | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "KiwoomTokenManager":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def get_token(
        self,
        force_refresh: bool = False,
    ) -> KiwoomAccessToken:
        if (
            not force_refresh
            and self._token is not None
            and not self._token.is_expiring()
        ):
            return self._token

        async with self._lock:
            if (
                not force_refresh
                and self._token is not None
                and not self._token.is_expiring()
            ):
                return self._token

            self._token = await self._issue_token()
            return self._token

    async def _issue_token(self) -> KiwoomAccessToken:
        try:
            self._settings.validate_kiwoom_credentials()
        except ValueError as exc:
            raise KiwoomConfigurationError(str(exc)) from exc

        client = await self._get_http_client()
        url = f"{self._settings.kiwoom_base_url}{TOKEN_ENDPOINT}"

        payload = {
            "grant_type": TOKEN_GRANT_TYPE,
            "appkey": self._settings.kiwoom_app_key,
            "secretkey": self._settings.kiwoom_secret_key,
        }

        try:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                },
            )
        except httpx.HTTPError as exc:
            raise KiwoomAuthenticationError(
                f"Kiwoom token request failed: {exc.__class__.__name__}"
            ) from exc

        if response.is_error:
            raise KiwoomAuthenticationError(
                "Kiwoom token request failed "
                f"with HTTP {response.status_code}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise KiwoomAuthenticationError(
                "Kiwoom token response was not valid JSON"
            ) from exc

        token_value = str(body.get("token", "")).strip()

        if not token_value:
            message = body.get("return_msg") or body.get("message")
            raise KiwoomAuthenticationError(
                f"Kiwoom token response did not contain a token: {message}"
            )

        token_type = str(body.get("token_type") or "Bearer").strip()
        expires_at = _parse_expiration(body.get("expires_dt"))

        logger.info(
            "kiwoom_token_issued",
            environment=(
                "mock" if self._settings.kiwoom_use_mock else "real"
            ),
            expires_at=expires_at.isoformat(),
        )

        return KiwoomAccessToken(
            value=token_value,
            token_type=token_type,
            expires_at=expires_at,
        )

    async def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self._settings.kiwoom_timeout_seconds
                ),
            )

        return self._http_client
