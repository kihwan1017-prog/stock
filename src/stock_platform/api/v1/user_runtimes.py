"""STEP 8-5-5 — USER Strategy Runtime 조회 (본인만)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.strategy_deployment.runtime_manager import (
    dynamic_strategy_runtime_manager,
)


router = APIRouter(
    prefix="/api/v1/user/runtimes",
    tags=["User Strategy Runtimes"],
)


@router.get("")
def list_my_runtimes(
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
):
    entries = dynamic_strategy_runtime_manager.list_entries(
        user_id=int(user.user_id)
    )
    return {
        "items": [e.as_dict() for e in entries],
        "total": len(entries),
    }


@router.get("/{scope_key:path}")
def get_my_runtime(
    scope_key: str,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
):
    entry = dynamic_strategy_runtime_manager.get_entry(scope_key)
    if entry is None or entry.scope.user_id != int(user.user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runtime not found",
        )
    return entry.as_dict()
