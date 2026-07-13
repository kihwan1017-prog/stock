from datetime import date
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_platform.markets.models import Instrument, PriceDaily


class PriceDailyRepository:
    """Database operations for daily market prices."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_instrument(
        self,
        exchange_code: str,
        symbol: str,
    ) -> Instrument | None:
        stmt = select(Instrument).where(
            Instrument.exchange_code == exchange_code,
            Instrument.symbol == symbol,
        )
        return self._session.scalar(stmt)

    def find_latest(
        self,
        instrument_id: int,
    ) -> PriceDaily | None:
        stmt = (
            select(PriceDaily)
            .where(PriceDaily.instrument_id == instrument_id)
            .order_by(PriceDaily.trade_date.desc())
            .limit(1)
        )
        return self._session.scalar(stmt)

    def find_between(
        self,
        instrument_id: int,
        start_date: date,
        end_date: date,
    ) -> list[PriceDaily]:
        stmt = (
            select(PriceDaily)
            .where(
                PriceDaily.instrument_id == instrument_id,
                PriceDaily.trade_date >= start_date,
                PriceDaily.trade_date <= end_date,
            )
            .order_by(PriceDaily.trade_date.asc())
        )
        return list(self._session.scalars(stmt))

    def upsert_many(
        self,
        rows: Iterable[dict],
    ) -> int:
        values = list(rows)

        if not values:
            return 0

        stmt = insert(PriceDaily).values(values)

        update_columns = {
            "open_price": stmt.excluded.open_price,
            "high_price": stmt.excluded.high_price,
            "low_price": stmt.excluded.low_price,
            "close_price": stmt.excluded.close_price,
            "volume": stmt.excluded.volume,
            "trade_value": stmt.excluded.trade_value,
            "change_rate": stmt.excluded.change_rate,
            "source": stmt.excluded.source,
            "updated_at": stmt.excluded.updated_at,
        }

        stmt = stmt.on_conflict_do_update(
            index_elements=[
                PriceDaily.instrument_id,
                PriceDaily.trade_date,
            ],
            set_=update_columns,
        )

        result = self._session.execute(stmt)
        self._session.commit()

        return result.rowcount or len(values)

    def delete_after(
        self,
        instrument_id: int,
        trade_date: date,
    ) -> int:
        stmt = delete(PriceDaily).where(
            PriceDaily.instrument_id == instrument_id,
            PriceDaily.trade_date > trade_date,
        )

        result = self._session.execute(stmt)
        self._session.commit()

        return result.rowcount or 0
