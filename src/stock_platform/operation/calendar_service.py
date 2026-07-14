from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from stock_platform.operation.calendar_repository import (
    TradingCalendarRepository,
)


@dataclass(frozen=True, slots=True)
class TradingDayDecision:
    exchange_code: str
    calendar_date: date
    is_trading_day: bool
    reason_code: str
    holiday_name: str | None
    source_code: str


class TradingCalendarService:
    """거래일 여부와 직전·다음 거래일을 판단한다."""

    ALWAYS_OPEN_EXCHANGES = {"UPBIT"}

    def __init__(
        self,
        repository: TradingCalendarRepository,
    ) -> None:
        self._repository = repository

    def evaluate(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
    ) -> TradingDayDecision:
        exchange = exchange_code.strip().upper()

        if exchange in self.ALWAYS_OPEN_EXCHANGES:
            return TradingDayDecision(
                exchange_code=exchange,
                calendar_date=calendar_date,
                is_trading_day=True,
                reason_code="ALWAYS_OPEN",
                holiday_name=None,
                source_code="SYSTEM",
            )

        stored = self._repository.get_day(
            exchange_code=exchange,
            calendar_date=calendar_date,
        )

        if stored is not None:
            return TradingDayDecision(
                exchange_code=exchange,
                calendar_date=calendar_date,
                is_trading_day=stored.is_trading_day,
                reason_code=(
                    "CALENDAR_OPEN"
                    if stored.is_trading_day
                    else "CALENDAR_CLOSED"
                ),
                holiday_name=stored.holiday_name,
                source_code=stored.source_code,
            )

        if calendar_date.weekday() >= 5:
            return TradingDayDecision(
                exchange_code=exchange,
                calendar_date=calendar_date,
                is_trading_day=False,
                reason_code="WEEKEND",
                holiday_name=None,
                source_code="SYSTEM",
            )

        return TradingDayDecision(
            exchange_code=exchange,
            calendar_date=calendar_date,
            is_trading_day=True,
            reason_code="WEEKDAY_FALLBACK",
            holiday_name=None,
            source_code="SYSTEM",
        )

    def require_trading_day(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
    ) -> TradingDayDecision:
        decision = self.evaluate(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
        )

        if not decision.is_trading_day:
            detail = decision.holiday_name or decision.reason_code
            raise ValueError(
                f"Not a trading day: "
                f"{decision.exchange_code}/"
                f"{decision.calendar_date}/"
                f"{detail}"
            )

        return decision

    def previous_trading_day(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
        maximum_search_days: int = 30,
    ) -> date:
        return self._search(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
            step=-1,
            maximum_search_days=maximum_search_days,
        )

    def next_trading_day(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
        maximum_search_days: int = 30,
    ) -> date:
        return self._search(
            exchange_code=exchange_code,
            calendar_date=calendar_date,
            step=1,
            maximum_search_days=maximum_search_days,
        )

    def _search(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
        step: int,
        maximum_search_days: int,
    ) -> date:
        if maximum_search_days <= 0:
            raise ValueError(
                "maximum_search_days must be greater than zero"
            )

        current = calendar_date

        for _ in range(maximum_search_days):
            current += timedelta(days=step)

            if self.evaluate(
                exchange_code=exchange_code,
                calendar_date=current,
            ).is_trading_day:
                return current

        raise LookupError(
            "Trading day was not found within search range"
        )
