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
from stock_platform.strategy_deployment.automation_service import (
    StrategyAutoDeploymentService,
)
from stock_platform.strategy_deployment.policy_repository import (
    StrategyApprovalRepository,
)


router = APIRouter(
    prefix="/api/v1/strategy-policy",
    tags=["Strategy Approval Policy"],
)


class EvaluateStrategyPolicyRequest(BaseModel):
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
    auto_deploy: bool = False


class StrategyPolicyActionRequest(BaseModel):
    actor: str = Field(
        min_length=1,
        max_length=100,
    )
    reason: str = Field(
        default="manual action",
        min_length=1,
        max_length=500,
    )


@router.post("/evaluate")
def evaluate_strategy_policy(
    request: EvaluateStrategyPolicyRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return StrategyAutoDeploymentService(
            session=session
        ).evaluate_latest(
            market_code=request.market_code,
            symbol=request.symbol,
            requested_by=request.requested_by,
            auto_deploy=request.auto_deploy,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/{approval_run_id}/force")
def force_strategy_deployment(
    approval_run_id: int,
    request: StrategyPolicyActionRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return StrategyAutoDeploymentService(
            session=session
        ).force_deploy(
            approval_run_id=approval_run_id,
            actor=request.actor,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/{approval_run_id}/reject")
def reject_strategy_policy(
    approval_run_id: int,
    request: StrategyPolicyActionRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return StrategyAutoDeploymentService(
            session=session
        ).reject(
            approval_run_id=approval_run_id,
            actor=request.actor,
            reason=request.reason,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/history")
def get_strategy_policy_history(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
):
    return StrategyApprovalRepository(
        session
    ).history(limit=limit)
