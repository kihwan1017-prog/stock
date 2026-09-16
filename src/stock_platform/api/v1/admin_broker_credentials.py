"""STEP 8-5-2 / 8-9C — ADMIN Broker Credential API (원문 조회 금지).

등록(upsert)·재검증·폐기를 지원한다. 응답에 Access/Secret 원문을 넣지 않는다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import (
    AuditLogService,
    get_audit_service,
    require_admin,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
)
from stock_platform.database.session import get_db_session
from stock_platform.risk_engine.user_risk_service import UserRiskSettingService
from stock_platform.trading.account_models import UserBrokerAccount


router = APIRouter(
    prefix="/api/v1/admin/accounts",
    tags=["Admin Broker Credentials"],
    dependencies=[Depends(require_admin)],
)


class AdminCredentialUpsertRequest(BaseModel):
    """Admin 대리 등록 — 원문은 요청 바디에만 존재, 응답/로그 금지."""

    app_key: str | None = Field(default=None, max_length=200)
    secret_key: str | None = Field(default=None, max_length=200)
    account_number: str | None = Field(default=None, max_length=64)
    account_product_code: str | None = Field(default=None, max_length=20)
    is_mock: bool | None = None
    access_key: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _require_some_secret(self) -> "AdminCredentialUpsertRequest":
        has_kiwoom = bool(
            self.app_key and self.secret_key and self.account_number
        )
        has_upbit = bool(self.access_key and self.secret_key)
        if not has_kiwoom and not has_upbit:
            raise ValueError("Credential fields incomplete for broker")
        return self

    def as_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


def _http(exc: BrokerCredentialVaultError) -> HTTPException:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code == "credential_missing":
        code = status.HTTP_404_NOT_FOUND
    elif exc.code == "vault_unavailable":
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif exc.code == "upbit_rate_limited":
        code = status.HTTP_429_TOO_MANY_REQUESTS
    elif exc.code == "upbit_blocked_418":
        code = status.HTTP_423_LOCKED
    return HTTPException(
        status_code=code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.get("/{uba_id}/credentials/status")
def admin_credential_status(
    uba_id: int,
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    uba = session.get(UserBrokerAccount, int(uba_id))
    if uba is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User broker account not found",
        )
    view = BrokerCredentialVaultService(session).status(uba_id)
    risk = UserRiskSettingService(session).snapshot_account(uba_id)
    return {
        **view.as_dict(),
        "owner_user_id": int(uba.user_id),
        "uba_connection_status": uba.connection_status,
        "uba_is_active": bool(uba.is_active),
        "account_paused": bool(
            (risk or {}).get("account_paused")
            if isinstance(risk, dict)
            else False
        ),
    }


@router.post(
    "/{uba_id}/credentials",
    status_code=status.HTTP_201_CREATED,
)
def admin_register_credential(
    uba_id: int,
    body: AdminCredentialUpsertRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    uba = session.get(UserBrokerAccount, int(uba_id))
    if uba is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User broker account not found",
        )
    service = BrokerCredentialVaultService(session)
    before = service.status(uba_id)
    try:
        after = service.upsert(
            user_broker_account_id=uba_id,
            owner_user_id=int(uba.user_id),
            plaintext=body.as_payload(),
            actor=f"admin:{user.user_id}",
            replace=False,
        )
    except BrokerCredentialVaultError as exc:
        raise _http(exc) from exc

    audit.record(
        event_type="ADMIN_BROKER_CREDENTIAL_REGISTER",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "owner_user_id": int(uba.user_id),
            "before_status": before.verification_status,
            "after_status": after.verification_status,
            "key_version": after.key_version,
            "connected": after.connected,
        },
    )
    return after.as_dict()


@router.put("/{uba_id}/credentials")
def admin_replace_credential(
    uba_id: int,
    body: AdminCredentialUpsertRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    uba = session.get(UserBrokerAccount, int(uba_id))
    if uba is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User broker account not found",
        )
    service = BrokerCredentialVaultService(session)
    before = service.status(uba_id)
    try:
        after = service.upsert(
            user_broker_account_id=uba_id,
            owner_user_id=int(uba.user_id),
            plaintext=body.as_payload(),
            actor=f"admin:{user.user_id}",
            replace=True,
        )
    except BrokerCredentialVaultError as exc:
        raise _http(exc) from exc

    audit.record(
        event_type="ADMIN_BROKER_CREDENTIAL_REPLACE",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "owner_user_id": int(uba.user_id),
            "before_status": before.verification_status,
            "after_status": after.verification_status,
            "key_version": after.key_version,
        },
    )
    return after.as_dict()


@router.post("/{uba_id}/credentials/verify")
def admin_verify_credential(
    uba_id: int,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = BrokerCredentialVaultService(session)
    before = service.status(uba_id)
    try:
        after = service.verify(
            user_broker_account_id=uba_id,
            owner_user_id=None,
            actor=f"admin:{user.user_id}",
            admin=True,
        )
    except BrokerCredentialVaultError as exc:
        audit.record(
            event_type="ADMIN_BROKER_CREDENTIAL_VERIFY_FAILED",
            actor=f"admin:{user.user_id}",
            request_id=getattr(request.state, "request_id", None),
            detail={
                "user_broker_account_id": uba_id,
                "code": exc.code,
                "before_status": before.verification_status,
            },
        )
        raise _http(exc) from exc

    audit.record(
        event_type="ADMIN_BROKER_CREDENTIAL_VERIFY",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "before_status": before.verification_status,
            "after_status": after.verification_status,
            "key_version": after.key_version,
        },
    )
    return after.as_dict()


@router.post("/{uba_id}/credentials/revoke")
def admin_revoke_credential(
    uba_id: int,
    request: Request,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
    audit: AuditLogService = Depends(get_audit_service),
):
    service = BrokerCredentialVaultService(session)
    before = service.status(uba_id)
    try:
        after = service.revoke(
            user_broker_account_id=uba_id,
            owner_user_id=None,
            actor=f"admin:{user.user_id}",
            admin=True,
        )
    except BrokerCredentialVaultError as exc:
        raise _http(exc) from exc

    risk_svc = UserRiskSettingService(session)
    before_risk = risk_svc.snapshot_account(uba_id)
    risk_svc.upsert_account(
        uba_id,
        {"account_paused": True},
        actor=f"admin:{user.user_id}",
    )
    session.commit()

    audit.record(
        event_type="ADMIN_BROKER_CREDENTIAL_REVOKE",
        actor=f"admin:{user.user_id}",
        request_id=getattr(request.state, "request_id", None),
        detail={
            "user_broker_account_id": uba_id,
            "before_status": before.verification_status,
            "after_status": after.verification_status,
            "account_paused": True,
            "before_paused": (
                (before_risk or {}).get("account_paused")
                if isinstance(before_risk, dict)
                else None
            ),
        },
    )
    return {
        **after.as_dict(),
        "account_paused": True,
    }
