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

@router.get("/autotrading-performance")
def get_autotrading_performance(
    broker: str = Query(default="ALL", pattern="^(ALL|UPBIT|KIWOOM)$"),
    period: str = Query(default="30D", pattern="^(TODAY|7D|30D|90D|ALL)$"),
    include_ops: bool = Query(default=False),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """AUTO strategy-owned 성과 집계 — Read-only, MANUAL/계좌전체 PnL 제외."""

    from stock_platform.operation.autotrading_performance_service import (
        AutotradingPerformanceService,
    )

    return AutotradingPerformanceService(session).build(
        broker=broker,  # type: ignore[arg-type]
        period=period,  # type: ignore[arg-type]
        include_ops=include_ops,
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

