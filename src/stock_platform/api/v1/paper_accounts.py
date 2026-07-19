from __future__ import annotations

from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.account_ownership import (
    assert_paper_account_access,
)
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.database.session import get_db_session
from stock_platform.trading.account_models import PaperAccount
from stock_platform.trading.account_repository import (
    PaperAccountRepository,
)
from stock_platform.trading.account_service import (
    PaperAccountError,
    PaperAccountService,
)
from stock_platform.trading.models import OrderSide


router = APIRouter(
    prefix="/api/v1/paper-accounts",
    tags=["Paper Accounts"],
)

_DEFAULT_INITIAL_CASH = Decimal("10000000")


class CreatePaperAccountRequest(BaseModel):
    account_name: str = Field(
        min_length=1,
        max_length=100,
    )
    initial_cash: Decimal = Field(gt=0)
    currency_code: str = Field(
        default="KRW",
        min_length=1,
        max_length=10,
    )


class ApplyFillRequest(BaseModel):
    exchange_code: str = Field(
        min_length=1,
        max_length=20,
    )
    symbol: str = Field(
        min_length=1,
        max_length=30,
    )
    side: OrderSide
    quantity: Decimal = Field(gt=0)
    fill_price: Decimal = Field(gt=0)
    order_id: int | None = Field(
        default=None,
        gt=0,
    )


class AccountValuationRequest(BaseModel):
    prices: dict[str, Decimal]


def _service(session: Session) -> PaperAccountService:
    return PaperAccountService(
        PaperAccountRepository(session)
    )


def _account_dict(account: PaperAccount) -> dict:
    return {
        "account_id": account.account_id,
        "user_id": account.user_id,
        "account_name": account.account_name,
        "currency_code": account.currency_code,
        "initial_cash": account.initial_cash,
        "available_cash": account.available_cash,
        "realized_profit_loss": account.realized_profit_loss,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def _ensure_my_account(
    user: AuthenticatedUser,
    session: Session,
) -> PaperAccount:
    """내 Paper 계좌 — 없으면 lazy 생성."""

    repo = PaperAccountRepository(session)
    existing = repo.get_primary_for_user(user.user_id)
    if existing is not None:
        return existing
    try:
        return _service(session).create_account(
            account_name=f"user-{user.user_id}-default",
            initial_cash=_DEFAULT_INITIAL_CASH,
            currency_code="KRW",
            user_id=user.user_id,
        )
    except PaperAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/me")
def get_my_paper_account(
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """로그인 사용자 기본 Paper 계좌 (없으면 생성)."""

    return _account_dict(_ensure_my_account(user, session))


@router.get("")
def list_paper_accounts(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """모의 계좌 목록 — admin 전체, 그 외 본인 소유만."""

    repo = PaperAccountRepository(session)
    if user.is_admin:
        rows = repo.list_accounts(limit=limit, offset=offset)
    else:
        rows = repo.list_accounts(
            limit=limit,
            offset=offset,
            user_id=user.user_id,
        )
    return [_account_dict(row) for row in rows]


@router.get("/{account_id}")
def get_paper_account(
    account_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    account = assert_paper_account_access(
        user, account_id, session
    )
    return _account_dict(account)


@router.post("")
def create_paper_account(
    request: CreatePaperAccountRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        account = _service(session).create_account(
            account_name=request.account_name,
            initial_cash=request.initial_cash,
            currency_code=request.currency_code,
            user_id=user.user_id,
        )
    except PaperAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _account_dict(account)


@router.post("/{account_id}/fills")
def apply_paper_fill(
    account_id: int,
    request: ApplyFillRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    assert_paper_account_access(user, account_id, session)
    try:
        return _service(session).apply_fill(
            account_id=account_id,
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            fill_price=request.fill_price,
            order_id=request.order_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/{account_id}/positions")
def list_paper_positions(
    account_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    assert_paper_account_access(user, account_id, session)
    return PaperAccountRepository(session).list_positions(
        account_id=account_id
    )


@router.post("/{account_id}/valuation")
def value_paper_account(
    account_id: int,
    request: AccountValuationRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    assert_paper_account_access(user, account_id, session)
    try:
        return _service(session).value_account(
            account_id=account_id,
            prices={
                key.upper(): value
                for key, value in request.prices.items()
            },
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PaperAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
