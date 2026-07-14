from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.trading.models import PaperOrder


class PaperOrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, order: PaperOrder) -> PaperOrder:
        self._session.add(order)
        self._session.commit()
        self._session.refresh(order)
        return order

    def get(self, order_id: int) -> PaperOrder | None:
        return self._session.get(PaperOrder, order_id)

    def list_recent(
        self,
        *,
        exchange_code: str | None = None,
        limit: int = 100,
    ) -> list[PaperOrder]:
        stmt = select(PaperOrder)

        if exchange_code:
            stmt = stmt.where(
                PaperOrder.exchange_code
                == exchange_code.upper()
            )

        stmt = stmt.order_by(
            PaperOrder.created_at.desc(),
            PaperOrder.order_id.desc(),
        ).limit(limit)

        return list(self._session.scalars(stmt))
