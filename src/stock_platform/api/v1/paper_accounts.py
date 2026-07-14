from __future__ import annotations

from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
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


def _service(
    session: Session,
) -> PaperAccountService:
    return PaperAccountService(
        PaperAccountRepository(session)
    )


@router.post("")
def create_paper_account(
    request: CreatePaperAccountRequest,
    session: Session = Depends(get_db_session),
):
    try:
        account = _service(session).create_account(
            account_name=request.account_name,
            initial_cash=request.initial_cash,
            currency_code=request.currency_code,
        )
    except PaperAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return account


@router.post("/{account_id}/fills")
def apply_paper_fill(
    account_id: int,
    request: ApplyFillRequest,
    session: Session = Depends(get_db_session),
):
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
    session: Session = Depends(get_db_session),
):
    repository = PaperAccountRepository(session)

    if repository.get_account(account_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Paper account not found: {account_id}"
            ),
        )

    return repository.list_positions(
        account_id=account_id
    )


@router.post("/{account_id}/valuation")
def value_paper_account(
    account_id: int,
    request: AccountValuationRequest,
    session: Session = Depends(get_db_session),
):
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
