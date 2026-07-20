from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import (
    get_db_session,
)
from stock_platform.api.deps_admin import require_admin
from stock_platform.strategy_deployment.pipeline_repository import (
    StrategyDeploymentPipelineRepository,
)
from stock_platform.strategy_deployment.pipeline_runtime import (
    strategy_deployment_pipeline_manager,
)


router = APIRouter(
    prefix="/api/v1/strategy-deployment-pipeline",
    tags=["Strategy Deployment Pipeline"],
    dependencies=[Depends(require_admin)],
)


class StrategyDeploymentPipelineRequest(BaseModel):
    market_code: str = Field(
        min_length=1,
        max_length=30,
    )
    symbol: str | None = Field(
        default=None,
        max_length=30,
    )
    requested_by: str = Field(
        default="operator",
        min_length=1,
        max_length=100,
    )
    sample_context: dict[str, Any] = {}
    allow_auto_deploy: bool = False


@router.post("/run")
async def run_strategy_deployment_pipeline(
    request: StrategyDeploymentPipelineRequest,
):
    try:
        return await (
            strategy_deployment_pipeline_manager.run(
                market_code=request.market_code,
                symbol=request.symbol,
                requested_by=request.requested_by,
                sample_context=request.sample_context,
                allow_auto_deploy=(
                    request.allow_auto_deploy
                ),
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/status")
def get_strategy_deployment_pipeline_status():
    return strategy_deployment_pipeline_manager.status()


@router.get("/history")
def get_strategy_deployment_pipeline_history(
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    session: Session = Depends(get_db_session),
):
    return StrategyDeploymentPipelineRepository(
        session
    ).history(limit=limit)
