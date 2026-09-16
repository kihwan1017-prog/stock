"""관심종목 Repository — STEP67."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.trading.watchlist_models import WatchlistItem


class WatchlistRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_user(self, user_id: int) -> list[WatchlistItem]:
        stmt = (
            select(WatchlistItem)
            .where(WatchlistItem.user_id == user_id)
            .order_by(
                WatchlistItem.display_order.asc(),
                WatchlistItem.watchlist_id.asc(),
            )
        )
        return list(self._session.scalars(stmt))

    def get_owned(
        self,
        *,
        user_id: int,
        watchlist_id: int,
    ) -> WatchlistItem | None:
        return self._session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.watchlist_id == watchlist_id,
                WatchlistItem.user_id == user_id,
            )
        )

    def find_by_symbol(
        self,
        *,
        user_id: int,
        market: str,
        symbol: str,
    ) -> WatchlistItem | None:
        return self._session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.user_id == user_id,
                WatchlistItem.market == market.upper(),
                WatchlistItem.symbol == symbol.upper(),
            )
        )

    def count_for_user(self, user_id: int) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(WatchlistItem)
                .where(WatchlistItem.user_id == user_id)
            )
            or 0
        )

    def max_display_order(self, user_id: int) -> int:
        value = self._session.scalar(
            select(func.max(WatchlistItem.display_order)).where(
                WatchlistItem.user_id == user_id
            )
        )
        return int(value or 0)

    def save(self, row: WatchlistItem) -> WatchlistItem:
        self._session.add(row)
        self._session.commit()
        self._session.refresh(row)
        return row

    def delete(self, row: WatchlistItem) -> None:
        self._session.delete(row)
        self._session.commit()

    def commit(self) -> None:
        self._session.commit()
