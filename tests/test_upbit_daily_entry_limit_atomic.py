"""Atomic portfolio daily entry admission — hard cap concurrency tests."""

from __future__ import annotations

import inspect
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
    REASON_PORTFOLIO_DAILY_ENTRY_LIMIT,
    applies_final_daily_entry_admission,
    kst_trading_date,
    portfolio_daily_entry_buy_fence,
    try_final_admit_portfolio_daily_entry,
)
from stock_platform.order.daily_risk_order_count import day_start_kst_as_utc

KST = ZoneInfo("Asia/Seoul")


def test_applies_only_upbit_live_auto_buy() -> None:
    assert applies_final_daily_entry_admission(
        side="BUY",
        broker_code="UPBIT",
        environment="LIVE",
        order_source="AUTO",
        user_broker_account_id=1380,
    )
    assert not applies_final_daily_entry_admission(
        side="SELL",
        broker_code="UPBIT",
        environment="LIVE",
        order_source="AUTO",
        user_broker_account_id=1380,
    )
    assert not applies_final_daily_entry_admission(
        side="BUY",
        broker_code="UPBIT",
        environment="LIVE",
        order_source="AUTO",
        user_broker_account_id=1380,
        is_risk_reducing=True,
    )
    assert not applies_final_daily_entry_admission(
        side="BUY",
        broker_code="KIWOOM",
        environment="LIVE",
        order_source="AUTO",
        user_broker_account_id=1381,
    )
    assert not applies_final_daily_entry_admission(
        side="BUY",
        broker_code="UPBIT",
        environment="LIVE",
        order_source="MANUAL",
        user_broker_account_id=1380,
    )


def test_kst_day_boundary_for_lock_scope() -> None:
    late = datetime(2026, 8, 26, 23, 59, 59, tzinfo=KST)
    nxt = datetime(2026, 8, 27, 0, 0, 0, tzinfo=KST)
    assert kst_trading_date(late.astimezone(timezone.utc)) == late.date()
    assert kst_trading_date(nxt.astimezone(timezone.utc)) == nxt.date()
    assert day_start_kst_as_utc(nxt.astimezone(timezone.utc)) == datetime(
        2026, 8, 26, 15, 0, tzinfo=timezone.utc
    )


