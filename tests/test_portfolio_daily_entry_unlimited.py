"""Daily entry LIMITED/UNLIMITED admission tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from stock_platform.notification.alert_v2.formatters import format_auto_buy_filled
from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
    MODE_LIMITED,
    MODE_UNLIMITED,
    resolve_portfolio_daily_entry_policy,
    try_final_admit_portfolio_daily_entry,
)
from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
    summarize_portfolio_daily_entries,
)


def test_resolve_limited_policy() -> None:
    session = MagicMock()
    session.scalar.return_value = SimpleNamespace(
        portfolio_daily_entry_limit=10,
        portfolio_daily_entry_limit_mode="LIMITED",
    )
    mode, lim = resolve_portfolio_daily_entry_policy(session, 1380)
    assert mode == MODE_LIMITED
    assert lim == 10


def test_resolve_unlimited_policy() -> None:
    session = MagicMock()
    session.scalar.return_value = SimpleNamespace(
        portfolio_daily_entry_limit=10,
        portfolio_daily_entry_limit_mode="UNLIMITED",
    )
    mode, lim = resolve_portfolio_daily_entry_policy(session, 1380)
    assert mode == MODE_UNLIMITED
    assert lim is None


def test_summarize_unlimited_label() -> None:
    session = MagicMock()
    with (
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_count.count_portfolio_daily_real_entries",
            return_value=7,
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_count.count_portfolio_daily_consumed_entries",
            return_value=7,
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_count.count_portfolio_daily_reserved_entries",
            return_value=0,
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_count.count_portfolio_daily_zero_fill_cancelled",
            return_value=0,
        ),
    ):
        usage = summarize_portfolio_daily_entries(
            session, 1380, daily_limit=10, mode="UNLIMITED"
        )
    assert usage["blocking"] is False
    assert usage["entry_limit"] is None
    assert "제한 없음" in usage["label_ko"]


def _admit_with_used(used: int, *, mode: str, limit: int | None = 10) -> dict:
    session = MagicMock()
    resolved = (
        (MODE_UNLIMITED, None)
        if mode == MODE_UNLIMITED
        else (MODE_LIMITED, limit)
    )
    with (
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission.resolve_portfolio_daily_entry_policy",
            return_value=resolved,
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission.acquire_portfolio_daily_entry_xact_lock",
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission.count_portfolio_daily_real_entries",
            return_value=used,
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission.day_start_kst_as_utc",
        ),
    ):
        return try_final_admit_portfolio_daily_entry(
            session, user_broker_account_id=1380
        )


def test_admit_limited_used9_pass() -> None:
    out = _admit_with_used(9, mode=MODE_LIMITED, limit=10)
    assert out["allowed"] is True


def test_admit_limited_used10_block() -> None:
    out = _admit_with_used(10, mode=MODE_LIMITED, limit=10)
    assert out["allowed"] is False


def test_admit_limited_used11_block() -> None:
    out = _admit_with_used(11, mode=MODE_LIMITED, limit=10)
    assert out["allowed"] is False


def test_admit_unlimited_used0_pass() -> None:
    out = _admit_with_used(0, mode=MODE_UNLIMITED)
    assert out["allowed"] is True
    assert out["mode"] == MODE_UNLIMITED


def test_admit_unlimited_used10_pass() -> None:
    out = _admit_with_used(10, mode=MODE_UNLIMITED)
    assert out["allowed"] is True


def test_admit_unlimited_used100_pass() -> None:
    out = _admit_with_used(100, mode=MODE_UNLIMITED)
    assert out["allowed"] is True
    assert out["mode"] == MODE_UNLIMITED


def test_alert_v2_limited_entry_format() -> None:
    _title, body = format_auto_buy_filled(
        detail={
            "symbol": "KRW-BTC",
            "daily_entry_used": 7,
            "daily_entry_limit": 10,
            "daily_entry_limit_mode": "LIMITED",
        }
    )
    assert "오늘 신규진입" in body
    assert "7/10" in body


def test_alert_v2_unlimited_entry_format() -> None:
    _title, body = format_auto_buy_filled(
        detail={
            "symbol": "KRW-BTC",
            "daily_entry_used": 7,
            "daily_entry_limit": None,
            "daily_entry_limit_mode": "UNLIMITED",
        }
    )
    assert "7건 / 제한 없음" in body
