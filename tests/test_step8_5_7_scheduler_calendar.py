"""STEP 8-5-7 — Recovery scheduler calendar skip classification."""

from stock_platform.broker.recovery_scheduler_service import (
    classify_krx_calendar_skip,
)
from stock_platform.operation.calendar_constants import (
    CalendarReasonCode,
)


def test_classify_calendar_unavailable() -> None:
    assert (
        classify_krx_calendar_skip(
            CalendarReasonCode.CALENDAR_MISSING.value
        )
        == "SKIPPED_CALENDAR_UNAVAILABLE"
    )
    assert (
        classify_krx_calendar_skip(
            CalendarReasonCode.CALENDAR_STALE.value
        )
        == "SKIPPED_CALENDAR_UNAVAILABLE"
    )


def test_classify_market_closed() -> None:
    assert (
        classify_krx_calendar_skip(
            CalendarReasonCode.CALENDAR_CLOSED.value
        )
        == "SKIPPED_MARKET_CLOSED"
    )
    assert (
        classify_krx_calendar_skip(CalendarReasonCode.WEEKEND.value)
        == "SKIPPED_MARKET_CLOSED"
    )
