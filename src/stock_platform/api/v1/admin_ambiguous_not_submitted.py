"""Admin — AMBIGUOUS CONFIRMED_NOT_SUBMITTED resolution."""

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
from stock_platform.order.ambiguous_not_submitted_resolution_service import (
    ADMIN_AUDIT,
    AmbiguousNotSubmittedResolutionError,
    AmbiguousNotSubmittedResolutionService,
)
from stock_platform.order.unsubmitted_live_order_retire_service import (
    UnsubmittedLiveOrderRetireError,
    UnsubmittedLiveOrderRetireService,
)

admin_router = APIRouter(
    prefix="/api/v1/admin/orders",
    tags=["Admin Ambiguous Not-Submitted Resolution"],
    dependencies=[Depends(require_admin)],
)


class ResolveNotSubmittedBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


@admin_router.get("/{order_id}/resolve-not-submitted/preview")
def preview_resolve_not_submitted(
    order_id: int,
    session: Session = Depends(get_db_session),
):
    """상태 변경 없이 CONFIRMED_NOT_SUBMITTED 가능 여부만 조회.

    일반 retire preview와 독립 — AMBIGUOUS는 여기서만 후보.
    """

    preview = AmbiguousNotSubmittedResolutionService(session).preview(
        int(order_id)
    )
    # 참고: 일반 retire는 계속 차단되는지 함께 표시
    regular = UnsubmittedLiveOrderRetireService(session).preview(
        int(order_id)
    )
    data = preview.as_dict()
    data["regular_retire_blocked"] = not regular.retirable
    data["regular_retire_blockers"] = list(regular.blockers)
    return data


@admin_router.post("/{order_id}/resolve-not-submitted")
def resolve_not_submitted(
    order_id: int,
    body: ResolveNotSubmittedBody,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """AMBIGUOUS + pre-send local failure → Upbit READ-ONLY 재검증 → retire.

    일반 retire API 게이트는 완화하지 않는다.
    POST /v1/orders · create_order 금지.
    """

    service = AmbiguousNotSubmittedResolutionService(session)
    try:
        result = service.resolve_and_retire(
            int(order_id),
            reason=body.reason,
            actor=user.username,
            skip_broker_lookup=False,
        )
        session.commit()
    except AmbiguousNotSubmittedResolutionError as exc:
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
    except UnsubmittedLiveOrderRetireError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": exc.code,
                "message": exc.message,
                "blockers": exc.blockers,
            },
        ) from exc

    audit.record(
        event_type=ADMIN_AUDIT,
        actor=user.username,
        order_id=int(order_id),
        detail={
            "order_id": result.get("order_id"),
            "outbox_id": result.get("outbox_id"),
            "resolution": result.get("resolution"),
            "reason_code": result.get("reason_code"),
            "idempotent": result.get("idempotent"),
            "identifier": result.get("identifier"),
            "broker_api_calls": 0,
            "create_order_calls": 0,
        },
    )
    return result
