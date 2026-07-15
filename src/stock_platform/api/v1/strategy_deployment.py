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
from stock_platform.strategy_deployment.models import (
    StrategyDeploymentMode,
    StrategyDeploymentRequest,
)
from stock_platform.strategy_deployment.repository import (
    StrategyDeploymentRepository,
)
from stock_platform.strategy_deployment.service import (
    PaperStrategyDeploymentService,
)


router = APIRouter(
    prefix="/api/v1/strategy-deployments",
    tags=["Strategy Deployments"],
)


class StrategyDeploymentCreateRequest(BaseModel):
    strategy_code: str = Field(
        min_length=1,
        max_length=100,
    )
    strategy_performance_run_id: int = Field(gt=0)
    market_code: str = Field(
        min_length=1,
        max_length=30,
    )
    symbol: str | None = Field(
        default=None,
        max_length=30,
    )
    mode: StrategyDeploymentMode = (
        StrategyDeploymentMode.PAPER
    )
    parameter_payload: dict[str, Any] = {}
    requested_by: str = Field(
        min_length=1,
        max_length=100,
    )


class StrategyDeploymentStopRequest(BaseModel):
    actor: str = Field(
        min_length=1,
        max_length=100,
    )
    reason: str = Field(
        min_length=1,
        max_length=500,
    )


@router.post("")
def deploy_strategy(
    request: StrategyDeploymentCreateRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return PaperStrategyDeploymentService(
            session
        ).deploy(
            StrategyDeploymentRequest(
                strategy_code=request.strategy_code,
                strategy_performance_run_id=(
                    request
                    .strategy_performance_run_id
                ),
                market_code=request.market_code,
                symbol=request.symbol,
                mode=request.mode,
                parameter_payload=(
                    request.parameter_payload
                ),
                requested_by=request.requested_by,
            )
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (
        ValueError,
        PermissionError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{deployment_id}/stop")
def stop_strategy_deployment(
    deployment_id: int,
    request: StrategyDeploymentStopRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return PaperStrategyDeploymentService(
            session
        ).stop(
            deployment_id=deployment_id,
            actor=request.actor,
            reason=request.reason,
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


@router.get("/active")
def get_active_strategy_deployment(
    market_code: str,
    mode: StrategyDeploymentMode = (
        StrategyDeploymentMode.PAPER
    ),
    symbol: str | None = None,
    session: Session = Depends(get_db_session),
):
    return StrategyDeploymentRepository(
        session
    ).get_active(
        market_code=market_code,
        symbol=symbol,
        mode_code=mode.value,
    )
