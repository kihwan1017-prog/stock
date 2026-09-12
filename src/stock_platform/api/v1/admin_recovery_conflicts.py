"""STEP 8-5-4 — ADMIN Recovery Conflict API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.broker.recovery_conflict_service import (
    BrokerRecoveryConflictService,
    RecoveryConflictError,
)
from stock_platform.database.session import get_db_session
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)


router = APIRouter(
    prefix="/api/v1/admin/recovery",
    tags=["Admin Recovery Conflicts"],
    dependencies=[Depends(require_admin)],
)


class NoteBody(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class ApproveBody(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ResumeBody(BaseModel):
    """STEP 8-15A — Pause 해제는 명시 reason·correlation_id 필수."""

    reason: str = Field(min_length=1, max_length=2000)
    correlation_id: str = Field(min_length=1, max_length=128)


class ResolveSelectedBody(BaseModel):
    conflict_ids: list[int] = Field(min_length=1, max_length=200)
    resolution: str = Field(min_length=1, max_length=60)
    reason: str = Field(min_length=1, max_length=2000)
    expected_status: str | None = Field(default=None, max_length=40)


class ResolveOneBody(BaseModel):
    resolution: str = Field(min_length=1, max_length=60)
    reason: str = Field(min_length=1, max_length=2000)
    expected_status: str | None = Field(default=None, max_length=40)


def _http(exc: RecoveryConflictError) -> HTTPException:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "conflict_not_found":
        code = status.HTTP_404_NOT_FOUND
    elif exc.code == "upbit_rate_limited":
        code = status.HTTP_429_TOO_MANY_REQUESTS
    elif exc.code == "upbit_blocked_418":
        code = status.HTTP_423_LOCKED
    elif exc.code == "upbit_temporary_unavailable":
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif exc.code in {
        "unresolved_conflicts",
        "already_resolved",
        "kill_switch_active",
        "recovery_running",
        "duplicate_internal_order",
        "db_open_orders",
        "submission_unknown",
        "cancel_pending",
        "replace_pending",
        "resume_blocked",
        "resolve_ineligible",
        "bulk_clear_disabled",
        "execute_disabled",
        "uba_mismatch",
        "status_mismatch",
        "EXECUTED_VOLUME_EXISTS",
        "REMOTE_ORDER_OPEN",
        "REMOTE_NOT_CANCEL",
        "LOCAL_ORDER_LINKED",
        "DUPLICATE_ACTIVE_UUID",
        "USE_APPROVE_IMPORT_API",
    }:
        code = status.HTTP_409_CONFLICT
    elif exc.code in {
        "reason_required",
        "correlation_id_required",
        "invalid_resolution",
        "note_required",
    }:
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    detail: dict = {"code": exc.code, "message": exc.message}
    if getattr(exc, "detail", None):
        # Secret 없이 안전 필드만
        safe = {
            k: v
            for k, v in exc.detail.items()
            if k
            in {
                "retry_after_seconds",
                "cooldown_until",
                "http_status",
                "db_open",
                "submission_unknown",
                "cancel_pending",
                "replace_pending",
                "resumable",
                "blockers",
                "dry_run",
                "resume_check",
                "user_broker_account_id",
            }
        }
        detail.update(safe)
    return HTTPException(status_code=code, detail=detail)


@router.get("/conflicts")
def list_conflicts(
    broker_code: str | None = None,
    user_id: int | None = None,
    user_broker_account_id: int | None = None,
    review_status: str | None = None,
    conflict_type: str | None = None,
    market_code: str | None = None,
    resolved: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    svc = BrokerRecoveryConflictService(session)
    rows = svc.list_conflicts(
        broker_code=broker_code,
        user_id=user_id,
        user_broker_account_id=user_broker_account_id,
        review_status=review_status,
        conflict_type=conflict_type,
        market_code=market_code,
        resolved=resolved,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [svc.as_list_item(r) for r in rows],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
    }


@router.get("/conflicts/{conflict_id}")
def get_conflict(
    conflict_id: int,
    _: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    svc = BrokerRecoveryConflictService(session)
    try:
        row = svc.get(conflict_id)
    except RecoveryConflictError as exc:
        raise _http(exc) from exc
    return svc.as_detail(row)


@router.post("/conflicts/{conflict_id}/refresh")
def refresh_conflict(
    conflict_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    svc = BrokerRecoveryConflictService(session)
    try:
        before = svc.get(conflict_id)
        before_status = before.review_status
        row = svc.refresh_from_remote(
            conflict_id, actor=f"admin:{user.user_id}"
        )
        session.commit()
    except RecoveryConflictError as exc:
        session.rollback()
        raise _http(exc) from exc

    audit.record(
        event_type="RECOVERY_CONFLICT_REFRESH",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "conflict_id": conflict_id,
            "before_status": before_status,
            "after_status": row.review_status,
            "external_order_id_masked": row.external_order_id_masked,
            "user_broker_account_id": row.user_broker_account_id,
        },
    )
    return svc.as_detail(row)


@router.post("/conflicts/{conflict_id}/approve-import")
def approve_import(
    conflict_id: int,
    body: ApproveBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    svc = BrokerRecoveryConflictService(session)
    try:
        before = svc.get(conflict_id)
        before_status = before.review_status
        # Body의 주문 필드는 무시 — Conflict/원격 조회만 신뢰
        result = svc.approve_import(
            conflict_id,
            actor=f"admin:{user.user_id}",
            note=body.note,
        )
        session.commit()
    except RecoveryConflictError as exc:
        session.rollback()
        raise _http(exc) from exc

    audit.record(
        event_type="RECOVERY_CONFLICT_APPROVE_IMPORT",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        order_id=result.get("internal_order_id"),
        detail={
            "conflict_id": conflict_id,
            "before_status": before_status,
            "after_status": "APPROVED_IMPORT",
            "internal_order_id": result.get("internal_order_id"),
            "imported_fills": result.get("imported_fills"),
            "broker_submit": False,
            "note": body.note,
        },
    )
    return result


@router.post("/conflicts/{conflict_id}/ignore")
def ignore_conflict(
    conflict_id: int,
    body: NoteBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    svc = BrokerRecoveryConflictService(session)
    try:
        before = svc.get(conflict_id)
        before_status = before.review_status
        row = svc.ignore(
            conflict_id,
            actor=f"admin:{user.user_id}",
            note=body.note,
        )
        session.commit()
    except RecoveryConflictError as exc:
        session.rollback()
        raise _http(exc) from exc

    from datetime import datetime, timezone

    correlation_id = getattr(request.state, "request_id", None)
    occurred_at = datetime.now(timezone.utc).isoformat()
    audit.record(
        event_type="RECOVERY_CONFLICT_IGNORE",
        actor=f"admin:{user.user_id}",
        request_id=correlation_id,
        detail={
            "conflict_id": conflict_id,
            "before_status": before_status,
            "after_status": row.review_status,
            "remote_status": row.external_status,
            "executed_volume": (
                str(row.executed_quantity)
                if row.executed_quantity is not None
                else None
            ),
            "reason": body.note,
            "note": body.note,
            "correlation_id": correlation_id,
            "occurred_at": occurred_at,
            "user_broker_account_id": row.user_broker_account_id,
        },
    )
    return svc.as_list_item(row)


@router.post("/conflicts/{conflict_id}/preserve-history")
def preserve_history_conflict(
    conflict_id: int,
    body: NoteBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """HISTORY_PRESERVE — Import/Ignore 없이 검토 완료·이력 보존."""

    from datetime import datetime, timezone

    svc = BrokerRecoveryConflictService(session)
    try:
        before = svc.get(conflict_id)
        before_status = before.review_status
        row = svc.preserve_history(
            conflict_id,
            actor=f"admin:{user.user_id}",
            note=body.note,
        )
        session.commit()
    except RecoveryConflictError as exc:
        session.rollback()
        raise _http(exc) from exc

    correlation_id = getattr(request.state, "request_id", None)
    occurred_at = datetime.now(timezone.utc).isoformat()
    audit.record(
        event_type="RECOVERY_CONFLICT_HISTORY_PRESERVED",
        actor=f"admin:{user.user_id}",
        request_id=correlation_id,
        detail={
            "conflict_id": conflict_id,
            "before_status": before_status,
            "after_status": row.review_status,
            "broker_uuid_masked": row.external_order_id_masked,
            "reason": body.note,
            "correlation_id": correlation_id,
            "occurred_at": occurred_at,
            "user_broker_account_id": row.user_broker_account_id,
            "resolution_type": row.resolution_type,
        },
    )
    return svc.as_list_item(row)


@router.post("/conflicts/{conflict_id}/hold")
def hold_conflict(
    conflict_id: int,
    body: NoteBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    svc = BrokerRecoveryConflictService(session)
    try:
        before = svc.get(conflict_id)
        before_status = before.review_status
        row = svc.hold(
            conflict_id,
            actor=f"admin:{user.user_id}",
            note=body.note,
        )
        session.commit()
    except RecoveryConflictError as exc:
        session.rollback()
        raise _http(exc) from exc

    audit.record(
        event_type="RECOVERY_CONFLICT_HOLD",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "conflict_id": conflict_id,
            "before_status": before_status,
            "after_status": row.review_status,
            "note": body.note,
        },
    )
    return svc.as_list_item(row)


@router.post("/accounts/{uba_id}/resume")
def resume_uba_trading(
    uba_id: int,
    body: ResumeBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """Account Trading Pause 해제 — Admin 전용. Recovery는 이 API를 호출하지 않는다."""
    try:
        kill_active = bool(KillSwitchService(session).is_active())
    except Exception:  # noqa: BLE001 — fail-closed
        kill_active = True

    svc = BrokerRecoveryConflictService(session)
    try:
        result = svc.resume_account(
            uba_id,
            actor=f"admin:{user.user_id}",
            reason=body.reason,
            correlation_id=body.correlation_id,
            kill_switch_active=kill_active,
        )
        session.commit()
    except RecoveryConflictError as exc:
        session.rollback()
        audit.record(
            event_type="RECOVERY_ACCOUNT_RESUME_FAILED",
            actor=f"admin:{user.user_id}",
            request_id=getattr(request.state, "request_id", None),
            detail={
                "user_broker_account_id": uba_id,
                "code": exc.code,
                "correlation_id": body.correlation_id,
                "reason": body.reason[:200],
            },
        )
        raise _http(exc) from exc

    audit.record(
        event_type="RECOVERY_ACCOUNT_RESUME",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "trading_paused": False,
            "reason": body.reason,
            "correlation_id": body.correlation_id,
            "before_trading_paused": result.get(
                "before_trading_paused"
            ),
            "resumed": result.get("resumed"),
            "already_resumed": result.get("already_resumed"),
        },
    )
    return result


@router.post("/accounts/{uba_id}/clear-conflicts")
def clear_uba_conflicts(
    uba_id: int,
    body: NoteBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """Deprecated — 일괄 Ignore 사용 중단."""
    svc = BrokerRecoveryConflictService(session)
    try:
        result = svc.clear_active_conflicts_for_uba(
            uba_id,
            actor=f"admin:{user.user_id}",
            note=body.note,
        )
        session.commit()
    except RecoveryConflictError as exc:
        session.rollback()
        audit.record(
            event_type="RECOVERY_ACCOUNT_CLEAR_CONFLICTS_REJECTED",
            actor=f"admin:{user.user_id}",
            request_id=getattr(request.state, "request_id", None),
            detail={
                "user_broker_account_id": uba_id,
                "code": exc.code,
                "message": exc.message,
            },
        )
        raise _http(exc) from exc
    return result


@router.get("/accounts/{uba_id}/resume-check")
def resume_check_uba(
    uba_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """Resume 사전 점검 — 조회 전용, 상태 변경 없음."""
    from stock_platform.broker.recovery_resolution_service import (
        RecoveryResolutionService,
    )

    try:
        kill_active = bool(KillSwitchService(session).is_active())
    except Exception:  # noqa: BLE001
        kill_active = True
    return RecoveryResolutionService(session).resume_check(
        uba_id,
        kill_switch_active=kill_active,
        check_remote_open_orders=True,
    )


@router.get("/accounts/{uba_id}/conflict-summary")
def conflict_summary_uba(
    uba_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    from stock_platform.broker.recovery_resolution_service import (
        RecoveryResolutionService,
    )

    return RecoveryResolutionService(session).build_conflict_summary(
        uba_id
    )


@router.post("/accounts/{uba_id}/conflicts/resolve-dry-run")
def resolve_conflicts_dry_run(
    uba_id: int,
    body: ResolveSelectedBody,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """선택 Conflict 처리 dry-run — DB 변경 없음."""
    from stock_platform.broker.recovery_resolution_service import (
        RecoveryResolutionService,
    )

    try:
        return RecoveryResolutionService(session).dry_run_resolve(
            uba_id,
            conflict_ids=body.conflict_ids,
            resolution=body.resolution,
            reason=body.reason,
            expected_status=body.expected_status,
        )
    except RecoveryConflictError as exc:
        raise _http(exc) from exc


@router.post("/accounts/{uba_id}/conflicts/resolve-selected")
def resolve_conflicts_selected(
    uba_id: int,
    body: ResolveSelectedBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """선택 Conflict Resolution 실행 (feature flag 필요)."""
    from stock_platform.broker.recovery_resolution_service import (
        RecoveryResolutionService,
    )
    from stock_platform.common.settings import get_settings

    execute_enabled = bool(
        getattr(
            get_settings(),
            "recovery_conflict_resolve_execute_enabled",
            False,
        )
    )
    actor = f"admin:{user.user_id}"
    try:
        result = RecoveryResolutionService(session).resolve_selected(
            uba_id,
            conflict_ids=body.conflict_ids,
            resolution=body.resolution,
            reason=body.reason,
            actor=actor,
            expected_status=body.expected_status,
            execute_enabled=execute_enabled,
        )
        session.commit()
    except RecoveryConflictError as exc:
        session.rollback()
        audit.record(
            event_type="RECOVERY_CONFLICT_RESOLVE_FAILED",
            actor=actor,
            request_id=getattr(request.state, "request_id", None),
            detail={
                "uba_id": uba_id,
                "conflict_ids": body.conflict_ids,
                "resolution": body.resolution,
                "code": exc.code,
                "message": exc.message,
            },
        )
        raise _http(exc) from exc

    for item in result.get("processed") or []:
        audit.record(
            event_type="RECOVERY_CONFLICT_RESOLVE",
            actor=actor,
            request_id=getattr(request.state, "request_id", None),
            detail={
                "action": "resolve_selected",
                "admin_user_id": user.user_id,
                "uba_id": uba_id,
                "conflict_id": item.get("conflict_id"),
                "previous_status": (item.get("before") or {}).get(
                    "review_status"
                ),
                "new_status": (item.get("after") or {}).get(
                    "review_status"
                ),
                "resolution": body.resolution,
                "reason": body.reason[:500],
                "before_snapshot": item.get("before"),
                "after_snapshot": item.get("after"),
            },
        )
    return result


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_one_conflict(
    conflict_id: int,
    body: ResolveOneBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    from stock_platform.broker.recovery_resolution_service import (
        RecoveryResolutionService,
    )
    from stock_platform.common.settings import get_settings

    execute_enabled = bool(
        getattr(
            get_settings(),
            "recovery_conflict_resolve_execute_enabled",
            False,
        )
    )
    actor = f"admin:{user.user_id}"
    try:
        result = RecoveryResolutionService(session).resolve_one(
            conflict_id,
            resolution=body.resolution,
            reason=body.reason,
            actor=actor,
            expected_status=body.expected_status,
            execute_enabled=execute_enabled,
        )
        session.commit()
    except RecoveryConflictError as exc:
        session.rollback()
        raise _http(exc) from exc

    for item in result.get("processed") or []:
        audit.record(
            event_type="RECOVERY_CONFLICT_RESOLVE",
            actor=actor,
            request_id=getattr(request.state, "request_id", None),
            detail={
                "action": "resolve_one",
                "admin_user_id": user.user_id,
                "uba_id": result.get("uba_id"),
                "conflict_id": item.get("conflict_id"),
                "previous_status": (item.get("before") or {}).get(
                    "review_status"
                ),
                "new_status": (item.get("after") or {}).get(
                    "review_status"
                ),
                "resolution": body.resolution,
                "reason": body.reason[:500],
                "before_snapshot": item.get("before"),
                "after_snapshot": item.get("after"),
            },
        )
    return result


@router.post("/accounts/{uba_id}/unlock")
def unlock_uba_account(
    uba_id: int,
    body: NoteBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """Risk account_paused 해제 — Unlock Account."""
    from stock_platform.risk_engine.user_risk_service import (
        RiskSettingValidationError,
        UserRiskSettingService,
    )
    from stock_platform.trading.account_models import UserBrokerAccount

    uba = session.get(UserBrokerAccount, int(uba_id))
    if uba is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User broker account not found",
        )
    risk_svc = UserRiskSettingService(session)
    before = risk_svc.snapshot_account(uba_id)
    try:
        risk_svc.upsert_account(
            uba_id,
            {"account_paused": False},
            actor=f"admin:{user.user_id}",
        )
        session.commit()
    except RiskSettingValidationError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    after = risk_svc.snapshot_account(uba_id)
    audit.record(
        event_type="RECOVERY_ACCOUNT_UNLOCK",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "note": body.note[:200],
            "before_account_paused": (
                (before or {}).get("account_paused")
                if isinstance(before, dict)
                else None
            ),
            "after_account_paused": (
                (after or {}).get("account_paused")
                if isinstance(after, dict)
                else None
            ),
        },
    )
    return {
        "user_broker_account_id": uba_id,
        "account_paused": False,
        "note": body.note,
    }