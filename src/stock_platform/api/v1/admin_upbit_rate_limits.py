"""STEP 8-5-8 — ADMIN / USER Upbit Rate Limit 상태 API."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser, require_permission
from stock_platform.broker.upbit.rate_limit_coordinator import (
    get_upbit_rate_limit_coordinator,
)
from stock_platform.database.session import get_db_session
from stock_platform.trading.account_models import UserBrokerAccount


admin_router = APIRouter(
    prefix="/api/v1/admin/upbit/rate-limits",
    tags=["Admin Upbit Rate Limits"],
    dependencies=[Depends(require_admin)],
)

user_router = APIRouter(
    prefix="/api/v1/user/upbit/rate-limits",
    tags=["User Upbit Rate Limits"],
)


def _mask_account(uba: UserBrokerAccount) -> str:
    masked = (getattr(uba, "masked_account_number", None) or "").strip()
    if masked:
        return masked
    return ""


def _enrich_admin_row(
    session: Session, row: dict
) -> dict:
    out = dict(row)
    uba_id = int(out.get("user_broker_account_id") or 0)
    out["user_id"] = None
    out["account_masked"] = None
    if uba_id > 0:
        uba = session.get(UserBrokerAccount, uba_id)
        if uba is not None:
            out["user_id"] = int(uba.user_id)
            out["account_masked"] = _mask_account(uba)
    return out


def _user_summary(rows: list[dict]) -> dict:
    """USER용 요약 — Endpoint/Instance 세부 숨김."""

    now = datetime.now(timezone.utc)
    statuses: list[str] = []
    retry_at: datetime | None = None
    for row in rows:
        st = str(row.get("status") or "OK").upper()
        statuses.append(st)
        for key in ("cooldown_until", "blocked_until"):
            raw = row.get(key)
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt > now and (retry_at is None or dt < retry_at):
                retry_at = dt

    if any(s == "BLOCKED_418" for s in statuses):
        api_status = "ADMIN_REVIEW_REQUIRED"
        message = "관리자 확인이 필요합니다. 동기화가 일시중지되었을 수 있습니다."
    elif any(s in {"COOLDOWN", "DEFERRED"} for s in statuses):
        api_status = "RATE_LIMITED"
        message = "일시적 요청 제한 중입니다. 잠시 후 자동 재시도됩니다."
    else:
        api_status = "OK"
        message = "Upbit API 정상"

    return {
        "upbit_api_status": api_status,
        "message": message,
        "retry_scheduled_at": (
            retry_at.isoformat() if retry_at else None
        ),
        "sync_delayed": api_status != "OK",
        "admin_review_required": api_status
        == "ADMIN_REVIEW_REQUIRED",
    }


@admin_router.get("")
def list_rate_limits(
    limit: int = 100,
    _: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    """전체 Upbit Rate Limit Cooldown 상태 (Secret 미포함)."""

    limit = max(1, min(int(limit), 500))
    rows = get_upbit_rate_limit_coordinator().list_states(limit=limit)
    return {
        "items": [_enrich_admin_row(session, r) for r in rows],
        "total": len(rows),
        "health": get_upbit_rate_limit_coordinator().health_summary(),
    }


@admin_router.get("/{uba_id}")
def get_rate_limits_for_uba(
    uba_id: int,
    _: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
):
    uba = session.get(UserBrokerAccount, int(uba_id))
    if uba is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "account_not_found", "message": "계좌 없음"},
        )
    rows = get_upbit_rate_limit_coordinator().get_uba_states(int(uba_id))
    return {
        "user_broker_account_id": int(uba_id),
        "user_id": int(uba.user_id),
        "account_masked": _mask_account(uba),
        "items": [_enrich_admin_row(session, r) for r in rows],
    }


@admin_router.post("/{uba_id}/recheck")
def recheck_rate_limits(
    uba_id: int,
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    session: Session = Depends(get_db_session),
    audit: AuditLogService = Depends(get_audit_service),
):
    """
    안전한 Recheck — PG 상태 재조회만.
    강제 Cooldown 해제는 제공하지 않는다.
    """

    uba = session.get(UserBrokerAccount, int(uba_id))
    if uba is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "account_not_found", "message": "계좌 없음"},
        )
    rows = get_upbit_rate_limit_coordinator().get_uba_states(int(uba_id))
    audit.record(
        event_type="ADMIN_UPBIT_RATE_LIMIT_RECHECK",
        actor=user.username or f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": int(uba_id),
            "row_count": len(rows),
        },
    )
    return {
        "user_broker_account_id": int(uba_id),
        "rechecked": True,
        "force_clear": False,
        "items": [_enrich_admin_row(session, r) for r in rows],
        "summary": _user_summary(rows),
    }


@user_router.get("/{uba_id}")
def get_user_rate_limit_summary(
    uba_id: int,
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """본인 Upbit 계좌 Rate Limit 요약만 (내부 상세 비노출)."""

    uba = session.scalar(
        select(UserBrokerAccount).where(
            UserBrokerAccount.user_broker_account_id == int(uba_id),
            UserBrokerAccount.user_id == int(user.user_id),
        )
    )
    if uba is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "account_not_found", "message": "계좌 없음"},
        )
    broker = str(getattr(uba, "broker_code", "") or "").upper()
    if broker != "UPBIT":
        return {
            "user_broker_account_id": int(uba_id),
            "upbit_api_status": "N/A",
            "message": "Upbit 계좌가 아닙니다.",
            "retry_scheduled_at": None,
            "sync_delayed": False,
            "admin_review_required": False,
        }
    rows = get_upbit_rate_limit_coordinator().get_uba_states(int(uba_id))
    summary = _user_summary(rows)
    summary["user_broker_account_id"] = int(uba_id)
    return summary
