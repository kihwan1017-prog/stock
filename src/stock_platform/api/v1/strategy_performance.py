from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import (
    get_db_session,
)
from stock_platform.performance.models import (
    PerformanceRunType,
    StrategyPerformanceMetrics,
)
from stock_platform.performance.repository import (
    StrategyPerformanceRepository,
)
from stock_platform.performance.service import (
    StrategyPerformanceService,
)


router = APIRouter(
    prefix="/api/v1/strategy-performance",
    tags=["Strategy Performance"],
)


class StrategyPerformanceRunRequest(BaseModel):
    strategy_code: str = Field(
        min_length=1,
        max_length=100,
    )
    run_type: PerformanceRunType
    market_code: str = Field(
        min_length=1,
        max_length=30,
    )
    symbol: str | None = Field(
        default=None,
        max_length=30,
    )
    period_start_date: date
    period_end_date: date
    parameter_payload: dict[str, Any] = {}


class StrategyPerformanceCompleteRequest(BaseModel):
    initial_capital: Decimal = Field(gt=0)
    final_capital: Decimal = Field(ge=0)
    total_return_rate: Decimal
    annualized_return_rate: Decimal | None = None
    maximum_drawdown_rate: Decimal
    volatility_rate: Decimal | None = None
    sharpe_ratio: Decimal | None = None
    sortino_ratio: Decimal | None = None
    win_rate: Decimal
    profit_factor: Decimal | None = None
    total_trade_count: int = Field(ge=0)
    winning_trade_count: int = Field(ge=0)
    losing_trade_count: int = Field(ge=0)
    average_profit_amount: Decimal
    average_loss_amount: Decimal
    gross_profit_amount: Decimal
    gross_loss_amount: Decimal
    net_profit_amount: Decimal
    result_payload: dict[str, Any] = {}


@router.post("/runs")
def create_performance_run(
    request: StrategyPerformanceRunRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return StrategyPerformanceService(
            session
        ).create_run(
            strategy_code=request.strategy_code,
            run_type=request.run_type,
            market_code=request.market_code,
            symbol=request.symbol,
            period_start_date=request.period_start_date,
            period_end_date=request.period_end_date,
            parameter_payload=request.parameter_payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/runs/{run_id}/complete")
def complete_performance_run(
    run_id: int,
    request: StrategyPerformanceCompleteRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return StrategyPerformanceService(
            session
        ).complete_run(
            run_id=run_id,
            metrics=StrategyPerformanceMetrics(
                initial_capital=request.initial_capital,
                final_capital=request.final_capital,
                total_return_rate=(
                    request.total_return_rate
                ),
                annualized_return_rate=(
                    request.annualized_return_rate
                ),
                maximum_drawdown_rate=(
                    request.maximum_drawdown_rate
                ),
                volatility_rate=request.volatility_rate,
                sharpe_ratio=request.sharpe_ratio,
                sortino_ratio=request.sortino_ratio,
                win_rate=request.win_rate,
                profit_factor=request.profit_factor,
                total_trade_count=(
                    request.total_trade_count
                ),
                winning_trade_count=(
                    request.winning_trade_count
                ),
                losing_trade_count=(
                    request.losing_trade_count
                ),
                average_profit_amount=(
                    request.average_profit_amount
                ),
                average_loss_amount=(
                    request.average_loss_amount
                ),
                gross_profit_amount=(
                    request.gross_profit_amount
                ),
                gross_loss_amount=(
                    request.gross_loss_amount
                ),
                net_profit_amount=(
                    request.net_profit_amount
                ),
            ),
            result_payload=request.result_payload,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/runs/{run_id}")
def get_performance_run(
    run_id: int,
    session: Session = Depends(get_db_session),
):
    run, metric = StrategyPerformanceRepository(
        session
    ).get_detail(run_id=run_id)

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy performance run not found",
        )

    return {
        "run": run,
        "metric": metric,
    }
