"""portfolio_daily_entry_limit — REAL AUTO BUY + KST day SoT regression."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
    count_portfolio_daily_real_entries,
    summarize_portfolio_daily_entries,
)
from stock_platform.order.daily_risk_order_count import day_start_kst_as_utc

KST = ZoneInfo("Asia/Seoul")


def test_day_boundary_kst_not_utc() -> None:
    """UTC 00:00은 KST day를 reset하지 않는다."""

    # 2026-08-25 00:30 KST = 2026-08-24 15:30 UTC
    now = datetime(2026, 8, 24, 15, 30, tzinfo=timezone.utc)
    start = day_start_kst_as_utc(now)
    assert start == datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)

    # UTC midnight 직후 (KST 09:00) — 아직 같은 KST day가 아님
    utc_midnight = datetime(2026, 8, 25, 0, 0, tzinfo=timezone.utc)
    start2 = day_start_kst_as_utc(utc_midnight)
    assert start2 == datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)

    # KST 00:00 직후
    kst_midnight = datetime(2026, 8, 25, 0, 0, tzinfo=KST)
    start3 = day_start_kst_as_utc(kst_midnight.astimezone(timezone.utc))
    assert start3 == datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)


def test_kst_2359_belongs_today_0000_next_day() -> None:
    # 2026-08-25 23:59 KST → day_start = 2026-08-25 00:00 KST = 08-24 15:00 UTC
    late = datetime(2026, 8, 25, 23, 59, tzinfo=KST).astimezone(timezone.utc)
    assert day_start_kst_as_utc(late) == datetime(
        2026, 8, 24, 15, 0, tzinfo=timezone.utc
    )
    # 2026-08-26 00:00 KST → next KST day
    next_day = datetime(2026, 8, 26, 0, 0, tzinfo=KST).astimezone(timezone.utc)
    assert day_start_kst_as_utc(next_day) == datetime(
        2026, 8, 25, 15, 0, tzinfo=timezone.utc
    )


def test_summarize_blocking_at_limit() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_daily_entry_count."
        "count_portfolio_daily_real_entries",
        return_value=10,
    ):
        out = summarize_portfolio_daily_entries(
            session, 1380, daily_limit=10
        )
    assert out["entry_count"] == 10
    assert out["entry_limit"] == 10
    assert out["remaining"] == 0
    assert out["blocking"] is True
    assert out["timezone"] == "Asia/Seoul"
    assert "SUPERSEDED_SELECTION" in out["excludes"]


def test_summarize_remaining_capacity() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_daily_entry_count."
        "count_portfolio_daily_real_entries",
        return_value=3,
    ):
        out = summarize_portfolio_daily_entries(
            session, 1380, daily_limit=10
        )
    assert out["remaining"] == 7
    assert out["blocking"] is False


def test_consume_top_k_uses_real_buy_count_not_selection() -> None:
    """소스 계약: consume_top_k가 selection row count가 아닌 REAL BUY 집계를 사용."""

    import inspect

    from stock_platform.operation.upbit_full_market import portfolio_service

    src = inspect.getsource(portfolio_service.UpbitPortfolioService.consume_top_k)
    assert "summarize_portfolio_daily_entries" in src
    assert "PORTFOLIO_DAILY_ENTRY_LIMIT" in src
    # 구 selection 집계 제거
    assert "selection_reason.like" not in src
    assert "UpbitLiveCandidateSelectionEntity" not in src


def test_sell_and_shadow_excluded_from_contract() -> None:
    with patch(
        "stock_platform.operation.upbit_full_market.portfolio_daily_entry_count."
        "count_portfolio_daily_real_entries",
        return_value=0,
    ):
        out = summarize_portfolio_daily_entries(
            MagicMock(), 1, daily_limit=10
        )
    assert "SELL" in out["excludes"]
    assert "SHADOW" in out["excludes"]
    assert "PAPER" in out["excludes"]
    assert "MANUAL" in out["excludes"]
    assert "SLOT_REPLACEMENT" in out["excludes"]
