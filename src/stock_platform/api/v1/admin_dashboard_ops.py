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
    start_date: str | None = Query(default=None, description="KST YYYY-MM-DD inclusive"),
    end_date: str | None = Query(default=None, description="KST YYYY-MM-DD inclusive"),
    user_broker_account_id: int | None = Query(default=None, ge=1),
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
        start_date=start_date,
        end_date=end_date,
        user_broker_account_id=user_broker_account_id,
    )


@router.get("/autotrading-symbol-performance")
def get_autotrading_symbol_performance(
    broker: str = Query(default="UPBIT", pattern="^(ALL|UPBIT|KIWOOM)$"),
    period: str = Query(default="TODAY", pattern="^(TODAY|7D|30D|90D|ALL)$"),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    user_broker_account_id: int | None = Query(default=None, ge=1),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """종목별 AUTO 성과 aggregate — performance API의 symbol slice."""

    from stock_platform.operation.autotrading_performance_service import (
        AutotradingPerformanceService,
    )

    payload = AutotradingPerformanceService(session).build(
        broker=broker,  # type: ignore[arg-type]
        period=period,  # type: ignore[arg-type]
        start_date=start_date,
        end_date=end_date,
        user_broker_account_id=user_broker_account_id,
    )
    return {
        "period": payload.get("period_window") or {"period": payload.get("period")},
        "totals": payload.get("symbol_performance_totals") or {},
        "symbols": payload.get("symbol_performance") or [],
        "inclusion_rule": payload.get("inclusion_rule"),
        "exclusion_rule": payload.get("exclusion_rule"),
    }


@router.get("/autotrading-symbol-detail")
def get_autotrading_symbol_detail(
    symbol: str = Query(..., min_length=1),
    broker: str = Query(default="UPBIT", pattern="^(ALL|UPBIT|KIWOOM)$"),
    period: str = Query(default="TODAY", pattern="^(TODAY|7D|30D|90D|ALL)$"),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    user_broker_account_id: int | None = Query(default=None, ge=1),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """종목 Drawer — 일별/건별 AUTO 거래 상세 (조회 전용)."""

    from stock_platform.operation.autotrading_performance_service import (
        AutotradingPerformanceService,
    )

    return AutotradingPerformanceService(session).build_symbol_detail(
        symbol=symbol,
        broker=broker,  # type: ignore[arg-type]
        period=period,  # type: ignore[arg-type]
        start_date=start_date,
        end_date=end_date,
        user_broker_account_id=user_broker_account_id,
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
