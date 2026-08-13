"""Admin — Historical test AMBIGUOUS outbox 안전 정리."""

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
from stock_platform.order.historical_test_outbox_resolution_service import (
    APPROVAL_PHRASE,
    AUDIT_EVENT,
    HistoricalTestOutboxResolutionError,
    HistoricalTestOutboxResolutionService,
)

admin_router = APIRouter(
    prefix="/api/v1/admin/orders/historical-test-outbox",
    tags=["Admin Historical Test Outbox Resolution"],
    dependencies=[Depends(require_admin)],
)


class ResolveHistoricalTestOutboxBody(BaseModel):
    outbox_id: int
    order_id: int
    fingerprint: str = Field(min_length=16, max_length=128)
    approval_phrase: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


@admin_router.get("/{outbox_id}/preview")
def preview_historical_test_outbox(
    outbox_id: int,
    order_id: int,
    session: Session = Depends(get_db_session),
):
    """상태 변경 없이 테스트 fixture 정리 가능 여부·fingerprint만 조회."""

    preview = HistoricalTestOutboxResolutionService(session).preview(
        outbox_id=int(outbox_id),
        order_id=int(order_id),
    )
    data = preview.as_dict()
    data["approval_phrase_hint"] = APPROVAL_PHRASE
    return data


@admin_router.post("/resolve")
def resolve_historical_test_outbox(
    body: ResolveHistoricalTestOutboxBody,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """payload.test fixture AMBIGUOUS → FAILED (일반 AMBIGUOUS 게이트 미완화)."""

    service = HistoricalTestOutboxResolutionService(session)
    try:
        result = service.resolve(
            outbox_id=int(body.outbox_id),
            order_id=int(body.order_id),
            approval_phrase=body.approval_phrase,
            fingerprint=body.fingerprint,
            actor=user.username,
            reason=body.reason,
        )
        session.commit()
    except HistoricalTestOutboxResolutionError as exc:
        session.rollback()
        status_code = (
            status.HTTP_409_CONFLICT
            if exc.http_status == 409
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
                "blockers": exc.blockers,
            },
        ) from exc

    audit.record(
        event_type=AUDIT_EVENT,
        actor=user.username,
        order_id=int(body.order_id),
        detail={
            "outbox_id": result.get("outbox_id"),
            "order_id": result.get("order_id"),
            "resolution": result.get("resolution"),
            "reason_code": result.get("reason_code"),
            "idempotent": result.get("idempotent"),
            "code": result.get("code"),
            "payload_test": True,
            "broker_api_calls": 0,
            "create_order_calls": 0,
        },
    )
    return result
