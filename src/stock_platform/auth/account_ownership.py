"""Paper 계좌 소유권 검사 (STEP52/STEP65)."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.trading.account_models import (
    PaperAccount,
    UserBrokerAccount,
)
from stock_platform.trading.account_repository import PaperAccountRepository


def assert_paper_account_access(
    user: AuthenticatedUser,
    account_id: int,
    session: Session,
) -> PaperAccount:
    """
    admin은 모든 Paper 계좌 접근 가능.
    그 외는 paper_account.user_id == user.user_id 만 허용.
    """

    account = PaperAccountRepository(session).get_account(account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Paper account not found: {account_id}",
        )
    if user.is_admin:
        return account
    if account.user_id is None or int(account.user_id) != int(user.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 Paper 계좌에 대한 권한이 없습니다.",
        )
    return account


def assert_trading_account_access(
    user: AuthenticatedUser,
    account_id: int,
    session: Session,
) -> None:
    """
    주문·계좌 리소스용.
    Paper 계좌가 있으면 소유권 검사.
    Paper에 없으면 admin만 허용 (브로커 계좌 등).
    """

    if user.is_admin:
        return
    account = PaperAccountRepository(session).get_account(account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 계좌에 대한 권한이 없습니다.",
        )
    if account.user_id is None or int(account.user_id) != int(user.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 계좌에 대한 권한이 없습니다.",
        )


def assert_broker_account_access(
    user: AuthenticatedUser,
    user_broker_account_id: int,
    session: Session,
) -> UserBrokerAccount:
    """회원별 Broker 연결 소유권."""

    row = session.get(UserBrokerAccount, user_broker_account_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Broker 계좌 연결을 찾을 수 없습니다.",
        )
    if user.is_admin:
        return row
    if int(row.user_id) != int(user.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 Broker 계좌에 대한 권한이 없습니다.",
        )
    return row


def assert_account_access(
    user: AuthenticatedUser,
    account_id: int,
    session: Session,
    *,
    account_type: str | None = None,
) -> PaperAccount | UserBrokerAccount:
    """공통 소유권 Guard — Paper 또는 Broker 연결."""

    kind = (account_type or "").strip().upper() or None
    if kind is None or kind == "PAPER":
        paper = PaperAccountRepository(session).get_account(account_id)
        if paper is not None:
            if user.is_admin:
                return paper
            if (
                paper.user_id is not None
                and int(paper.user_id) == int(user.user_id)
            ):
                return paper
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="해당 계좌에 대한 권한이 없습니다.",
            )
    if kind is None or kind in {"KIWOOM", "UPBIT"}:
        return assert_broker_account_access(
            user, account_id, session
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="계좌를 찾을 수 없습니다.",
    )
