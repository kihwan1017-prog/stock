"""STEP 8-5-7/8-5-11 — Admin/User Trading Calendar API + Change Requests."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser, get_current_user
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_db_session
from stock_platform.operation.calendar_audit import audit_calendar_event
from stock_platform.operation.calendar_change_constants import (
    CalendarChangeType,
    CalendarSourceType,
)
from stock_platform.operation.calendar_change_service import (
    CalendarChangeError,
    TradingCalendarChangeService,
    day_snapshot,
    request_as_dict,
)
from stock_platform.operation.calendar_constants import (
    CALENDAR_UNAVAILABLE_REASONS,
    KRX_TIMEZONE,
    CalendarSessionType,
    CalendarVerifiedStatus,
)
from stock_platform.operation.calendar_repository import (
    TradingCalendarRepository,
)
from stock_platform.operation.calendar_service import TradingCalendarService
from stock_platform.operation.calendar_sync_service import (
    TradingCalendarSyncService,
)


admin_router = APIRouter(
    prefix="/api/v1/admin/market-calendar",
    tags=["Admin Market Calendar"],
    dependencies=[Depends(require_admin)],
)

user_router = APIRouter(
    prefix="/api/v1/user/market-calendar",
    tags=["User Market Calendar"],
)


def _day_admin_dict(row) -> dict:
    return {
        "calendar_day_id": int(row.calendar_day_id),
        "exchange_code": row.exchange_code,
        "calendar_date": row.calendar_date.isoformat(),
        "is_trading_day": row.is_trading_day,
        "session_type": row.session_type,
        "preopen_at": row.preopen_at.isoformat() if row.preopen_at else None,
        "regular_open_at": (
            row.regular_open_at.isoformat() if row.regular_open_at else None
        ),
        "regular_close_at": (
            row.regular_close_at.isoformat()
            if row.regular_close_at
            else None
        ),
        "timezone": row.timezone,
        "holiday_name": row.holiday_name,
        "closure_reason": row.closure_reason,
        "source_type": row.source_type,
        "source_code": row.source_code,
        "source_reference": row.source_reference,
        "source_updated_at": (
            row.source_updated_at.isoformat()
            if row.source_updated_at
            else None
        ),
        "verified_status": row.verified_status,
        "verified_by": row.verified_by,
        "verified_at": (
            row.verified_at.isoformat() if row.verified_at else None
        ),
        "revision": int(getattr(row, "revision", 1) or 1),
        "active_change_request_id": getattr(
            row, "active_change_request_id", None
        ),
        "last_changed_at": (
            row.last_changed_at.isoformat()
            if getattr(row, "last_changed_at", None)
            else None
        ),
    }


def _change_svc(session: Session) -> TradingCalendarChangeService:
    settings = get_settings()
    return TradingCalendarChangeService(
        session,
        require_separate_approver=bool(
            settings.krx_calendar_require_separate_approver
        ),
    )


def _raise_change(exc: CalendarChangeError) -> None:
    code = exc.code
    http = status.HTTP_400_BAD_REQUEST
    if code in {"not_found", "history_not_found"}:
        http = status.HTTP_404_NOT_FOUND
    elif code in {"revision_conflict", "conflict"}:
        http = status.HTTP_409_CONFLICT
    elif code == "same_approver_forbidden":
        http = status.HTTP_403_FORBIDDEN
    raise HTTPException(status_code=http, detail=exc.message)


def _infer_change_type(
    *,
    is_trading_day: bool,
    session_type: str,
) -> str:
    if not is_trading_day or session_type == CalendarSessionType.CLOSED.value:
        return CalendarChangeType.FULL_DAY_CLOSE.value
    if session_type == CalendarSessionType.DELAYED_OPEN.value:
        return CalendarChangeType.DELAYED_OPEN.value
    if session_type == CalendarSessionType.EARLY_CLOSE.value:
        return CalendarChangeType.EARLY_CLOSE.value
    if session_type == CalendarSessionType.SPECIAL_SESSION.value:
        return CalendarChangeType.SPECIAL_SESSION.value
    return CalendarChangeType.OPEN_DAY_OVERRIDE.value


class CalendarUpsertBody(BaseModel):
    """레거시 PUT — 내부적으로 Change Request 생성 (직접 UPDATE 금지)."""

    is_trading_day: bool
    session_type: str = CalendarSessionType.REGULAR.value
    holiday_name: str | None = Field(default=None, max_length=200)
    closure_reason: str | None = Field(default=None, max_length=200)
    regular_open_at: time | None = None
    regular_close_at: time | None = None
    preopen_at: time | None = None
    reason: str = Field(min_length=3, max_length=200)
    source_type: str = CalendarSourceType.ADMIN_MANUAL.value
    source_reference: str | None = Field(default=None, max_length=200)
    emergency: bool = False
    expected_revision: int | None = None
    # True면 submit→approve→apply까지 (비상 또는 소규모 운영)
    apply_now: bool = False


class SyncBody(BaseModel):
    from_date: date | None = None
    to_date: date | None = None
    mark_verified: bool = True
    past_years: int = Field(default=1, ge=0, le=5)


class VerifyBody(BaseModel):
    status: str = CalendarVerifiedStatus.VERIFIED.value
    reason: str = Field(default="admin verify", min_length=3, max_length=200)
    apply_now: bool = True


class ChangeRequestCreateBody(BaseModel):
    exchange_code: str = "KRX"
    market_date: date
    change_type: str
    requested_values: dict
    reason: str = Field(min_length=3, max_length=500)
    source_type: str = CalendarSourceType.ADMIN_MANUAL.value
    source_reference: str | None = Field(default=None, max_length=200)
    emergency: bool = False
    expected_revision: int | None = None


class ReviewBody(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


class RejectBody(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class RollbackBody(BaseModel):
    target_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


@admin_router.get("")
def list_calendar(
    exchange_code: str = Query("KRX"),
    start_date: date = Query(...),
    end_date: date = Query(...),
    verified_status: str | None = None,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    if end_date < start_date:
        raise HTTPException(400, detail="end_date must be >= start_date")
    rows = TradingCalendarRepository(session).list_between(
        exchange_code=exchange_code,
        start_date=start_date,
        end_date=end_date,
        verified_status=verified_status,
    )
    return {
        "items": [_day_admin_dict(r) for r in rows],
        "count": len(rows),
    }


@admin_router.get("/coverage")
def calendar_coverage(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    return TradingCalendarSyncService(session).check_coverage()


@admin_router.get("/change-health")
def calendar_change_health(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    summary = _change_svc(session).health_summary()
    try:
        from stock_platform.operation.calendar_scheduler_recompute import (
            scheduler_recompute_failure_count,
        )

        summary["scheduler_recompute_failures"] = (
            scheduler_recompute_failure_count()
        )
    except Exception:  # noqa: BLE001
        summary["scheduler_recompute_failures"] = None

    # STEP 8-5-13 — KRX Session Timeline 상태
    try:
        timeline = TradingCalendarService(
            TradingCalendarRepository(session)
        ).resolve_timeline(
            "KRX", datetime.now(ZoneInfo(KRX_TIMEZONE)).date()
        )
        now = datetime.now(ZoneInfo(KRX_TIMEZONE))
        summary["krx_timeline"] = {
            "phase": timeline.phase_at(now).value,
            "revision": timeline.revision,
            "reason_code": timeline.reason_code,
            "ok": (
                timeline.reason_code not in CALENDAR_UNAVAILABLE_REASONS
            ),
        }
    except Exception:  # noqa: BLE001
        summary["krx_timeline"] = None

    # STEP 8-5-15 — 영속 Market Session Job 요약 (Due/Running/Failed/Lag)
    try:
        from stock_platform.operation.market_session_job_service import (
            MarketSessionJobService,
        )

        summary["market_session_jobs"] = MarketSessionJobService(
            session
        ).health_summary()
    except Exception:  # noqa: BLE001
        summary["market_session_jobs"] = None
    return summary


@admin_router.get("/change-requests")
def list_change_requests(
    status_filter: str | None = Query(None, alias="status"),
    exchange_code: str = Query("KRX"),
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    rows = _change_svc(session).list_requests(
        status=status_filter,
        exchange_code=exchange_code,
        limit=limit,
    )
    return {
        "items": [request_as_dict(r) for r in rows],
        "count": len(rows),
    }


@admin_router.post("/change-requests")
def create_change_request(
    body: ChangeRequestCreateBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    try:
        row = _change_svc(session).create_request(
            exchange_code=body.exchange_code,
            market_date=body.market_date,
            change_type=body.change_type,
            requested_values=body.requested_values,
            reason=body.reason,
            source_type=body.source_type,
            source_reference=body.source_reference,
            emergency=body.emergency,
            expected_revision=body.expected_revision,
            requested_by=user.username,
        )
        if body.emergency:
            # 긴급: DRAFT에서 바로 적용 (요청 이력 유지)
            row = _change_svc(session).apply(
                int(row.change_request_id), actor=user.username
            )
        session.commit()
        audit.record(
            event_type="ADMIN_CALENDAR_CHANGE_REQUEST",
            actor=user.username,
            request_id=getattr(http_request.state, "request_id", None),
            detail={
                "change_request_id": int(row.change_request_id),
                "status": row.status,
                "emergency": bool(body.emergency),
            },
        )
        session.commit()
        return request_as_dict(row)
    except CalendarChangeError as exc:
        session.rollback()
        _raise_change(exc)


@admin_router.get("/change-requests/{request_id}")
def get_change_request(
    request_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    row = _change_svc(session).get_request(request_id)
    if row is None:
        raise HTTPException(404, detail="Change request not found")
    return request_as_dict(row)


@admin_router.post("/change-requests/{request_id}/submit")
def submit_change_request(
    request_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    try:
        row = _change_svc(session).submit(
            request_id, actor=user.username
        )
        session.commit()
        return request_as_dict(row)
    except CalendarChangeError as exc:
        session.rollback()
        _raise_change(exc)


@admin_router.post("/change-requests/{request_id}/approve")
def approve_change_request(
    request_id: int,
    body: ReviewBody | None = None,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    try:
        row = _change_svc(session).approve(
            request_id,
            actor=user.username,
            comment=(body.comment if body else None),
        )
        session.commit()
        return request_as_dict(row)
    except CalendarChangeError as exc:
        session.rollback()
        _raise_change(exc)


@admin_router.post("/change-requests/{request_id}/reject")
def reject_change_request(
    request_id: int,
    body: RejectBody,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    try:
        row = _change_svc(session).reject(
            request_id, actor=user.username, reason=body.reason
        )
        session.commit()
        return request_as_dict(row)
    except CalendarChangeError as exc:
        session.rollback()
        _raise_change(exc)


@admin_router.post("/change-requests/{request_id}/apply")
def apply_change_request(
    request_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    try:
        row = _change_svc(session).apply(
            request_id, actor=user.username
        )
        session.commit()
        return request_as_dict(row)
    except CalendarChangeError as exc:
        session.rollback()
        _raise_change(exc)


@admin_router.post("/change-requests/{request_id}/cancel")
def cancel_change_request(
    request_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    try:
        row = _change_svc(session).cancel(
            request_id, actor=user.username
        )
        session.commit()
        return request_as_dict(row)
    except CalendarChangeError as exc:
        session.rollback()
        _raise_change(exc)


@admin_router.post("/sync")
def sync_calendar(
    body: SyncBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    try:
        from stock_platform.broker.recovery_distributed_lock import (
            LockAcquireResult,
            LockReleaseReason,
            build_distributed_lock_manager_from_settings,
        )
        from stock_platform.broker.recovery_distributed_lock_scope import (
            RecoveryAccountKind,
            RecoveryLockScope,
        )

        lock_mgr = build_distributed_lock_manager_from_settings()
        scope = RecoveryLockScope(
            account_kind=RecoveryAccountKind.SYSTEM,
            account_id=0,
            broker_code="KRX_CALENDAR",
            market_type="SYNC",
        )
        result, handle = lock_mgr.acquire(scope, timeout=0)
        if result in {
            LockAcquireResult.BUSY,
            LockAcquireResult.TIMEOUT,
        } or handle is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Calendar sync already running on another instance",
            )
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        handle = None
        lock_mgr = None

    try:
        out = TradingCalendarSyncService(session).sync_krx(
            from_date=body.from_date,
            to_date=body.to_date,
            trigger_type="ADMIN",
            requested_by=user.username,
            mark_verified=body.mark_verified,
            past_years=body.past_years,
        )
        audit.record(
            event_type="ADMIN_CALENDAR_SYNC",
            actor=user.username,
            request_id=getattr(http_request.state, "request_id", None),
            detail={
                "status": out.get("status"),
                "upserted_count": out.get("upserted_count"),
            },
        )
        session.commit()
        return out
    finally:
        if lock_mgr is not None and handle is not None:
            try:
                lock_mgr.release(handle, LockReleaseReason.SUCCESS)
            except Exception:  # noqa: BLE001
                pass


@admin_router.get("/{exchange_code}/{calendar_date}/history")
def calendar_day_history(
    exchange_code: str,
    calendar_date: date,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    rows = _change_svc(session).list_history(
        exchange_code=exchange_code, market_date=calendar_date
    )
    return {
        "items": [
            {
                "history_id": int(h.history_id),
                "revision": int(h.revision),
                "change_request_id": h.change_request_id,
                "before_snapshot": h.before_snapshot,
                "after_snapshot": h.after_snapshot,
                "reason": h.reason,
                "source_type": h.source_type,
                "emergency": bool(h.emergency),
                "applied_by": h.applied_by,
                "applied_at": (
                    h.applied_at.isoformat() if h.applied_at else None
                ),
            }
            for h in rows
        ],
        "count": len(rows),
    }


@admin_router.post("/{exchange_code}/{calendar_date}/rollback")
def rollback_calendar_day(
    exchange_code: str,
    calendar_date: date,
    body: RollbackBody,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    try:
        row = _change_svc(session).create_rollback_request(
            exchange_code=exchange_code,
            market_date=calendar_date,
            target_revision=body.target_revision,
            reason=body.reason,
            requested_by=user.username,
        )
        session.commit()
        return request_as_dict(row)
    except CalendarChangeError as exc:
        session.rollback()
        _raise_change(exc)


@admin_router.get("/{exchange_code}/{calendar_date}/timeline")
def get_calendar_timeline(
    exchange_code: str,
    calendar_date: date,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """STEP 8-5-13 — 해당 일자의 Session Timeline (Phase 경계 포함)."""

    svc = TradingCalendarService(TradingCalendarRepository(session))
    timeline = svc.resolve_timeline(exchange_code, calendar_date)
    now = datetime.now(ZoneInfo(timeline.timezone or KRX_TIMEZONE))
    current_phase = timeline.phase_at(now)
    next_at, next_phase = timeline.next_transition(now)
    payload = timeline.to_dict()
    payload["current_phase"] = current_phase.value
    payload["next_transition_at"] = (
        next_at.isoformat() if next_at else None
    )
    payload["next_transition_phase"] = (
        next_phase.value if next_phase else None
    )
    return payload


@admin_router.get("/{exchange_code}/{calendar_date}/jobs")
def get_calendar_jobs(
    exchange_code: str,
    calendar_date: date,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """STEP 8-5-15 — 해당 일자에 영속된 Market Session Job 목록 (DB 우선).

    DB(`operation.market_session_job`)가 Source of Truth. 조회 실패 시에만
    Deprecated 메모리 미러(`_DYNAMIC_JOBS`)로 Fallback한다.
    """

    from stock_platform.operation.market_session_job_service import (
        MarketSessionJobService,
        job_as_dict,
    )

    exchange = exchange_code.strip().upper()
    try:
        rows = MarketSessionJobService(session).list_for_date(
            exchange_code=exchange, market_date=calendar_date
        )
        # Admin 프론트(MarketCalendarPanel)의 기존 컬럼(job_id/status/run_at/
        # revision)과 호환되도록 필드명을 유지하면서 상세 필드도 함께 내려준다.
        items = [
            {
                **job_as_dict(r),
                "status": r.status_code,
                "run_at": r.scheduled_for.isoformat()
                if r.scheduled_for
                else None,
                "revision": int(r.calendar_revision),
            }
            for r in rows
        ]
        return {"items": items, "count": len(items), "source": "DB"}
    except Exception:  # noqa: BLE001
        from stock_platform.operation.calendar_scheduler_recompute import (
            list_dynamic_jobs,
        )

        target_date = calendar_date.isoformat()
        items = [
            job
            for job in list_dynamic_jobs()
            if job.get("exchange_code") == exchange
            and job.get("market_date") == target_date
        ]
        return {"items": items, "count": len(items), "source": "MEMORY_FALLBACK"}


@admin_router.post("/{exchange_code}/{calendar_date}/recompute-jobs")
def recompute_calendar_jobs(
    exchange_code: str,
    calendar_date: date,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    """STEP 8-5-13 — Session Job(Preopen/Open/Cutoff/Close/Postclose 등)을

    현재 Calendar Revision 기준으로 강제 재계산한다.
    """

    from stock_platform.operation.calendar_scheduler_recompute import (
        recompute_krx_session_jobs,
    )

    row = TradingCalendarRepository(session).get_day(
        exchange_code=exchange_code, calendar_date=calendar_date
    )
    if row is None:
        raise HTTPException(404, detail="Calendar day not found")
    snapshot = day_snapshot(row) or {}
    result = recompute_krx_session_jobs(
        exchange_code=exchange_code,
        market_date=calendar_date,
        revision=int(getattr(row, "revision", 1) or 1),
        session_snapshot=snapshot,
        session=session,
    )
    audit.record(
        event_type="ADMIN_CALENDAR_RECOMPUTE_JOBS",
        actor=user.username,
        detail={
            "exchange_code": exchange_code.upper(),
            "calendar_date": calendar_date.isoformat(),
            "status": result.get("status"),
        },
    )
    session.commit()
    return result


@admin_router.get("/{exchange_code}/{calendar_date}")
def get_calendar_day(
    exchange_code: str,
    calendar_date: date,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    row = TradingCalendarRepository(session).get_day(
        exchange_code=exchange_code,
        calendar_date=calendar_date,
    )
    decision = TradingCalendarService(
        TradingCalendarRepository(session)
    ).evaluate(
        exchange_code=exchange_code,
        calendar_date=calendar_date,
    )
    return {
        "stored": _day_admin_dict(row) if row else None,
        "decision": decision,
    }


@admin_router.put("/{exchange_code}/{calendar_date}")
def update_calendar_day(
    exchange_code: str,
    calendar_date: date,
    body: CalendarUpsertBody,
    http_request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    """레거시 PUT — Change Request 경유 (직접 Calendar UPDATE 차단)."""

    if body.session_type not in {s.value for s in CalendarSessionType}:
        raise HTTPException(400, detail="Invalid session_type")
    audit_calendar_event(
        "CALENDAR_DIRECT_UPDATE_REDIRECTED",
        actor=user.username,
        detail={
            "exchange_code": exchange_code.upper(),
            "calendar_date": calendar_date.isoformat(),
            "emergency": body.emergency,
        },
    )
    change_type = _infer_change_type(
        is_trading_day=body.is_trading_day,
        session_type=body.session_type,
    )
    requested = {
        "is_trading_day": body.is_trading_day,
        "session_type": body.session_type,
        "holiday_name": body.holiday_name,
        "closure_reason": body.closure_reason or body.reason,
        "regular_open_at": (
            body.regular_open_at.isoformat() if body.regular_open_at else None
        ),
        "regular_close_at": (
            body.regular_close_at.isoformat()
            if body.regular_close_at
            else None
        ),
        "preopen_at": (
            body.preopen_at.isoformat() if body.preopen_at else None
        ),
        "verified_status": CalendarVerifiedStatus.VERIFIED.value,
    }
    source_type = (
        CalendarSourceType.EMERGENCY_ADMIN.value
        if body.emergency
        else body.source_type
    )
    if body.emergency and not body.source_reference:
        raise HTTPException(
            400, detail="emergency requires source_reference"
        )
    try:
        svc = _change_svc(session)
        row = svc.create_request(
            exchange_code=exchange_code,
            market_date=calendar_date,
            change_type=change_type,
            requested_values=requested,
            reason=body.reason,
            source_type=source_type,
            source_reference=body.source_reference
            or f"legacy-put:{body.reason[:160]}",
            emergency=body.emergency,
            expected_revision=body.expected_revision,
            requested_by=user.username,
        )
        apply_now = body.emergency or body.apply_now
        if apply_now and not body.emergency:
            svc.submit(int(row.change_request_id), actor=user.username)
            svc.approve(
                int(row.change_request_id), actor=user.username
            )
            row = svc.apply(
                int(row.change_request_id), actor=user.username
            )
        elif body.emergency:
            row = svc.apply(
                int(row.change_request_id), actor=user.username
            )
        session.commit()
        audit.record(
            event_type="ADMIN_CALENDAR_UPSERT_VIA_CHANGE_REQUEST",
            actor=user.username,
            request_id=getattr(http_request.state, "request_id", None),
            detail={
                "change_request_id": int(row.change_request_id),
                "status": row.status,
                "emergency": body.emergency,
            },
        )
        session.commit()
        day = TradingCalendarRepository(session).get_day(
            exchange_code=exchange_code, calendar_date=calendar_date
        )
        return {
            "change_request": request_as_dict(row),
            "stored": _day_admin_dict(day) if day else None,
        }
    except CalendarChangeError as exc:
        session.rollback()
        _raise_change(exc)


@admin_router.post("/{exchange_code}/{calendar_date}/verify")
def verify_calendar_day(
    exchange_code: str,
    calendar_date: date,
    body: VerifyBody,
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
    session: Session = Depends(get_db_session),
):
    if body.status not in {s.value for s in CalendarVerifiedStatus}:
        raise HTTPException(400, detail="Invalid verified status")
    try:
        svc = _change_svc(session)
        row = svc.create_request(
            exchange_code=exchange_code,
            market_date=calendar_date,
            change_type=CalendarChangeType.VERIFICATION_CHANGE.value,
            requested_values={"verified_status": body.status},
            reason=body.reason,
            source_type=CalendarSourceType.ADMIN_MANUAL.value,
            source_reference=f"verify:{body.status}",
            requested_by=user.username,
        )
        if body.apply_now:
            svc.submit(int(row.change_request_id), actor=user.username)
            svc.approve(
                int(row.change_request_id), actor=user.username
            )
            row = svc.apply(
                int(row.change_request_id), actor=user.username
            )
        session.commit()
        audit.record(
            event_type="ADMIN_CALENDAR_VERIFY_VIA_CHANGE_REQUEST",
            actor=user.username,
            detail={
                "change_request_id": int(row.change_request_id),
                "status": body.status,
            },
        )
        session.commit()
        day = TradingCalendarRepository(session).get_day(
            exchange_code=exchange_code, calendar_date=calendar_date
        )
        return {
            "change_request": request_as_dict(row),
            "stored": _day_admin_dict(day) if day else None,
        }
    except CalendarChangeError as exc:
        session.rollback()
        _raise_change(exc)


@user_router.get("/status")
def user_calendar_status(
    exchange_code: str = Query("KRX"),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(get_current_user),
):
    return TradingCalendarService(
        TradingCalendarRepository(session)
    ).user_status(exchange_code)
