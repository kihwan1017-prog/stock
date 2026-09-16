"""STEP 8-5-7 — KRX Calendar constants, sync builder, migration."""

from __future__ import annotations

from datetime import date

from stock_platform.operation.calendar_constants import (
    CalendarSessionType,
    CalendarVerifiedStatus,
)
from stock_platform.operation.calendar_krx_holidays import (
    curated_krx_holidays_for_years,
)
from stock_platform.operation.calendar_sync_service import (
    TradingCalendarSyncService,
)
from tests.migration_helpers import (
    alembic_current_head,
    assert_revision_exists,
)


def test_step8_5_7_revision_head() -> None:
    assert_revision_exists("x1b2c3d4e5f6")
    # 후속 STEP이 head를 전진시켜도 revision 체인·단일 head만 검증
    head = alembic_current_head()
    assert head
    assert_revision_exists(head)


def test_curated_holidays_include_substitute() -> None:
    holidays = curated_krx_holidays_for_years([2026])
    assert date(2026, 8, 17) in holidays  # 광복절 대체
    assert date(2026, 12, 31) in holidays


def test_sync_builder_marks_weekend_closed() -> None:
    class _Sess:
        pass

    svc = TradingCalendarSyncService(_Sess())  # type: ignore[arg-type]
    rows = svc.build_krx_rows(
        from_date=date(2026, 7, 17),
        to_date=date(2026, 7, 20),
        mark_verified=True,
    )
    by_date = {r["calendar_date"]: r for r in rows}
    assert by_date[date(2026, 7, 18)]["is_trading_day"] is False
    assert by_date[date(2026, 7, 18)]["session_type"] == (
        CalendarSessionType.CLOSED.value
    )
    assert by_date[date(2026, 7, 20)]["is_trading_day"] is True
    assert by_date[date(2026, 7, 20)]["verified_status"] == (
        CalendarVerifiedStatus.VERIFIED.value
    )
    assert by_date[date(2026, 7, 20)]["timezone"] == "Asia/Seoul"


def test_enums_stable() -> None:
    assert CalendarVerifiedStatus.VERIFIED.value == "VERIFIED"
    assert CalendarSessionType.EARLY_CLOSE.value == "EARLY_CLOSE"
