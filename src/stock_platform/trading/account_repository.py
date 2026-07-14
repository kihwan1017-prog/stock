from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
    PaperTrade,
)


class PaperAccountRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_account(
        self,
        account: PaperAccount,
    ) -> PaperAccount:
        self._session.add(account)
        self._session.commit()
        self._session.refresh(account)
        return account

    def get_account(
        self,
        account_id: int,
    ) -> PaperAccount | None:
        return self._session.get(PaperAccount, account_id)

    def get_position(
        self,
        *,
        account_id: int,
        exchange_code: str,
        symbol: str,
    ) -> PaperPosition | None:
        return self._session.scalar(
            select(PaperPosition).where(
                PaperPosition.account_id == account_id,
                PaperPosition.exchange_code
                == exchange_code.upper(),
                PaperPosition.symbol == symbol.upper(),
            )
        )

    def list_positions(
        self,
        *,
        account_id: int,
    ) -> list[PaperPosition]:
        stmt = (
            select(PaperPosition)
            .where(
                PaperPosition.account_id == account_id,
                PaperPosition.quantity > 0,
            )
            .order_by(
                PaperPosition.exchange_code.asc(),
                PaperPosition.symbol.asc(),
            )
        )
        return list(self._session.scalars(stmt))

    def save_position(
        self,
        position: PaperPosition,
    ) -> PaperPosition:
        self._session.add(position)
        self._session.flush()
        return position

    def save_trade(
        self,
        trade: PaperTrade,
    ) -> PaperTrade:
        self._session.add(trade)
        self._session.commit()
        self._session.refresh(trade)
        return trade

    def commit(self) -> None:
        self._session.commit()
