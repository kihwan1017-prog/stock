from datetime import date
from types import SimpleNamespace

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
        return self.rows.get(
            (exchange_code, calendar_date)
        )


def test_weekend_is_closed_for_krx() -> None:
    service = TradingCalendarService(
        FakeRepository()  # type: ignore[arg-type]
    )

    result = service.evaluate(
        exchange_code="KRX",
        calendar_date=date(2026, 7, 18),
    )

    assert result.is_trading_day is False
    assert result.reason_code == "WEEKEND"


def test_upbit_is_always_open() -> None:
    service = TradingCalendarService(
        FakeRepository()  # type: ignore[arg-type]
    )

    result = service.evaluate(
        exchange_code="UPBIT",
        calendar_date=date(2026, 7, 18),
    )

    assert result.is_trading_day is True
    assert result.reason_code == "ALWAYS_OPEN"


def test_stored_holiday_overrides_weekday() -> None:
    holiday = date(2026, 8, 17)

    repository = FakeRepository(
        {
            ("KRX", holiday): SimpleNamespace(
                is_trading_day=False,
                holiday_name="대체공휴일",
                source_code="MANUAL",
            )
        }
    )

    result = TradingCalendarService(
        repository  # type: ignore[arg-type]
    ).evaluate(
        exchange_code="KRX",
        calendar_date=holiday,
    )

    assert result.is_trading_day is False
    assert result.holiday_name == "대체공휴일"


def test_next_trading_day_skips_weekend() -> None:
    service = TradingCalendarService(
        FakeRepository()  # type: ignore[arg-type]
    )

    result = service.next_trading_day(
        exchange_code="KRX",
        calendar_date=date(2026, 7, 17),
    )

    assert result == date(2026, 7, 20)
