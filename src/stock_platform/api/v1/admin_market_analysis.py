"""Admin Market Analysis — user-facing summary (projection only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.markets.user_friendly_reasons import friendly_reason
from stock_platform.markets.market_analysis_summary_service import (
    MarketAnalysisSummaryService,
)


router = APIRouter(
    prefix="/api/v1/admin/market-analysis",
    tags=["admin-market-analysis"],
    dependencies=[Depends(require_admin)],
)


@router.get("/summary")
def market_analysis_summary(
    session: Session = Depends(get_db_session),
):
    """시장 분석 사용자 Summary — REAL trading gate 아님."""

    return MarketAnalysisSummaryService(session).summary()


@router.get("/reason")
def map_reason(
    code: str = Query(...),
):
    return {"code": code, "message_ko": friendly_reason(code)}
