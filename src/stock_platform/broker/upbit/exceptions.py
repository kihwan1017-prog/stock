"""STEP 8-5-8 — Upbit 오류 계층 확장."""

from __future__ import annotations

from datetime import datetime


class UpbitError(RuntimeError):
    """Base exception for Upbit API failures."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        error_code: str | None = None,
        endpoint_group: str | None = None,
        operation_type: str | None = None,
        retry_after_seconds: float | None = None,
        cooldown_until: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.error_code = error_code
        self.endpoint_group = endpoint_group
        self.operation_type = operation_type
        self.retry_after_seconds = retry_after_seconds
        self.cooldown_until = cooldown_until


class UpbitRequestError(UpbitError):
    """Raised when an Upbit REST request fails."""


class UpbitAuthenticationError(UpbitRequestError):
    """401."""


class UpbitPermissionError(UpbitRequestError):
    """403."""


class UpbitInvalidRequestError(UpbitRequestError):
    """400."""


class UpbitInsufficientFundsError(UpbitRequestError):
    """잔고 부족."""


class UpbitOrderNotFoundError(UpbitRequestError):
    """404 order."""


class UpbitRateLimitError(UpbitRequestError):
    """429."""


class UpbitBanOrBlockError(UpbitRequestError):
    """418 — 자동 재시도 금지."""


class UpbitTemporaryUnavailableError(UpbitRequestError):
    """503 / 일시 불가."""


class UpbitNetworkError(UpbitError):
    """Timeout / connection / DNS."""


class UpbitAmbiguousOrderResultError(UpbitError):
    """주문 생성·취소 결과가 불명확 — 동일 요청 재전송 금지."""
