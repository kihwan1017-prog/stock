from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from stock_platform.api.deps_admin import require_admin
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.database.session import get_db_session
from stock_platform.strategy_deployment.switch_service import (
    SafeStrategyRuntimeSwitchService,
)


router = APIRouter(
    prefix="/api/v1/strategy-runtime-switch",
    tags=["Strategy Runtime Switch"],
    dependencies=[Depends(require_admin)],
)


class StrategyRuntimeSwitchRequest(BaseModel):
    target_deployment_id: int = Field(gt=0)
    requested_by: str = Field(
        min_length=1,
        max_length=100,
    )
    scope_key: str = Field(
        min_length=1,
        max_length=500,
        description="STEP 8-5-5 — 대상 Runtime Scope (필수)",
    )
    sample_context: dict[str, Any] = {}


@router.post("")
async def switch_strategy_runtime(
    request: StrategyRuntimeSwitchRequest,
    session: Session = Depends(get_db_session),
):
    try:
        return await SafeStrategyRuntimeSwitchService(
            session
        ).switch(
            target_deployment_id=(
                request.target_deployment_id
            ),
            requested_by=request.requested_by,
            sample_context=request.sample_context,
            scope_key=request.scope_key,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
