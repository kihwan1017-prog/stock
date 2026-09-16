from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.risk_engine.position_limit_repository import (
    PositionLimitRepository,
)
from stock_platform.trading.account_identity import AccountIdentityError


router = APIRouter(
    prefix="/api/v1/risk/position-limits",
    tags=["Position Limits"],
    dependencies=[Depends(require_admin)],
)


class PositionLimitRequest(BaseModel):
    broker_code: str = Field(
        default="KIWOOM",
        min_length=1,
        max_length=30,
    )
    user_broker_account_id: int | None = Field(default=None, ge=1)
    paper_account_id: int | None = Field(default=None, ge=1)
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    max_quantity: Decimal = Field(gt=0)
    max_position_amount: Decimal = Field(gt=0)
    max_position_weight: Decimal = Field(gt=0, le=1)
    enabled: bool = True
    masked_account_ref: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _exactly_one_scope(self) -> "PositionLimitRequest":
        uba = self.user_broker_account_id is not None
        paper = self.paper_account_id is not None
        if uba == paper:
            raise ValueError(
                "exactly one of user_broker_account_id "
                "or paper_account_id is required"
            )
        return self


@router.put("")
def save_position_limit(
    request: PositionLimitRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return PositionLimitRepository(session).upsert(
            broker_code=request.broker_code,
            user_broker_account_id=request.user_broker_account_id,
            paper_account_id=request.paper_account_id,
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            max_quantity=request.max_quantity,
            max_position_amount=request.max_position_amount,
            max_position_weight=request.max_position_weight,
            enabled=request.enabled,
            masked_account_ref=request.masked_account_ref,
        )
    except (AccountIdentityError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/by-uba/{user_broker_account_id}/{exchange_code}/{symbol}")
def get_position_limit_by_uba(
    user_broker_account_id: int,
    exchange_code: str,
    symbol: str,
    session: Session = Depends(get_db_session),
):
    return PositionLimitRepository(session).get_by_uba(
        user_broker_account_id=user_broker_account_id,
        exchange_code=exchange_code,
        symbol=symbol,
    )


@router.get("/by-paper/{paper_account_id}/{exchange_code}/{symbol}")
def get_position_limit_by_paper(
    paper_account_id: int,
    exchange_code: str,
    symbol: str,
    session: Session = Depends(get_db_session),
):
    return PositionLimitRepository(session).get_by_paper(
        paper_account_id=paper_account_id,
        exchange_code=exchange_code,
        symbol=symbol,
    )


@router.get("/{account_number}/{exchange_code}/{symbol}")
def get_position_limit_legacy(
    account_number: str,
    exchange_code: str,
    symbol: str,
):
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "LEGACY_ACCOUNT_NUMBER_ONLY",
            "message": "Use /by-uba/{id}/... or /by-paper/{id}/...",
        },
    )
