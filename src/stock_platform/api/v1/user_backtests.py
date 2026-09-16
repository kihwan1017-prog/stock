"""회원용 백테스트 API.

백테스트는 계좌·실거래 상태와 무관한 무상태(stateless) 시뮬레이션이며
(exchange_code/symbol/기간/파라미터만으로 결과를 계산), 공유 런타임이나
다른 회원의 실행에 영향을 주지 않는다. 따라서 조회뿐 아니라 실행(POST)도
회원 권한(trading:write)으로 개방한다 — 전략 배포/런타임 제어와는 다른
성격이다. 서비스 계층은 기존 admin 라우터(backtests.py, backtest_runs.py,
walk_forward.py, portfolio_backtests.py)와 동일한 것을 재사용한다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.backtest.engine import BacktestValidationError
from stock_platform.backtest.portfolio_models import PortfolioBacktestAsset
from stock_platform.backtest.portfolio_report import (
    PortfolioBacktestReportBuilder,
)
from stock_platform.backtest.portfolio_service import PortfolioBacktestService
from stock_platform.backtest.repository import BacktestRepository
from stock_platform.backtest.service import BacktestService
from stock_platform.backtest.walk_forward_report import (
    WalkForwardReportBuilder,
)
from stock_platform.backtest.walk_forward_service import (
    WalkForwardValidationService,
)
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.database.session import get_db_session


router = APIRouter(
    prefix="/api/v1/user/backtests",
    tags=["User Backtests"],
)


class MovingAverageBacktestRequest(BaseModel):
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    start_date: date
    end_date: date
    initial_capital: Decimal = Field(gt=0)
    short_window: int = Field(default=5, ge=2, le=200)
    long_window: int = Field(default=20, ge=3, le=500)
    stop_loss_ratio: Decimal = Field(default=Decimal("0.05"), gt=0, le=1)
    take_profit_ratio: Decimal = Field(default=Decimal("0.10"), gt=0, le=1)
    position_ratio: Decimal = Field(default=Decimal("0.20"), gt=0, le=1)
    fee_ratio: Decimal = Field(
        default=Decimal("0.00015"), ge=0, le=Decimal("0.20")
    )
    sell_tax_ratio: Decimal = Field(
        default=Decimal("0.0018"), ge=0, le=Decimal("0.20")
    )
    slippage_ratio: Decimal = Field(
        default=Decimal("0"), ge=0, le=Decimal("0.20")
    )


@router.post("/moving-average")
def run_moving_average_backtest(
    request: MovingAverageBacktestRequest,
    http_request: Request,
    _: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    # 고비용 백테스트 — IP당 분당 10회 (admin 라우터와 동일 제한)
    enforce_rate_limit(
        http_request,
        scope="backtest_moving_average",
        limit=10,
        window_seconds=60,
    )
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
        return BacktestService(session).run_moving_average_backtest(
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
    except BacktestValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/runs")
def list_backtest_runs(
    exchange_code: str | None = None,
    symbol: str | None = None,
    strategy_code: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    return BacktestRepository(session).list_runs(
        exchange_code=exchange_code,
        symbol=symbol,
        strategy_code=strategy_code,
        limit=limit,
    )


class WalkForwardRequest(BaseModel):
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    start_date: date
    end_date: date
    initial_capital: Decimal = Field(gt=0)
    train_months: int = Field(default=12, ge=1, le=120)
    test_months: int = Field(default=3, ge=1, le=24)
    short_windows: list[int] = Field(min_length=1, max_length=20)
    long_windows: list[int] = Field(min_length=1, max_length=20)
    stop_loss_ratios: list[Decimal] = Field(min_length=1, max_length=20)
    take_profit_ratios: list[Decimal] = Field(min_length=1, max_length=20)
    position_ratios: list[Decimal] = Field(min_length=1, max_length=20)
    fee_ratio: Decimal = Field(
        default=Decimal("0.00015"), ge=0, le=Decimal("0.20")
    )
    sell_tax_ratio: Decimal = Field(
        default=Decimal("0.0018"), ge=0, le=Decimal("0.20")
    )
    slippage_ratio: Decimal = Field(
        default=Decimal("0.001"), ge=0, le=Decimal("0.20")
    )


@router.post("/walk-forward")
def run_walk_forward_validation(
    request: WalkForwardRequest,
    _: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        result = WalkForwardValidationService(session).run(
            exchange_code=request.exchange_code,
            symbol=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            train_months=request.train_months,
            test_months=request.test_months,
            short_windows=request.short_windows,
            long_windows=request.long_windows,
            stop_loss_ratios=request.stop_loss_ratios,
            take_profit_ratios=request.take_profit_ratios,
            position_ratios=request.position_ratios,
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
        "report_text": WalkForwardReportBuilder.build(result),
    }


class PortfolioAssetRequest(BaseModel):
    exchange_code: str = Field(min_length=1, max_length=20)
    symbol: str = Field(min_length=1, max_length=30)
    weight: Decimal = Field(gt=0, le=1)


class PortfolioBacktestRequest(BaseModel):
    assets: list[PortfolioAssetRequest] = Field(min_length=1, max_length=50)
    start_date: date
    end_date: date
    initial_capital: Decimal = Field(gt=0)
    short_window: int = Field(default=5, ge=2, le=200)
    long_window: int = Field(default=20, ge=3, le=500)
    stop_loss_ratio: Decimal = Field(default=Decimal("0.05"), gt=0, le=1)
    take_profit_ratio: Decimal = Field(default=Decimal("0.10"), gt=0, le=1)
    fee_ratio: Decimal = Field(
        default=Decimal("0.00015"), ge=0, le=Decimal("0.20")
    )
    sell_tax_ratio: Decimal = Field(
        default=Decimal("0.0018"), ge=0, le=Decimal("0.20")
    )
    slippage_ratio: Decimal = Field(
        default=Decimal("0.001"), ge=0, le=Decimal("0.20")
    )


@router.post("/portfolio")
def run_portfolio_backtest(
    request: PortfolioBacktestRequest,
    _: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        result = PortfolioBacktestService(session).run(
            assets=[
                PortfolioBacktestAsset(
                    asset.exchange_code, asset.symbol, asset.weight
                )
                for asset in request.assets
            ],
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            short_window=request.short_window,
            long_window=request.long_window,
            stop_loss_ratio=request.stop_loss_ratio,
            take_profit_ratio=request.take_profit_ratio,
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
        "start_date": result.start_date,
        "end_date": result.end_date,
        "summary": result.summary,
        "assets": result.assets,
        "equity_curve": result.equity_curve,
        "failures": result.failures,
        "report_text": PortfolioBacktestReportBuilder.build(result),
    }
