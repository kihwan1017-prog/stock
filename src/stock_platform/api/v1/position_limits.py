from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.risk_engine.position_limit_repository import (
    PositionLimitRepository,
)


router = APIRouter(
    prefix="/api/v1/risk/position-limits",
    tags=["Position Limits"],
)


class PositionLimitRequest(BaseModel):
    broker_code: str = Field(
        default="KIWOOM",
        min_length=1,
        max_length=30,
    )
    account_number: str = Field(
        min_length=1,
        max_length=30,
    )
    exchange_code: str = Field(
        min_length=1,
        max_length=20,
    )
    symbol: str = Field(
        min_length=1,
        max_length=30,
    )
    max_quantity: Decimal = Field(gt=0)
    max_position_amount: Decimal = Field(gt=0)
    max_position_weight: Decimal = Field(
        gt=0,
        le=1,
    )
    enabled: bool = True


@router.put("")
def save_position_limit(
    request: PositionLimitRequest,
    session: Session = Depends(get_db_session),
):
    return PositionLimitRepository(
        session
    ).upsert(
        broker_code=request.broker_code,
        account_number=request.account_number,
        exchange_code=request.exchange_code,
        symbol=request.symbol,
        max_quantity=request.max_quantity,
        max_position_amount=(
            request.max_position_amount
        ),
        max_position_weight=(
            request.max_position_weight
        ),
        enabled=request.enabled,
    )


@router.get(
    "/{account_number}/{exchange_code}/{symbol}"
)
def get_position_limit(
    account_number: str,
    exchange_code: str,
    symbol: str,
    session: Session = Depends(get_db_session),
):
    return PositionLimitRepository(session).get(
        broker_code="KIWOOM",
        account_number=account_number,
        exchange_code=exchange_code,
        symbol=symbol,
    )
