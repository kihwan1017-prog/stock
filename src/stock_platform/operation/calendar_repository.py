from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_platform.operation.calendar_models import (
    TradingCalendarDay,
)


class TradingCalendarRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_days(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        stmt = insert(TradingCalendarDay).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                TradingCalendarDay.exchange_code,
                TradingCalendarDay.calendar_date,
            ],
            set_={
                "is_trading_day": (
                    stmt.excluded.is_trading_day
                ),
                "holiday_name": stmt.excluded.holiday_name,
                "source_code": stmt.excluded.source_code,
            },
        )

        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or len(rows)

    def get_day(
        self,
        *,
        exchange_code: str,
        calendar_date: date,
    ) -> TradingCalendarDay | None:
        return self._session.scalar(
            select(TradingCalendarDay).where(
                TradingCalendarDay.exchange_code
                == exchange_code.upper(),
                TradingCalendarDay.calendar_date
                == calendar_date,
            )
        )

    def list_between(
        self,
        *,
        exchange_code: str,
        start_date: date,
        end_date: date,
    ) -> list[TradingCalendarDay]:
        stmt = (
            select(TradingCalendarDay)
            .where(
                TradingCalendarDay.exchange_code
                == exchange_code.upper(),
                TradingCalendarDay.calendar_date
                >= start_date,
                TradingCalendarDay.calendar_date
                <= end_date,
            )
            .order_by(
                TradingCalendarDay.calendar_date.asc()
            )
        )
        return list(self._session.scalars(stmt))
