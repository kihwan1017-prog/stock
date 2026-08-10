"""Admin — 미전송 LIVE/PAPER 주문 내부 폐기 (브로커 API 0회)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.order.unsubmitted_live_order_retire_service import (
    UnsubmittedLiveOrderRetireError,
    UnsubmittedLiveOrderRetireService,
)

admin_router = APIRouter(
    prefix="/api/v1/admin/orders",
    tags=["Admin Unsubmitted Order Retire"],
    dependencies=[Depends(require_admin)],
)


class RetireUnsubmittedBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


@admin_router.get("/{order_id}/retire-unsubmitted/preview")
def preview_retire_unsubmitted(
    order_id: int,
    session: Session = Depends(get_db_session),
):
    """실제 상태 변경 없이 폐기 가능 여부만 조회."""

    preview = UnsubmittedLiveOrderRetireService(session).preview(
        int(order_id)
    )
    return preview.as_dict()


@admin_router.post("/{order_id}/retire-unsubmitted")
def retire_unsubmitted(
    order_id: int,
    body: RetireUnsubmittedBody,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """브로커 미전송 LIVE/PAPER PENDING + Outbox만 내부 종결.

    adapter / dispatcher / Upbit API 호출 금지.
    """

    service = UnsubmittedLiveOrderRetireService(session)
    try:
        result = service.retire(
            int(order_id),
            reason=body.reason,
            actor=user.username,
        )
        session.commit()
    except UnsubmittedLiveOrderRetireError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": exc.message, "blockers": exc.blockers},
        ) from exc
    except LookupError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    audit.record(
        event_type="ADMIN_UNSUBMITTED_ORDER_RETIRE",
        actor=user.username,
        order_id=int(order_id),
        detail={
            "order_id": result.get("order_id"),
            "outbox_id": result.get("outbox_id"),
            "idempotent": result.get("idempotent"),
            "broker_api_calls": 0,
        },
    )
    return result
