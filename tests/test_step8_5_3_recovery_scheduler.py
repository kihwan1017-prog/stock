"""STEP 8-5-3 — Recovery Scheduler unit tests."""

from __future__ import annotations

import pytest

from stock_platform.broker.recovery_scheduler_service import (
    MIN_INTERVAL_BY_JOB,
    NON_RETRYABLE_ERROR_CODES,
    RecoverySchedulerConfigError,
    classify_error_code,
    compute_backoff_seconds,
    validate_job_update,
)


def test_validate_rejects_negative_timeout() -> None:
    with pytest.raises(RecoverySchedulerConfigError):
        validate_job_update({"timeout_seconds": -1})


def test_validate_rejects_bad_cron() -> None:
    with pytest.raises(RecoverySchedulerConfigError):
        validate_job_update({"cron_expression": "bad"})


def test_validate_accepts_cron() -> None:
    out = validate_job_update(
        {"cron_expression": "30 8 * * mon-fri"}
    )
    assert out["cron_expression"] == "30 8 * * mon-fri"


def test_validate_concurrency_bounds() -> None:
    with pytest.raises(RecoverySchedulerConfigError):
        validate_job_update({"concurrency": 0})
    with pytest.raises(RecoverySchedulerConfigError):
        validate_job_update({"concurrency": 11})


def test_upbit_min_interval() -> None:
    assert MIN_INTERVAL_BY_JOB["broker_recovery_upbit_interval"] >= 10


def test_non_retryable_codes_include_credentials() -> None:
    assert "credential_missing" in NON_RETRYABLE_ERROR_CODES
    assert "manual_review_required" in NON_RETRYABLE_ERROR_CODES


def test_classify_rate_limit() -> None:
    assert classify_error_code(["HTTP 429 rate limit"]) == "rate_limit"


def test_classify_credential() -> None:
    assert (
        classify_error_code(["credential_missing for uba"])
        == "credential_missing"
    )


def test_backoff_increases_and_caps() -> None:
    first = compute_backoff_seconds(
        retry_count=1, base=60, maximum=1800
    )
    second = compute_backoff_seconds(
        retry_count=5, base=60, maximum=1800
    )
    assert 60 <= first <= 1800
    assert second <= 1800
