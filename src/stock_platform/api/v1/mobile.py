# -*- coding: utf-8 -*-
"""Mobile PWA V1 — READ-ONLY API.

GET only. LIVE/ARM/주문/설정 mutation 엔드포인트 없음.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.operation.mobile_overview_service import (
    get_mobile_overview_cached,
)

router = APIRouter(
    prefix="/api/v1/mobile",
    tags=["Mobile Read-Only"],
    dependencies=[Depends(require_admin)],
)


@router.get("/overview")
def get_mobile_overview(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """모바일 홈 집계 — 조회 전용. Cache TTL ~8s."""

    return get_mobile_overview_cached(session)


@router.get("/health")
def get_mobile_api_health(
    _: AuthenticatedUser = Depends(require_admin),
):
    """모바일 API 생존 확인 — mutation 없음."""

    return {
        "status": "UP",
        "read_only": True,
        "write_methods": [],
    }
