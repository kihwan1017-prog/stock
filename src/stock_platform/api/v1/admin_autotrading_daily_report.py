"""Admin autotrading daily operation report — READ ONLY."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.operation.autotrading_daily_report_service import (
    build_autotrading_daily_report,
)

router = APIRouter(
    prefix="/api/v1/admin/autotrading",
    tags=["Admin Autotrading Daily Report"],
    dependencies=[Depends(require_admin)],
)


@router.get("/daily-report")
def get_autotrading_daily_report(
    date_param: str | None = Query(
        default=None,
        alias="date",
        description="YYYY-MM-DD (KST calendar day)",
    ),
    market: Literal["ALL", "UPBIT", "KIWOOM"] = Query(default="ALL"),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    """일일 자동매매 운영보고 — REAL decision / mutation 없음."""

    report_date: date | None = None
    if date_param:
        report_date = date.fromisoformat(str(date_param).strip()[:10])
    return build_autotrading_daily_report(
        session,
        report_date=report_date,
        market=market,
    )
