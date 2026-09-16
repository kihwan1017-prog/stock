"""STEP 8-9C — Admin Broker Account (UBA) CRUD API.

실주문 / ARM / LIVE ON 엔드포인트는 포함하지 않는다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser, admin_actor_label
from stock_platform.database.session import get_db_session
from stock_platform.trading.admin_broker_account_service import (
    AdminBrokerAccountService,
)
from stock_platform.trading.user_account_service import UserAccountError


router = APIRouter(
    prefix="/api/v1/admin/broker-accounts",
    tags=["Admin Broker Accounts"],
    dependencies=[Depends(require_admin)],
)


class AdminCreateBrokerAccountRequest(BaseModel):
    owner_user_id: int = Field(gt=0)
    broker_code: str = Field(
        default="UPBIT",
        min_length=1,
        max_length=20,
        description="UPBIT | KIWOOM",
    )
    account_alias: str | None = Field(default=None, max_length=100)
    account_number: str = Field(
        min_length=1,
        max_length=64,
        description="해시·마스킹만 저장 (업비트는 MAIN 등 ref)",
    )
    currency_code: str = Field(default="KRW", max_length=10)
    is_default: bool = False
    apply_recommended_risk: bool = Field(
        default=True,
        description="UPBIT만 5000/1/1 계좌 Risk 오버레이",
    )


class AdminUpdateBrokerAccountRequest(BaseModel):
    account_alias: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


def _http(exc: UserAccountError) -> HTTPException:
    """도메인 오류 → 4xx (Traceback/내부 스택은 응답에 넣지 않음)."""

    msg = str(exc)
    lower = msg.lower()
    if "not found" in lower or "찾을 수 없" in msg:
        code = status.HTTP_404_NOT_FOUND
    elif "이미 연결" in msg or "duplicate" in lower:
        code = status.HTTP_409_CONFLICT
    elif (
        "account_number" in lower
        or "unsupported" in lower
        or "필요합니다" in msg
        or "invalid" in lower
    ):
        code = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=msg)


@router.get("")
def admin_list_broker_accounts(
    broker_code: str | None = Query(default="UPBIT"),
    owner_user_id: int | None = Query(default=None),
    include_inactive: bool = Query(default=True),
    # STEP 2-5-1 — 기본값 False: 관리자 목록도 삭제 계좌는 기본 제외,
    # 명시적으로 true를 줘야만 삭제 계좌를 포함한다.
    include_deleted: bool = Query(default=False),
    # 운영 UI 기본: REAL_OPERATION만. 테스트/PAPER/MOCK/UNKNOWN 숨김.
    include_test_accounts: bool = Query(default=False),
    # 목록 N+1 완화 — detail drawer에서 full enrich.
    enrich: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    try:
        return AdminBrokerAccountService(session).list_accounts(
            broker_code=broker_code,
            owner_user_id=owner_user_id,
            include_inactive=include_inactive,
            include_deleted=include_deleted,
            include_test_accounts=include_test_accounts,
            enrich=enrich,
            limit=limit,
            offset=offset,
        )
    except UserAccountError as exc:
        raise _http(exc) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
def admin_create_broker_account(
    body: AdminCreateBrokerAccountRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    # actor = 로그인 관리자 / owner_user_id = 계좌 소유자 (혼동 금지)
    actor = admin_actor_label(user)
    try:
        created = AdminBrokerAccountService(session).create_account(
            owner_user_id=body.owner_user_id,
            broker_code=body.broker_code,
            account_alias=body.account_alias,
            account_number=body.account_number,
            currency_code=body.currency_code,
            is_default=body.is_default,
            apply_recommended_risk=body.apply_recommended_risk,
            actor=actor,
        )
    except UserAccountError as exc:
        session.rollback()
        raise _http(exc) from exc

    audit.record(
        event_type="ADMIN_BROKER_ACCOUNT_CREATE",
        actor=actor,
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": created.get("user_broker_account_id"),
            "owner_user_id": body.owner_user_id,
            "broker_code": str(body.broker_code).upper(),
            "recommended_risk_applied": created.get(
                "recommended_risk_applied"
            ),
            "live_order_enabled": created.get("live_order_enabled"),
        },
    )
    session.commit()
    return created


@router.get("/{uba_id}")
def admin_get_broker_account(
    uba_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    try:
        return AdminBrokerAccountService(session).get_account(uba_id)
    except UserAccountError as exc:
        raise _http(exc) from exc


@router.patch("/{uba_id}")
def admin_update_broker_account(
    uba_id: int,
    body: AdminUpdateBrokerAccountRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = admin_actor_label(user)
    try:
        updated = AdminBrokerAccountService(session).update_account(
            uba_id,
            account_alias=body.account_alias,
            is_active=body.is_active,
            actor=actor,
        )
    except UserAccountError as exc:
        session.rollback()
        raise _http(exc) from exc
    audit.record(
        event_type="ADMIN_BROKER_ACCOUNT_UPDATE",
        actor=actor,
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "account_alias": body.account_alias,
            "is_active": body.is_active,
        },
    )
    session.commit()
    return updated


@router.delete("/{uba_id}")
def admin_delete_broker_account(
    uba_id: int,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = admin_actor_label(user)
    try:
        result = AdminBrokerAccountService(session).delete_account(
            uba_id, actor=actor
        )
    except UserAccountError as exc:
        session.rollback()
        raise _http(exc) from exc
    audit.record(
        event_type="ADMIN_BROKER_ACCOUNT_DELETE",
        actor=actor,
        request_id=getattr(request.state, "request_id", None),
        detail={"user_broker_account_id": uba_id, **result},
    )
    session.commit()
    return result


@router.post("/{uba_id}/apply-recommended-risk")
def admin_apply_recommended_risk(
    uba_id: int,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    actor = admin_actor_label(user)
    try:
        result = AdminBrokerAccountService(session).apply_recommended_risk(
            uba_id, actor=actor
        )
    except UserAccountError as exc:
        session.rollback()
        raise _http(exc) from exc
    audit.record(
        event_type="ADMIN_BROKER_ACCOUNT_RECOMMENDED_RISK",
        actor=actor,
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "risk": result.get("risk"),
        },
    )
    session.commit()
    return result


@router.get("/{uba_id}/ops-status")
def admin_get_broker_account_ops_status(
    uba_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """관리자 전용 운영 상세 — Conflict/Pause/Recovery/Runtime/Scheduler/Credential."""
    try:
        return AdminBrokerAccountService(session).get_ops_status(uba_id)
    except UserAccountError as exc:
        raise _http(exc) from exc
