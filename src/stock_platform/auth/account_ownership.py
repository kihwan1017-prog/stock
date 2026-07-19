"""Paper 계좌 소유권 검사 (STEP52)."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.trading.account_models import PaperAccount
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
