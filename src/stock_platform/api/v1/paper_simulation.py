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

from stock_platform.database.session import get_db_session
from stock_platform.trading.account_service import (
    PaperAccountError,
)
from stock_platform.trading.paper_engine import (
    PaperOrderValidationError,
)
from stock_platform.trading.simulation_models import (
    SimulationRequest,
)
from stock_platform.trading.simulation_service import (
    DailyCloseFillSimulator,
    PaperFillSimulationError,
)


router = APIRouter(
    prefix="/api/v1/paper-simulation",
    tags=["Paper Simulation"],
)


class DailyCloseSimulationRequest(BaseModel):
    account_id: int = Field(gt=0)
    exchange_code: str = Field(
        min_length=1,
        max_length=20,
    )
    symbol: str = Field(
        min_length=1,
        max_length=30,
    )
    trade_date: date
    slippage_ratio: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=Decimal("0.20"),
    )
    fill_ratio: Decimal = Field(
        default=Decimal("1"),
        gt=0,
        le=1,
    )


@router.post("/orders/{order_id}/daily-close")
def simulate_order_by_daily_close(
    order_id: int,
    request: DailyCloseSimulationRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return DailyCloseFillSimulator(
            session
        ).simulate_order(
            order_id=order_id,
            request=SimulationRequest(
                account_id=request.account_id,
                exchange_code=request.exchange_code,
                symbol=request.symbol,
                trade_date=request.trade_date,
                slippage_ratio=(
                    request.slippage_ratio
                ),
                fill_ratio=request.fill_ratio,
            ),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (
        ValueError,
        PaperFillSimulationError,
        PaperOrderValidationError,
        PaperAccountError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/open-orders/daily-close")
def simulate_open_orders_by_daily_close(
    request: DailyCloseSimulationRequest,
    limit: int = 100,
    session: Session = Depends(get_db_session),
):
    try:
        results = DailyCloseFillSimulator(
            session
        ).simulate_open_orders(
            request=SimulationRequest(
                account_id=request.account_id,
                exchange_code=request.exchange_code,
                symbol=request.symbol,
                trade_date=request.trade_date,
                slippage_ratio=(
                    request.slippage_ratio
                ),
                fill_ratio=request.fill_ratio,
            ),
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (
        ValueError,
        PaperOrderValidationError,
        PaperAccountError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "processed_count": len(results),
        "results": results,
    }
