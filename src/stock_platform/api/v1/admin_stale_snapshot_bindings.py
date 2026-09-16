"""Admin — Stale ACTIVE snapshot binding 승인형 RETIRE."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.broker.stale_snapshot_binding_retire_service import (
    APPROVAL_PHRASE,
    AUDIT_EVENT,
    StaleSnapshotBindingRetireError,
    StaleSnapshotBindingRetireService,
)
from stock_platform.database.session import get_db_session

admin_router = APIRouter(
    prefix="/api/v1/admin/broker-snapshots/stale-bindings",
    tags=["Admin Stale Snapshot Binding Retire"],
    dependencies=[Depends(require_admin)],
)


class PreviewBody(BaseModel):
    snapshot_ids: list[int] = Field(min_length=1, max_length=50)


class ApplyBody(BaseModel):
    snapshot_ids: list[int] = Field(min_length=1, max_length=50)
    fingerprint: str = Field(min_length=16, max_length=128)
    approval_phrase: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=2000)


@admin_router.post("/preview")
def preview_stale_snapshot_bindings(
    body: PreviewBody,
    session: Session = Depends(get_db_session),
):
    """READ ONLY — SAFE_STALE_HISTORY 여부·fingerprint만 반환."""

    preview = StaleSnapshotBindingRetireService(session).preview(
        list(body.snapshot_ids)
    )
    data = preview.as_dict()
    data["approval_phrase_hint"] = APPROVAL_PHRASE
    return data


@admin_router.post("/retire")
def retire_stale_snapshot_bindings(
    body: ApplyBody,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """승인 phrase + fingerprint 일치 시에만 ACTIVE → RETIRED."""

    service = StaleSnapshotBindingRetireService(session)
    try:
        result = service.apply(
            snapshot_ids=list(body.snapshot_ids),
            approval_phrase=body.approval_phrase,
            fingerprint=body.fingerprint,
            actor=admin_actor_label(user),
            reason=body.reason,
        )
        # Audit 을 동일 트랜잭션에 묶음 (중복 apply 시 audit_events=0)
        for payload in result.get("audit_payloads") or []:
            audit.record(
                event_type=AUDIT_EVENT,
                actor=admin_actor_label(user),
                detail=payload,
                auto_commit=False,
            )
        session.commit()
    except StaleSnapshotBindingRetireError as exc:
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
                "mutation": exc.mutation,
            },
        ) from exc

    # 응답에서 내부 audit_payloads 는 축소
    out = dict(result)
    out.pop("audit_payloads", None)
    return out
