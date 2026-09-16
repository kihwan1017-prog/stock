"""Admin cross-market shadow research status — READ ONLY.

Prefix: /api/v1/admin/autotrading/research
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.operation.autotrading_research.status import (
    build_cross_market_research_status,
    build_kiwoom_research_status,
    build_upbit_research_status,
)

router = APIRouter(
    prefix="/api/v1/admin/autotrading/research",
    tags=["Admin Autotrading Research"],
    dependencies=[Depends(require_admin)],
)


@router.get("/status")
def get_autotrading_research_status(
    market: str | None = Query(
        default=None, description="UPBIT | KIWOOM | omit for both"
    ),
    upbit_uba_id: int = Query(default=1380, ge=1),
    kiwoom_uba_id: int | None = Query(default=1381, ge=1),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    m = (market or "").strip().upper()
    if m == "UPBIT":
        return build_upbit_research_status(
            session, user_broker_account_id=int(upbit_uba_id)
        )
    if m == "KIWOOM":
        return build_kiwoom_research_status(
            session, user_broker_account_id=int(kiwoom_uba_id or 1381)
        )
    return build_cross_market_research_status(
        session,
        upbit_uba_id=int(upbit_uba_id),
        kiwoom_uba_id=int(kiwoom_uba_id) if kiwoom_uba_id else None,
    )
