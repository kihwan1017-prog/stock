from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_platform.markets.models import IndicatorDaily


class IndicatorDailyRepository:
    """market.indicator_daily Upsert·조회."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_between(
        self,
        instrument_id: int,
        start_date: date,
        end_date: date,
    ) -> list[IndicatorDaily]:
        stmt = (
            select(IndicatorDaily)
            .where(
                IndicatorDaily.instrument_id == instrument_id,
                IndicatorDaily.trade_date >= start_date,
                IndicatorDaily.trade_date <= end_date,
            )
            .order_by(IndicatorDaily.trade_date.asc())
        )
        return list(self._session.scalars(stmt))

    def find_latest(
        self,
        instrument_id: int,
    ) -> IndicatorDaily | None:
        stmt = (
            select(IndicatorDaily)
            .where(IndicatorDaily.instrument_id == instrument_id)
            .order_by(IndicatorDaily.trade_date.desc())
            .limit(1)
        )
        return self._session.scalar(stmt)

    def upsert_many(self, rows: Iterable[dict]) -> int:
        values = list(rows)
        if not values:
            return 0

        stmt = insert(IndicatorDaily).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                IndicatorDaily.instrument_id,
                IndicatorDaily.trade_date,
            ],
            set_={
                "close_price": stmt.excluded.close_price,
                "volume": stmt.excluded.volume,
                "ma5": stmt.excluded.ma5,
                "ma20": stmt.excluded.ma20,
                "ma60": stmt.excluded.ma60,
                "ema12": stmt.excluded.ema12,
                "ema26": stmt.excluded.ema26,
                "rsi14": stmt.excluded.rsi14,
                "macd": stmt.excluded.macd,
                "macd_signal": stmt.excluded.macd_signal,
                "macd_histogram": stmt.excluded.macd_histogram,
                "bollinger_middle": stmt.excluded.bollinger_middle,
                "bollinger_upper": stmt.excluded.bollinger_upper,
                "bollinger_lower": stmt.excluded.bollinger_lower,
                "atr14": stmt.excluded.atr14,
                "volume_ma20": stmt.excluded.volume_ma20,
                "high_52w": stmt.excluded.high_52w,
                "low_52w": stmt.excluded.low_52w,
                "status_code": stmt.excluded.status_code,
                "missing_fields": stmt.excluded.missing_fields,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or len(values)
