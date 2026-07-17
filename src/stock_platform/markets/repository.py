from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_platform.markets.models import (
    CandleMinute,
    Instrument,
    OrderbookSnapshot,
    PriceDaily,
    QuoteSnapshot,
    TradeTick,
)


class InstrumentRepository:
    """market.instrument 조회·Upsert."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find(
        self,
        exchange_code: str,
        symbol: str,
    ) -> Instrument | None:
        stmt = select(Instrument).where(
            Instrument.exchange_code == exchange_code,
            Instrument.symbol == symbol,
        )
        return self._session.scalar(stmt)

    def list(
        self,
        *,
        exchange_code: str | None = None,
        active_only: bool = True,
        limit: int = 5000,
    ) -> list[Instrument]:
        stmt = select(Instrument)

        if exchange_code is not None:
            stmt = stmt.where(
                Instrument.exchange_code == exchange_code
            )

        if active_only:
            stmt = stmt.where(Instrument.is_active.is_(True))

        stmt = stmt.order_by(
            Instrument.exchange_code.asc(),
            Instrument.symbol.asc(),
        ).limit(limit)

        return list(self._session.scalars(stmt))

    def upsert_many(
        self,
        rows: Iterable[dict],
    ) -> int:
        values = list(rows)
        if not values:
            return 0

        stmt = insert(Instrument).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                Instrument.exchange_code,
                Instrument.symbol,
            ],
            set_={
                "asset_type": stmt.excluded.asset_type,
                "name": stmt.excluded.name,
                "currency_code": stmt.excluded.currency_code,
                "listed_date": stmt.excluded.listed_date,
                "delisted_date": stmt.excluded.delisted_date,
                "is_active": stmt.excluded.is_active,
                "extra_data": stmt.excluded.extra_data,
                "updated_at": stmt.excluded.updated_at,
            },
        )

        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or len(values)


class PriceDailyRepository:
    """market.price_daily 조회·Upsert."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_instrument(
        self,
        exchange_code: str,
        symbol: str,
    ) -> Instrument | None:
        return InstrumentRepository(self._session).find(
            exchange_code,
            symbol,
        )

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

    def list_recent(
        self,
        instrument_id: int,
        *,
        limit: int = 200,
    ) -> list[PriceDaily]:
        stmt = (
            select(PriceDaily)
            .where(PriceDaily.instrument_id == instrument_id)
            .order_by(PriceDaily.trade_date.desc())
            .limit(limit)
        )
        rows = list(self._session.scalars(stmt))
        rows.reverse()
        return rows

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


class CandleMinuteRepository:
    """market.candle_minute 조회·Upsert."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_instrument(
        self,
        exchange_code: str,
        symbol: str,
    ) -> Instrument | None:
        return InstrumentRepository(self._session).find(
            exchange_code,
            symbol,
        )

    def find_latest(
        self,
        instrument_id: int,
        timeframe: int,
    ) -> CandleMinute | None:
        stmt = (
            select(CandleMinute)
            .where(
                CandleMinute.instrument_id == instrument_id,
                CandleMinute.timeframe == timeframe,
            )
            .order_by(CandleMinute.candle_at.desc())
            .limit(1)
        )
        return self._session.scalar(stmt)

    def list_recent(
        self,
        instrument_id: int,
        timeframe: int,
        *,
        limit: int = 200,
    ) -> list[CandleMinute]:
        stmt = (
            select(CandleMinute)
            .where(
                CandleMinute.instrument_id == instrument_id,
                CandleMinute.timeframe == timeframe,
            )
            .order_by(CandleMinute.candle_at.desc())
            .limit(limit)
        )
        rows = list(self._session.scalars(stmt))
        rows.reverse()
        return rows

    def upsert_many(self, rows: Iterable[dict]) -> int:
        values = list(rows)
        if not values:
            return 0

        stmt = insert(CandleMinute).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                CandleMinute.instrument_id,
                CandleMinute.timeframe,
                CandleMinute.candle_at,
            ],
            set_={
                "open_price": stmt.excluded.open_price,
                "high_price": stmt.excluded.high_price,
                "low_price": stmt.excluded.low_price,
                "close_price": stmt.excluded.close_price,
                "volume": stmt.excluded.volume,
                "trade_value": stmt.excluded.trade_value,
                "source": stmt.excluded.source,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or len(values)


class QuoteSnapshotRepository:
    """market.quote_snapshot Upsert·조회."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, instrument_id: int) -> QuoteSnapshot | None:
        return self._session.get(QuoteSnapshot, instrument_id)

    def upsert(self, row: dict) -> int:
        stmt = insert(QuoteSnapshot).values(row)
        stmt = stmt.on_conflict_do_update(
            index_elements=[QuoteSnapshot.instrument_id],
            set_={
                "trade_price": stmt.excluded.trade_price,
                "bid_price": stmt.excluded.bid_price,
                "ask_price": stmt.excluded.ask_price,
                "change_price": stmt.excluded.change_price,
                "change_rate": stmt.excluded.change_rate,
                "volume": stmt.excluded.volume,
                "quoted_at": stmt.excluded.quoted_at,
                "source": stmt.excluded.source,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or 1


class TradeTickRepository:
    """market.trade_tick 적재·조회."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, rows: Iterable[dict]) -> int:
        values = list(rows)
        if not values:
            return 0

        stmt = insert(TradeTick).values(values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[
                TradeTick.instrument_id,
                TradeTick.trade_id,
            ]
        )
        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or 0

    def list_recent(
        self,
        instrument_id: int,
        *,
        limit: int = 100,
    ) -> list[TradeTick]:
        stmt = (
            select(TradeTick)
            .where(TradeTick.instrument_id == instrument_id)
            .order_by(TradeTick.traded_at.desc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt))


class OrderbookSnapshotRepository:
    """market.orderbook_snapshot 적재·조회."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, row: dict) -> int:
        stmt = insert(OrderbookSnapshot).values(row)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                OrderbookSnapshot.instrument_id,
                OrderbookSnapshot.captured_at,
            ],
            set_={
                "bids": stmt.excluded.bids,
                "asks": stmt.excluded.asks,
                "source": stmt.excluded.source,
            },
        )
        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or 1

    def find_latest(
        self,
        instrument_id: int,
    ) -> OrderbookSnapshot | None:
        stmt = (
            select(OrderbookSnapshot)
            .where(
                OrderbookSnapshot.instrument_id == instrument_id
            )
            .order_by(OrderbookSnapshot.captured_at.desc())
            .limit(1)
        )
        return self._session.scalar(stmt)

    def list_recent(
        self,
        instrument_id: int,
        *,
        limit: int = 50,
        since: datetime | None = None,
    ) -> list[OrderbookSnapshot]:
        stmt = select(OrderbookSnapshot).where(
            OrderbookSnapshot.instrument_id == instrument_id
        )
        if since is not None:
            stmt = stmt.where(
                OrderbookSnapshot.captured_at >= since
            )
        stmt = stmt.order_by(
            OrderbookSnapshot.captured_at.desc()
        ).limit(limit)
        return list(self._session.scalars(stmt))
