from datetime import date
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
from stock_platform.performance.backtest_integration_service import (
    BacktestPerformanceIntegrationService,
)
from stock_platform.performance.backtest_result_adapter import (
    BacktestResultPayloadAdapter,
)


router = APIRouter(
    prefix="/api/v1/backtest-performance",
    tags=["Backtest Performance"],
)


class BacktestPerformanceSaveRequest(BaseModel):
    strategy_code: str = Field(
        min_length=1,
        max_length=100,
    )
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
    result_payload: dict[str, Any]


@router.post("/save")
def save_backtest_performance(
    request: BacktestPerformanceSaveRequest,
    session: Session = Depends(get_db_session),
):
    try:
        source = BacktestResultPayloadAdapter.from_payload(
            strategy_code=request.strategy_code,
            market_code=request.market_code,
            symbol=request.symbol,
            period_start_date=request.period_start_date,
            period_end_date=request.period_end_date,
            parameter_payload=request.parameter_payload,
            result_payload=request.result_payload,
        )

        return BacktestPerformanceIntegrationService(
            session
        ).save_completed_backtest(source)

    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
