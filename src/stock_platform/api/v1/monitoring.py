"""STEP61 — Monitoring & Observability API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_platform.auth.deps import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.operation.audit_repository import (
    AuditEventRepository,
)
from stock_platform.operation.monitoring_snapshot import (
    build_monitoring_overview,
    evaluate_alert_rules,
)


router = APIRouter(
    prefix="/api/v1/monitoring",
    tags=["Monitoring"],
    dependencies=[Depends(require_admin)],
)


@router.get("/overview")
async def monitoring_overview(
    session: Session = Depends(get_db_session),
    evaluate_alerts: bool = Query(
        default=True,
        description="Alert 규칙 평가·Audit 기록 여부",
    ),
    refresh: bool = Query(
        default=False,
        description="캐시 무시하고 재집계",
    ),
) -> dict[str, Any]:
    return await build_monitoring_overview(
        session,
        evaluate_alerts=evaluate_alerts,
        use_cache=not refresh,
    )


@router.get("/alerts")
def monitoring_alerts(
    session: Session = Depends(get_db_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Audit 에 저장된 MONITORING_ALERT 최근 목록."""

    repo = AuditEventRepository(session)
    # event_type 정확 매칭만 지원 → prefix 수동 필터
    recent = repo.list_recent(limit=min(limit * 3, 200))
    items = [
        {
            "audit_event_id": row.audit_event_id,
            "event_type": row.event_type,
            "actor": row.actor,
            "detail": row.detail,
            "created_at": row.created_at,
        }
        for row in recent
        if str(row.event_type).startswith("MONITORING_ALERT")
    ][:limit]
    return {"items": items, "limit": limit}


@router.post("/alerts/evaluate")
async def monitoring_alerts_evaluate(
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """즉시 Alert 규칙 평가 (캐시 무시)."""

    snapshot = await build_monitoring_overview(
        session,
        evaluate_alerts=False,
        use_cache=False,
    )
    fired = evaluate_alert_rules(
        snapshot,
        session=session,
        dispatch=True,
    )
    return {
        "status": snapshot.get("status"),
        "fired": fired,
        "count": len(fired),
    }
