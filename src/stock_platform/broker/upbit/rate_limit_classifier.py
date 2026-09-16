"""STEP 8-5-8 — HTTP/Transport → Upbit 예외 분류."""

from __future__ import annotations

from typing import Any

import httpx

from stock_platform.broker.upbit.exceptions import (
    UpbitAmbiguousOrderResultError,
    UpbitAuthenticationError,
    UpbitBanOrBlockError,
    UpbitError,
    UpbitInsufficientFundsError,
    UpbitInvalidRequestError,
    UpbitNetworkError,
    UpbitOrderNotFoundError,
    UpbitPermissionError,
    UpbitRateLimitError,
    UpbitRequestError,
    UpbitTemporaryUnavailableError,
)
from stock_platform.broker.upbit.rate_limit_constants import (
    UpbitOperationType,
)
from stock_platform.broker.upbit.rate_limit_header_parser import (
    UpbitRateLimitHeaderParser,
    UpbitRateLimitSnapshot,
)


def extract_upbit_error_body(response: httpx.Response) -> tuple[str | None, str]:
    try:
        body = response.json()
    except ValueError:
        return None, (response.text or "")[:200]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            code = error.get("name") or error.get("error_code")
            msg = error.get("message") or error.get("name") or str(error)
            return (
                str(code) if code else None,
                str(msg)[:200],
            )
        return None, str(body)[:200]
    return None, str(body)[:200]


class UpbitErrorClassifier:
    def __init__(
        self,
        header_parser: UpbitRateLimitHeaderParser | None = None,
    ) -> None:
        self._parser = header_parser or UpbitRateLimitHeaderParser()

    def classify_response(
        self,
        response: httpx.Response,
        *,
        operation: UpbitOperationType,
        endpoint_group: str = "default",
    ) -> tuple[UpbitError | None, UpbitRateLimitSnapshot]:
        snapshot = self._parser.parse(response.headers)
        status = int(response.status_code)
        code, detail = extract_upbit_error_body(response)

        common = {
            "http_status": status,
            "error_code": code,
            "endpoint_group": endpoint_group,
            "operation_type": operation.value,
            "retry_after_seconds": snapshot.retry_after_seconds,
        }

        if status == 418:
            return (
                UpbitBanOrBlockError(
                    f"Upbit blocked (418): {detail}",
                    **common,
                ),
                snapshot,
            )
        if status == 429:
            return (
                UpbitRateLimitError(
                    f"Upbit rate limit (429): {detail}",
                    **common,
                ),
                snapshot,
            )
        if status == 401:
            return (
                UpbitAuthenticationError(
                    f"Upbit auth failed: {detail}", **common
                ),
                snapshot,
            )
        if status == 403:
            return (
                UpbitPermissionError(
                    f"Upbit permission denied: {detail}", **common
                ),
                snapshot,
            )
        if status == 404:
            return (
                UpbitOrderNotFoundError(
                    f"Upbit not found: {detail}", **common
                ),
                snapshot,
            )
        if status == 400:
            lowered = detail.lower()
            if "insufficient" in lowered or "fund" in lowered:
                return (
                    UpbitInsufficientFundsError(
                        f"Upbit insufficient funds: {detail}",
                        **common,
                    ),
                    snapshot,
                )
            return (
                UpbitInvalidRequestError(
                    f"Upbit invalid request: {detail}", **common
                ),
                snapshot,
            )
        if status in {502, 503, 504}:
            if operation in {
                UpbitOperationType.ORDER_CREATE,
                UpbitOperationType.ORDER_CANCEL,
            }:
                return (
                    UpbitAmbiguousOrderResultError(
                        f"Upbit ambiguous order result HTTP {status}: "
                        f"{detail}",
                        **common,
                    ),
                    snapshot,
                )
            return (
                UpbitTemporaryUnavailableError(
                    f"Upbit temporary unavailable HTTP {status}: "
                    f"{detail}",
                    **common,
                ),
                snapshot,
            )
        if status >= 500:
            return (
                UpbitTemporaryUnavailableError(
                    f"Upbit server error HTTP {status}: {detail}",
                    **common,
                ),
                snapshot,
            )
        if response.is_error:
            return (
                UpbitRequestError(
                    f"Upbit request failed HTTP {status}: {detail}",
                    **common,
                ),
                snapshot,
            )
        return None, snapshot

    def classify_transport(
        self,
        exc: BaseException,
        *,
        operation: UpbitOperationType,
        endpoint_group: str = "default",
    ) -> UpbitError:
        common: dict[str, Any] = {
            "http_status": None,
            "endpoint_group": endpoint_group,
            "operation_type": operation.value,
        }
        if isinstance(
            exc,
            (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ),
        ):
            if operation in {
                UpbitOperationType.ORDER_CREATE,
                UpbitOperationType.ORDER_CANCEL,
            }:
                return UpbitAmbiguousOrderResultError(
                    f"Upbit order transport ambiguous: "
                    f"{exc.__class__.__name__}",
                    **common,
                )
            return UpbitNetworkError(
                f"Upbit network error: {exc.__class__.__name__}",
                **common,
            )
        return UpbitNetworkError(
            f"Upbit transport error: {exc.__class__.__name__}",
            **common,
        )
