from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.operation.audit_repository import (
    AuditEventRepository,
)


router = APIRouter(
    prefix="/api/v1/audit",
    tags=["Audit"],
)


@router.get("/events")
def list_audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    event_type: str | None = None,
    _: str = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    rows = AuditEventRepository(session).list_recent(
        limit=limit,
        event_type=event_type,
    )
    return {
        "items": rows,
        "limit": limit,
    }
