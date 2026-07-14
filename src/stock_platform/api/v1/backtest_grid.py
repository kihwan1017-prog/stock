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

from stock_platform.backtest.grid_models import (
    BacktestGridRequest,
)
from stock_platform.backtest.grid_report import (
    BacktestGridReportBuilder,
)
from stock_platform.backtest.grid_service import (
    BacktestGridService,
)
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/backtest-grid",
    tags=["Backtest Grid"],
)


class BacktestGridApiRequest(BaseModel):
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
    top_n: int = Field(default=10, ge=1, le=100)


@router.post("")
def run_backtest_grid(
    request: BacktestGridApiRequest,
    session: Session = Depends(get_db_session),
):
    try:
        result = BacktestGridService(
            session
        ).run(
            BacktestGridRequest(
                exchange_code=request.exchange_code,
                symbol=request.symbol,
                start_date=request.start_date,
                end_date=request.end_date,
                initial_capital=request.initial_capital,
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
                top_n=request.top_n,
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "exchange_code": result.exchange_code,
        "symbol": result.symbol,
        "combination_count": (
            result.combination_count
        ),
        "success_count": result.success_count,
        "failed_count": result.failed_count,
        "top_results": result.top_results,
        "failures": result.failures,
        "report_text": (
            BacktestGridReportBuilder.build(result)
        ),
    }
