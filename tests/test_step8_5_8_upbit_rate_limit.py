"""STEP 8-5-8 — Upbit Rate Limit / Retry-After unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import httpx
import pytest

from stock_platform.broker.upbit.exceptions import (
    UpbitAmbiguousOrderResultError,
    UpbitAuthenticationError,
    UpbitBanOrBlockError,
    UpbitNetworkError,
    UpbitRateLimitError,
    UpbitTemporaryUnavailableError,
)
from stock_platform.broker.upbit.rate_limit_classifier import (
    UpbitErrorClassifier,
)
from stock_platform.broker.upbit.rate_limit_constants import (
    UpbitOperationType,
    UpbitRetryDecision,
)
from stock_platform.broker.upbit.rate_limit_coordinator import (
    UpbitRateLimitCoordinator,
    reset_upbit_rate_limit_coordinator_for_tests,
)
from stock_platform.broker.upbit.rate_limit_header_parser import (
    UpbitRateLimitHeaderParser,
)
from stock_platform.broker.upbit.rate_limit_http import (
    execute_upbit_http_with_policy,
    infer_operation,
)
from stock_platform.broker.upbit.rate_limit_policy import (
    UpbitRetryDelayCalculator,
    UpbitRetryPolicyResolver,
)
from tests.migration_helpers import (
    assert_revision_exists,
    alembic_current_head,
)


@pytest.fixture(autouse=True)
def _reset_coordinator() -> None:
    reset_upbit_rate_limit_coordinator_for_tests()
    yield
    reset_upbit_rate_limit_coordinator_for_tests()


def test_migration_revision_y2c3d4e5f6a7_in_chain() -> None:
    assert_revision_exists("y2c3d4e5f6a7")
    head = alembic_current_head()
    assert head
    assert_revision_exists(head)


def test_remaining_req_parse_normal_and_reordered() -> None:
    parser = UpbitRateLimitHeaderParser()
    snap = parser.parse(
        {"Remaining-Req": "group=default; min=1800; sec=29"}
    )
    assert snap.parse_ok
    assert snap.group == "default"
    assert snap.remaining_minute == 1800
    assert snap.remaining_second == 29

    snap2 = parser.parse(
        {"Remaining-Req": "sec=5; group=order ;min=100"}
    )
    assert snap2.parse_ok
    assert snap2.group == "order"
    assert snap2.remaining_second == 5
    assert snap2.remaining_minute == 100


def test_remaining_req_invalid_number_parse_fail() -> None:
    parser = UpbitRateLimitHeaderParser()
    snap = parser.parse(
        {"Remaining-Req": "group=default; min=abc; sec=1"}
    )
    assert snap.parse_ok is False
    assert snap.parse_error


def test_remaining_req_missing_header_ok() -> None:
    snap = UpbitRateLimitHeaderParser().parse({})
    assert snap.parse_ok
    assert snap.group is None


def test_retry_after_seconds_and_cap() -> None:
    parser = UpbitRateLimitHeaderParser(retry_after_max_seconds=300)
    assert parser.parse_retry_after("5") == 5.0
    assert parser.parse_retry_after("0") == 0.0
    assert parser.parse_retry_after("-3") == 0.0
    assert parser.parse_retry_after("9999") == 300.0
    assert parser.parse_retry_after("1.5") == 1.5


def test_retry_after_http_date_with_response_date() -> None:
    parser = UpbitRateLimitHeaderParser(retry_after_max_seconds=300)
    base = datetime(2015, 10, 21, 7, 28, 0, tzinfo=timezone.utc)
    target = "Wed, 21 Oct 2015 07:28:10 GMT"
    delay = parser.parse_retry_after(
        target, response_date=base, now=base
    )
    assert delay == pytest.approx(10.0)


def test_retry_after_past_date_zero() -> None:
    parser = UpbitRateLimitHeaderParser()
    now = datetime(2015, 10, 21, 8, 0, 0, tzinfo=timezone.utc)
    delay = parser.parse_retry_after(
        "Wed, 21 Oct 2015 07:28:00 GMT", now=now
    )
    assert delay == 0.0


def test_retry_after_invalid_date() -> None:
    parser = UpbitRateLimitHeaderParser()
    with pytest.raises(ValueError):
        parser.parse_retry_after("not-a-date")


def test_classifier_status_codes() -> None:
    clf = UpbitErrorClassifier()
    cases = [
        (400, "UpbitInvalidRequestError"),
        (401, "UpbitAuthenticationError"),
        (403, "UpbitPermissionError"),
        (404, "UpbitOrderNotFoundError"),
        (418, "UpbitBanOrBlockError"),
        (429, "UpbitRateLimitError"),
        (503, "UpbitTemporaryUnavailableError"),
    ]
    for status, expected_name in cases:
        resp = httpx.Response(
            status,
            json={"error": {"name": "x", "message": "m"}},
            request=httpx.Request("GET", "https://api.upbit.com/v1/x"),
        )
        err, _ = clf.classify_response(
            resp,
            operation=UpbitOperationType.PRIVATE_ACCOUNT_READ,
        )
        assert err is not None
        assert err.__class__.__name__ == expected_name


def test_classifier_order_create_503_ambiguous() -> None:
    clf = UpbitErrorClassifier()
    resp = httpx.Response(
        503,
        json={"error": {"name": "server", "message": "busy"}},
        request=httpx.Request("POST", "https://api.upbit.com/v1/orders"),
    )
    err, _ = clf.classify_response(
        resp, operation=UpbitOperationType.ORDER_CREATE
    )
    assert isinstance(err, UpbitAmbiguousOrderResultError)


def test_classifier_timeout_order_create_ambiguous() -> None:
    clf = UpbitErrorClassifier()
    err = clf.classify_transport(
        httpx.ReadTimeout("t"),
        operation=UpbitOperationType.ORDER_CREATE,
    )
    assert isinstance(err, UpbitAmbiguousOrderResultError)


def test_classifier_dns_network() -> None:
    clf = UpbitErrorClassifier()
    err = clf.classify_transport(
        httpx.ConnectError("dns"),
        operation=UpbitOperationType.PUBLIC_MARKET_DATA,
    )
    assert isinstance(err, UpbitNetworkError)


def test_policy_read_429_retry_and_418_pause() -> None:
    calc = UpbitRetryDelayCalculator(
        base_delay_seconds=1, max_delay_seconds=60, jitter_ratio=0
    )
    policy = UpbitRetryPolicyResolver(
        calc, max_attempts_read=4, max_attempts_write=1
    )
    plan = policy.resolve(
        error=UpbitRateLimitError("rl", http_status=429),
        operation=UpbitOperationType.PRIVATE_ACCOUNT_READ,
        attempt=1,
    )
    assert plan.decision == UpbitRetryDecision.RETRY

    ban = policy.resolve(
        error=UpbitBanOrBlockError("ban", http_status=418),
        operation=UpbitOperationType.PRIVATE_ACCOUNT_READ,
        attempt=1,
    )
    assert ban.decision == UpbitRetryDecision.PAUSE_ACCOUNT

    auth = policy.resolve(
        error=UpbitAuthenticationError("a", http_status=401),
        operation=UpbitOperationType.CREDENTIAL_VERIFY,
        attempt=1,
    )
    assert auth.decision == UpbitRetryDecision.DO_NOT_RETRY


def test_policy_order_create_no_auto_resend() -> None:
    calc = UpbitRetryDelayCalculator(jitter_ratio=0)
    policy = UpbitRetryPolicyResolver(calc)
    for err in (
        UpbitRateLimitError("rl", http_status=429),
        UpbitTemporaryUnavailableError("t", http_status=503),
        UpbitNetworkError("n"),
        UpbitAmbiguousOrderResultError("a"),
    ):
        plan = policy.resolve(
            error=err,
            operation=UpbitOperationType.ORDER_CREATE,
            attempt=1,
        )
        assert plan.decision in {
            UpbitRetryDecision.DEFER_UNTIL,
            UpbitRetryDecision.REFRESH_REMOTE_STATE,
        }
        assert plan.decision != UpbitRetryDecision.RETRY


def test_policy_retry_after_priority() -> None:
    calc = UpbitRetryDelayCalculator(
        base_delay_seconds=1,
        max_delay_seconds=60,
        jitter_ratio=0,
        retry_after_max_seconds=300,
    )
    from stock_platform.broker.upbit.rate_limit_header_parser import (
        UpbitRateLimitSnapshot,
    )

    snap = UpbitRateLimitSnapshot(
        group="default",
        remaining_minute=10,
        remaining_second=10,
        retry_after_seconds=12.0,
        response_date=None,
        parsed_at=datetime.now(timezone.utc),
        raw_remaining_masked=None,
        parse_ok=True,
    )
    delay = calc.compute(attempt=3, snapshot=snap)
    assert delay == 12.0


def test_backoff_exponential_with_jitter_bound() -> None:
    calc = UpbitRetryDelayCalculator(
        base_delay_seconds=1,
        max_delay_seconds=60,
        jitter_ratio=0.2,
    )
    for _ in range(20):
        d = calc.compute(attempt=3, snapshot=None)
        # base * 2^2 = 4, jitter ±0.8
        assert 3.0 <= d <= 5.0


def test_coordinator_account_isolation() -> None:
    coord = UpbitRateLimitCoordinator(
        enabled=True,
        persist_cooldown_seconds=9999,  # memory only (no persist threshold hit unless 429)
        default_418_block_seconds=600,
    )
    # USER A cooldown
    snap = MagicMock()
    snap.retry_after_seconds = 30.0
    snap.remaining_second = 0
    snap.remaining_minute = 0
    coord.report_response(
        user_broker_account_id=101,
        endpoint_group="order",
        http_status=429,
        snapshot=snap,
    )
    ok_a, reason_a, wait_a = coord.check_allowed(
        user_broker_account_id=101, endpoint_group="order"
    )
    assert ok_a is False
    assert reason_a == "COOLDOWN"
    assert wait_a > 0

    ok_b, reason_b, _ = coord.check_allowed(
        user_broker_account_id=202, endpoint_group="order"
    )
    assert ok_b is True
    assert reason_b is None

    ok_pub, _, _ = coord.check_allowed(
        user_broker_account_id=None,
        endpoint_group="market",
        is_public=True,
    )
    assert ok_pub is True


def test_coordinator_group_isolation() -> None:
    # persist 임계를 올려 테스트가 PG를 오염시키지 않음
    coord = UpbitRateLimitCoordinator(
        enabled=True, persist_cooldown_seconds=99999
    )
    snap = MagicMock()
    snap.retry_after_seconds = 20.0
    snap.remaining_second = None
    snap.remaining_minute = None
    coord.report_response(
        user_broker_account_id=777,
        endpoint_group="order",
        http_status=429,
        snapshot=snap,
    )
    ok_order, _, _ = coord.check_allowed(
        user_broker_account_id=777, endpoint_group="order"
    )
    ok_account, _, _ = coord.check_allowed(
        user_broker_account_id=777, endpoint_group="account"
    )
    assert ok_order is False
    assert ok_account is True


def test_coordinator_418_blocks() -> None:
    coord = UpbitRateLimitCoordinator(
        enabled=True,
        default_418_block_seconds=600,
        persist_cooldown_seconds=99999,
    )
    snap = MagicMock()
    snap.retry_after_seconds = None
    snap.remaining_second = None
    snap.remaining_minute = None
    coord.report_response(
        user_broker_account_id=908,
        endpoint_group="account",
        http_status=418,
        snapshot=snap,
    )
    with pytest.raises(UpbitBanOrBlockError):
        coord.wait_if_needed(
            user_broker_account_id=908,
            endpoint_group="account",
            max_wait_seconds=1.0,
        )


def test_infer_operation_order_create() -> None:
    assert (
        infer_operation("POST", "/v1/orders")
        == UpbitOperationType.ORDER_CREATE
    )
    assert (
        infer_operation("DELETE", "/v1/order")
        == UpbitOperationType.ORDER_CANCEL
    )


def test_order_create_http_policy_no_resend_on_timeout() -> None:
    reset_upbit_rate_limit_coordinator_for_tests()
    calls = {"n": 0}

    def send() -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("timeout")

    with pytest.raises(UpbitAmbiguousOrderResultError):
        execute_upbit_http_with_policy(
            send=send,
            method="POST",
            endpoint="/v1/orders",
            operation=UpbitOperationType.ORDER_CREATE,
            user_broker_account_id=55101,
        )
    assert calls["n"] == 1


def test_read_http_policy_retries_429() -> None:
    reset_upbit_rate_limit_coordinator_for_tests()
    calls = {"n": 0}

    def send() -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"error": {"name": "too_many", "message": "x"}},
                request=httpx.Request(
                    "GET", "https://api.upbit.com/v1/accounts"
                ),
            )
        return httpx.Response(
            200,
            json=[{"currency": "KRW"}],
            request=httpx.Request(
                "GET", "https://api.upbit.com/v1/accounts"
            ),
        )

    payload = execute_upbit_http_with_policy(
        send=send,
        method="GET",
        endpoint="/v1/accounts",
        operation=UpbitOperationType.PRIVATE_ACCOUNT_READ,
        user_broker_account_id=55102,
    )
    assert isinstance(payload, list)
    assert calls["n"] == 3


def test_header_no_secret_in_masked() -> None:
    snap = UpbitRateLimitHeaderParser().parse(
        {
            "Remaining-Req": "group=default; min=1; sec=1",
            "Authorization": "Bearer SUPER_SECRET_TOKEN",
        }
    )
    assert snap.raw_remaining_masked is not None
    assert "SECRET" not in (snap.raw_remaining_masked or "")
    assert "Bearer" not in (snap.raw_remaining_masked or "")
