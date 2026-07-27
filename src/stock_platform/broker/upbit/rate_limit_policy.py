"""STEP 8-5-8 — Retry Policy + Delay Calculator."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone

from stock_platform.broker.upbit.exceptions import (
    UpbitAmbiguousOrderResultError,
    UpbitAuthenticationError,
    UpbitBanOrBlockError,
    UpbitError,
    UpbitInvalidRequestError,
    UpbitNetworkError,
    UpbitOrderNotFoundError,
    UpbitPermissionError,
    UpbitRateLimitError,
    UpbitTemporaryUnavailableError,
)
from stock_platform.broker.upbit.rate_limit_constants import (
    UpbitOperationType,
    UpbitRetryDecision,
)
from stock_platform.broker.upbit.rate_limit_header_parser import (
    UpbitRateLimitSnapshot,
)


@dataclass(frozen=True, slots=True)
class UpbitRetryPlan:
    decision: UpbitRetryDecision
    delay_seconds: float
    reason: str
    defer_until: datetime | None = None


class UpbitRetryDelayCalculator:
    def __init__(
        self,
        *,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 60.0,
        jitter_ratio: float = 0.2,
        retry_after_max_seconds: float = 300.0,
    ) -> None:
        if base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be >= 0")
        if max_delay_seconds < base_delay_seconds:
            raise ValueError(
                "max_delay_seconds must be >= base_delay_seconds"
            )
        if not 0 <= jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be in [0, 1]")
        self._base = float(base_delay_seconds)
        self._max = float(max_delay_seconds)
        self._jitter = float(jitter_ratio)
        self._retry_after_max = float(retry_after_max_seconds)

    def compute(
        self,
        *,
        attempt: int,
        snapshot: UpbitRateLimitSnapshot | None = None,
    ) -> float:
        # 1) Retry-After 우선
        if (
            snapshot is not None
            and snapshot.retry_after_seconds is not None
        ):
            return min(
                float(snapshot.retry_after_seconds),
                self._retry_after_max,
            )
        # 2) Remaining-Req sec 소진 임박
        if (
            snapshot is not None
            and snapshot.remaining_second is not None
            and snapshot.remaining_second <= 1
        ):
            return min(1.0 + self._bounded_jitter(1.0), self._max)
        # 3) 지수 + jitter
        exp = self._base * (2 ** max(attempt - 1, 0))
        delay = min(self._max, exp)
        return max(0.0, delay + self._bounded_jitter(delay))

    def _bounded_jitter(self, delay: float) -> float:
        if self._jitter <= 0 or delay <= 0:
            return 0.0
        span = delay * self._jitter
        return random.uniform(-span, span)


class UpbitRetryPolicyResolver:
    """조회는 Retry, 주문 생성 자동 재전송은 금지."""

    WRITE_OPS = {
        UpbitOperationType.ORDER_CREATE,
        UpbitOperationType.ORDER_CANCEL,
    }

    def __init__(
        self,
        delay_calculator: UpbitRetryDelayCalculator,
        *,
        max_attempts_read: int = 4,
        max_attempts_write: int = 1,
    ) -> None:
        if max_attempts_read < 0 or max_attempts_write < 0:
            raise ValueError("max attempts must be >= 0")
        self._delay = delay_calculator
        self._max_read = max_attempts_read
        self._max_write = max_attempts_write

    def resolve(
        self,
        *,
        error: UpbitError,
        operation: UpbitOperationType,
        attempt: int,
        snapshot: UpbitRateLimitSnapshot | None = None,
        has_external_order_id: bool = False,
    ) -> UpbitRetryPlan:
        now = datetime.now(timezone.utc)
        is_write = operation in self.WRITE_OPS
        max_attempts = self._max_write if is_write else self._max_read

        if isinstance(error, UpbitBanOrBlockError):
            delay = self._delay.compute(
                attempt=attempt, snapshot=snapshot
            )
            # 418은 최소 더 긴 대기 — caller가 default block 적용
            return UpbitRetryPlan(
                decision=UpbitRetryDecision.PAUSE_ACCOUNT,
                delay_seconds=delay,
                reason="HTTP_418_BAN",
                defer_until=now,
            )

        if isinstance(
            error,
            (
                UpbitAuthenticationError,
                UpbitPermissionError,
                UpbitInvalidRequestError,
                UpbitOrderNotFoundError,
            ),
        ):
            return UpbitRetryPlan(
                decision=UpbitRetryDecision.DO_NOT_RETRY,
                delay_seconds=0.0,
                reason=error.__class__.__name__,
            )

        if isinstance(error, UpbitAmbiguousOrderResultError):
            return UpbitRetryPlan(
                decision=UpbitRetryDecision.REFRESH_REMOTE_STATE,
                delay_seconds=0.0,
                reason="AMBIGUOUS_ORDER_RESULT",
            )

        if isinstance(error, UpbitRateLimitError):
            delay = self._delay.compute(
                attempt=attempt, snapshot=snapshot
            )
            if operation == UpbitOperationType.ORDER_CREATE:
                # 동일 주문 즉시 재전송 금지 — DEFER
                return UpbitRetryPlan(
                    decision=UpbitRetryDecision.DEFER_UNTIL,
                    delay_seconds=delay,
                    reason="ORDER_CREATE_429",
                    defer_until=datetime.fromtimestamp(
                        now.timestamp() + delay, tz=timezone.utc
                    ),
                )
            if operation == UpbitOperationType.ORDER_CANCEL:
                return UpbitRetryPlan(
                    decision=UpbitRetryDecision.REFRESH_REMOTE_STATE,
                    delay_seconds=delay,
                    reason="ORDER_CANCEL_429",
                )
            if attempt >= max_attempts:
                return UpbitRetryPlan(
                    decision=UpbitRetryDecision.DEFER_UNTIL,
                    delay_seconds=delay,
                    reason="RATE_LIMIT_MAX_ATTEMPTS",
                    defer_until=datetime.fromtimestamp(
                        now.timestamp() + delay, tz=timezone.utc
                    ),
                )
            return UpbitRetryPlan(
                decision=UpbitRetryDecision.RETRY,
                delay_seconds=delay,
                reason="RATE_LIMIT_RETRY",
                defer_until=datetime.fromtimestamp(
                    now.timestamp() + delay, tz=timezone.utc
                ),
            )

        if isinstance(
            error, (UpbitTemporaryUnavailableError, UpbitNetworkError)
        ):
            if operation == UpbitOperationType.ORDER_CREATE:
                return UpbitRetryPlan(
                    decision=UpbitRetryDecision.REFRESH_REMOTE_STATE,
                    delay_seconds=0.0,
                    reason="ORDER_CREATE_NO_AUTO_RESEND",
                )
            if operation == UpbitOperationType.ORDER_CANCEL:
                return UpbitRetryPlan(
                    decision=UpbitRetryDecision.REFRESH_REMOTE_STATE,
                    delay_seconds=0.0,
                    reason="ORDER_CANCEL_REFRESH",
                )
            if attempt >= max_attempts:
                return UpbitRetryPlan(
                    decision=UpbitRetryDecision.DO_NOT_RETRY,
                    delay_seconds=0.0,
                    reason="MAX_ATTEMPTS",
                )
            delay = self._delay.compute(
                attempt=attempt, snapshot=snapshot
            )
            return UpbitRetryPlan(
                decision=UpbitRetryDecision.RETRY,
                delay_seconds=delay,
                reason="TRANSIENT_RETRY",
            )

        return UpbitRetryPlan(
            decision=UpbitRetryDecision.DO_NOT_RETRY,
            delay_seconds=0.0,
            reason="UNKNOWN",
        )
