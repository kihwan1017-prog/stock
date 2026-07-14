from __future__ import annotations

from datetime import date
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

from stock_platform.backtest.comparison_service import (
    BacktestComparisonService,
)
from stock_platform.backtest.engine import (
    BacktestValidationError,
)
from stock_platform.backtest.persistence_service import (
    BacktestPersistenceService,
)
from stock_platform.backtest.repository import (
    BacktestRepository,
)
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/backtest-runs",
    tags=["Backtest Runs"],
)


class BacktestRunRequest(BaseModel):
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
    short_window: int = Field(default=5, ge=2, le=200)
    long_window: int = Field(default=20, ge=3, le=500)
    stop_loss_ratio: Decimal = Field(
        default=Decimal("0.05"),
        gt=0,
        le=1,
    )
    take_profit_ratio: Decimal = Field(
        default=Decimal("0.10"),
        gt=0,
        le=1,
    )
    position_ratio: Decimal = Field(
        default=Decimal("0.20"),
        gt=0,
        le=1,
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
        default=Decimal("0"),
        ge=0,
        le=Decimal("0.20"),
    )


@router.post("")
def run_and_save_backtest(
    request: BacktestRunRequest,
    session: Session = Depends(get_db_session),
):
    if request.start_date > request.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must not be after end_date",
        )

    if request.short_window >= request.long_window:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="short_window must be smaller than long_window",
        )

    try:
        run, result = (
            BacktestPersistenceService(session)
            .run_and_save_moving_average(
                exchange_code=request.exchange_code,
                symbol=request.symbol,
                start_date=request.start_date,
                end_date=request.end_date,
                initial_capital=request.initial_capital,
                short_window=request.short_window,
                long_window=request.long_window,
                stop_loss_ratio=request.stop_loss_ratio,
                take_profit_ratio=request.take_profit_ratio,
                position_ratio=request.position_ratio,
                fee_ratio=request.fee_ratio,
                sell_tax_ratio=request.sell_tax_ratio,
                slippage_ratio=request.slippage_ratio,
            )
        )
    except BacktestValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "backtest_run_id": run.backtest_run_id,
        "strategy_code": run.strategy_code,
        "exchange_code": run.exchange_code,
        "symbol": run.symbol,
        "summary": result.summary,
        "trade_count": len(result.trades),
        "equity_point_count": len(
            result.equity_curve
        ),
    }


@router.get("/{backtest_run_id}")
def get_backtest_run(
    backtest_run_id: int,
    session: Session = Depends(get_db_session),
):
    repository = BacktestRepository(session)
    run = repository.get_run(backtest_run_id)

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backtest run not found",
        )

    return {
        "run": run,
        "trades": repository.get_trades(
            backtest_run_id
        ),
        "equity_curve": repository.get_equity_curve(
            backtest_run_id
        ),
    }


@router.get("")
def list_backtest_runs(
    exchange_code: str | None = None,
    symbol: str | None = None,
    strategy_code: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_db_session),
):
    return BacktestRepository(session).list_runs(
        exchange_code=exchange_code,
        symbol=symbol,
        strategy_code=strategy_code,
        limit=limit,
    )


@router.get("/compare/ranking")
def compare_backtest_runs(
    exchange_code: str | None = None,
    symbol: str | None = None,
    strategy_code: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    session: Session = Depends(get_db_session),
):
    return BacktestComparisonService(
        session
    ).compare(
        exchange_code=exchange_code,
        symbol=symbol,
        strategy_code=strategy_code,
        limit=limit,
    )
