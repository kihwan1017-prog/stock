"""SYSTEM_START Upbit daily entry display — UNLIMITED sentinel must not leak."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from stock_platform.notification.user_facing_alerts import (
    _try_upbit_daily_line,
    format_system_start_upbit_daily_entry_lines,
)
from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
    MODE_LIMITED,
    MODE_UNLIMITED,
)


def test_unlimited_display_hides_sentinel_and_remaining() -> None:
    lines = format_system_start_upbit_daily_entry_lines(
        {"mode": MODE_UNLIMITED, "entry_count": 43, "entry_limit": None}
    )
    assert lines == ["오늘 신규매수: 43건 / 제한 없음"]
    joined = "\n".join(lines)
    assert "1000000000" not in joined
    assert "추가 가능" not in joined


def test_limited_display_shows_used_limit_and_remaining() -> None:
    lines = format_system_start_upbit_daily_entry_lines(
        {
            "mode": MODE_LIMITED,
            "entry_count": 2,
            "entry_limit": 6,
            "remaining": 4,
        }
    )
    assert lines == [
        "오늘 신규매수: 2 / 6",
        "추가 가능: 4건",
    ]


def test_limited_at_cap_shows_zero_remaining() -> None:
    lines = format_system_start_upbit_daily_entry_lines(
        {
            "mode": MODE_LIMITED,
            "entry_count": 6,
            "entry_limit": 6,
            "remaining": 0,
        }
    )
    assert lines[-1] == "추가 가능: 0건"


def test_try_upbit_daily_line_uses_policy_resolver_not_sentinel_limit() -> None:
    session = MagicMock()
    session_factory = MagicMock(return_value=session)
    with (
        patch(
            "stock_platform.database.session.get_session_factory",
            return_value=session_factory,
        ),
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission.resolve_portfolio_daily_entry_policy",
            return_value=(MODE_UNLIMITED, None),
        ) as policy_mock,
        patch(
            "stock_platform.operation.upbit_full_market.portfolio_daily_entry_count.summarize_portfolio_daily_entries",
            return_value={
                "mode": MODE_UNLIMITED,
                "entry_count": 43,
                "entry_limit": None,
            },
        ) as summary_mock,
    ):
        lines = _try_upbit_daily_line(1380)

    policy_mock.assert_called_once_with(session, 1380)
    summary_mock.assert_called_once_with(
        session, 1380, daily_limit=None, mode=MODE_UNLIMITED
    )
    assert lines == ["오늘 신규매수: 43건 / 제한 없음"]


def test_try_upbit_daily_line_fail_open_on_resolver_error() -> None:
    with patch(
        "stock_platform.database.session.get_session_factory",
        side_effect=RuntimeError("db down"),
    ):
        assert _try_upbit_daily_line(1380) == []
