"""STEP 10-3 — Admin Operations Center Dashboard Summary API (Read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.operation.operations_center_dashboard_service import (
    OperationsCenterDashboardService,
)

router = APIRouter(
    prefix="/api/v1/admin/dashboard",
    tags=["Admin Operations Center"],
    dependencies=[Depends(require_admin)],
)


@router.get("/summary")
def get_operations_center_summary(
    cache_ttl_sec: float = Query(default=3.0, ge=0.0, le=30.0),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """운영 통합 Dashboard — 조회 전용 (Mutation 없음)."""

    return OperationsCenterDashboardService(session).summary(
        cache_ttl_sec=cache_ttl_sec
    )
