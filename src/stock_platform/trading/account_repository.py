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

    def list_accounts(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        user_id: int | None = None,
    ) -> list[PaperAccount]:
        stmt = select(PaperAccount)
        if user_id is not None:
            stmt = stmt.where(PaperAccount.user_id == user_id)
        stmt = (
            stmt.order_by(PaperAccount.account_id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(stmt))

    def get_primary_for_user(
        self,
        user_id: int,
    ) -> PaperAccount | None:
        """회원 기본 Paper 계좌 (가장 작은 account_id)."""

        stmt = (
            select(PaperAccount)
            .where(PaperAccount.user_id == user_id)
            .order_by(PaperAccount.account_id.asc())
            .limit(1)
        )
        return self._session.scalar(stmt)

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