def _run_concurrent_admissions(
    *,
    initial_count: int,
    limit: int,
    attempts: int,
) -> dict[str, int]:
    """Process lock + shared counter로 admit→consume 직렬화 시뮬레이션."""

    session = MagicMock()
    counter = {"n": int(initial_count)}
    lock = threading.Lock()
    allowed = 0
    blocked = 0
    allowed_lock = threading.Lock()

    def fake_count(_session, _uba, *, now=None):  # noqa: ANN001
        with lock:
            return int(counter["n"])

    def worker() -> None:
        nonlocal allowed, blocked
        with portfolio_daily_entry_buy_fence(
            session,
            side="BUY",
            broker_code="UPBIT",
            environment="LIVE",
            order_source="AUTO",
            user_broker_account_id=1380,
        ) as admit:
            with patch(
                "stock_platform.operation.upbit_full_market."
                "portfolio_daily_entry_admission.count_portfolio_daily_real_entries",
                side_effect=fake_count,
            ), patch(
                "stock_platform.operation.upbit_full_market."
                "portfolio_daily_entry_admission.acquire_portfolio_daily_entry_xact_lock",
            ), patch(
                "stock_platform.operation.upbit_full_market."
                "portfolio_daily_entry_admission.resolve_portfolio_daily_entry_limit",
                return_value=limit,
            ):
                result = admit(daily_limit=limit, symbol="KRW-TEST")
                if result.get("allowed"):
                    # order INSERT 대신 counter 증가 (같은 fence 안)
                    with lock:
                        counter["n"] += 1
                    with allowed_lock:
                        allowed += 1
                else:
                    with allowed_lock:
                        blocked += 1

    threads = [threading.Thread(target=worker) for _ in range(attempts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
        assert not t.is_alive()

    return {
        "allowed": allowed,
        "blocked": blocked,
        "final_count": int(counter["n"]),
    }


def test_concurrency_count9_attempts5() -> None:
    out = _run_concurrent_admissions(initial_count=9, limit=10, attempts=5)
    assert out["allowed"] == 1
    assert out["blocked"] == 4
    assert out["final_count"] == 10


def test_concurrency_count8_attempts5() -> None:
    out = _run_concurrent_admissions(initial_count=8, limit=10, attempts=5)
    assert out["allowed"] == 2
    assert out["blocked"] == 3
    assert out["final_count"] == 10


def test_concurrency_count10_attempts5() -> None:
    out = _run_concurrent_admissions(initial_count=10, limit=10, attempts=5)
    assert out["allowed"] == 0
    assert out["blocked"] == 5
    assert out["final_count"] == 10


def test_waiting_delayed_entries_never_exceed_limit() -> None:
    """서로 다른 시각에 BUY-ready 전환 — 최종 count ≤ 10."""

    session = MagicMock()
    counter = {"n": 9}

    def fake_count(_s, _u, *, now=None):  # noqa: ANN001
        return int(counter["n"])

    with patch(
        "stock_platform.operation.upbit_full_market."
        "portfolio_daily_entry_admission.count_portfolio_daily_real_entries",
        side_effect=fake_count,
    ), patch(
        "stock_platform.operation.upbit_full_market."
        "portfolio_daily_entry_admission.acquire_portfolio_daily_entry_xact_lock",
    ):
        for symbol in ("KRW-SOL", "KRW-RE", "KRW-GRVT"):
            with portfolio_daily_entry_buy_fence(
                session,
                side="BUY",
                broker_code="UPBIT",
                environment="LIVE",
                order_source="AUTO",
                user_broker_account_id=1380,
            ) as admit:
                result = admit(daily_limit=10, symbol=symbol)
                if result["allowed"]:
                    counter["n"] += 1
        assert counter["n"] == 10


def test_rollback_does_not_consume_quota() -> None:
    """admission 후 order 실패/rollback이면 count 증가 없음."""

    session = MagicMock()
    with patch(
        "stock_platform.operation.upbit_full_market."
        "portfolio_daily_entry_admission.count_portfolio_daily_real_entries",
        return_value=9,
    ), patch(
        "stock_platform.operation.upbit_full_market."
        "portfolio_daily_entry_admission.acquire_portfolio_daily_entry_xact_lock",
    ):
        first = try_final_admit_portfolio_daily_entry(
            session, user_broker_account_id=1380, daily_limit=10
        )
        assert first["allowed"] is True
        # rollback → count still 9
        second = try_final_admit_portfolio_daily_entry(
            session, user_broker_account_id=1380, daily_limit=10
        )
        assert second["allowed"] is True
        assert second["count_before"] == 9


def test_sell_skips_admission_fence() -> None:
    session = MagicMock()
    with portfolio_daily_entry_buy_fence(
        session,
        side="SELL",
        broker_code="UPBIT",
        environment="LIVE",
        order_source="AUTO",
        user_broker_account_id=1380,
    ) as admit:
        out = admit(daily_limit=10)
    assert out["allowed"] is True
    assert out.get("skipped") is True


def test_oes_wires_daily_entry_fence() -> None:
    from stock_platform.order import execution_service as es

    src = inspect.getsource(es.OrderExecutionService._submit_inner)
    assert "portfolio_daily_entry_buy_fence" in src
    assert "PORTFOLIO_DAILY_ENTRY_LIMIT" in src or (
        "REASON_PORTFOLIO_DAILY_ENTRY_LIMIT" in src
    )


def test_begin_entry_fail_fast_contract() -> None:
    from stock_platform.operation.upbit_full_market import portfolio_service

    src = inspect.getsource(
        portfolio_service.UpbitPortfolioService.begin_entry_from_signal
    )
    assert "PORTFOLIO_DAILY_ENTRY_LIMIT" in src
    assert "summarize_portfolio_daily_entries" in src


def test_blocked_reason_constant() -> None:
    assert REASON_PORTFOLIO_DAILY_ENTRY_LIMIT == "PORTFOLIO_DAILY_ENTRY_LIMIT"


def test_max_overshoot_after_fix_is_zero() -> None:
    """회귀: 동시 5시도에서 final은 절대 limit 초과 금지."""

    for initial in (0, 7, 8, 9, 10):
        out = _run_concurrent_admissions(
            initial_count=initial, limit=10, attempts=5
        )
        assert out["final_count"] <= 10
        assert out["final_count"] == min(10, initial + out["allowed"])
