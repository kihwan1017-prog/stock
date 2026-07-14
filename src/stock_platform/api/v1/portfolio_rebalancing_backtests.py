from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.backtest.rebalancing_models import (
    RebalancingAsset,
    RebalancingFrequency,
)
from stock_platform.backtest.rebalancing_report import (
    RebalancingBacktestReportBuilder,
)
from stock_platform.backtest.rebalancing_service import (
    PortfolioRebalancingBacktestService,
)
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/portfolio-rebalancing-backtests",
    tags=["Portfolio Rebalancing Backtests"],
)


class RebalancingAssetRequest(BaseModel):
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    target_weight: Decimal = Field(gt=0, le=1)


class RebalancingBacktestRequest(BaseModel):
    assets: list[RebalancingAssetRequest] = Field(
        min_length=1,
        max_length=50,
    )
    start_date: date
    end_date: date
    initial_capital: Decimal = Field(gt=0)
    frequency: RebalancingFrequency = (
        RebalancingFrequency.MONTHLY
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
    rebalance_threshold: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=Decimal("0.20"),
    )


@router.post("")
def run_rebalancing_backtest(
    request: RebalancingBacktestRequest,
    session: Session = Depends(get_db_session),
):
    try:
        result = PortfolioRebalancingBacktestService(
            session
        ).run(
            assets=[
                RebalancingAsset(
                    exchange_code=item.exchange_code,
                    symbol=item.symbol,
                    target_weight=item.target_weight,
                )
                for item in request.assets
            ],
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            frequency=request.frequency,
            fee_ratio=request.fee_ratio,
            sell_tax_ratio=request.sell_tax_ratio,
            slippage_ratio=request.slippage_ratio,
            rebalance_threshold=(
                request.rebalance_threshold
            ),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {
        "start_date": result.start_date,
        "end_date": result.end_date,
        "frequency": result.frequency,
        "summary": result.summary,
        "trades": result.trades,
        "snapshots": result.snapshots,
        "final_weights": result.final_weights,
        "report_text": (
            RebalancingBacktestReportBuilder.build(result)
        ),
    }
