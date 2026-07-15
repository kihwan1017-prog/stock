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
from stock_platform.performance.walk_forward_models import (
    WalkForwardPerformanceInput,
    WalkForwardWindowPerformanceInput,
)
from stock_platform.performance.walk_forward_repository import (
    WalkForwardWindowMetricRepository,
)
from stock_platform.performance.walk_forward_service import (
    WalkForwardPerformanceIntegrationService,
)


router = APIRouter(
    prefix="/api/v1/walk-forward-performance",
    tags=["Walk Forward Performance"],
)


class WalkForwardWindowRequest(BaseModel):
    window_no: int = Field(gt=0)
    train_start_date: date
    train_end_date: date
    test_start_date: date
    test_end_date: date
    parameter_payload: dict[str, Any] = {}
    result_payload: dict[str, Any]


class WalkForwardPerformanceRequest(BaseModel):
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
    aggregate_parameter_payload: dict[str, Any] = {}
    windows: list[WalkForwardWindowRequest] = Field(
        min_length=1
    )


@router.post("/save")
def save_walk_forward_performance(
    request: WalkForwardPerformanceRequest,
    session: Session = Depends(get_db_session),
):
    try:
        source = WalkForwardPerformanceInput(
            strategy_code=request.strategy_code,
            market_code=request.market_code,
            symbol=request.symbol,
            period_start_date=request.period_start_date,
            period_end_date=request.period_end_date,
            aggregate_parameter_payload=(
                request.aggregate_parameter_payload
            ),
            windows=[
                WalkForwardWindowPerformanceInput(
                    window_no=item.window_no,
                    train_start_date=(
                        item.train_start_date
                    ),
                    train_end_date=item.train_end_date,
                    test_start_date=(
                        item.test_start_date
                    ),
                    test_end_date=item.test_end_date,
                    parameter_payload=(
                        item.parameter_payload
                    ),
                    result_payload=item.result_payload,
                )
                for item in request.windows
            ],
        )

        return WalkForwardPerformanceIntegrationService(
            session
        ).save(source)

    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/runs/{run_id}/windows")
def get_walk_forward_windows(
    run_id: int,
    session: Session = Depends(get_db_session),
):
    return WalkForwardWindowMetricRepository(
        session
    ).list_by_run(
        strategy_performance_run_id=run_id
    )
