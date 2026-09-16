"""Admin development work history — READ ONLY."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.operation.ai_development_work_history_service import (
    DevelopmentWorkHistoryService,
)

router = APIRouter(
    prefix="/api/v1/admin/development-work-history",
    tags=["Admin Development Work History"],
    dependencies=[Depends(require_admin)],
)


@router.get("")
def list_development_work_history(
    project_code: str | None = Query(default="stock-platform"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    svc = DevelopmentWorkHistoryService(session)
    items = svc.list_recent_work(project_code=project_code, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/related")
def find_related_development_work(
    dedupe_key: str | None = Query(default=None),
    work_type: str | None = Query(default=None),
    keywords: str | None = Query(default=None),
    result_commit: str | None = Query(default=None),
    project_code: str = Query(default="stock-platform"),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    svc = DevelopmentWorkHistoryService(session)
    items = svc.find_related_work(
        project_code=project_code,
        work_type=work_type,
        dedupe_key=dedupe_key,
        keywords=keywords,
        result_commit=result_commit,
    )
    dup = svc.find_duplicate_work(
        project_code=project_code,
        work_type=work_type or "",
        dedupe_key=dedupe_key,
    )
    return {"items": items, "duplicate_verdict": dup}


@router.get("/{work_id}")
def get_development_work_history(
    work_id: str,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
) -> dict[str, Any]:
    svc = DevelopmentWorkHistoryService(session)
    row = svc.get_work(work_id)
    if row is None:
        raise HTTPException(status_code=404, detail="work_id not found")
    return row
