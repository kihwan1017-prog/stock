from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.backtest.walk_forward_report import (
    WalkForwardReportBuilder,
)
from stock_platform.backtest.walk_forward_service import (
    WalkForwardValidationService,
)
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/walk-forward",
    tags=["Walk Forward"],
)


class WalkForwardRequest(BaseModel):
    exchange_code: str = Field(
        min_length=1,
        max_length=20,
    )
    symbol: str = Field(
        min_length=1,
        max_length=30,
    )
    start_date: date
    end_date: date
    initial_capital: Decimal = Field(gt=0)
    train_months: int = Field(
        default=12,
        ge=1,
        le=120,
    )
    test_months: int = Field(
        default=3,
        ge=1,
        le=24,
    )
    short_windows: list[int] = Field(
        min_length=1,
        max_length=20,
    )
    long_windows: list[int] = Field(
        min_length=1,
        max_length=20,
    )
    stop_loss_ratios: list[Decimal] = Field(
        min_length=1,
        max_length=20,
    )
    take_profit_ratios: list[Decimal] = Field(
        min_length=1,
        max_length=20,
    )
    position_ratios: list[Decimal] = Field(
        min_length=1,
        max_length=20,
    )
    fee_ratio: Decimal = Field(
        default=Decimal("0.00015"),
        ge=0,
        le=Decimal("0.20"),
    )
    sell_tax_ratio: Decimal = Field(
        default=Decimal("0.0018"),
        ge=0,
        le=Decimal("0.20"),
    )
    slippage_ratio: Decimal = Field(
        default=Decimal("0.001"),
        ge=0,
        le=Decimal("0.20"),
    )


@router.post("")
def run_walk_forward_validation(
    request: WalkForwardRequest,
    session: Session = Depends(get_db_session),
):
    try:
        result = WalkForwardValidationService(
            session
        ).run(
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            train_months=request.train_months,
            test_months=request.test_months,
            short_windows=request.short_windows,
            long_windows=request.long_windows,
            stop_loss_ratios=(
                request.stop_loss_ratios
            ),
            take_profit_ratios=(
                request.take_profit_ratios
            ),
            position_ratios=(
                request.position_ratios
            ),
            fee_ratio=request.fee_ratio,
            sell_tax_ratio=request.sell_tax_ratio,
            slippage_ratio=request.slippage_ratio,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "exchange_code": result.exchange_code,
        "symbol": result.symbol,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "train_months": result.train_months,
        "test_months": result.test_months,
        "summary": result.summary,
        "windows": result.windows,
        "failures": result.failures,
        "report_text": (
            WalkForwardReportBuilder.build(result)
        ),
    }
