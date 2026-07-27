"""STEP 8-11 — Admin 통합 운영 모니터링 Dashboard API (Read-only)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.operation.ops_monitoring.service import (
    OpsMonitoringDashboardService,
)


router = APIRouter(
    prefix="/api/v1/admin/operations-dashboard",
    tags=["Admin Operations Dashboard"],
    dependencies=[Depends(require_admin)],
)


def _svc(session: Session) -> OpsMonitoringDashboardService:
    return OpsMonitoringDashboardService(session)


@router.get("/overview")
def get_overview(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return _svc(session).overview()


@router.get("/accounts")
def get_accounts(
    include_broker_balances: bool = Query(default=True),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return _svc(session).accounts(
        include_broker_balances=include_broker_balances
    )


@router.get("/schedulers")
def get_schedulers(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return _svc(session).schedulers()


@router.get("/runtimes")
def get_runtimes(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return _svc(session).runtimes()


@router.get("/risk")
def get_risk(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return _svc(session).risk()


@router.get("/orders")
def get_orders(
    status_code: str | None = Query(default=None, alias="status"),
    broker_code: str | None = None,
    user_broker_account_id: int | None = None,
    market: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="created_at"),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    try:
        return _svc(session).orders(
            status=status_code,
            broker_code=broker_code,
            user_broker_account_id=user_broker_account_id,
            market=market,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
            sort=sort,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/positions")
def get_positions(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return _svc(session).positions()


@router.get("/alerts")
def get_alerts(
    limit: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return _svc(session).alerts(limit=limit)


@router.get("/audits")
def get_audits(
    event_type: str | None = None,
    actor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return _svc(session).audits(
        event_type=event_type, actor=actor, limit=limit
    )


@router.get("/notifications")
def get_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return _svc(session).notifications(limit=limit)
