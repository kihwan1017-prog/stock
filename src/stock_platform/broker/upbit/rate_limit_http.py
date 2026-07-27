"""STEP 8-5-8 — Upbit HTTP 요청 공통 처리 (Order sync client)."""

from __future__ import annotations

import time
from typing import Any, Callable

import httpx
import structlog

from stock_platform.broker.upbit.exceptions import UpbitError
from stock_platform.broker.upbit.rate_limit_classifier import (
    UpbitErrorClassifier,
)
from stock_platform.broker.upbit.rate_limit_constants import (
    UpbitEndpointGroup,
    UpbitOperationType,
    UpbitRetryDecision,
)
from stock_platform.broker.upbit.rate_limit_coordinator import (
    get_upbit_rate_limit_coordinator,
)
from stock_platform.broker.upbit.rate_limit_header_parser import (
    UpbitRateLimitHeaderParser,
)
from stock_platform.broker.upbit.rate_limit_policy import (
    UpbitRetryDelayCalculator,
    UpbitRetryPolicyResolver,
)
from stock_platform.common.settings import get_settings

logger = structlog.get_logger(__name__)


def infer_operation(method: str, endpoint: str) -> UpbitOperationType:
    ep = endpoint.lower()
    m = method.upper()
    if m == "POST" and "/orders" in ep and not ep.rstrip("/").endswith("order"):
        return UpbitOperationType.ORDER_CREATE
    if m == "DELETE" and "/order" in ep:
        return UpbitOperationType.ORDER_CANCEL
    if "/orders" in ep or ep.endswith("/order"):
        return UpbitOperationType.ORDER_QUERY
    if "/accounts" in ep:
        return UpbitOperationType.PRIVATE_ACCOUNT_READ
    return UpbitOperationType.RECOVERY_QUERY


def infer_group(operation: UpbitOperationType) -> str:
    if operation in {
        UpbitOperationType.ORDER_CREATE,
        UpbitOperationType.ORDER_CANCEL,
        UpbitOperationType.ORDER_QUERY,
    }:
        return UpbitEndpointGroup.ORDER.value
    if operation in {
        UpbitOperationType.PRIVATE_ACCOUNT_READ,
        UpbitOperationType.CREDENTIAL_VERIFY,
    }:
        return UpbitEndpointGroup.ACCOUNT.value
    if operation == UpbitOperationType.PUBLIC_MARKET_DATA:
        return UpbitEndpointGroup.MARKET.value
    return UpbitEndpointGroup.DEFAULT.value


def build_policy_resolver() -> UpbitRetryPolicyResolver:
    s = get_settings()
    calc = UpbitRetryDelayCalculator(
        base_delay_seconds=float(
            getattr(s, "upbit_retry_base_delay_seconds", 1.0)
        ),
        max_delay_seconds=float(
            getattr(s, "upbit_retry_max_delay_seconds", 60.0)
        ),
        jitter_ratio=float(
            getattr(s, "upbit_retry_jitter_ratio", 0.2)
        ),
        retry_after_max_seconds=float(
            getattr(s, "upbit_retry_after_max_seconds", 300.0)
        ),
    )
    return UpbitRetryPolicyResolver(
        calc,
        max_attempts_read=int(
            getattr(s, "upbit_retry_max_attempts_read", 4)
        ),
        max_attempts_write=int(
            getattr(s, "upbit_retry_max_attempts_write", 1)
        ),
    )


def execute_upbit_http_with_policy(
    *,
    send: Callable[[], httpx.Response],
    method: str,
    endpoint: str,
    operation: UpbitOperationType | None = None,
    user_broker_account_id: int | None = None,
    is_public: bool = False,
    audit_hook: Callable[[str, dict[str, Any]], None] | None = None,
) -> Any:
    """
    동기 HTTP 실행.
    조회: 제한 Retry. 주문 생성: 자동 재전송 없음 (정책이 DEFER/REFRESH).
    """

    op = operation or infer_operation(method, endpoint)
    group = infer_group(op)
    coordinator = get_upbit_rate_limit_coordinator()
    classifier = UpbitErrorClassifier(
        UpbitRateLimitHeaderParser(
            retry_after_max_seconds=float(
                getattr(
                    get_settings(),
                    "upbit_retry_after_max_seconds",
                    300.0,
                )
            )
        )
    )
    policy = build_policy_resolver()
    max_read = int(
        getattr(get_settings(), "upbit_retry_max_attempts_read", 4)
    )
    # WRITE 자동 재전송 없음 — attempt 루프는 READ만
    max_attempts = 1 if op in {
        UpbitOperationType.ORDER_CREATE,
        UpbitOperationType.ORDER_CANCEL,
    } else max_read

    attempt = 0
    while True:
        attempt += 1
        coordinator.wait_if_needed(
            user_broker_account_id=user_broker_account_id,
            endpoint_group=group,
            is_public=is_public,
        )
        try:
            response = send()
        except httpx.HTTPError as exc:
            err = classifier.classify_transport(
                exc, operation=op, endpoint_group=group
            )
            plan = policy.resolve(
                error=err,
                operation=op,
                attempt=attempt,
            )
            if (
                plan.decision == UpbitRetryDecision.RETRY
                and attempt < max_attempts
            ):
                time.sleep(plan.delay_seconds)
                continue
            raise err from exc

        error, snapshot = classifier.classify_response(
            response, operation=op, endpoint_group=group
        )
        coordinator.report_response(
            user_broker_account_id=user_broker_account_id,
            endpoint_group=group,
            http_status=response.status_code,
            snapshot=snapshot,
            is_public=is_public,
            error_code=error.error_code if error else None,
        )
        if error is None:
            try:
                return response.json()
            except ValueError as exc:
                from stock_platform.broker.upbit.exceptions import (
                    UpbitRequestError,
                )

                raise UpbitRequestError(
                    "Upbit response was not valid JSON"
                ) from exc

        plan = policy.resolve(
            error=error,
            operation=op,
            attempt=attempt,
            snapshot=snapshot,
        )
        if audit_hook and isinstance(
            error, (UpbitError,)
        ):
            try:
                audit_hook(
                    "UPBIT_RATE_LIMIT_OR_ERROR",
                    {
                        "operation": op.value,
                        "endpoint_group": group,
                        "http_status": error.http_status,
                        "decision": plan.decision.value,
                        "attempt": attempt,
                        "uba_id": user_broker_account_id,
                    },
                )
            except Exception:  # noqa: BLE001
                pass

        if (
            plan.decision == UpbitRetryDecision.RETRY
            and attempt < max_attempts
        ):
            logger.warning(
                "upbit_retrying",
                endpoint=endpoint,
                attempt=attempt,
                delay=plan.delay_seconds,
                reason=plan.reason,
            )
            time.sleep(max(0.0, plan.delay_seconds))
            continue

        # DEFER/PAUSE 메타를 exception에 부착
        if plan.defer_until is not None:
            error.cooldown_until = plan.defer_until
            error.retry_after_seconds = plan.delay_seconds
        raise error
