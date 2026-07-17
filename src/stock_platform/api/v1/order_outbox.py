from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.database.session import (
    get_db_session,
)
from stock_platform.order.outbox_entities import (
    OrderOutbox,
)
from stock_platform.order.outbox_repository import (
    OrderOutboxRepository,
)


router = APIRouter(
    prefix="/api/v1/order-outbox",
    tags=["Order Outbox"],
)


class RetryOutboxRequest(BaseModel):
    outbox_id: int


@router.get("")
def list_outbox(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_db_session),
) -> list[dict[str, Any]]:
    stmt = (
        select(OrderOutbox)
        .order_by(OrderOutbox.outbox_id.desc())
        .limit(limit)
    )

    if status:
        stmt = stmt.where(
            OrderOutbox.status_code
            == status.upper()
        )

    rows = list(session.scalars(stmt))
    return [
        {
            "outbox_id": row.outbox_id,
            "order_id": row.order_id,
            "event_type": row.event_type,
            "status_code": row.status_code,
            "retry_count": row.retry_count,
            "max_retry_count": (
                row.max_retry_count
            ),
            "next_retry_at": row.next_retry_at,
            "last_error": row.last_error,
            "created_at": row.created_at,
            "processed_at": row.processed_at,
        }
        for row in rows
    ]


@router.post("/retry")
def retry_outbox(
    request: RetryOutboxRequest,
    session: Session = Depends(get_db_session),
):
    try:
        entity = OrderOutboxRepository(
            session
        ).retry_failed(
            outbox_id=request.outbox_id
        )
        session.commit()
        session.refresh(entity)
        return entity
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
