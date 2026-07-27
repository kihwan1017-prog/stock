from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
    PaperTrade,
)
from stock_platform.trading.models import PaperOrder


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
        *,
        include_deleted: bool = False,
    ) -> PaperAccount | None:
        account = self._session.get(PaperAccount, account_id)
        if account is None:
            return None
        if not include_deleted and account.deleted_at is not None:
            return None
        return account

    def list_accounts(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        user_id: int | None = None,
        include_deleted: bool = False,
    ) -> list[PaperAccount]:
        stmt = select(PaperAccount)
        if user_id is not None:
            stmt = stmt.where(PaperAccount.user_id == user_id)
        if not include_deleted:
            stmt = stmt.where(PaperAccount.deleted_at.is_(None))
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
        """회원 기본 Paper 계좌 — is_default 우선, 없으면 최소 account_id."""

        default_stmt = (
            select(PaperAccount)
            .where(
                PaperAccount.user_id == user_id,
                PaperAccount.is_default.is_(True),
                PaperAccount.is_active.is_(True),
                PaperAccount.deleted_at.is_(None),
            )
            .order_by(PaperAccount.account_id.asc())
            .limit(1)
        )
        found = self._session.scalar(default_stmt)
        if found is not None:
            return found

        stmt = (
            select(PaperAccount)
            .where(
                PaperAccount.user_id == user_id,
                PaperAccount.is_active.is_(True),
                PaperAccount.deleted_at.is_(None),
            )
            .order_by(PaperAccount.account_id.asc())
            .limit(1)
        )
        return self._session.scalar(stmt)

    def has_order_or_trade_history(self, account_id: int) -> bool:
        """주문 또는 체결(거래) 이력이 있으면 True — Hard Delete 금지 판단용."""

        order_exists = self._session.scalar(
            select(
                exists().where(PaperOrder.account_id == account_id)
            )
        )
        if order_exists:
            return True
        trade_exists = self._session.scalar(
            select(
                exists().where(PaperTrade.account_id == account_id)
            )
        )
        return bool(trade_exists)

    def has_trading_activity(self, account_id: int) -> bool:
        """
        주문·체결·보유(수량>0) 이력이 있으면 True.
        초기 자산(initial_cash) 수정 가능 여부 판단에 사용.
        """

        if self.has_order_or_trade_history(account_id):
            return True
        return self.count_open_positions(account_id) > 0

    def find_by_account_name(
        self,
        account_name: str,
        *,
        exclude_account_id: int | None = None,
    ) -> PaperAccount | None:
        stmt = select(PaperAccount).where(
            PaperAccount.account_name == account_name,
            PaperAccount.deleted_at.is_(None),
        )
        if exclude_account_id is not None:
            stmt = stmt.where(
                PaperAccount.account_id != exclude_account_id
            )
        return self._session.scalar(stmt.limit(1))

    def clear_defaults_for_user(
        self,
        user_id: int,
        *,
        exclude_account_id: int | None = None,
    ) -> None:
        stmt = select(PaperAccount).where(
            PaperAccount.user_id == user_id,
            PaperAccount.is_default.is_(True),
            PaperAccount.deleted_at.is_(None),
        )
        if exclude_account_id is not None:
            stmt = stmt.where(
                PaperAccount.account_id != exclude_account_id
            )
        for row in self._session.scalars(stmt):
            row.is_default = False
            self._session.add(row)

    def persist_account(self, account: PaperAccount) -> PaperAccount:
        """UPDATE flush (commit은 Service/Router 트랜잭션에서)."""

        self._session.add(account)
        self._session.flush()
        self._session.refresh(account)
        return account

    def soft_delete_account(
        self,
        account: PaperAccount,
        *,
        deleted_at: datetime | None = None,
    ) -> PaperAccount:
        """
        Soft Delete — 행을 물리 삭제하지 않음.
        (주문/체결 이력이 있어도 Soft Delete만 허용, Hard Delete 금지)
        """

        if account.deleted_at is not None:
            return account

        stamp = deleted_at or datetime.now(timezone.utc)
        original_name = (account.account_name or "").strip() or "paper"
        # unique(account_name) 충돌 방지 — 삭제 표시용으로 이름 변경
        suffix = f"__deleted_{account.account_id}"
        max_base = max(1, 100 - len(suffix))
        account.account_name = f"{original_name[:max_base]}{suffix}"
        account.is_active = False
        account.is_default = False
        account.deleted_at = stamp
        account.updated_at = stamp
        self._session.add(account)
        self._session.flush()
        return account

    def count_open_positions(self, account_id: int) -> int:
        value = self._session.scalar(
            select(func.count())
            .select_from(PaperPosition)
            .where(
                PaperPosition.account_id == account_id,
                PaperPosition.quantity > 0,
            )
        )
        return int(value or 0)

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
