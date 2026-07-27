from datetime import date, time
from types import SimpleNamespace

import pytest

from stock_platform.operation.calendar_constants import (
    CalendarReasonCode,
    CalendarVerifiedStatus,
)
from stock_platform.operation.calendar_service import (
    TradingCalendarService,
)


class FakeRepository:
    def __init__(self, rows=None):
        self.rows = rows or {}

    def get_day(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
    ):
        return self.rows.get((exchange_code, calendar_date))

    def coverage_stats(self, *, exchange_code, from_date, to_date):
        return {
            "exchange_code": exchange_code,
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "expected_calendar_days": (to_date - from_date).days + 1,
            "stored_days": 0,
            "missing_days": (to_date - from_date).days + 1,
            "verified_trading_days": 0,
            "by_verified_status": {},
            "coverage_complete": False,
        }


def _verified_open(d: date):
    return SimpleNamespace(
        exchange_code="KRX",
        calendar_date=d,
        is_trading_day=True,
        holiday_name=None,
        source_code="GENERATED_WEEKDAY",
        source_type="GENERATED_WEEKDAY",
        session_type="REGULAR",
        verified_status=CalendarVerifiedStatus.VERIFIED.value,
        regular_open_at=time(9, 0),
        regular_close_at=time(15, 30),
        timezone="Asia/Seoul",
    )


def _verified_closed(d: date, name: str = "휴장"):
    return SimpleNamespace(
        exchange_code="KRX",
        calendar_date=d,
        is_trading_day=False,
        holiday_name=name,
        source_code="CURATED_KR_HOLIDAY",
        source_type="CURATED_KR_HOLIDAY",
        session_type="CLOSED",
        verified_status=CalendarVerifiedStatus.VERIFIED.value,
        regular_open_at=None,
        regular_close_at=None,
        timezone="Asia/Seoul",
    )


def test_weekend_without_row_is_closed() -> None:
    service = TradingCalendarService(
        FakeRepository(),  # type: ignore[arg-type]
        allow_weekday_fallback=False,
    )
    result = service.evaluate(
        exchange_code="KRX",
        calendar_date=date(2026, 7, 18),
    )
    assert result.is_trading_day is False
    assert result.reason_code == CalendarReasonCode.WEEKEND.value
    assert result.live_allowed is False


def test_weekday_missing_fail_closed() -> None:
    service = TradingCalendarService(
        FakeRepository(),  # type: ignore[arg-type]
        allow_weekday_fallback=False,
    )
    result = service.evaluate(
        exchange_code="KRX",
        calendar_date=date(2026, 7, 20),
    )
    assert result.is_trading_day is False
    assert result.reason_code == CalendarReasonCode.CALENDAR_MISSING.value
    assert result.live_allowed is False


def test_weekday_fallback_only_when_allowed() -> None:
    service = TradingCalendarService(
        FakeRepository(),  # type: ignore[arg-type]
        allow_weekday_fallback=True,
    )
    result = service.evaluate(
        exchange_code="KRX",
        calendar_date=date(2026, 7, 20),
    )
    assert result.is_trading_day is True
    assert result.reason_code == CalendarReasonCode.WEEKDAY_FALLBACK.value
    assert result.live_allowed is False


def test_upbit_is_always_open() -> None:
    service = TradingCalendarService(
        FakeRepository(),  # type: ignore[arg-type]
        allow_weekday_fallback=False,
    )
    result = service.evaluate(
        exchange_code="UPBIT",
        calendar_date=date(2026, 7, 18),
    )
    assert result.is_trading_day is True
    assert result.reason_code == CalendarReasonCode.ALWAYS_OPEN.value
    assert result.live_allowed is True


def test_stored_holiday_overrides_weekday() -> None:
    holiday = date(2026, 8, 17)
    repository = FakeRepository(
        {("KRX", holiday): _verified_closed(holiday, "대체공휴일")}
    )
    result = TradingCalendarService(
        repository,  # type: ignore[arg-type]
        allow_weekday_fallback=False,
    ).evaluate(exchange_code="KRX", calendar_date=holiday)
    assert result.is_trading_day is False
    assert result.holiday_name == "대체공휴일"
    assert result.live_allowed is False


def test_unverified_not_live() -> None:
    d = date(2026, 7, 20)
    row = _verified_open(d)
    row.verified_status = CalendarVerifiedStatus.UNVERIFIED.value
    service = TradingCalendarService(
        FakeRepository({("KRX", d): row}),  # type: ignore[arg-type]
        allow_weekday_fallback=False,
    )
    result = service.evaluate(exchange_code="KRX", calendar_date=d)
    assert result.is_trading_day is False
    assert result.reason_code == CalendarReasonCode.CALENDAR_UNVERIFIED.value


def test_next_trading_day_skips_weekend() -> None:
    rows = {
        ("KRX", date(2026, 7, 20)): _verified_open(date(2026, 7, 20)),
        ("KRX", date(2026, 7, 21)): _verified_open(date(2026, 7, 21)),
    }
    service = TradingCalendarService(
        FakeRepository(rows),  # type: ignore[arg-type]
        allow_weekday_fallback=False,
    )
    result = service.next_trading_day(
        exchange_code="KRX",
        calendar_date=date(2026, 7, 17),
    )
    assert result == date(2026, 7, 20)


def test_coverage_incomplete() -> None:
    report = TradingCalendarService(
        FakeRepository(),  # type: ignore[arg-type]
        allow_weekday_fallback=False,
    ).validate_calendar_coverage(
        "KRX", date(2026, 7, 1), date(2026, 7, 31)
    )
    assert report.live_trading_allowed is False
    assert report.missing_days > 0
